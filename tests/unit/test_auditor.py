"""Auditor 规则引擎单元测试：11 条规则正反用例，纯离线（不依赖 ERP）。

差旅标准为测试夹具注入（数值与制度静态块一致量级），不真实调用 travel-standards API。
"""

import pytest

from core.auditor import Auditor
from data.travel_data import TravelDataManager

COMPANY_NAME = "启衡精密制造有限公司"
COMPANY_TAX_NO = "91320594MA1TXXXX7Q"


def make_travel_manager() -> TravelDataManager:
    """构造离线 TravelDataManager：直接填充标准/城市缓存，绕过 ERP。"""
    tm = TravelDataManager(client=None)
    tm._standards = [
        {"jobLevel": "STAFF", "cityTier": "TIER1", "hotelCapPerNightFen": 50000,
         "mealAllowancePerDayFen": 10000, "cityTransportPerDayFen": 2000,
         "longDistanceClass": "TRAIN_2ND"},
        {"jobLevel": "STAFF", "cityTier": "TIER2", "hotelCapPerNightFen": 42000,
         "mealAllowancePerDayFen": 10000, "cityTransportPerDayFen": 2000,
         "longDistanceClass": "TRAIN_2ND"},
        {"jobLevel": "STAFF", "cityTier": "TIER3", "hotelCapPerNightFen": 30000,
         "mealAllowancePerDayFen": 8000, "cityTransportPerDayFen": 1500,
         "longDistanceClass": "TRAIN_2ND"},
        {"jobLevel": "MANAGER", "cityTier": "TIER2", "hotelCapPerNightFen": 55000,
         "mealAllowancePerDayFen": 15000, "cityTransportPerDayFen": 3000,
         "longDistanceClass": "TRAIN_1ST"},
        {"jobLevel": "DIRECTOR", "cityTier": "TIER2", "hotelCapPerNightFen": 80000,
         "mealAllowancePerDayFen": 20000, "cityTransportPerDayFen": 4000,
         "longDistanceClass": "FLIGHT_ECON"},
    ]
    tm._build_standards_cache()
    tm._city_tiers = [
        {"name": "上海", "tier": "TIER1"},
        {"name": "成都", "tier": "TIER2"},
        {"name": "潍坊", "tier": "TIER3"},
    ]
    tm._build_city_cache()
    return tm


@pytest.fixture
def auditor() -> Auditor:
    return Auditor(make_travel_manager())


def make_line(expense_type, amount_fen, description="", invoice=None,
              attachment=None, line_no=1, gl_account=None, purpose=""):
    line = {
        "lineNo": line_no,
        "expenseType": expense_type,
        "amountFen": amount_fen,
        "description": description,
        "purpose": purpose,
    }
    if invoice is not None:
        line["invoice"] = invoice
    if attachment is not None:
        line["attachment"] = attachment
    if gl_account is not None:
        line["glAccount"] = gl_account
    return line


def make_claim(lines, claim_id="BX-TEST-1", job_level="STAFF",
               department="财务部", claim_type="TRAVEL",
               city="成都", nights=2):
    return {
        "id": claim_id,
        "jobLevel": job_level,
        "departmentName": department,
        "claimType": claim_type,
        "trip": {"city": city, "nights": nights},
        "lines": lines,
    }


def invoice(code="CODE1", no="1001", total_fen=None, buyer=COMPANY_NAME, tax_no=COMPANY_TAX_NO):
    inv = {"invoiceCode": code, "invoiceNo": no,
           "buyer": {"name": buyer, "taxNo": tax_no}, "seller": {"name": "某酒店"}}
    if total_fen is not None:
        inv["totalFen"] = total_fen
    return inv


ATT_OK = {"id": "ATT-1", "migrated": True}
ATT_UNMIGRATED = {"id": "ATT-1", "migrated": False}


def codes(result):
    return {v.code for v in result.violations}


# ---------- R1 住宿超标 ----------

def test_r1_hotel_over_standard_reject(auditor):
    c = make_claim([make_line("HOTEL", 100000, "住宿两晚")])  # 500元/晚 > 420
    r = auditor.audit_claim(c, [])
    assert r.result == "REJECT"
    assert "OVER_STANDARD_HOTEL" in codes(r)


