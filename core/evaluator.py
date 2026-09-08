"""
自建评测工具

使用公开样例标签（public-sample-labels.json）对审核引擎进行评测，计算：
- 驳回判定F1分数
- 违规代码完全一致率
- 详细评测报告
"""

import os
import json
from typing import Optional, Dict, Any

from core.client import QihengClient, QihengError
from core.auditor import Auditor
from core.invoice_ocr import InvoiceOCREngine
from core.claim_store import load_invoice_index
from core.submission import _OFFICIAL_M2_VIOLATIONS
from data.travel_data import TravelDataManager
from core.logger import get_logger

logger = get_logger("evaluator")


class Evaluator:
    """自建评测工具"""

    _DEFAULT_LABELS_FILE = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "labels", "public-sample-labels.json",
    )
    _OCR_CACHE_FILE = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "output", "cache", "ocr_samples_{engine}.json",
    )

    def __init__(self, client: QihengClient, labels_path: Optional[str] = None,
                 use_ocr: bool = True) -> None:
        self.client: QihengClient = client
        self.use_ocr: bool = use_ocr
        self.ocr_engine: Optional[InvoiceOCREngine] = InvoiceOCREngine() if use_ocr else None
        if labels_path:
            self.labels_path: str = labels_path
        else:
            self.labels_path = self._DEFAULT_LABELS_FILE
        self.travel_manager: TravelDataManager = TravelDataManager(client)
        self.auditor: Auditor = Auditor(self.travel_manager)
        self.labels: Optional[Dict[str, Any]] = None

    def load_labels(self) -> dict:
        """加载公开样例标签"""
        if not os.path.exists(self.labels_path):
            raise FileNotFoundError(f"未找到标签文件: {self.labels_path}")

        with open(self.labels_path, 'r', encoding='utf-8') as f:
            self.labels = json.load(f)

        return self.labels

    def evaluate(self) -> dict:
        """执行评测"""
        logger.info("=== 自建评测开始 ===")

        # 加载标签
        logger.info("\n[步骤1] 加载公开样例标签...")
        self.load_labels()
        claims_info = self.labels.get('claims', {})
        claim_ids = list(claims_info.keys())
        logger.info(f"✓ 加载 {len(claim_ids)} 条样例标签")

        # 加载差旅数据
        logger.info("\n[步骤2] 加载差旅标准数据...")
        self.travel_manager.load_data()

        # 构建全量发票索引（跨历史单据查重）
        logger.info("\n[步骤3] 构建全量发票索引...")
        invoice_index = load_invoice_index(self.client)
        self.auditor.set_invoice_index(invoice_index)

        # 步骤3.5: OCR 识别样例单票据（票面为准，带磁盘缓存）
        ocr_results = {}
        if self.use_ocr and self.ocr_engine:
            logger.info("\n[步骤3.5] OCR 识别样例单发票...")
            engine_name = getattr(self.ocr_engine, "engine_type", "ocr")
            ocr_cache_file = self._OCR_CACHE_FILE.format(engine=engine_name)
            cache = {}
            if os.path.exists(ocr_cache_file):
                with open(ocr_cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                logger.info(f"  (复用 OCR 缓存 {len(cache)} 张)")
            for claim_id in claim_ids:
                try:
                    claim_detail = self.client.expense_claims_get(claim_id)
                except QihengError:
                    continue
                for line in claim_detail.get('lines', []):
                    attachment = line.get('attachment')
                    if not attachment or not attachment.get('migrated', False):
                        continue
                    attach_id = attachment['id']
                    if attach_id in ocr_results:
                        continue
                    if attach_id in cache:
                        ocr_results[attach_id] = cache[attach_id]
                        continue
                    try:
                        image_bytes = self.client._request(
                            'GET', f'/v1/attachments/{attach_id}/content')
                        result = self.ocr_engine.ocr_invoice(
                            image_bytes, attachment.get('mimeType', 'image/jpeg'), attach_id)
                        if result:
                            ocr_results[attach_id] = result
                            cache[attach_id] = result
                    except (ValueError, IOError, QihengError):
                        continue
            os.makedirs(os.path.dirname(ocr_cache_file), exist_ok=True)
            with open(ocr_cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            logger.info(f"✓ OCR 完成: 识别 {len(ocr_results)} 张发票")

        # 逐单审核并对比
        logger.info(f"\n[步骤4] 逐单审核并对比（共 {len(claim_ids)} 单）...")

        tp = 0  # 真阳性：预测REJECT，实际REJECT
        tn = 0  # 真阴性：预测APPROVE/FLAG，实际APPROVE
        fp = 0  # 假阳性：预测REJECT，实际APPROVE
        fn = 0  # 假阴性：预测APPROVE/FLAG，实际REJECT

        violation_match_count = 0  # 违规代码完全一致的数量
        total_reject_cases = 0  # 实际REJECT的数量

        details = []

        for claim_id in claim_ids:
            expected = claims_info[claim_id]
            expected_verdict = expected['expectedVerdict']
            expected_violations = set(expected['violations'])

            try:
                # 获取报销单详情和审批记录
                claim_detail = self.client.expense_claims_get(claim_id)
                approvals = self.client.approvals_for_claim(claim_id)

                # 执行审核（票面 OCR 优先）
                result = self.auditor.audit_claim(
                    claim_detail, approvals,
                    ocr_results=ocr_results if self.use_ocr else None,
                )
                actual_verdict = result.result
                actual_violations = set([v.code for v in result.violations])
                # 官方码口径（与 submission 净化同源）：扩展规则（如 ACCOUNT_MISMATCH）
                # 是引擎的额外信号，不计入官方违规一致率，避免扩展规则误伤官方指标
                actual_official = actual_violations & _OFFICIAL_M2_VIOLATIONS
                extended_hit = sorted(actual_violations - _OFFICIAL_M2_VIOLATIONS)

                # 判断预测结果
                # 评分口径：REJECT 与 FLAG 同等视为「提请关注」
                predicted_reject = actual_verdict in ('REJECT', 'FLAG')
                actual_reject = expected_verdict == 'REJECT'

                # 计算混淆矩阵
                if predicted_reject and actual_reject:
                    tp += 1
                elif predicted_reject and not actual_reject:
                    fp += 1
                elif not predicted_reject and actual_reject:
                    fn += 1
                else:
                    tn += 1

                # 违规代码完全一致率（仅统计实际REJECT的情况，官方码口径）
                if actual_reject:
                    total_reject_cases += 1
                    if actual_official == expected_violations:
                        violation_match_count += 1

                # 记录详情
                details.append({
                    'claimId': claim_id,
                    'expectedVerdict': expected_verdict,
                    'actualVerdict': actual_verdict,
                    'expectedViolations': sorted(list(expected_violations)),
                    'actualViolations': sorted(list(actual_violations)),
                    'extendedHit': extended_hit,
                    'match': predicted_reject == actual_reject,
                    'violationMatch': actual_official == expected_violations
                })

            except (ValueError, KeyError, QihengError) as e:
                logger.warning(f"  ✗ 审核 {claim_id} 失败: {e}")
                details.append({
                    'claimId': claim_id,
                    'expectedVerdict': expected_verdict,
                    'actualVerdict': 'ERROR',
                    'expectedViolations': sorted(list(expected_violations)),
                    'actualViolations': [],
                    'match': False,
                    'violationMatch': False
                })

        # 计算指标
        logger.info("\n[步骤5] 计算评测指标...")

        # 驳回判定F1分数
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        # 违规代码完全一致率
        violation_accuracy = violation_match_count / total_reject_cases if total_reject_cases > 0 else 0

        # 整体准确率
        accuracy = (tp + tn) / len(claim_ids) if len(claim_ids) > 0 else 0

        # 输出评测报告
        logger.info("\n=== 评测报告 ===")
        logger.info(f"样例数量: {len(claim_ids)}")
        logger.info("\n混淆矩阵:")
        logger.info(f"  真阳性(TP): {tp}")
        logger.info(f"  真阴性(TN): {tn}")
        logger.info(f"  假阳性(FP): {fp}")
        logger.info(f"  假阴性(FN): {fn}")
        logger.info("\n驳回判定指标:")
        logger.info(f"  精确率(Precision): {precision:.4f}")
        logger.info(f"  召回率(Recall): {recall:.4f}")
        logger.info(f"  F1分数: {f1:.4f}")
        logger.info(f"\n违规代码完全一致率: {violation_accuracy:.4f}")
        logger.info(f"整体准确率: {accuracy:.4f}")

        # 输出详细结果
        logger.info("\n详细结果:")
        for detail in details:
            status = "✓" if detail['match'] else "✗"
            violation_status = "✓" if detail['violationMatch'] else "✗"
            logger.info(
                "%s %s: 预期=%s, 实际=%s, 违规匹配=%s",
                status, detail['claimId'], detail['expectedVerdict'],
                detail['actualVerdict'], violation_status,
            )

        return {
            'sampleSize': len(claim_ids),
            'confusionMatrix': {
                'tp': tp,
                'tn': tn,
                'fp': fp,
                'fn': fn
            },
            'verdictMetrics': {
                'precision': precision,
                'recall': recall,
                'f1': f1
            },
            'violationAccuracy': violation_accuracy,
            'accuracy': accuracy,
            'details': details
        }


if __name__ == "__main__":
    import os

    api_key = os.environ['QIHENG_API_KEY']
    client = QihengClient(api_key=api_key)

    evaluator = Evaluator(client)
    result = evaluator.evaluate()

    # 保存评测结果
    output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'output', 'evaluation_result.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 评测结果已保存: {output_path}")


_HARD_SET_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "labels", "hard-set-labels.json",
)


def evaluate_hard_set(labels_path: Optional[str] = None) -> dict:
    """自建困难集离线评测（设计文档2.0 §3.6②）。

    纯合成单据固件驱动 Auditor，不依赖 ERP 与 OCR：
    覆盖特批叠加、城市边界、多违规复合、缺票、R9 回归、R1/R2 边界、
    税号骨架、科目归集、注入样例等维度，指标为结论准确率与违规集一致率（引擎口径）。
    """
    labels_path = labels_path or _HARD_SET_FILE
    with open(labels_path, "r", encoding="utf-8") as f:
        labels = json.load(f)

    tm = TravelDataManager(client=None)
    tm._standards = labels["standards"]
    tm._build_standards_cache()
    tm._city_tiers = labels["cities"]
    tm._build_city_cache()
    aud = Auditor(tm)

    verdict_ok = 0
    violation_ok = 0
    details = []
    for case in labels["cases"]:
        aud.set_invoice_index(case.get("invoiceIndex") or {})
        r = aud.audit_claim(
            case["claim"], case.get("approvals") or [],
            ocr_results=case.get("ocr") or None,
        )
        actual_codes = sorted({v.code for v in r.violations})
        expected_codes = sorted(case["expectedViolations"])
        d_ok = r.result == case["expectedVerdict"]
        v_ok = actual_codes == expected_codes
        verdict_ok += d_ok
        violation_ok += v_ok
        details.append({
            "id": case["id"], "dimension": case.get("dimension", ""),
            "expectedVerdict": case["expectedVerdict"], "actualVerdict": r.result,
            "expectedViolations": expected_codes, "actualViolations": actual_codes,
            "verdictMatch": d_ok, "violationMatch": v_ok,
        })
    n = len(labels["cases"]) or 1
    return {
        "cases": n,
        "verdictAccuracy": round(verdict_ok / n, 4),
        "violationAccuracy": round(violation_ok / n, 4),
        "failures": [d for d in details if not (d["verdictMatch"] and d["violationMatch"])],
        "details": details,
    }
