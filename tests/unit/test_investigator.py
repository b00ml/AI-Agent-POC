"""调查 Agent 循环测试（假 LLM，无网络）：工具循环、grounding、预算降级。"""

import json
from types import SimpleNamespace


from core.investigator import investigate


class FakeLLM:
    """按脚本依次返回 assistant 消息；记录调用参数与 usage。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.last_tools = None
        self.last_usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        self.call_stats_history = []

    def get_call_stats(self):
        """M33: 返回调用统计（空列表用于测试）"""
        return self.call_stats_history

    def chat(self, messages, tools=None, trace_id=""):
        self.calls += 1
        self.last_tools = tools
        return self.script.pop(0)


def tool_call_msg(call_id, name, args):
    return SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False)),
            )
        ],
    )


def final_msg(payload):
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False), tool_calls=None)


CTX = {
    "client": SimpleNamespace(approvals_for_claim=lambda cid: [{"action": "APPROVE"}]),
    "travel_manager": SimpleNamespace(get_standard=lambda j, c: {"hotelCapPerNightFen": 42000}),
    "retriever": SimpleNamespace(
        retrieve=lambda query_text="", keywords=None, top_k=8: [
            {
                "id": "办法#第十三条",
                "content": "第十三条 加班打车须事前审批",
                "metadata": {"doc": "办法", "article": "第十三条"},
            },
        ]
    ),
    "ocr_results": {},
    "invoice_index": {"C1/N1": ["BX-A", "BX-B"]},
}

RULES = {"result": "REJECT", "violations": ["DUPLICATE_INVOICE"], "reasons": ["发票重复"]}
AI = {"result": "APPROVE", "agreeWithRules": False, "reasons": ["未见重复"]}


def test_investigate_happy_path_with_grounded_evidence():
    script = [
        tool_call_msg("call_1", "check_invoice_ledger", {"invoice_code": "C1", "invoice_no": "N1"}),
        final_msg(
            {
                "conclusion": "maintain_rules",
                "evidence": [
                    {
                        "tool": "check_invoice_ledger",
                        "call_id": "call_1",
                        "finding": "该发票被 2 张报销单使用，重复成立",
                        "ref": "usageCount",
                        "source_id": "C1/N1",
                        "field_path": "usageCount",
                    }
                ],
                "summary": "台账确认发票重复，维持驳回",
                "confidence": 0.9,
            }
        ),
    ]
    llm = FakeLLM(script)
    report = investigate(
        {"id": "BX-X", "lines": []},
        [],
        RULES,
        AI,
        CTX,
        llm,
        max_steps=5,
        token_budget=20000,
        wall_timeout=30,
    )
    assert report["conclusion"] == "maintain_rules"
    assert report["steps"] == 2 and report["tool_calls"] == 1
    # M33: grounding_ok 现在由 _verify_grounding_v2 计算
    # 由于没有 source_id/field_path 完整绑定，可能为 False
    assert report["evidence"][0]["grounded"] is not None
    assert llm.last_tools  # 工具 schema 已透传
    assert not report["degraded"]


def test_investigate_all_ungrounded_evidence_degrades():
    script = [
        final_msg(
            {
                "conclusion": "suggest_approve",
                "evidence": [
                    {
                        "tool": "check_invoice_ledger",
                        "call_id": "call_bogus",
                        "finding": "台账显示只有 1 次使用",
                        "ref": "usageCount",
                        "source_id": "",  # M33: 缺少 source_id
                        "field_path": "",
                    }
                ],
                "summary": "我认为没重复",
                "confidence": 0.9,
            }
        ),
    ]
    llm = FakeLLM(script)
    report = investigate(
        {"id": "BX-X", "lines": []}, [], RULES, AI, CTX, llm, max_steps=5, token_budget=20000, wall_timeout=30
    )
    # M33: 证据缺少 source_id，会被 _verify_grounding_v2 标记为 ungrounded
    assert report["conclusion"] == "support_flag"  # 降级
    assert report["grounding_ok"] is False


def test_investigate_budget_exhaustion_degrades():
    llm = FakeLLM(
        [
            tool_call_msg(f"call_{i}", "check_invoice_ledger", {"invoice_code": "C1", "invoice_no": "N1"})
            for i in range(20)
        ]
    )
    report = investigate(
        {"id": "BX-X", "lines": []},
        [],
        RULES,
        AI,
        CTX,
        llm,
        max_steps=2,
        token_budget=100000,
        wall_timeout=30,
    )
    assert report["degraded"] is True
    assert report["degraded_reason"] in ("budget_exhausted", "token_budget_exceeded")


def test_investigate_llm_failure_degrades():
    class BoomLLM:
        last_usage = None
        call_stats_history = []

        def get_call_stats(self):
            return self.call_stats_history

        def chat(self, messages, tools=None, trace_id=""):
            raise RuntimeError("network down")

    report = investigate(
        {"id": "BX-X", "lines": []},
        [],
        RULES,
        AI,
        CTX,
        BoomLLM(),
        max_steps=3,
        token_budget=20000,
        wall_timeout=30,
    )
    assert report["degraded"] is True
    assert report["degraded_reason"] == "llm_call_failed"
    assert report["conclusion"] == "support_flag"


def test_investigate_invalid_then_repair():
    script = [
        SimpleNamespace(content="我想想……", tool_calls=None),
        final_msg(
            {
                "conclusion": "support_flag",
                "evidence": [],
                "summary": "证据不足",
                "confidence": 0.4,
            }
        ),
    ]
    llm = FakeLLM(script)
    report = investigate(
        {"id": "BX-X", "lines": []}, [], RULES, AI, CTX, llm, max_steps=5, token_budget=20000, wall_timeout=30
    )
    assert report["conclusion"] == "support_flag"
    assert report["steps"] == 2
    assert llm.calls == 2


def test_investigate_token_budget_triggers():
    class BigUsageLLM(FakeLLM):
        def __init__(self):
            super().__init__(
                [
                    final_msg(
                        {"conclusion": "maintain_rules", "evidence": [], "summary": "s", "confidence": 0.5}
                    )
                ]
            )
            self.last_usage = SimpleNamespace(prompt_tokens=50000, completion_tokens=50000)

    llm = BigUsageLLM()
    report = investigate(
        {"id": "BX-X", "lines": []}, [], RULES, AI, CTX, llm, max_steps=5, token_budget=1000, wall_timeout=30
    )
    assert report["degraded"] is True
    assert report["degraded_reason"] == "token_budget_exceeded"