def test_r1_hotel_within_standard_approve(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿两晚")])  # 400元/晚 ≤ 420
    r = auditor.audit_claim(c, [])
    assert r.result == "APPROVE"
    assert not r.violations


def test_r1_unknown_city_flags_for_manual(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿两晚")], city="拉萨")
    r = auditor.audit_claim(c, [])
    assert r.result == "FLAG"
    assert any("不在城市档次表" in s for s in r.reasons)


# ---------- R2 伙食补助 ----------

def test_r2_meal_over_standard(auditor):
    # 2 晚 → 3 天，330 元 / 3 = 110 元/天 > 100 元标准
    c = make_claim([make_line("MEAL", 33000, "伙食")])
    r = auditor.audit_claim(c, [])
    assert "OVER_STANDARD_MEAL" in codes(r)


def test_r2_meal_within_standard(auditor):
    c = make_claim([make_line("MEAL", 30000, "伙食")])  # 100 元/天 = 标准
    r = auditor.audit_claim(c, [])
    assert "OVER_STANDARD_MEAL" not in codes(r)


def test_r2_daily_claim_not_subject_to_travel_standard(auditor):
    c = make_claim([make_line("MEAL", 30000, "工作餐")],
                   claim_type="DAILY", nights=0)
    r = auditor.audit_claim(c, [])
    assert r.result == "APPROVE"


# ---------- R3 市内交通超标 + R9 打车路由回归 ----------

def test_r3_city_transport_over_standard(auditor):
    # 3 天 × 20 元 = 60 元上限，报 70 元
    c = make_claim([make_line("CITY_TRANSPORT", 7000, "市内公共交通")])
    r = auditor.audit_claim(c, [])
    assert "OVER_STANDARD_CITY_TRANSPORT" in codes(r)


def test_r3_city_transport_within_standard(auditor):
    c = make_claim([make_line("CITY_TRANSPORT", 5000, "市内公共交通")])
    r = auditor.audit_claim(c, [])
    assert r.result == "APPROVE"


def test_travel_taxi_description_routes_to_r3_not_r9(auditor):
    """回归（设计文档 §3.6①）：差旅单描述含「打车」但无加班语境时，
    必须走 R3 市内交通标准校验，不得误报 R9 加班打车缺审批。"""
    compliant = make_claim([make_line("CITY_TRANSPORT", 5000, "出差打车")])
    r = auditor.audit_claim(compliant, [])
    assert r.result == "APPROVE"
    assert "MISSING_APPROVAL_OVERTIME_TAXI" not in codes(r)

    over = make_claim([make_line("CITY_TRANSPORT", 7000, "出差打车")])
    r2 = auditor.audit_claim(over, [])
    assert codes(r2) == {"OVER_STANDARD_CITY_TRANSPORT"}


def test_r9_overtime_taxi_requires_pre_approval(auditor):
    c = make_claim([make_line("CITY_TRANSPORT", 3000, "加班打车回家")])
    r = auditor.audit_claim(c, [])
    assert "MISSING_APPROVAL_OVERTIME_TAXI" in codes(r)


def test_r9_overtime_taxi_with_special_approve_ok(auditor):
    c = make_claim([make_line("CITY_TRANSPORT", 3000, "加班打车回家")])
    r = auditor.audit_claim(c, [{"action": "SPECIAL_APPROVE"}])
    assert "MISSING_APPROVAL_OVERTIME_TAXI" not in codes(r)


def test_r9_overtime_taxi_pre_stage_approval_ok(auditor):
    c = make_claim([make_line("CITY_TRANSPORT", 3000, "加班打车回家")])
    r = auditor.audit_claim(c, [{"action": "APPROVE", "stage": "事前审批", "comment": ""}])
    assert "MISSING_APPROVAL_OVERTIME_TAXI" not in codes(r)
    assert r.result == "APPROVE"
    assert r.confidence == pytest.approx(0.9)  # 有环节字段，无置信度惩罚


def test_r9_overtime_taxi_keyword_approval_penalized(auditor):
    """无环节字段、按备注关键词近似判定：不违规但置信度下降 0.1。"""
    c = make_claim([make_line("CITY_TRANSPORT", 3000, "加班打车回家")])
    r = auditor.audit_claim(c, [{"action": "APPROVE", "comment": "同意加班用车"}])
    assert r.result == "APPROVE"
    assert r.confidence == pytest.approx(0.8)


# ---------- R4 长途舱位 ----------

def test_r4_long_transport_over_class(auditor):
    c = make_claim([make_line("LONG_TRANSPORT", 55000, "高铁一等座")])  # STAFF 标准二等座
    r = auditor.audit_claim(c, [])
    assert "OVER_STANDARD_TRANSPORT_CLASS" in codes(r)


def test_r4_long_transport_within_class(auditor):
    c = make_claim([make_line("LONG_TRANSPORT", 55000, "高铁二等座")])
    r = auditor.audit_claim(c, [])
    assert "OVER_STANDARD_TRANSPORT_CLASS" not in codes(r)


def test_r4_manager_first_class_allowed(auditor):
    c = make_claim([make_line("LONG_TRANSPORT", 55000, "高铁一等座")],
                   job_level="MANAGER")
    r = auditor.audit_claim(c, [])
    assert "OVER_STANDARD_TRANSPORT_CLASS" not in codes(r)


# ---------- R5/R6/R7 票面校验 ----------

def test_r5_title_mismatch_by_ocr(auditor):
    inv = invoice()
    ocr = {"ATT-1": {"buyerName": "别的公司有限公司", "buyerTaxNo": COMPANY_TAX_NO,
                      "totalAmount": "800.00"}}
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              invoice=inv, attachment=ATT_OK)])
    r = auditor.audit_claim(c, [], ocr_results=ocr)
    assert "INVOICE_TITLE_MISMATCH" in codes(r)


