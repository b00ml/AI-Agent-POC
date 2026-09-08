"""LangGraph 工作流测试（假 LLM/工具件，无网络）：图流转、分歧转 FLAG、HITL。"""

import json
from types import SimpleNamespace


from core import workflow as wf
from core.workflow import M2GraphRunner, combine_opinions, need_investigation


RULES = {"result": "REJECT", "violations": ["DUPLICATE_INVOICE"],
         "reasons": ["发票重复"], "confidence": 0.8}


class FakeReviewer:
    """review_claim 返回与规则相反的意见（模拟分歧）"""

    def __init__(self, result="APPROVE"):
        self.result = result
        self.client = None

    def review_claim(self, claim_detail, approvals, travel_standards=None,
                     ocr_fields=None, rules_opinion=None):
        return {
            "result": self.result,
            "reasons": ["未见重复"],
            "confidence": 0.75,
            "agreeWithRules": self.result == rules_opinion.get("result"),
        }


class FakeTravel:
    def list_standards(self):
        return []


class FakeRetriever:
    def retrieve(self, query_text="", keywords=None, top_k=8):
        return [{"id": "办法#第十七条", "content": "同一张发票不得重复报销",
                 "metadata": {"doc": "办法", "article": "第十七条"}}]


class FakeClient:
    def approvals_for_claim(self, claim_id):
        return []


class FakeFinalLLM:
    """调查 Agent 的 chat：先真实调用一次台账工具，再回 grounded 报告。

    conclusion/summary 可参数化，用于覆盖裁决节点的三种映射。
    """

    last_usage = None

    def __init__(self, conclusion="maintain_rules", summary="维持驳回"):
        self.conclusion = conclusion
        self.summary = summary
        self.call_stats_history = []

    def chat(self, messages, tools=None, trace_id=""):
        if len(messages) == 2:  # 首轮：发起工具调用
            return SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    id="c0",
                    function=SimpleNamespace(
                        name="check_invoice_ledger",
                        arguments=json.dumps({"invoice_code": "C1", "invoice_no": "N1"}),
                    ),
                )],
            )
        from core.llm_client import LLMCallStats
        stats = LLMCallStats(
            trace_id=trace_id, model="fake-model",
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            total_cost=0.001, duration_ms=100, ok=True
        )
        self.call_stats_history.append(stats)
        return SimpleNamespace(
            content=json.dumps({
                "conclusion": self.conclusion,
                "evidence": [{"tool": "check_invoice_ledger", "call_id": "c0",
                              "finding": "台账显示该发票已 2 次报销或使用", "ref": "usageCount",
                              "source_id": "C1/N1", "field_path": "usageCount"}],
                "summary": self.summary,
                "confidence": 0.85,
            }),
            tool_calls=None,
        )

    def get_call_stats(self):
        return self.call_stats_history

CTX = {
    "client": FakeClient(),
    "travel_manager": FakeTravel(),
    "retriever": FakeRetriever(),
    "ocr_results": {},
    "invoice_index": {"C1/N1": ["BX-1", "BX-2"]},
}

CLAIM = {"id": "BX-WF-1", "claimNo": "BX-WF-1", "lines": []}
WRITTEN = []


def write_back_fn(payload):
    WRITTEN.append(payload)


def make_runner(monkeypatch, agent_enabled=False, human_gate=False, reviewer="default", tmp_path=None):
    monkeypatch.setattr(wf, "AGENT_ENABLED", agent_enabled, raising=False)
    monkeypatch.setattr(wf, "HUMAN_GATE_ENABLED", human_gate, raising=False)
    WRITTEN.clear()
    if reviewer == "default":
        reviewer = FakeReviewer()
    paths = {}
    if tmp_path is not None:
        paths = {
            "checkpoint_path": str(tmp_path / "checkpoints.db"),
            "workflow_store_path": str(tmp_path / "workflow_runs.db"),
        }
    return M2GraphRunner(
        client=CTX["client"], travel_manager=CTX["travel_manager"],
        retriever=CTX["retriever"], llm_reviewer=reviewer,
        write_back_fn=write_back_fn,
        **paths,
    )


def test_combine_opinions_divergence_flags():
    result, reasons, confidence = combine_opinions(RULES, {
        "result": "APPROVE", "reasons": ["未见问题"],
    })
    assert result == "FLAG"
    assert confidence == 0.5
    assert any("不一致" in r for r in reasons)


def test_combine_opinions_agreement_keeps_rules():
    result, _, _ = combine_opinions(RULES, {"result": "REJECT", "reasons": []})
    assert result == "REJECT"


def test_run_claim_no_agent_writes_rules_opinion(monkeypatch, tmp_path):
    runner = make_runner(monkeypatch, agent_enabled=False, reviewer=None, tmp_path=tmp_path)
    state = runner.run_claim(CLAIM, [], {}, {}, RULES, write_back=True)
    assert state["final_result"] == "REJECT"
    assert state["write_done"] is True
    assert WRITTEN and WRITTEN[0]["claimId"] == "BX-WF-1"
    assert WRITTEN[0]["violations"] == ["DUPLICATE_INVOICE"]


