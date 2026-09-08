"""m3-ai-review Skill 的 3 条测试：正常流程 / 失败场景 / 边界场景。

运行：python -B test_m3_ai_review.py（需 DeepSeek Key，即 LLM_REVIEW_API_KEY；
T1/T2 为真实 LLM 调用，T3 为结构校验单元测试）。
覆盖作业要求：Skill 原型至少展示一个正常流程和一个失败或边界场景。
"""

import sys

from core.llm_reviewer import LLMReviewer, _valid_m3_review


def _review(payload, keywords):
    """真实调用 DeepSeek 按 skill 工作流复核一条异常"""
    reviewer = LLMReviewer()
    return reviewer.review_m3_anomaly(payload, keywords)


def t1_normal():
    """T1 正常流程：明确违规（分公司抬头）→ 期望 CONFIRM（异常成立）"""
    payload = {
        "type": "TITLE_WRONG",
        "invoiceId": "INV-007889",
        "basis": "发票抬头为「苏州启衡精密制造有限公司」，与公司全称不符",
        "invoice": {"buyerName": "苏州启衡精密制造有限公司"},
    }
    out = _review(payload, {"抬头", "发票", "全称", "分公司"})
    assert out.get("verdict") == "CONFIRM", out
    assert 0 <= out.get("confidence", 0) <= 1
    assert out.get("reasons")
    return out


def t2_false_alarm():
    """T2 失败场景：规则误报（办公采购 13% 普票，制度合法）→ 期望 FALSE_ALARM 或 DOUBT"""
    payload = {
        "type": "TAX_RATE_WRONG",
        "invoiceId": "INV-100001",
        "basis": "增值税普通发票应适用 6% 税率，实为 13%",
        "invoice": {"invoiceKind": "VAT_GENERAL", "taxRate": 0.13},
    }
    out = _review(payload, {"税率", "适用", "增值税", "发票"})
    assert out.get("verdict") in ("FALSE_ALARM", "DOUBT"), out
    assert out.get("reasons")
    return out


def t3_boundary():
    """T3 边界场景：
    ① 结构校验拦截非法输出（确定性单元测试）；
    ② 异常信息缺失（无 basis/空发票）→ 不崩溃，输出合法 verdict（LLM 降级为 DOUBT 或按核心口径判定）。
    """
    assert _valid_m3_review({"verdict": "NOPE", "reasons": [], "confidence": 0.5}) is False
    assert _valid_m3_review({"verdict": "CONFIRM", "reasons": ["理由"], "confidence": 0.9}) is True
    assert _valid_m3_review({"verdict": "DOUBT", "reasons": ["x"], "confidence": 1.2}) is False

    out = _review(
        {"type": "OTHER", "invoiceId": "", "basis": "", "invoice": {}},
        {"发票", "合规"},
    )
    assert out.get("verdict") in ("CONFIRM", "DOUBT", "FALSE_ALARM"), out
    return out


if __name__ == "__main__":
    print("T1 正常流程(违规成立)   :", t1_normal())
    print("T2 失败场景(规则误报)   :", t2_false_alarm())
    print("T3 边界(非法输出拦截)   : 非法 verdict→False, 合法→True, 超界置信度→False")
    print("T3 边界(缺字段样例)     :", t3_boundary())
    print("\n3 条测试全部通过 [OK]")