def test_r5_title_ok_with_company_name(auditor):
    ocr = {"ATT-1": {"buyerName": COMPANY_NAME, "buyerTaxNo": COMPANY_TAX_NO,
                     "totalAmount": "800.00"}}
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              invoice=invoice(), attachment=ATT_OK)])
    r = auditor.audit_claim(c, [], ocr_results=ocr)
    assert "INVOICE_TITLE_MISMATCH" not in codes(r)


def test_r6_taxno_skeleton_match_ignores_x_count(auditor):
    """税号 X 脱敏位数量不一致但骨架一致：不判违规。"""
    ocr = {"ATT-1": {"buyerName": COMPANY_NAME,
                     "buyerTaxNo": "91320594MA1TXXXXXX7Q",  # 6 个 X
                     "totalAmount": "800.00"}}
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              invoice=invoice(), attachment=ATT_OK)])
    r = auditor.audit_claim(c, [], ocr_results=ocr)
    assert "INVOICE_TAXNO_MISMATCH" not in codes(r)


def test_r6_taxno_skeleton_mismatch_detected(auditor):
    ocr = {"ATT-1": {"buyerName": COMPANY_NAME,
                     "buyerTaxNo": "91320594MA1WXXXX7Q",  # T→W，骨架不同
                     "totalAmount": "800.00"}}
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              invoice=invoice(), attachment=ATT_OK)])
    r = auditor.audit_claim(c, [], ocr_results=ocr)
    assert "INVOICE_TAXNO_MISMATCH" in codes(r)


def test_r7_amount_mismatch_by_ocr(auditor):
    ocr = {"ATT-1": {"buyerName": COMPANY_NAME, "buyerTaxNo": COMPANY_TAX_NO,
                     "totalAmount": "600.00"}}
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              invoice=invoice(), attachment=ATT_OK)])
    r = auditor.audit_claim(c, [], ocr_results=ocr)
    assert "AMOUNT_MISMATCH" in codes(r)


def test_r7_amount_falls_back_to_system_value_without_ocr(auditor):
    c = make_claim([make_line("HOTEL", 50000, "住宿",
                              invoice=invoice(total_fen=60000), attachment=ATT_OK)])
    r = auditor.audit_claim(c, [])
    assert "AMOUNT_MISMATCH" in codes(r)


# ---------- R8 重复报销 ----------

def test_r8_duplicate_invoice_detected(auditor):
    auditor.set_invoice_index({"CODE1/1001": ["BX-TEST-1", "BX-OTHER"]})
    c = make_claim([make_line("HOTEL", 80000, "住宿", invoice=invoice())])
    r = auditor.audit_claim(c, [])
    assert "DUPLICATE_INVOICE" in codes(r)


