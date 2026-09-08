"""
M3 异常检测业务逻辑服务
"""
import json
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.schemas.m3 import (
    ScanRequest,
    AIReviewRequest,
    AIScanRequest,
)
from app.jobs import start_job, update_progress, get_job
from app.repositories.artifact import ArtifactRepository


class M3Service:
    """M3 异常检测服务"""

    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: 输出目录根路径（通常是项目根/output）
        """
        self.output_dir = Path(output_dir)
        self.reports_dir = self.output_dir / "reports"
        self.cache_dir = self.output_dir / "cache"
        self.artifacts = ArtifactRepository(self.output_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ==================== 扫描相关 ====================

    def scan_anomalies(self, req: ScanRequest) -> Dict[str, Any]:
        """执行 M3 全量发票异常检测"""
        # 使用缓存结果（快速加载）
        if req.useCached:
            cached = self._read_latest_payload("m3-scan", self.reports_dir / "m3_result.json")
            if cached is not None:
                return self._enrich_from_cache(cached)

        # 执行全量扫描
        from core.client import QihengClient
        from core.m3_processor import M3Processor
        from core.claim_store import fetch_all_claims

        client = QihengClient(api_key=req.apiKey, base_url=req.apiUrl or None)
        processor = M3Processor(client=client)
        results = processor.run(limit=req.limit)

        artifact = self.artifacts.write("m3-scan", results)

        # 附加发票明细
        claims = fetch_all_claims(client)
        response = self._enrich_invoice_details(claims, results)
        response["artifact"] = artifact
        return response

    def get_scan_results(self) -> Dict[str, Any]:
        """获取最近一次扫描结果"""
        result = self._read_latest_payload("m3-scan", self.reports_dir / "m3_result.json")
        if result is not None:
            return result
        return {
            "duplicateInvoices": [],
            "invoiceIssues": [],
            "message": "请先执行扫描"
        }

    # ==================== AI 复核相关 ====================

    def start_ai_review(self, req: AIReviewRequest) -> Dict[str, str]:
        """启动 AI 复核异步任务"""
        req_data = req.model_dump()

        def worker(job_id: str) -> None:
            from core.llm_reviewer import LLMReviewer
            reviewer = LLMReviewer()

            # 加载扫描结果
            scan = self._enrich_from_cache({})
            tasks = []
            if req_data["scope"] in ("all", "issues"):
                tasks += [("issue", it) for it in scan.get("invoiceIssues", [])]
            if req_data["scope"] in ("all", "duplicates"):
                tasks += [("duplicate", it) for it in scan.get("duplicateInvoices", [])]

            results = {}
            failed = 0

            def _one(kind_item):
                kind, item = kind_item
                sub = (
                    f"{item.get('issue')}:{item.get('invoiceId')}"
                    if kind == "issue"
                    else f"{item.get('invoiceCode')}/{item.get('invoiceNo')}"
                )
                try:
                    out = reviewer.review_m3_anomaly(
                        self._build_anomaly_payload(item, kind),
                        self._anomaly_keywords(item, kind),
                    )
                    return kind, sub, out
                except Exception as e:
                    return kind, sub, {"error": str(e)[:200]}

            done = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(_one, t) for t in tasks]
                for fut in as_completed(futures):
                    kind, sub, out = fut.result()
                    results[f"{kind}:{sub}"] = out
                    if out.get("error"):
                        failed += 1
                    done += 1
                    update_progress(job_id, len(tasks), done)

            # 保存复核结果
            payload = {
                "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                "model": reviewer.model,
                "skill": "m3-ai-review",
                "scope": req_data["scope"],
                "total": len(tasks),
                "failed": failed,
                "results": results,
                "fromCache": False,
            }
            payload["artifact"] = self.artifacts.write("m3-ai-review", payload, job_id=job_id)
            update_progress(job_id, len(tasks), len(tasks), results=payload)

        job_id = start_job("m3-ai-review", worker)
        return {"jobId": job_id, "status": "queued"}

    def get_ai_review_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """查询 AI 复核任务状态"""
        return get_job(job_id)

    def get_ai_review_results(self) -> Dict[str, Any]:
        """获取最近一次 AI 复核结果"""
        result = self._read_latest_payload("m3-ai-review", self.reports_dir / "m3_ai_review.json")
        if result is not None:
            return result
        return {"results": {}, "total": 0, "message": "尚未执行 AI 复核"}

    # ==================== AI 全量巡检相关 ====================

    def start_ai_scan(self, req: AIScanRequest) -> Dict[str, str]:
        """启动 AI 全量巡检异步任务"""
        req_data = req.model_dump()

        def worker(job_id: str) -> None:
            ledger_file = self.cache_dir / "invoice_ledger.json"

            # 加载或获取发票台账
            if req_data["useCached"] and ledger_file.exists():
                with open(ledger_file, "r", encoding="utf-8") as f:
                    invoices = json.load(f)
            else:
                from core.client import QihengClient
                client = QihengClient(
                    api_key=req_data["apiKey"],
                    base_url=req_data["apiUrl"] or None
                )
                invoices = list(client.invoices_iterate())
                with open(ledger_file, "w", encoding="utf-8") as f:
                    json.dump(invoices, f, ensure_ascii=False)

            def cb(total: int, processed: int) -> None:
                update_progress(job_id, total, processed, phase="scan")

            # 执行全量扫描
            from core.m3_ai_scan import run_full_scan
            report = run_full_scan(
                invoices,
                batch_size=max(1, req_data["batchSize"]),
                limit=req_data["limit"],
                max_workers=4,
                progress_cb=cb,
            )
            report["fromCache"] = bool(req_data["useCached"])

            # 保存扫描结果
            report["artifact"] = self.artifacts.write("m3-ai-scan", report, job_id=job_id)
            update_progress(
                job_id, report["batchCount"], report["batchCount"],
                results=report, phase="done",
            )

        job_id = start_job("m3-ai-scan", worker)
        return {"jobId": job_id, "status": "queued"}

    def get_ai_scan_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """查询 AI 全量巡检任务状态"""
        return get_job(job_id)

    def get_ai_scan_results(self) -> Dict[str, Any]:
        """获取最近一次 AI 全量巡检结果（附带发票详情）"""
        report = self._read_latest_payload("m3-ai-scan", self.reports_dir / "m3_ai_scan.json")
        if report is None:
            return {
                "results": {},
                "flaggedCount": 0,
                "message": "尚未执行 AI 全量巡检"
            }
        # 附加发票详情
        claims = []
        claims_file = self.cache_dir / "all_claims.json"
        if claims_file.exists():
            with open(claims_file, "r", encoding="utf-8") as f:
                claims = json.load(f)

        inv_by_id, _ = self._build_invoice_detail_map(claims)

        flagged = []
        for iid, it in (report.get("results") or {}).items():
            entry = dict(it)
            entry["invoiceId"] = iid
            entry["invoice"] = inv_by_id.get(iid) or {}
            flagged.append(entry)

        report["flagged"] = flagged
        return report

    # ==================== 辅助方法 ====================

    def _anomaly_keywords(self, item: dict, kind: str) -> set:
        """为异常项生成关键词集合（用于 RAG 检索）"""
        if kind == "duplicate":
            return {"重复", "查重", "发票", "报销"}
        issue = item.get("issue", "")
        if issue == "TITLE_WRONG":
            return {"抬头", "发票", "全称", "分公司"}
        if issue == "TAXNO_WRONG":
            return {"税号", "纳税人识别号", "抬头"}
        if issue == "TAX_RATE_WRONG":
            return {"税率", "适用", "增值税", "发票"}
        if issue == "CONSECUTIVE_NO":
            return {"连号", "发票", "连续", "拆分", "开具"}
        if issue == "SUPPLIER_DUP":
            return {"供应商", "重复", "档案", "税号", "建档"}
        return {"发票", "合规"}

    def _build_anomaly_payload(self, item: dict, kind: str) -> dict:
        """构建异常条目的标准化 payload（用于 LLM 复核）"""
        if kind == "duplicate":
            return {
                "type": "重复报销",
                "invoiceCode": item.get("invoiceCode"),
                "invoiceNo": item.get("invoiceNo"),
                "claimIds": item.get("claimIds", []),
                "basis": item.get("basis", ""),
                "invoices": [
                    {
                        "claimNo": i.get("claimNo"),
                        "invoiceKind": i.get("invoiceKind"),
                        "issuedOn": i.get("issuedOn"),
                        "buyerName": i.get("buyerName"),
                        "sellerName": i.get("sellerName"),
                        "totalFen": i.get("totalFen"),
                    }
                    for i in item.get("invoices", [])
                ],
            }

        inv = item.get("invoice") or {}
        return {
            "type": item.get("issue"),
            "invoiceId": item.get("invoiceId"),
            "basis": item.get("basis", ""),
            "invoice": {
                "invoiceCode": inv.get("invoiceCode"),
                "invoiceNo": inv.get("invoiceNo"),
                "invoiceKind": inv.get("invoiceKind"),
                "issuedOn": inv.get("issuedOn"),
                "buyerName": inv.get("buyerName"),
                "buyerTaxNo": inv.get("buyerTaxNo"),
                "sellerName": inv.get("sellerName"),
                "taxRate": inv.get("taxRate"),
                "totalFen": inv.get("totalFen"),
            },
        }

    def _build_invoice_detail_map(self, claims: list) -> Tuple[Dict, Dict]:
        """从单据构建发票明细映射（id -> detail 和 code/no -> details[]）"""
        inv_by_id = {}
        inv_by_key = {}

        # 从单据行提取发票
        for cl in claims:
            for ln in cl.get("lines", []):
                inv = ln.get("invoice") or {}
                if not inv.get("id"):
                    continue
                detail = {
                    "invoiceId": inv.get("id"),
                    "claimId": cl.get("id"),
                    "claimNo": cl.get("claimNo", ""),
                    "lineNo": ln.get("lineNo"),
                    "invoiceCode": inv.get("invoiceCode", ""),
                    "invoiceNo": inv.get("invoiceNo", ""),
                    "invoiceKind": inv.get("invoiceKind", ""),
                    "issuedOn": inv.get("issuedOn", ""),
                    "buyerName": (inv.get("buyer") or {}).get("name", ""),
                    "buyerTaxNo": (inv.get("buyer") or {}).get("taxNo", ""),
                    "sellerName": (inv.get("seller") or {}).get("name", ""),
                    "sellerTaxNo": (inv.get("seller") or {}).get("taxNo", ""),
                    "totalFen": inv.get("totalFen"),
                    "taxRate": inv.get("taxRate"),
                    "attachmentId": (ln.get("attachment") or {}).get("id"),
                    "migrated": (ln.get("attachment") or {}).get("migrated"),
                }
                inv_by_id.setdefault(inv["id"], detail)
                key = f"{inv.get('invoiceCode', '')}/{inv.get('invoiceNo', '')}"
                inv_by_key.setdefault(key, []).append(detail)

        # 从台账补充非报销类发票
        ledger_file = self.cache_dir / "invoice_ledger.json"
        if ledger_file.exists():
            with open(ledger_file, "r", encoding="utf-8") as f:
                ledger = json.load(f)
            for inv in ledger:
                iid = inv.get("id")
                if iid and iid not in inv_by_id:
                    inv_by_id[iid] = {
                        "invoiceId": iid,
                        "claimId": None,
                        "claimNo": None,
                        "lineNo": None,
                        "invoiceCode": inv.get("invoiceCode", ""),
                        "invoiceNo": inv.get("invoiceNo", ""),
                        "invoiceKind": inv.get("invoiceKind", ""),
                        "issuedOn": inv.get("issuedOn", ""),
                        "buyerName": (inv.get("buyer") or {}).get("name", ""),
                        "buyerTaxNo": (inv.get("buyer") or {}).get("taxNo", ""),
                        "sellerName": (inv.get("seller") or {}).get("name", ""),
                        "sellerTaxNo": (inv.get("seller") or {}).get("taxNo", ""),
                        "totalFen": inv.get("totalFen"),
                        "taxRate": inv.get("taxRate"),
                        "attachmentId": None,
                        "fromLedger": True,
                    }
                    key = f"{inv.get('invoiceCode', '')}/{inv.get('invoiceNo', '')}"
                    if key not in inv_by_key:
                        inv_by_key[key] = [inv_by_id[iid]]

        return inv_by_id, inv_by_key

    def _enrich_invoice_details(self, claims: list, result: dict) -> dict:
        """附加发票明细到扫描结果"""
        inv_by_id, inv_by_key = self._build_invoice_detail_map(claims)

        # 附加重复发票明细
        for dup in result.get("duplicateInvoices", []):
            key = f"{dup.get('invoiceCode', '')}/{dup.get('invoiceNo', '')}"
            dup["invoices"] = inv_by_key.get(key, [])

        # 附加发票问题明细
        for iss in result.get("invoiceIssues", []):
            d = inv_by_id.get(iss.get("invoiceId"))
            if d:
                iss["invoice"] = d
            if iss.get("issue") == "SUPPLIER_DUP" and iss.get("invoiceIds"):
                iss["invoices"] = [
                    inv_by_id[iid] for iid in iss["invoiceIds"]
                    if iid in inv_by_id
                ]

        # 附加供应商档案明细
        for prof in result.get("supplierProfiles", []):
            prof["invoices"] = [
                inv_by_id[iid] for iid in prof.get("invoiceIds", [])
                if iid in inv_by_id
            ]

        return result

    def _enrich_from_cache(self, cached: dict) -> dict:
        """从缓存加载扫描结果并附加发票明细"""
        data = dict(cached) if cached else {}

        cache_file = self.cache_dir / "all_claims.json"
        claims = []
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                claims = json.load(f)

        data["fromCache"] = True
        return self._enrich_invoice_details(claims, data)

    def _read_latest_payload(self, artifact_type: str, legacy_path: Path) -> Optional[Dict[str, Any]]:
        """Read versioned output first; legacy reports are read-only migration fallback."""
        envelope = self.artifacts.read_latest(artifact_type)
        if envelope is not None:
            payload = envelope.get("payload")
            if isinstance(payload, dict):
                return payload
        if legacy_path.exists():
            with legacy_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        return None
