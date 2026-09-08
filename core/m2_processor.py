"""
M2审核流程编排器（集成 DeepSeek V4-Flash OCR）

功能：
1. 拉取待审池全部300单报销单
2. 下载发票图片，DeepSeek V4-Flash OCR识别票面内容
3. 以OCR票面数据为准，比对系统录入数据
4. 执行审核规则
5. 通过API写回审核意见
6. 生成审核报告（JSON格式）
"""

import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any

from filelock import FileLock

from core.client import QihengClient, QihengError
from core.auditor import Auditor, AuditResult
from core.invoice_ocr import InvoiceOCREngine
from core.claim_store import load_invoice_index
from core.logger import get_logger
from data.travel_data import TravelDataManager
from data.config import REPORTS_DIR

logger = get_logger("m2")

_STATUS_LOCK = FileLock(
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "output", "cache", "m2_audit_status.json.lock",
    )
)


def _atomic_write_json(path: str, data) -> None:
    """原子写 JSON：临时文件 + os.replace，避免读到半截文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_audit_status() -> Dict[str, dict]:
    """加载每单审核状态（结果 + 是否已写回 ERP）。
    首次运行（状态文件不存在）时，从全量审核报告播种历史结论。
    """
    with _STATUS_LOCK:
        status_file = M2Processor.AUDIT_STATUS_FILE
        if os.path.exists(status_file):
            with open(status_file, "r", encoding="utf-8") as f:
                return json.load(f)

        status: Dict[str, dict] = {}
        report_path = os.path.join(REPORTS_DIR, "audit_report.json")
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for r in data.get("reviews", []):
                cid = r.get("claimId")
                if not cid:
                    continue
                status[cid] = {
                    "result": r.get("result"),
                    "aiReview": r.get("aiReview"),
                    "writtenBack": True,  # 全量报告运行已回写
                    "updatedAt": data.get("generatedAt"),
                }
            _atomic_write_json(M2Processor.AUDIT_STATUS_FILE, status)
        return status


def save_audit_status(status: Dict[str, dict]) -> None:
    """持久化每单审核状态到 output/cache/m2_audit_status.json（文件锁 + 原子写）"""
    with _STATUS_LOCK:
        _atomic_write_json(M2Processor.AUDIT_STATUS_FILE, status)


class M2Processor:
    """M2审核流程编排器（集成OCR）"""

    OCR_CACHE_FILE = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "output", "cache", "ocr_all_{engine}.json",
    )
    AUDIT_STATUS_FILE = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "output", "cache", "m2_audit_status.json",
    )

    def __init__(self, client: QihengClient, use_ocr: bool = True) -> None:
        self.client: QihengClient = client
        self.travel_manager: TravelDataManager = TravelDataManager(client)
        self.auditor: Auditor = Auditor(self.travel_manager)
        self.ocr_engine: Optional[InvoiceOCREngine] = InvoiceOCREngine() if use_ocr else None
        self.use_ocr: bool = use_ocr
        self.llm_reviewer = None
        from core.llm_reviewer import is_llm_review_enabled
        if is_llm_review_enabled():
            try:
                from core.llm_reviewer import LLMReviewer
                self.llm_reviewer = LLMReviewer()
            except (ImportError, ValueError) as e:
                logger.warning(f"  ⚠ AI 复核助手未启用: {e}")
        self.results: List[AuditResult] = []
        self.ocr_results: Dict[str, dict] = {}
        self.ocr_comparisons: Dict[str, dict] = {}
        # 失败清单（拉详情/审核/回写），落盘为可重放队列（设计文档2.0 §3.8）
        self.failures: List[Dict[str, str]] = []
        # 图管线中暂停等待人工终审的单（AGENT_HUMAN_GATE=1 时产生）
        self.pending_human: List[dict] = []

    def run(self, limit: Optional[int] = None, claim_ids: Optional[List[str]] = None,
            write_back: bool = True,
            progress_cb: Optional[Any] = None) -> List[AuditResult]:
        """执行M2审核流程"""
        _t0 = time.time()
        def _elapsed(tag: str) -> None:
            logger.info(f"  [计时] {tag}: {time.time() - _t0:.1f}s")
        logger.info("=== M2审核流程开始 ===")
        if self.use_ocr:
            engine_name = getattr(self.ocr_engine, "engine_type", "ocr")
            logger.info(f"  [OCR模式] 使用 {engine_name} 识别发票票面数据")
        if self.llm_reviewer:
            logger.info(f"  [AI复核] 启用 LLM 复核助手（{self.llm_reviewer.model}）")

        # 加载差旅数据
        self.travel_manager.load_data()

        # 步骤1: 拉取待审单列表
        logger.info("\n[步骤1] 拉取待审报销单...")
        claims = list(self.client.expense_claims_iterate(status="PENDING"))
        logger.info(f"✓ 待审池共 {len(claims)} 单")
        _elapsed("步骤1 拉取待审列表")

        # 应用限制
        if claim_ids:
            claims = [c for c in claims if c['id'] in claim_ids]
            logger.info(f"✓ 筛选后 {len(claims)} 单")
        elif limit and limit > 0:
            claims = claims[:limit]
            logger.info(f"✓ 限制处理前 {limit} 单")

        # 步骤2: 获取所有报销单详情
        logger.info("\n[步骤2] 获取报销单详情...")
        claim_details = []
        for i, claim in enumerate(claims, 1):
            claim_id = claim['id']
            try:
                detail = self.client.expense_claims_get(claim_id)
                claim_details.append(detail)
            except QihengError as e:
                logger.warning(f"  ✗ 获取 {claim_id} 详情失败: {e.message}")
                self.failures.append(
                    {"claimId": claim_id, "stage": "fetch_detail", "error": e.message}
                )

            if i % 50 == 0:
                logger.info(f"  已获取 {i}/{len(claims)} 单")
        logger.info(f"✓ 成功获取 {len(claim_details)} 单详情")
        _elapsed("步骤2 获取单据详情")

        # 步骤3: OCR识别发票图片
        if self.use_ocr and self.ocr_engine:
            logger.info("\n[步骤3] 千问 Qwen3.6-Flash OCR识别发票图片...")
            self._run_ocr(claim_details)
            ocr_stats = self.ocr_engine.get_stats()
            logger.info(f"✓ OCR完成: 调用千问={ocr_stats['totalCalls']}次, 缓存命中={ocr_stats['cacheHits']}次")
            _elapsed("步骤3 OCR识别")
        else:
            logger.info("\n[步骤3] 跳过OCR（非OCR模式）")

        # 步骤4: 构建全量发票索引（跨历史单据查重）
        logger.info("\n[步骤4] 构建全量发票索引（含历史单据）...")
        invoice_index = load_invoice_index(
            self.client,
            use_cache=not getattr(self.client, "is_demo", False),
            force=getattr(self.client, "is_demo", False),
        )
        self.auditor.set_invoice_index(invoice_index)
        logger.info(f"✓ 全量发票索引构建完成: {len(invoice_index)} 张发票")
        _elapsed("步骤4 构建发票索引")

        # 步骤5: 逐单规则审核（串行，AI 复核在下一步并行执行）
        logger.info(f"\n[步骤5] 逐单规则审核（共 {len(claim_details)} 单）...")
        success_count = 0
        fail_count = 0
        audit_items = []

        for i, claim_detail in enumerate(claim_details, 1):
            claim_id = claim_detail['id']
            logger.info(f"\n[{i}/{len(claim_details)}] 审核报销单 {claim_id}...")

            try:
                # 获取审批记录
                approvals = self.client.approvals_for_claim(claim_id)

                # 执行审核（传入OCR结果）
                result = self.auditor.audit_claim(
                    claim_detail, approvals,
                    ocr_results=self.ocr_results if self.use_ocr else None
                )

                # 记录结果
                self.results.append(result)
                audit_items.append((claim_detail, approvals, result))

                # 打印规则结论
                logger.info(f"  规则结论: {result.result}")
                logger.info(f"审核 {claim_id}: {result.result} decision_strength={result.decision_strength:.2f}")
                if result.violations:
                    logger.info(f"  违规: {[v.code for v in result.violations]}")
                    logger.info(f"  理由: {result.reasons[:3]}")
                    logger.info(f"违规 {claim_id}: {[v.code for v in result.violations]}")

                success_count += 1
                if progress_cb:
                    progress_cb(len(claim_details), i, phase="rules")

            except QihengError as e:
                logger.warning(f"  ✗ [API错误] {e.code}: {e.message}")
                self.failures.append(
                    {"claimId": claim_id, "stage": "audit", "error": f"{e.code}: {e.message}"}
                )
                fail_count += 1
                if progress_cb:
                    progress_cb(len(claim_details), i, phase="rules")
        _elapsed("步骤5 规则审核")

        # 步骤5.5: AI 复核助手（legacy 管线：并发受 LLM_MAX_CONCURRENCY 全局限流；分歧转 FLAG）
        pipeline = os.environ.get("M2_PIPELINE", "legacy").strip().lower()
        if pipeline == "graph":
            logger.info("\n[步骤5.5] 图管线（LangGraph）：AI 复核/调查/人工终审在图内执行")
        elif self.llm_reviewer and audit_items:
            logger.info(f"\n[步骤5.5] AI 复核（共 {len(audit_items)} 单，并发受全局限流器控制）...")
            done = 0

            def _review_one(item):
                d, ap, r = item
                return self._llm_second_opinion(r, d, ap, self.ocr_results)

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(_review_one, it) for it in audit_items]
                for fut in as_completed(futures):
                    fut.result()
                    done += 1
                    if progress_cb:
                        progress_cb(len(claim_details), done, phase="ai")
            logger.info("  最终结论:")
            for r in self.results:
                logger.info(f"    {r.claim_id}: {r.result}")
            _elapsed("步骤5.5 AI复核")
        else:
            if progress_cb:
                progress_cb(len(claim_details), len(claim_details), phase="done")

        # 持久化每单审核状态（AI 审核阶段，尚未写回）
        status_map = load_audit_status()
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        for r in self.results:
            status_map[r.claim_id] = {
                "result": r.result,
                "aiReview": r.ai_review,
                "writtenBack": False,
                "updatedAt": now_ts,
            }

        # 步骤5.6: 回写审核意见（AI 只给意见，不改变单据状态）
        if pipeline == "graph":
            self._run_graph_pipeline(audit_items, invoice_index, write_back,
                                     status_map, now_ts, progress_cb)
        elif write_back:
            logger.info(f"\n[步骤5.6] 回写审核意见（{len(self.results)} 单）...")
            for result in self.results:
                try:
                    self._write_review(result)
                    if result.claim_id in status_map:
                        status_map[result.claim_id]["writtenBack"] = True
                except QihengError as e:
                    logger.warning(f"  ✗ 回写 {result.claim_id} 失败: {e.message}")
                    self.failures.append(
                        {"claimId": result.claim_id, "stage": "writeback", "error": e.message}
                    )
                time.sleep(0.1)
        save_audit_status(status_map)

        # 步骤6: 生成报告（仅全量运行写入正式报告，局部运行不覆盖）
        if limit is None and not claim_ids:
            logger.info("\n[步骤6] 生成审核报告...")
            self._generate_report()
        else:
            logger.info(f"\n[步骤6] 局部运行（{len(self.results)} 单），不覆盖全量审核报告")

        if self.use_ocr and self.ocr_engine:
            ocr_stats = self.ocr_engine.get_stats()
            logger.info(
                "OCR统计: 总调用=%d, 缓存命中=%d, 缓存大小=%d",
                ocr_stats['totalCalls'], ocr_stats['cacheHits'], ocr_stats['cacheSize'],
            )

        logger.info("\n=== M2审核流程完成 ===")
        logger.info(f"成功: {success_count} 单")
        logger.warning(f"失败: {len(self.failures)} 单")
        self._save_failures()
        _elapsed("全流程")

        return self.results

    def _save_failures(self) -> None:
        """失败清单落盘为可重放队列（拉详情/审核/回写失败的单据与原因）"""
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.join(REPORTS_DIR, "m2_failures.json")
        _atomic_write_json(path, {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "count": len(self.failures),
            "failures": self.failures,
        })
        if self.failures:
            logger.warning(f"✗ 失败清单已落盘: {path}（{len(self.failures)} 条，可据此重放）")
        else:
            logger.info(f"✓ 无失败单（清单已刷新: {path}）")

    def _llm_second_opinion(
        self,
        rules_result: AuditResult,
        claim_detail: dict,
        approvals: list,
        ocr_results: dict,
    ) -> AuditResult:
        """LLM 独立复核；与规则结论不一致时转 FLAG（规则/LLM 双意见写入理由）"""
        try:
            opinion = {
                "result": rules_result.result,
                "violations": [v.code for v in rules_result.violations],
                "reasons": rules_result.reasons,
            }
            _call_t0 = time.time()
            out = self.llm_reviewer.review_claim(
                claim_detail,
                approvals,
                travel_standards=self.travel_manager.list_standards(),
                ocr_fields=ocr_results,
                rules_opinion=opinion,
            )
            logger.info(f"    [计时] LLM复核 {rules_result.claim_id}: {time.time() - _call_t0:.1f}s")
            llm_result = out.get("result")
            # 把 AI 复核结构化结果挂到审核结果上（前端「审核结果」页展示）
            rules_result.ai_review = {
                "result": llm_result,
                "reasons": out.get("reasons") or [],
                "confidence": out.get("confidence"),
                "agreeWithRules": out.get("agreeWithRules"),
            }
            if llm_result and llm_result != rules_result.result:
                rules_result.result = "FLAG"
                rules_result.reasons = [
                    f"AI 复核意见与规则引擎不一致（规则={opinion['result']}，AI={llm_result}），"
                    f"提请人工复核。AI 理由：{'; '.join(out.get('reasons') or [])}"
                ] + rules_result.reasons
                rules_result.confidence = 0.5
                logger.warning(f"    ⚠ AI复核分歧: 规则={opinion['result']} vs AI={llm_result} → FLAG")
            elif llm_result:
                logger.info(f"    ✓ AI复核一致: {llm_result}")
        except Exception as e:
            logger.warning(f"    ⚠ AI复核调用失败（按规则结论处理）: {e}")
        return rules_result

    def _run_ocr(self, claim_details: List[dict]) -> None:
        """对所有发票图片执行OCR识别"""
        # 收集所有需要OCR的发票附件
        all_attachments = {}
        for claim in claim_details:
            for line in claim.get('lines', []):
                invoice = line.get('invoice')
                attachment = line.get('attachment')
                if invoice and attachment:
                    attach_id = attachment['id']
                    if attach_id not in all_attachments:
                        all_attachments[attach_id] = {
                            'mime_type': attachment.get('mimeType', 'image/jpeg'),
                            'invoice': invoice
                        }

        logger.info(f"  共 {len(all_attachments)} 张发票图片待OCR")

        # 磁盘缓存（断点续跑：已识别的不重复调用云端）
        cache = {}
        engine_name = getattr(self.ocr_engine, "engine_type", "ocr")
        ocr_cache_file = self.OCR_CACHE_FILE.format(engine=engine_name)
        for cache_path in (
            ocr_cache_file,
            os.path.join(os.path.dirname(ocr_cache_file), f"ocr_samples_{engine_name}.json"),
        ):
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache.update(json.load(f))
        if cache:
            logger.info(f"  (复用 OCR 缓存 {len(cache)} 张)")
        os.makedirs(os.path.dirname(self.OCR_CACHE_FILE), exist_ok=True)

        def _save_cache() -> None:
            _atomic_write_json(ocr_cache_file, cache)

        # 逐张下载并OCR
        for i, (attach_id, info) in enumerate(all_attachments.items(), 1):
            logger.info(f"  [{i}/{len(all_attachments)}] OCR: {attach_id}...")

            if attach_id in cache:
                self.ocr_results[attach_id] = cache[attach_id]
                continue

            try:
                # 下载图片
                image_bytes = self.client._request('GET', f'/v1/attachments/{attach_id}/content')

                # OCR识别
                ocr_result = self.ocr_engine.ocr_invoice(
                    image_bytes, info['mime_type'], attach_id
                )

                if ocr_result:
                    self.ocr_results[attach_id] = ocr_result
                    cache[attach_id] = ocr_result
                    _save_cache()

                    # 与系统数据比对
                    comparison = self.ocr_engine.compare_with_system(
                        ocr_result, info['invoice']
                    )
                    if comparison['hasDiscrepancy']:
                        self.ocr_comparisons[attach_id] = comparison
                        logger.warning(f"    ⚠ 发现{len(comparison['discrepancies'])}处差异")

                # 限流（千问API QPS限制）
                if i % 10 == 0:
                    time.sleep(0.5)
                else:
                    time.sleep(0.1)

            except (ValueError, IOError, QihengError) as e:
                logger.warning(f"    ✗ OCR失败: {e}")

    def _write_review(self, result: AuditResult):
        """回写审核意见到ERP"""
        evidence = []
        for v in result.violations:
            evidence.append({"type": "policy", "ref": v.reason})

        self.client.expense_claims_review(
            claim_id=result.claim_id,
            result=result.result,
            reasons=result.reasons,
            evidence=evidence,
            confidence=result.confidence,
            violations=[v.code for v in result.violations],
        )

    def _write_review_payload(self, payload: dict) -> None:
        """图管线的回写适配：接受 payload dict，失败记入失败清单（不抛出）"""
        claim_id = payload.get("claimId", "")
        try:
            self.client.expense_claims_review(
                claim_id=claim_id,
                result=payload.get("result"),
                reasons=payload.get("reasons") or [],
                confidence=payload.get("confidence"),
                violations=payload.get("violations") or [],
            )
        except QihengError as e:
            self.failures.append(
                {"claimId": claim_id, "stage": "writeback", "error": e.message}
            )
            logger.warning(f"  ✗ 回写 {claim_id} 失败: {e.message}")

    def _build_retriever(self):
        """图管线/调查 Agent 的制度知识库检索器（复用 AI 复核助手实例）"""
        if self.llm_reviewer is not None and getattr(self.llm_reviewer, "retriever", None):
            return self.llm_reviewer.retriever
        from core.retrieval import PolicyRetriever
        return PolicyRetriever()

    def _run_graph_pipeline(self, audit_items, invoice_index, write_back,
                            status_map, now_ts, progress_cb=None) -> None:
        """M2_PIPELINE=graph：LangGraph 工作流（llm_review → 调查 → human_gate → write_back）"""
        from core.workflow import M2GraphRunner
        runner = M2GraphRunner(
            client=self.client,
            travel_manager=self.travel_manager,
            retriever=self._build_retriever(),
            llm_reviewer=self.llm_reviewer,
            write_back_fn=self._write_review_payload,
        )
        pending = []
        total = len(audit_items)
        for i, (claim_detail, approvals, result) in enumerate(audit_items, 1):
            claim_id = result.claim_id
            rules_opinion = {
                "result": result.result,
                "violations": [v.code for v in result.violations],
                "reasons": list(result.reasons),
                "confidence": result.confidence,
            }
            try:
                state = runner.run_claim(
                    claim_detail, approvals,
                    self.ocr_results if self.use_ocr else {},
                    invoice_index, rules_opinion, write_back,
                )
            except Exception as e:
                # 图管线单点失败 → 降级为规则意见回写（不中断批次）
                logger.warning(f"  ✗ 图管线异常 {claim_id}，按规则意见降级: {e}")
                self.failures.append(
                    {"claimId": claim_id, "stage": "graph", "error": str(e)[:200]}
                )
                if write_back:
                    try:
                        self._write_review(result)
                        status_map[claim_id] = {
                            "result": result.result, "aiReview": result.ai_review,
                            "writtenBack": True, "updatedAt": now_ts,
                        }
                    except QihengError as we:
                        self.failures.append(
                            {"claimId": claim_id, "stage": "writeback", "error": we.message}
                        )
                if progress_cb:
                    progress_cb(total, i, phase="ai")
                continue

            if state.get("awaiting_human"):
                pending.append({
                    "claimId": claim_id,
                    "workflowRunId": state.get("workflow_run_id"),
                    "revision": state.get("workflow_revision", 0),
                    "finalResult": state.get("final_result"),
                    "reasons": state.get("final_reasons"),
                })
                if progress_cb:
                    progress_cb(total, i, phase="ai")
                continue

            ai_review = state.get("ai_review")
            result.ai_review = ai_review
            if state.get("final_result") and state["final_result"] != result.result:
                result.result = state["final_result"]
                result.reasons = state.get("final_reasons") or result.reasons
                result.confidence = state.get("final_confidence", result.confidence)
            status_map[claim_id] = {
                "result": result.result,
                "aiReview": ai_review,
                "writtenBack": bool(state.get("write_done") and write_back),
                "updatedAt": now_ts,
            }
            if progress_cb:
                progress_cb(total, i, phase="ai")

        self.pending_human = pending
        if pending:
            self._save_pending_human(pending)
            logger.warning(f"  ⚠ {len(pending)} 单暂停等待人工终审（output/reports/m2_pending_human.json）")

    def _save_pending_human(self, pending: List[dict]) -> None:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        _atomic_write_json(
            os.path.join(REPORTS_DIR, "m2_pending_human.json"),
            {
                "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
                "count": len(pending),
                "pending": pending,
            },
        )

    def _generate_report(self):
        """生成审核报告"""
        os.makedirs(REPORTS_DIR, exist_ok=True)

        # 生成JSON报告
        report_data = {
            'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
            'totalClaims': len(self.results),
            'approveCount': sum(1 for r in self.results if r.result == 'APPROVE'),
            'rejectCount': sum(1 for r in self.results if r.result == 'REJECT'),
            'flagCount': sum(1 for r in self.results if r.result == 'FLAG'),
            'ocrMode': self.use_ocr,
            'ocrComparisons': len(self.ocr_comparisons),
            'reviews': [r.to_dict() for r in self.results]
        }

        report_path = os.path.join(REPORTS_DIR, 'audit_report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        logger.info(f"✓ JSON报告已生成: {report_path}")

        approve_count = report_data['approveCount']
        reject_count = report_data['rejectCount']
        flag_count = report_data['flagCount']

        logger.info("\n审核统计:")
        logger.info(f"  通过(APPROVE): {approve_count} 单")
        logger.info(f"  驳回(REJECT): {reject_count} 单")
        logger.info(f"  存疑(FLAG): {flag_count} 单")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ['QIHENG_API_KEY']
    client = QihengClient(api_key=api_key)

    processor = M2Processor(client, use_ocr=True)

    # 测试：只处理前5单
    results = processor.run(limit=5)
