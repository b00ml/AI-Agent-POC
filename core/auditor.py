"""
M2审核规则引擎

实现11种违规类型检测：
1. OVER_STANDARD_HOTEL - 住宿费超标
2. OVER_STANDARD_MEAL - 伙食补助超标
3. OVER_STANDARD_CITY_TRANSPORT - 市内交通超标
4. OVER_STANDARD_TRANSPORT_CLASS - 长途交通舱位超标
5. INVOICE_TITLE_MISMATCH - 发票抬头错误
6. INVOICE_TAXNO_MISMATCH - 发票税号错误
7. AMOUNT_MISMATCH - 金额不一致
8. DUPLICATE_INVOICE - 重复报销
9. MISSING_APPROVAL_OVERTIME_TAXI - 加班打车缺审批
10. MISSING_ATTACHMENT - 缺少票据附件
11. ACCOUNT_MISMATCH - 差旅科目归集错误（部门应与科目类别一致）
"""

import os
import re
from typing import Optional

from data.config import COMPANY_NAME, COMPANY_TAX_NO
from data.travel_data import TravelDataManager
from core.client import QihengError


class Violation:
    """违规信息"""
    def __init__(self, code: str, reason: str, evidence: str = "", suggest_flag: bool = False):
        self.code = code
        self.reason = reason
        self.evidence = evidence
        self.suggest_flag = suggest_flag

    def to_dict(self):
        return {
            'code': self.code,
            'reason': self.reason,
            'evidence': self.evidence
        }


class AuditResult:
    """审核结果"""
    def __init__(self, claim_id: str, result: str, violations: list = None,
                 reasons: list = None, confidence: float = 0.0,
                 ai_review: dict = None, decision_strength: Optional[float] = None):
        self.claim_id = claim_id
        self.result = result
        self.violations = violations or []
        self.reasons = reasons or []
        # `confidence` 是官方 ERP/submission v1 的兼容字段；规则分支分数不是校准概率。
        self.confidence = confidence
        self.decision_strength = confidence if decision_strength is None else decision_strength
        self.ai_review = ai_review

    def to_dict(self):
        return {
            'claimId': self.claim_id,
            'result': self.result,
            'violations': [v.code for v in self.violations],
            'reasons': self.reasons,
            'confidence': self.confidence,
            'decisionStrength': self.decision_strength,
            'aiReview': self.ai_review,
        }