def test_r8_single_use_invoice_ok(auditor):
    auditor.set_invoice_index({"CODE1/1001": ["BX-TEST-1"]})
    c = make_claim([make_line("HOTEL", 80000, "住宿", invoice=invoice())])
    r = auditor.audit_claim(c, [])
    assert "DUPLICATE_INVOICE" not in codes(r)


# ---------- R10 缺附件 ----------

def test_r10_missing_attachment_reject(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿", invoice=invoice())])
    r = auditor.audit_claim(c, [])
    assert "MISSING_ATTACHMENT" in codes(r)
    assert r.result == "REJECT"


def test_r10_missing_attachment_with_explanation_flags(auditor):
    c = make_claim([make_line("HOTEL", 80000, "发票丢失，已附情况说明",
                              invoice=invoice())])
    r = auditor.audit_claim(c, [])
    assert r.result == "FLAG"


def test_unmigrated_attachment_flags_for_manual(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              invoice=invoice(), attachment=ATT_UNMIGRATED)])
    r = auditor.audit_claim(c, [])
    assert r.result == "FLAG"
    assert any("影像不可用" in s for s in r.reasons)


# ---------- R11 科目归集 ----------

def test_r11_account_mismatch_sales_department(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              gl_account={"name": "管理费用-差旅费"})],
                   department="销售部")
    r = auditor.audit_claim(c, [])
    assert "ACCOUNT_MISMATCH" in codes(r)


def test_r11_account_correct_sales_expense_ok(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              gl_account={"name": "销售费用-差旅费"})],
                   department="销售部")
    r = auditor.audit_claim(c, [])
    assert "ACCOUNT_MISMATCH" not in codes(r)


def test_r11_research_department_expects_research_expense(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿",
                              gl_account={"name": "管理费用-差旅费"})],
                   department="研发中心")
    r = auditor.audit_claim(c, [])
    assert "ACCOUNT_MISMATCH" in codes(r)
    assert any("研发费用" in s for s in r.reasons)


def test_r11_entertainment_not_subject(auditor):
    c = make_claim([make_line("ENTERTAIN", 80000, "业务招待",
                              gl_account={"name": "管理费用-业务招待费"})],
                   department="销售部")
    r = auditor.audit_claim(c, [])
    assert "ACCOUNT_MISMATCH" not in codes(r)


# ---------- 特批豁免 ----------

def test_special_approval_exempts_over_standard(auditor):
    c = make_claim([make_line("HOTEL", 100000, "住宿两晚")])  # 超标
    r = auditor.audit_claim(c, [{"action": "SPECIAL_APPROVE", "comment": "总监特批"}])
    assert r.result == "APPROVE"
    assert any("特批" in s for s in r.reasons)


def test_special_approval_does_not_exempt_other_violations(auditor):
    inv = invoice(buyer="别的公司有限公司")
    c = make_claim([make_line("HOTEL", 100000, "住宿", invoice=inv)])
    r = auditor.audit_claim(c, [{"action": "SPECIAL_APPROVE"}])
    assert r.result == "REJECT"
    assert "INVOICE_TITLE_MISMATCH" in codes(r)
    assert "OVER_STANDARD_HOTEL" not in codes(r)


# ---------- 置信度 ----------

def test_confidence_reject_scales_with_violations(auditor):
    c = make_claim([
        make_line("HOTEL", 100000, "住宿两晚"),
        make_line("MEAL", 33000, "伙食"),
    ])
    r = auditor.audit_claim(c, [])
    assert r.result == "REJECT"
    assert r.confidence == pytest.approx(0.7 + 2 * 0.05)


def test_confidence_flag_is_half(auditor):
    c = make_claim([make_line("HOTEL", 80000, "住宿两晚")], city="拉萨")
    r = auditor.audit_claim(c, [])
    assert r.result == "FLAG"
    assert r.confidence == pytest.approx(0.5)


def test_rule_score_is_exposed_as_decision_strength_not_probability(auditor):
    c = make_claim([])
    r = auditor.audit_claim(c, [])
    assert r.decision_strength == pytest.approx(0.9)
    assert r.to_dict()["decisionStrength"] == pytest.approx(0.9)
