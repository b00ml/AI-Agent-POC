"""m3-invoice-audit Skill 的 3 条测试：正常流程 / 失败场景 / 边界场景。

运行：python -B test_m3_skill.py（无第三方依赖，Python 3.10+）
覆盖作业要求：Skill 原型至少展示一个正常流程和一个失败或边界场景。
"""

from check_m3_result import validate


def _fixture_valid() -> dict:
    """正常夹具：覆盖全部 6 类 issue + 精确/疑似重复，全部带 basis。"""
    return {
        "duplicateInvoices": [
            {
                "invoiceCode": "C1",
                "invoiceNo": "N1",
                "claimIds": ["BX-1", "BX-2"],
                "suspected": False,
                "basis": "同一发票代码+号码出现 2 次以上（V3.2 第十七条）",
            },
            {
                "invoiceCode": "C2",
                "invoiceNo": "N2",
                "otherCodes": ["C3"],
                "claimIds": [],
                "suspected": True,
                "basis": "同一发票号码出现在多个代码下，需人工确认",
            },
        ],
        "invoiceIssues": [
            {"invoiceId": "I1", "issue": "TITLE_WRONG", "basis": "抬头≠公司全称"},
            {"invoiceId": "I2", "issue": "TAXNO_WRONG", "basis": "税号骨架不一致"},
            {"invoiceId": "I3", "issue": "TAX_RATE_WRONG", "basis": "税率与票种不符"},
            {"invoiceId": "I4", "issue": "CONSECUTIVE_NO", "basis": "同代码≥3连号"},
            {
                "invoiceId": "I5",
                "issue": "SUPPLIER_DUP",
                "invoiceIds": ["I5", "I6"],
                "basis": "同税号下多个不同名称，疑似重复建档",
            },
        ],
    }


def t1_normal() -> list:
    """T1 正常流程：6 类 issue + 精确/疑似重复齐全，校验通过。"""
    problems = validate(_fixture_valid())
    assert not problems, problems
    return problems


def t2_fail_missing_basis() -> list:
    """T2 失败场景：票面问题缺判断依据（basis）→ 校验报错。"""
    data = _fixture_valid()
    data["invoiceIssues"][0]["basis"] = ""
    problems = validate(data)
    assert problems and "缺判断依据" in problems[0], problems
    return problems


def t3_boundary() -> tuple:
    """T3 边界场景：
    ① 未知 issue 类型 → 报错（门禁拦截）；
    ② 疑似重复无关联单据（suspected=true, claimIds=[]）→ 不误报。
    """
    data = _fixture_valid()
    data["invoiceIssues"][1]["issue"] = "UNKNOWN_TYPE"
    unknown = validate(data)
    assert unknown and "未知 issue 类型" in unknown[0], unknown

    dups = _fixture_valid()["duplicateInvoices"]
    suspect = [d for d in dups if d.get("suspected")][0]
    assert suspect["claimIds"] == []
    assert "缺关联单据" not in validate({"duplicateInvoices": [suspect], "invoiceIssues": []})
    return unknown, suspect


if __name__ == "__main__":
    print("T1 正常流程(校验通过)          :", t1_normal())
    print("T2 失败场景(缺basis被拦截)     :", t2_fail_missing_basis())
    unknown, suspect = t3_boundary()
    print("T3 边界(未知issue被拦截)       :", unknown)
    print("T3 边界(疑似重复无单据不误报)  :", suspect)
    print("\n3 条测试全部通过 [OK]")