def test_run_claim_with_agent_attaches_investigation(monkeypatch, tmp_path):
    reviewer = FakeReviewer(result="APPROVE")  # 与规则分歧 → 触发调查
    reviewer.client = FakeFinalLLM()
    from core import investigator as _inv
    _inv._get_system_prompt()  # 预热提示词缓存，避免 REPO_ROOT 补丁影响懒加载
    monkeypatch.setattr("core.investigator.REPO_ROOT", str(tmp_path))  # 防止测试写真实 output/
    runner = make_runner(monkeypatch, agent_enabled=True, reviewer=reviewer, tmp_path=tmp_path)
    state = runner.run_claim(CLAIM, [], CTX["ocr_results"], CTX["invoice_index"],
                             RULES, write_back=True)
    assert state["final_result"] == "FLAG"  # 分歧转 FLAG
    assert state["ai_review"]["investigation"]["conclusion"] == "maintain_rules"
    assert state["ai_review"]["investigation"]["grounding_ok"] is True
    assert WRITTEN[0]["result"] == "FLAG"


def test_human_gate_interrupt_and_resume(monkeypatch, tmp_path):
    runner = make_runner(monkeypatch, agent_enabled=False, human_gate=True, tmp_path=tmp_path)
    state = runner.run_claim(CLAIM, [], {}, {}, RULES, write_back=True)
    assert state.get("awaiting_human") is True
    assert state.get("__interrupt__")
    assert not WRITTEN  # 暂停期间不回写

    resumed = runner.resume(state["workflow_run_id"], decision="REJECT", comment="同意驳回")
    assert resumed is not None
    assert resumed.get("write_done") is True
    assert resumed["human_decision"]["decision"] == "REJECT"
    assert WRITTEN and any("人工终审决定：REJECT" in r for r in WRITTEN[0]["reasons"])


def test_resume_unknown_claim_returns_none(monkeypatch, tmp_path):
    runner = make_runner(monkeypatch, human_gate=True, tmp_path=tmp_path)
    assert runner.resume("BX-NONE", decision="APPROVE") is None


def test_need_investigation_conditions(monkeypatch):
    monkeypatch.setattr(wf, "AGENT_ENABLED", True, raising=False)
    assert need_investigation({"rules": RULES, "ai_review": None}) is True
    assert need_investigation({"rules": RULES,
                               "ai_review": {"agreeWithRules": False}}) is True
    assert need_investigation({"rules": RULES,
                               "ai_review": {"agreeWithRules": True}}) is False
    monkeypatch.setattr(wf, "AGENT_ENABLED", False, raising=False)
    assert need_investigation({"rules": RULES, "ai_review": None}) is False


def test_adjudication_support_flag_appends_summary(monkeypatch, tmp_path):
    """support_flag：调查摘要进入最终理由并随回写留痕"""
    reviewer = FakeReviewer(result="APPROVE")  # 与规则分歧 → FLAG → 调查
    reviewer.client = FakeFinalLLM(conclusion="support_flag", summary="关键证据不足")
    monkeypatch.setattr("core.investigator.REPO_ROOT", str(tmp_path))
    runner = make_runner(monkeypatch, agent_enabled=True, reviewer=reviewer, tmp_path=tmp_path)
    state = runner.run_claim(CLAIM, [], CTX["ocr_results"], CTX["invoice_index"],
                             RULES, write_back=True)
    assert state["final_result"] == "FLAG"
    assert any("[调查 Agent] 关键证据不足" in r for r in state["final_reasons"])
    assert WRITTEN and any("[调查 Agent]" in r for r in WRITTEN[0]["reasons"])


def test_adjudication_maintain_rules_no_rewrite(monkeypatch, tmp_path):
    """maintain_rules：不改写结论与理由"""
    reviewer = FakeReviewer(result="APPROVE")
    reviewer.client = FakeFinalLLM(conclusion="maintain_rules", summary="维持驳回")
    monkeypatch.setattr("core.investigator.REPO_ROOT", str(tmp_path))
    runner = make_runner(monkeypatch, agent_enabled=True, reviewer=reviewer, tmp_path=tmp_path)
    state = runner.run_claim(CLAIM, [], CTX["ocr_results"], CTX["invoice_index"],
                             RULES, write_back=True)
    assert state["final_result"] == "FLAG"  # 分歧本身产生的 FLAG
    assert not any("[调查 Agent]" in r for r in state["final_reasons"])


def test_adjudication_defensive_flag_promotion():
    """防御分支：结论非 FLAG 时 suggest_* 升级 FLAG（直接调用节点验证映射）"""
    from core.workflow import M2GraphRunner
    node = M2GraphRunner._node_adjudicate
    state = {
        "investigation": {"conclusion": "suggest_approve", "summary": "证据支持放行"},
        "final_result": "REJECT",
        "final_reasons": ["规则驳回"],
        "final_confidence": 0.8,
    }
    out = node(None, state)  # self 未用，传 None
    assert out["final_result"] == "FLAG"
    assert out["final_confidence"] == 0.5
    assert any("证据支持放行" in r for r in out["final_reasons"])


def test_human_override_survives_runner_reconstruction(monkeypatch, tmp_path):
    """A fresh runner reads the durable checkpoint and honors the human result."""
    first = make_runner(monkeypatch, agent_enabled=False, human_gate=True, tmp_path=tmp_path)
    paused = first.run_claim(CLAIM, [], {}, {}, RULES, write_back=True)
    run_id = paused["workflow_run_id"]

    # Simulate a backend restart: no active in-memory runner is consulted.
    M2GraphRunner._ACTIVE.clear()
    second = make_runner(monkeypatch, agent_enabled=False, human_gate=True, tmp_path=tmp_path)
    resumed = second.resume(run_id, decision="APPROVE", comment="凭人工证据放行")

    assert resumed is not None
    assert resumed["final_result"] == "APPROVE"
    assert WRITTEN[0]["result"] == "APPROVE"
    assert WRITTEN[0]["violations"] == []
