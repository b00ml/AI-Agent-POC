"""M4 银行对账纯函数测试：例外原因分类 + GBK 流水解析（离线，不依赖 ERP）。"""

from core.m4_processor import (
    M4Processor,
    UNIDENTIFIED_CATEGORY_LABELS,
    _categorize_unidentified,
    parse_bank_csv,
    parse_bank_csv_detailed,
)


def test_categorize_no_customer():
    assert _categorize_unidentified(
        "户名「某某公司」无对应未清应收（可能为无头款/个人账户/别名未登记）"
    ) == "NO_CUSTOMER"


def test_categorize_amount_mismatch():
    assert _categorize_unidentified("金额不匹配或候选不唯一，需人工认领") == "AMOUNT_OR_CANDIDATE"


def test_categorize_non_positive():
    assert _categorize_unidentified("金额非正") == "NON_POSITIVE"


def test_categorize_unknown_falls_back_to_amount():
    assert _categorize_unidentified("其他奇怪原因") == "AMOUNT_OR_CANDIDATE"


def test_categorize_budget_and_duplicate_as_distinct_operational_exceptions():
    assert _categorize_unidentified("组合搜索超过上限（2000），需人工认领") == "AMBIGUOUS_CANDIDATE"
    assert _categorize_unidentified("交易流水号重复，需人工核验后再认领") == "DUPLICATE_TXN"


def test_all_categories_have_labels():
    for cat in (
        "NO_CUSTOMER", "AMOUNT_OR_CANDIDATE", "AMBIGUOUS_CANDIDATE",
        "DUPLICATE_TXN", "NON_POSITIVE",
    ):
        assert cat in UNIDENTIFIED_CATEGORY_LABELS


def test_parse_bank_csv_gbk(tmp_path):
    """GBK 流水：第 6 行表头，只取贷方（收款）行。"""
    rows = [
        "2026-07-01,摘要,借贷方向,金额,?,?,?,?,流水号,备注".replace("借贷方向", "借贷"),
    ]
    header = ["", "", "收付", "交易金额", "", "对方户名", "", "", "", "交易流水号"]
    body_credit = ["20260701", "转账", "贷", '"1,234.56"', "", "客户A公司", "", "", "", "TXN001"]
    body_debit = ["20260702", "付款", "借", '"500.00"', "", "供应商B", "", "", "", "TXN002"]
    body_bad = ["20260703", "转账", "贷", "abc", "", "客户C", "", "", "", "TXN003"]

    lines = [""] * 5 + [",".join(header)] + [
        ",".join(body_credit), ",".join(body_debit), ",".join(body_bad), "",
    ]
    p = tmp_path / "flow.csv"
    p.write_text("\n".join(lines) + "\n", encoding="gbk")

    credits = parse_bank_csv(str(p))
    assert len(credits) == 1
    assert credits[0]["txnId"] == "TXN001"
    assert credits[0]["amountFen"] == 123456
    assert credits[0]["payer"] == "客户A公司"
    assert rows  # 占位，保持结构


def test_parse_bank_csv_detects_utf8_header_by_name_and_keeps_errors(tmp_path):
    p = tmp_path / "utf8-flow.csv"
    p.write_text(
        "导出说明\n交易日期,交易金额,对方户名,借贷方向,交易流水号\n"
        "2026-07-01,12.34,客户A,贷,UTF8-1\n"
        "2026-07-02,not-a-number,客户B,贷,UTF8-2\n",
        encoding="utf-8",
    )

    parsed = parse_bank_csv_detailed(str(p))

    assert parsed["encoding"] == "utf-8-sig"
    assert parsed["credits"] == [{
        "txnId": "UTF8-1", "date": "2026-07-01", "amountFen": 1234,
        "payer": "客户A", "sourceFile": str(p), "sourceRow": 3,
    }]
    assert parsed["parseErrors"][0]["reason"] == "贷方金额无法解析"


def test_parse_bank_csv_reports_duplicate_transaction_ids(tmp_path):
    p = tmp_path / "duplicate.csv"
    p.write_text(
        "日期,收付,交易金额,对方户名,交易流水号\n"
        "2026-07-01,贷,1.00,客户A,TXN-DUP\n"
        "2026-07-02,贷,2.00,客户A,TXN-DUP\n",
        encoding="utf-8",
    )

    assert parse_bank_csv_detailed(str(p))["duplicateTxnIds"] == ["TXN-DUP"]


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def _paginate(self, _path, _params):
        return iter(self.rows)


def test_m4_candidate_budget_routes_to_ambiguous_exception(tmp_path, monkeypatch):
    import core.m4_processor as m4

    monkeypatch.setattr(m4, "MAX_CANDIDATES", 2)
    (tmp_path / "flow.csv").write_text(
        "日期,收付,交易金额,对方户名,交易流水号\n2026-07-01,贷,50.00,客户A,TXN-1\n",
        encoding="utf-8",
    )
    rows = [
        {"id": f"AR-{index}", "status": "OPEN", "customerName": "客户A", "outstandingFen": 1000}
        for index in range(3)
    ]

    result = M4Processor(_FakeClient(rows)).run(str(tmp_path))

    assert result["matches"] == []
    assert result["unidentified"][0]["reason"] == "付款人候选应收超过上限（2），需人工认领"
    assert result["statistics"]["unidentifiedByReason"] == [{
        "category": "AMBIGUOUS_CANDIDATE",
        "label": UNIDENTIFIED_CATEGORY_LABELS["AMBIGUOUS_CANDIDATE"],
        "count": 1,
    }]


def test_m4_does_not_guess_partial_payment_without_payment_history(tmp_path):
    (tmp_path / "flow.csv").write_text(
        "日期,收付,交易金额,对方户名,交易流水号\n"
        "2026-07-01,贷,50.00,客户A,TXN-PARTIAL\n",
        encoding="utf-8",
    )
    rows = [{
        "id": "AR-1", "status": "OPEN", "customerName": "客户A", "outstandingFen": 10000,
    }]

    result = M4Processor(_FakeClient(rows)).run(str(tmp_path))

    assert result["matches"] == []
    assert result["unidentified"][0]["txnId"] == "TXN-PARTIAL"