class Auditor:
    """审核引擎"""

    def __init__(self, travel_manager: TravelDataManager):
        self.travel_manager = travel_manager
        self._invoice_index = {}  # 发票索引，用于重复报销检测

    def build_invoice_index(self, claims: list):
        """构建发票索引（用于重复报销检测）"""
        self._invoice_index = {}
        for claim in claims:
            if isinstance(claim, dict):
                # 如果是完整报销单详情，遍历费用行
                lines = claim.get('lines', [])
                for line in lines:
                    invoice = line.get('invoice')
                    if invoice:
                        key = f"{invoice['invoiceCode']}/{invoice['invoiceNo']}"
                        if key not in self._invoice_index:
                            self._invoice_index[key] = []
                        self._invoice_index[key].append(claim['id'])
            elif hasattr(claim, 'lines'):
                # 如果是对象，遍历费用行
                for line in claim.lines:
                    invoice = line.get('invoice')
                    if invoice:
                        key = f"{invoice['invoiceCode']}/{invoice['invoiceNo']}"
                        if key not in self._invoice_index:
                            self._invoice_index[key] = []
                        self._invoice_index[key].append(claim.id)

    def set_invoice_index(self, invoice_index: dict):
        """设置外部构建的全量发票索引（code/no -> [claimId]）"""
        self._invoice_index = invoice_index

    @staticmethod
    def _normalize_text(text) -> str:
        """去除空白字符（含全角空格）"""
        if not text:
            return ''
        return re.sub(r'[\s\u3000]+', '', str(text)).strip()

    @staticmethod
    def _taxno_matches(value: str, reference: str) -> bool:
        """
        税号比对：系统对税号做了 X 脱敏，票据影像/OCR 识别可能出现
        X 数量与系统不一致（OCR 漏读或多读）。因此剥除所有 X 占位符后
        比对剩余骨架；骨架不一致即视为税号不符。
        """
        value = Auditor._normalize_text(value)
        reference = Auditor._normalize_text(reference)
        value_clean = value.replace('X', '').replace('x', '')
        reference_clean = reference.replace('X', '').replace('x', '')
        if not value_clean or not reference_clean:
            return True  # 缺失数据不判违规
        return value_clean == reference_clean

    def check_has_special_approval(self, approvals: list) -> bool:
        """检查是否有特批豁免"""
        for approval in approvals:
            if approval.get('action') == 'SPECIAL_APPROVE':
                return True
        return False

    def audit_claim(self, claim_detail: dict, approvals: list, ocr_results: dict = None) -> AuditResult:
        """
        审核单个报销单
        
        Args:
            claim_detail: 报销单详情
            approvals: 审批记录
            ocr_results: OCR识别结果，key=attachment_id, value=OCR结果dict
        """
        violations = []
        reasons = []
        flag_reasons = []
        conf_penalty = 0.0
        claim_id = claim_detail['id']
        job_level = claim_detail.get('jobLevel', '')
        department = claim_detail.get('departmentName', '')
        trip = claim_detail.get('trip', {})
        city = trip.get('city', '') if isinstance(trip, dict) else ''
        nights = trip.get('nights', 0) if isinstance(trip, dict) else 0

        # 获取城市档次
        city_tier = self.travel_manager.get_city_tier(city)
        # 差旅单目的地城市未知：按制度边界标记 FLAG（不做默认档次静默假设）
        if trip and city and not self.travel_manager.has_city(city):
            flag_reasons.append(f"出差城市「{city}」不在城市档次表中，无法判定差旅标准，请人工复核")

        # 检查是否有特批
        has_special_approval = self.check_has_special_approval(approvals)

        # 逐行审核
        for line in claim_detail.get('lines', []):
            line_violations, line_reasons, line_flags, line_penalty = self._audit_line(
                line, job_level, city_tier, nights, claim_detail.get('claimType'),
                approvals, ocr_results, department,
            )
            violations.extend(line_violations)
            reasons.extend(line_reasons)
            flag_reasons.extend(line_flags)
            conf_penalty += line_penalty

        # 检查重复报销
        dup_violations, dup_reasons = self._check_duplicate_invoice(claim_detail)
        violations.extend(dup_violations)
        reasons.extend(dup_reasons)

        # 如果有特批，豁免超标类违规
        if has_special_approval:
            violations = [v for v in violations if not v.code.startswith('OVER_STANDARD')]
            if violations:
                reasons = [f"本单持有特批豁免，但存在其他违规: {v.reason}" for v in violations]
            else:
                reasons = ["本单持有财务总监事前特批，超标项已豁免"]

        # 缺票 + 情况说明：转 FLAG 提请人工裁定（而非直接驳回）
        if any(getattr(v, 'suggest_flag', False) for v in violations):
            flag_reasons.append("存在缺票但有情况说明，需人工裁定")

        # 生成结论
        if flag_reasons:
            result = 'FLAG'
            reasons = flag_reasons + [
                v.reason for v in violations
                if v.reason not in flag_reasons
            ]
        elif violations:
            result = 'REJECT'
        else:
            result = 'APPROVE'

        # 计算置信度
        decision_strength = self._calculate_decision_strength(result, violations, flag_reasons)
        decision_strength = max(0.0, decision_strength - conf_penalty)

        return AuditResult(
            claim_id, result, violations, reasons,
            confidence=decision_strength,
            decision_strength=decision_strength,
        )

    def _audit_line(self, line: dict, job_level: str, city_tier: str, nights: int,
                    claim_type: str, approvals: list, ocr_results: dict = None,
                    department: str = "") -> tuple:
        """审核单个费用行"""
        violations = []
        reasons = []
        flags = []
        conf_penalty = 0.0

        expense_type = line.get('expenseType', '')
        invoice = line.get('invoice')
        attachment = line.get('attachment')
        description = line.get('description', '')

        # 获取该行的OCR结果
        ocr_data = None
        if ocr_results and attachment:
            attach_id = attachment.get('id', '')
            ocr_data = ocr_results.get(attach_id)

        # R10: 缺附件检测（含情况说明时标记 suggest_flag → FLAG 人工裁定）
        if not attachment and invoice:
            has_explanation = any(
                kw in (description or '')
                for kw in ('丢失', '遗失', '情况说明', '说明', '补票')
            )
            violations.append(Violation(
                'MISSING_ATTACHMENT',
                f"费用行{line.get('lineNo')}缺少票据附件"
                + ("（单据含情况说明，建议人工裁定）" if has_explanation else ""),
                suggest_flag=has_explanation,
            ))
            reasons.append(violations[-1].reason)

        # 检查票据影像是否可用
        if attachment and not attachment.get('migrated', True):
            flags.append("票据影像不可用，请人工核对")
            return violations, reasons, flags, conf_penalty

        # 根据费用类型执行不同规则
        # 超标类规则（R1-R4）仅适用于差旅单；日常单的业务用餐/市内交通不套差旅标准
        is_travel = (claim_type == 'TRAVEL') or bool(nights)

        if expense_type == 'HOTEL' and is_travel:
            # R1: 住宿费超标检测
            violations_r1, reasons_r1 = self._check_hotel_over_standard(line, job_level, city_tier, nights)
            violations.extend(violations_r1)
            reasons.extend(reasons_r1)

        elif expense_type == 'MEAL' and is_travel:
            # R2: 伙食补助超标检测
            violations_r2, reasons_r2 = self._check_meal_over_standard(line, job_level, city_tier, nights)
            violations.extend(violations_r2)
            reasons.extend(reasons_r2)

        elif expense_type == 'CITY_TRANSPORT':
            # 加班打车：走 R9 事前审批检测（制度第十三条，不区分差旅/日常单）。
            # 「打车」一词不能单独触发 R9：普通差旅打车必须回落 R3 市内交通标准校验，
            # 仅「加班」语境（描述或事由含「加班」）才要求事前审批。
            is_overtime_taxi = ('加班' in description) or ('加班' in (line.get('purpose') or ''))
            if is_overtime_taxi:
                violations_r9, reasons_r9, r9_penalty = self._check_overtime_taxi_approval(line, approvals)
                violations.extend(violations_r9)
                reasons.extend(reasons_r9)
                conf_penalty += r9_penalty
            elif is_travel:
                # R3: 市内交通超标检测
                violations_r3, reasons_r3 = self._check_city_transport_over_standard(line, job_level, city_tier, nights)
                violations.extend(violations_r3)
                reasons.extend(reasons_r3)

        elif expense_type == 'LONG_TRANSPORT' and is_travel:
            # R4: 长途交通舱位超标检测
            violations_r4, reasons_r4 = self._check_long_transport_class(line, job_level, city_tier)
            violations.extend(violations_r4)
            reasons.extend(reasons_r4)

        elif expense_type == 'TAXI':
            # R9: 加班打车审批检测
            if '加班' in description or '加班' in line.get('purpose', ''):
                violations_r9, reasons_r9, r9_penalty = self._check_overtime_taxi_approval(line, approvals)
                violations.extend(violations_r9)
                reasons.extend(reasons_r9)
                conf_penalty += r9_penalty

        # R11: 差旅科目归集校验（部门应与科目类别一致，避免销售差旅挂管理费用）
        violations_r11, reasons_r11 = self._check_account_category(line, department)
        violations.extend(violations_r11)
        reasons.extend(reasons_r11)

        # R5: 发票抬头校验（以OCR票面为准）
        if invoice:
            violations_r5, reasons_r5 = self._check_invoice_title(invoice, ocr_data, line)
            violations.extend(violations_r5)
            reasons.extend(reasons_r5)

            # R6: 发票税号校验（以OCR票面为准）
            violations_r6, reasons_r6 = self._check_invoice_taxno(invoice, ocr_data, line)
            violations.extend(violations_r6)
            reasons.extend(reasons_r6)

            # R7: 金额一致性校验
            violations_r7, reasons_r7 = self._check_amount_match(line, invoice, ocr_data)
            violations.extend(violations_r7)
            reasons.extend(reasons_r7)

        return violations, reasons, flags, conf_penalty

    def _check_hotel_over_standard(self, line: dict, job_level: str, city_tier: str, nights: int) -> tuple:
        """R1: 住宿费超标检测"""
        violations = []
        reasons = []

        amount_fen = line.get('amountFen', 0)

        if nights <= 0:
            return violations, reasons

        # 获取标准
        cap_fen = self.travel_manager.get_hotel_cap(job_level, city_tier)

        # 「不得超过」按总额口径比较（amount > cap×nights 即违规），
        # 避免整除地板抹掉 0.5 元级超标（如 600.01/2晚 被地板成 300/晚）；
        # 展示单价用向上取整
        price_per_night_fen = -(-amount_fen // nights)
        
        if cap_fen > 0 and amount_fen > cap_fen * nights:
            violations.append(Violation(
                'OVER_STANDARD_HOTEL',
                f"{job_level}在{city_tier}地区住宿标准{(cap_fen // 100)}.{str(cap_fen % 100).zfill(2)}元/晚，实报{(price_per_night_fen // 100)}.{str(price_per_night_fen % 100).zfill(2)}元/晚"
            ))
            reasons.append(f"{job_level}在{city_tier}地区住宿标准{(cap_fen // 100)}.{str(cap_fen % 100).zfill(2)}元/晚，实报{(price_per_night_fen // 100)}.{str(price_per_night_fen % 100).zfill(2)}元/晚")

        return violations, reasons

    def _check_meal_over_standard(self, line: dict, job_level: str, city_tier: str, nights: int) -> tuple:
        """R2: 伙食补助超标检测"""
        violations = []
        reasons = []

        amount_fen = line.get('amountFen', 0)

        # 天数默认取nights+1（出差天数=住宿晚数+1），至少1天
        days = nights + 1 if nights > 0 else 1

        # 计算日均补助
        avg_per_day_fen = amount_fen // days

        # 获取标准
        cap_fen = self.travel_manager.get_meal_allowance(job_level, city_tier)

        if cap_fen > 0 and avg_per_day_fen > cap_fen:
            violations.append(Violation(
                'OVER_STANDARD_MEAL',
                f"{job_level}伙食补助标准{(cap_fen // 100)}.{str(cap_fen % 100).zfill(2)}元/天，实报{(avg_per_day_fen // 100)}.{str(avg_per_day_fen % 100).zfill(2)}元/天"
            ))
            reasons.append(f"{job_level}伙食补助标准{(cap_fen // 100)}.{str(cap_fen % 100).zfill(2)}元/天，实报{(avg_per_day_fen // 100)}.{str(avg_per_day_fen % 100).zfill(2)}元/天")

        return violations, reasons

    def _check_city_transport_over_standard(self, line: dict, job_level: str, city_tier: str, nights: int) -> tuple:
        """R3: 市内交通超标检测"""
        violations = []
        reasons = []

        amount_fen = line.get('amountFen', 0)

        # 天数默认取nights+1（出差天数=住宿晚数+1），至少1天
        days = nights + 1 if nights > 0 else 1

        # 获取标准
        cap_fen = self.travel_manager.get_city_transport(job_level, city_tier)
        total_cap_fen = cap_fen * days

        if cap_fen > 0 and amount_fen > total_cap_fen:
            violations.append(Violation(
                'OVER_STANDARD_CITY_TRANSPORT',
                f"市内交通补助标准{(cap_fen // 100)}.{str(cap_fen % 100).zfill(2)}元/天×{days}天={(total_cap_fen // 100)}.{str(total_cap_fen % 100).zfill(2)}元，实报{(amount_fen // 100)}.{str(amount_fen % 100).zfill(2)}元"
            ))
            reasons.append(f"市内交通补助标准{(cap_fen // 100)}.{str(cap_fen % 100).zfill(2)}元/天×{days}天={(total_cap_fen // 100)}.{str(total_cap_fen % 100).zfill(2)}元，实报{(amount_fen // 100)}.{str(amount_fen % 100).zfill(2)}元")

        return violations, reasons

    def _check_long_transport_class(self, line: dict, job_level: str, city_tier: str) -> tuple:
        """R4: 长途交通舱位超标检测"""
        violations = []
        reasons = []

        description = line.get('description', '')
        standard_class = self.travel_manager.get_long_distance_class(job_level, city_tier)

        # 根据标准判断舱位是否超标
        # 标准舱位映射:
        #   TRAIN_2ND=高铁二等座 → 一等座/商务座为超标
        #   TRAIN_1ST=高铁一等座 → 商务座为超标
        #   FLIGHT_ECON=经济舱   → 商务舱/头等舱为超标
        #   FLIGHT_BIZ=商务舱    → 头等舱为超标

        if standard_class == 'TRAIN_2ND':
            # STAFF标准为高铁二等座
            if '商务座' in description or '一等座' in description:
                violations.append(Violation(
                    'OVER_STANDARD_TRANSPORT_CLASS',
                    f"{job_level}长途交通标准为高铁二等座，实报{description}"
                ))
                reasons.append(f"{job_level}长途交通标准为高铁二等座，实报{description}")

        elif standard_class == 'TRAIN_1ST':
            # MANAGER标准为高铁一等座
            if '商务座' in description:
                violations.append(Violation(
                    'OVER_STANDARD_TRANSPORT_CLASS',
                    f"{job_level}长途交通标准为高铁一等座，实报{description}"
                ))
                reasons.append(f"{job_level}长途交通标准为高铁一等座，实报{description}")

        elif standard_class == 'FLIGHT_ECON':
            # DIRECTOR标准为经济舱
            if '商务舱' in description or '头等舱' in description:
                violations.append(Violation(
                    'OVER_STANDARD_TRANSPORT_CLASS',
                    f"{job_level}长途交通标准为经济舱，实报{description}"
                ))
                reasons.append(f"{job_level}长途交通标准为经济舱，实报{description}")

        elif standard_class == 'FLIGHT_BIZ':
            # EXECUTIVE标准为商务舱
            if '头等舱' in description:
                violations.append(Violation(
                    'OVER_STANDARD_TRANSPORT_CLASS',
                    f"{job_level}长途交通标准为商务舱，实报{description}"
                ))
                reasons.append(f"{job_level}长途交通标准为商务舱，实报{description}")

        return violations, reasons

    def _check_invoice_title(self, invoice: dict, ocr_data: dict = None, line: dict = None) -> tuple:
        """R5: 发票抬头校验（以OCR票面为准，严格匹配公司全称）"""
        violations = []
        reasons = []
        line_no = (line or {}).get('lineNo', '')
        inv_no = f"{invoice.get('invoiceCode', '')}/{invoice.get('invoiceNo', '')}"
        loc = f"费用行{line_no}发票{inv_no}" if line_no else f"发票{inv_no}"

        # 优先使用OCR票面数据
        if ocr_data and ocr_data.get('buyerName'):
            buyer_name = ocr_data['buyerName']
            source = "（OCR票面识别）"
        else:
            buyer_name = invoice.get('buyer', {}).get('name', '')
            source = ""

        buyer_name_norm = self._normalize_text(buyer_name)
        company_name_norm = self._normalize_text(COMPANY_NAME)
        basis = "（OCR票面识别）" if source else "（票面无购方信息，按系统录入判定）"

        # 严格比对公司全称（归一化后完全一致）
        if buyer_name_norm and buyer_name_norm != company_name_norm:
            violations.append(Violation(
                'INVOICE_TITLE_MISMATCH',
                f"{loc}抬头为「{buyer_name}」，与公司名称「{COMPANY_NAME}」不符{basis}"
            ))
            reasons.append(f"{loc}抬头为「{buyer_name}」，与公司名称「{COMPANY_NAME}」不符{basis}")

        return violations, reasons

    def _check_invoice_taxno(self, invoice: dict, ocr_data: dict = None, line: dict = None) -> tuple:
        """R6: 发票税号校验（以OCR票面为准，参考串X位不校验）"""
        violations = []
        reasons = []
        line_no = (line or {}).get('lineNo', '')
        inv_no = f"{invoice.get('invoiceCode', '')}/{invoice.get('invoiceNo', '')}"
        loc = f"费用行{line_no}发票{inv_no}" if line_no else f"发票{inv_no}"

        # 优先使用OCR票面数据
        if ocr_data and ocr_data.get('buyerTaxNo'):
            buyer_taxno = ocr_data['buyerTaxNo']
            source = "（OCR票面识别）"
        else:
            buyer_taxno = invoice.get('buyer', {}).get('taxNo', '')
            source = ""

        # 位置级比对：参考串 X 占位位不校验，其余位必须一致
        if not self._taxno_matches(buyer_taxno, COMPANY_TAX_NO):
            violations.append(Violation(
                'INVOICE_TAXNO_MISMATCH',
                f"{loc}购方税号为「{buyer_taxno}」，与公司税号「{COMPANY_TAX_NO}」不符{source}"
            ))
            reasons.append(f"{loc}购方税号为「{buyer_taxno}」，与公司税号「{COMPANY_TAX_NO}」不符{source}")

        return violations, reasons

    def _check_amount_match(self, line: dict, invoice: dict, ocr_data: dict = None) -> tuple:
        """R7: 金额一致性校验（以票面为准：OCR 票面金额优先）"""
        violations = []
        reasons = []

        line_amount_fen = line.get('amountFen', 0)
        invoice_total_fen = invoice.get('totalFen', 0)
        ocr_total_fen = self._parse_ocr_total_fen((ocr_data or {}).get('totalAmount'))

        # 票面金额优先（OCR 可解析时）；否则用系统录入值
        if ocr_total_fen is not None:
            compare_fen = ocr_total_fen
            compare_label = f"票面{(ocr_total_fen // 100)}.{str(ocr_total_fen % 100).zfill(2)}元"
        else:
            compare_fen = invoice_total_fen
            compare_label = f"票面{(invoice_total_fen // 100)}.{str(invoice_total_fen % 100).zfill(2)}元"

        if compare_fen > 0 and line_amount_fen != compare_fen:
            violations.append(Violation(
                'AMOUNT_MISMATCH',
                f"报销金额{(line_amount_fen // 100)}.{str(line_amount_fen % 100).zfill(2)}元，{compare_label}"
            ))
            reasons.append(f"报销金额{(line_amount_fen // 100)}.{str(line_amount_fen % 100).zfill(2)}元，{compare_label}")

        return violations, reasons

    @staticmethod
    def _parse_ocr_total_fen(value) -> Optional[int]:
        """把 OCR 的金额字符串（如 '1,292.00' / '788'）解析为分（整数）"""
        if not value:
            return None
        import re as _re
        s = _re.sub(r'[^0-9.]', '', str(value))
        if not s or s.count('.') > 1:
            return None
        try:
            return int(round(float(s) * 100))
        except (ValueError, TypeError):
            return None

    def _check_duplicate_invoice(self, claim_detail: dict) -> tuple:
        """R8: 重复报销检测"""
        violations = []
        reasons = []

        for line in claim_detail.get('lines', []):
            invoice = line.get('invoice')
            if invoice:
                key = f"{invoice['invoiceCode']}/{invoice['invoiceNo']}"
                claim_ids = self._invoice_index.get(key, [])

                # 如果同一张发票出现在多个报销单中
                if len(claim_ids) > 1:
                    other_claims = [cid for cid in claim_ids if cid != claim_detail['id']]
                    if other_claims:
                        violations.append(Violation(
                            'DUPLICATE_INVOICE',
                            f"发票{key}已在其他报销单中使用过"
                        ))
                        reasons.append(f"发票{key}已在其他报销单中使用过")

        return violations, reasons

    def _check_overtime_taxi_approval(self, line: dict, approvals: list) -> tuple:
        """R9: 加班打车审批检测"""
        violations = []
        reasons = []
        conf_penalty = 0.0

        # 检查是否有加班打车事前审批：
        # 审批记录带环节字段时，仅「事前」环节视为有效；无环节字段时按 action+关键词近似判定并降置信度
        has_approval = False
        stage_known = False
        for approval in approvals:
            action = approval.get('action', '')
            comment = approval.get('comment', '')
            stage = approval.get('stage') or approval.get('stageName') or approval.get('环节') or ''
            if stage:
                stage_known = True
                if '事前' in str(stage):
                    has_approval = True
                    break
                continue
            if action == 'SPECIAL_APPROVE':
                has_approval = True
                break
            if action == 'APPROVE' and any(
                kw in comment for kw in ('加班', '打车', '出租车', '用车')
            ):
                has_approval = True
                break

        if has_approval and not stage_known:
            # 无环节字段：无法确认是否「事前」，降低置信度提示人工留意
            conf_penalty = 0.1

        if not has_approval:
            violations.append(Violation(
                'MISSING_APPROVAL_OVERTIME_TAXI',
                "《费用报销管理办法 V3.2》第十三条要求加班打车须事前审批，本单无有效事前审批记录"
            ))
            reasons.append(violations[-1].reason)

        return violations, reasons, conf_penalty

    def _check_account_category(self, line: dict, department: str) -> tuple:
        """R11: 差旅科目归集校验
        访谈口径（周晓 zx-061）：销售部门差旅应挂销售费用、研发挂研发费用、其余挂管理费用。
        仅校验差旅类费用行，避免误伤办公费/招待费等其他科目的正常归集。
        """
        if line.get('expenseType') not in ('HOTEL', 'MEAL', 'CITY_TRANSPORT', 'LONG_TRANSPORT'):
            return [], []
        gl = line.get('glAccount') or {}
        gl_name = gl.get('name', '')
        if not gl_name:
            return [], []
        # 只对挂在「差旅费」科目上的行做部门归集校验，
        # 避免把业务招待费/市内交通费等正常归集误报为科目错误
        if '差旅费' not in gl_name:
            return [], []

        dept = department or ''
        if '销售' in dept or '售后' in dept:
            expected = '销售费用'
        elif '研发' in dept:
            expected = '研发费用'
        else:
            expected = '管理费用'

        if expected in gl_name:
            return [], []

        violation = Violation(
            'ACCOUNT_MISMATCH',
            f"费用行{line.get('lineNo')}科目归集错误：{dept or '未填部门'}差旅应归集至"
            f"「{expected}」，实为「{gl_name}」（《费用报销管理办法 V3.2》科目归集要求）",
        )
        return [violation], [violation.reason]

    def _calculate_decision_strength(self, result: str, violations: list, flag_reasons: list) -> float:
        """计算规则决策强度（0~1），不是统计学概率或校准置信度。"""
        if result == 'FLAG':
            return 0.5
        elif result == 'REJECT':
            # 违规越多，置信度越高
            base_confidence = 0.7
            confidence = min(base_confidence + len(violations) * 0.05, 0.95)
            return confidence
        else:
            # APPROVE
            return 0.9

    # 兼容已有内部调用方；新代码应使用语义明确的 decision_strength 命名。
    def _calculate_confidence(self, result: str, violations: list, flag_reasons: list) -> float:
        return self._calculate_decision_strength(result, violations, flag_reasons)


if __name__ == "__main__":
    import os
    from core.client import QihengClient

    api_key = os.environ['QIHENG_API_KEY']
    client = QihengClient(api_key=api_key)

    from data.travel_data import TravelDataManager
    travel_manager = TravelDataManager(client)
    travel_manager.load_data()

    auditor = Auditor(travel_manager)

    # 测试审核单个报销单
    print("=== 测试审核引擎 ===")

    # 获取一个报销单详情
    claim_id = 'BX-005767'  # 住宿费超标测试用例
    try:
        claim_detail = client.expense_claims_get(claim_id)
        approvals = client.approvals_for_claim(claim_id)

        # 构建发票索引（需要先拉取所有报销单）
        print("\n正在构建发票索引...")
        claims = list(client.expense_claims_iterate(status="PENDING"))
        auditor.build_invoice_index(claims)

        # 审核
        print(f"\n审核报销单 {claim_id}...")
        result = auditor.audit_claim(claim_detail, approvals)
        print(f"结论: {result.result}")
        print(f"违规: {[v.code for v in result.violations]}")
        print(f"理由: {result.reasons}")
        print(f"置信度: {result.confidence}")

        # 测试另一个用例
        claim_id2 = 'BX-005699'  # 伙食补助超标测试用例
        claim_detail2 = client.expense_claims_get(claim_id2)
        approvals2 = client.approvals_for_claim(claim_id2)

        print(f"\n审核报销单 {claim_id2}...")
        result2 = auditor.audit_claim(claim_detail2, approvals2)
        print(f"结论: {result2.result}")
        print(f"违规: {[v.code for v in result2.violations]}")
        print(f"理由: {result2.reasons}")

    except (ValueError, KeyError, QihengError) as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
