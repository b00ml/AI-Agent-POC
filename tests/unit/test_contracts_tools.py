"""输出契约（pydantic）与工具层单元测试。"""


import pytest
import time
from pydantic import ValidationError

from core.agent_tools import ToolCapability, ToolRegistry, build_default_registry
from core.contracts import (
    InvestigationReport,
    M2Review,
    make_m2_validator,
    make_m3_validator,
)


# ---------- contracts ----------

def test_m2_review_valid():
    r = M2Review.model_validate({
        "result": "REJECT",
        "violations": ["OVER_STANDARD_HOTEL", "ACCOUNT_MISMATCH"],
        "reasons": ["住宿超标"],
        "confidence": 0.85,
    })
    assert r.result == "REJECT"


def test_m2_review_rejects_bad_code_and_confidence():
    with pytest.raises(ValidationError):
        M2Review.model_validate({"result": "MAYBE", "violations": [], "reasons": [], "confidence": 0.5})
    with pytest.raises(ValidationError):
        M2Review.model_validate({"result": "APPROVE", "violations": [], "reasons": [], "confidence": 1.5})


def test_m2_validator_wraps_pydantic():
    ok = make_m2_validator()
    assert ok({"result": "FLAG", "violations": [], "reasons": ["r"], "confidence": 0.5})
    assert not ok({"result": "FLAG", "violations": [], "reasons": [], "confidence": 2.0})
    m3 = make_m3_validator()
    assert m3({"verdict": "CONFIRM", "reasons": ["r"], "confidence": 0.9})
    assert not m3({"verdict": "SURE", "reasons": ["r"], "confidence": 0.9})


def test_investigation_report_shape():
    r = InvestigationReport.model_validate({
        "conclusion": "maintain_rules",
        "evidence": [{"tool": "search_policy_kb", "call_id": "c1", "finding": "第十三条要求事前审批", "ref": "第十三条"}],
        "summary": "s",
        "confidence": 0.7,
    })
    assert r.evidence[0].grounded is None
    assert r.degraded is False
    with pytest.raises(ValidationError):
        InvestigationReport.model_validate({
            "conclusion": "whatever", "evidence": [], "summary": "s", "confidence": 0.1,
        })


# ---------- ToolRegistry ----------

def test_registry_dispatch_and_schema():
    reg = ToolRegistry()
    reg.register(
        "add", "加法", {"type": "object", "properties": {
            "a": {"type": "integer"}, "b": {"type": "integer"},
        }, "required": ["a", "b"]},
        lambda a, b: {"sum": a + b},
    )
    tools = reg.to_openai_tools()
    assert tools[0]["function"]["name"] == "add"
    out = reg.dispatch("add", '{"a": 2, "b": 3}', call_id="c1")
    assert out["ok"] and out["data"]["sum"] == 5 and out["call_id"] == "c1"


def test_registry_dispatch_unknown_tool_and_bad_json():
    reg = ToolRegistry()
    out = reg.dispatch("nope", "{}")
    assert not out["ok"]
    reg.register("echo", "e", {"type": "object", "properties": {}}, lambda: "x")
    out2 = reg.dispatch("echo", "{bad json")
    assert not out2["ok"] and "非法" in out2["error"]


def test_registry_tool_error_wrapped_not_raised():
    reg = ToolRegistry()
    def boom():
        raise ValueError("炸了")
    reg.register("boom", "b", {"type": "object", "properties": {}}, boom)
    out = reg.dispatch("boom", "{}")
    assert not out["ok"] and "炸了" in out["error"]


def test_registry_rejects_unknown_schema_fields():
    reg = ToolRegistry()
    reg.register(
        "echo", "e", {"type": "object", "properties": {"value": {"type": "string"}}},
        lambda value: value,
    )
    out = reg.dispatch("echo", '{"value": "ok", "extra": true}')
    assert not out["ok"]
    assert reg.to_openai_tools()[0]["function"]["parameters"]["additionalProperties"] is False


def test_registry_enforces_tool_timeout():
    reg = ToolRegistry()

    def slow():
        time.sleep(0.05)
        return "done"

    reg.register(
        "slow", "s", {"type": "object", "properties": {}}, slow,
        capability=ToolCapability(timeout_ms=5),
    )
    out = reg.dispatch("slow", "{}", call_id="timeout-1")
    assert not out["ok"]
    assert "TOOL_TIMEOUT" in reg.get_call_records()[-1].error_code


def test_default_registry_tools(ctx_stub):
    reg = build_default_registry(ctx_stub)
    assert set(reg.names) == {
        "query_travel_standards", "search_policy_kb", "get_approval_records",
        "get_invoice_ocr", "check_invoice_ledger",
    }

    out = reg.dispatch("query_travel_standards", '{"job_level": "STAFF", "city_tier": "TIER2"}')
    assert out["ok"] and out["data"]["hotelCapPerNightFen"] == 42000

    out = reg.dispatch("check_invoice_ledger", '{"invoice_code": "C1", "invoice_no": "N1"}')
    assert out["ok"] and out["data"]["duplicate"] is True and out["data"]["usageCount"] == 2

    out = reg.dispatch("get_invoice_ocr", '{"attachment_id": "A1"}')
    assert out["ok"] and out["data"]["found"] is True
    out = reg.dispatch("get_invoice_ocr", '{"attachment_id": "A-MISSING"}')
    assert out["ok"] and out["data"]["found"] is False

    out = reg.dispatch("get_approval_records", '{"claim_id": "BX-1"}')
    assert out["ok"] and out["data"][0]["action"] == "SPECIAL_APPROVE"

    out = reg.dispatch("search_policy_kb", '{"query": "住宿费超标怎么办"}')
    assert out["ok"] and out["data"]["clauses"]


@pytest.fixture
def ctx_stub():
    class TM:
        def get_standard(self, job_level, city_tier):
            return {"jobLevel": job_level, "cityTier": city_tier,
                    "hotelCapPerNightFen": 42000, "mealAllowancePerDayFen": 10000,
                    "cityTransportPerDayFen": 2000, "longDistanceClass": "TRAIN_2ND"}

    class Client:
        def approvals_for_claim(self, claim_id):
            return [{"action": "SPECIAL_APPROVE", "comment": "总监特批"}]

    class Retriever:
        def retrieve(self, query_text="", keywords=None, top_k=8):
            return [{"id": "办法#第五条", "content": "住宿费按每晚单价考核",
                     "metadata": {"doc": "办法", "article": "第五条"}}]

    return {
        "client": Client(),
        "travel_manager": TM(),
        "retriever": Retriever(),
        "ocr_results": {"A1": {"buyerName": "启衡精密制造有限公司", "totalAmount": "500.00"}},
        "invoice_index": {"C1/N1": ["BX-1", "BX-2"]},
    }
