"""
M2 审核 LangGraph 工作流（设计文档 2.0 §3.3）

状态图：START → llm_review → [need_investigation?] → investigate → human_gate → write_back → END
- M2_PIPELINE=graph 时由 m2_processor 启用；legacy 路径保持不变
- human_gate：AGENT_HUMAN_GATE=1 时以 interrupt() 暂停等待人工终审，
  人工通过 workflow_run_id 注入决定后继续回写；
  默认关闭——FLAG 意见照常回写，人工在 ERP 复核队列处理（与 legacy 行为一致）
- checkpointer：SQLite 快照（单节点 POC；支持进程重启后恢复）
- 红线：write_back 只写「审核意见」，不改变单据状态
"""

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from core.contracts import ALL_M2_VIOLATIONS
from core.checkpoints import SQLiteCheckpointSaver
from core.investigator import investigate, save_investigation_report
from core.logger import get_logger
from core.workflow_store import WorkflowRunStore

logger = get_logger("workflow")

AGENT_ENABLED = os.environ.get("AGENT_INVESTIGATION_ENABLED", "0") == "1"
HUMAN_GATE_ENABLED = os.environ.get("AGENT_HUMAN_GATE", "0") == "1"

JSON_WHITELIST = set(ALL_M2_VIOLATIONS)
RUNTIME_DIR = Path(__file__).resolve().parents[1] / "output" / "runtime"
CHECKPOINT_DB = str(RUNTIME_DIR / "workflow_checkpoints.db")
WORKFLOW_DB = str(RUNTIME_DIR / "workflow_runs.db")


class AuditState(TypedDict, total=False):
    workflow_run_id: str
    claim: dict
    approvals: list
    ocr_results: dict
    invoice_index: dict
    rules: dict                 # {result, violations, reasons, confidence/decisionStrength}
    ai_review: Optional[dict]
    investigation: Optional[dict]
    final_result: str
    final_reasons: List[str]
    final_confidence: float
    write_back: bool
    write_done: bool
    awaiting_human: bool
    human_decision: Optional[dict]


def combine_opinions(rules_result: dict, ai_review: Optional[dict]):
    """规则意见 × AI 复核意见 → 最终结论（分歧转 FLAG；双意见写入理由）。

    返回 (final_result, final_reasons, final_confidence)。
    """
    reasons = list(rules_result.get("reasons") or [])
    confidence = rules_result.get("decisionStrength", rules_result.get("confidence", 0.5))
    result = rules_result.get("result", "FLAG")
    if ai_review:
        llm_result = ai_review.get("result")
        if llm_result and llm_result != result:
            reasons = [
                f"AI 复核意见与规则引擎不一致（规则={result}，AI={llm_result}），"
                f"提请人工复核。AI 理由：{'; '.join(ai_review.get('reasons') or [])}"
            ] + reasons
            result = "FLAG"
            confidence = 0.5
    return result, reasons, confidence


def need_investigation(state: AuditState) -> bool:
    """分歧 / FLAG / AI 缺席 → 进入调查节点"""
    if not AGENT_ENABLED:
        return False
    rules = state.get("rules") or {}
    ai = state.get("ai_review")
    return bool(
        rules.get("result") == "FLAG"
        or ai is None
        or not ai.get("agreeWithRules")
    )


class M2GraphRunner:
    """单图实例 + SQLite checkpoint；每次执行使用独立 workflow_run_id。"""

    _ACTIVE: Dict[str, "M2GraphRunner"] = {}  # run_id -> runner（热路径复用）
    _DEFAULT_CHECKPOINTER: Optional[SQLiteCheckpointSaver] = None

    def __init__(self, client, travel_manager, retriever, llm_reviewer,
                 write_back_fn: Callable[[dict], Any], checkpoint_path: Optional[str] = None,
                 workflow_store_path: Optional[str] = None) -> None:
        self.client = client
        self.travel_manager = travel_manager
        self.retriever = retriever
        self.llm_reviewer = llm_reviewer
        self.write_back_fn = write_back_fn
        if checkpoint_path:
            self.checkpointer = SQLiteCheckpointSaver(checkpoint_path)
        else:
            if self._DEFAULT_CHECKPOINTER is None:
                self._DEFAULT_CHECKPOINTER = SQLiteCheckpointSaver(CHECKPOINT_DB)
            self.checkpointer = self._DEFAULT_CHECKPOINTER
        self.run_store = WorkflowRunStore(workflow_store_path or WORKFLOW_DB)
        self.graph = self._build()

    @classmethod
    def get_runner(cls, run_id: str) -> Optional["M2GraphRunner"]:
        return cls._ACTIVE.get(run_id)

    # ---------- 节点 ----------

    def _node_llm_review(self, state: AuditState) -> dict:
        rules = state["rules"]
        ai_review = None
        if self.llm_reviewer is not None:
            try:
                opinion = {
                    "result": rules.get("result"),
                    "violations": rules.get("violations") or [],
                    "reasons": rules.get("reasons") or [],
                }
                ai_review = self.llm_reviewer.review_claim(
                    state["claim"],
                    state["approvals"],
                    travel_standards=self.travel_manager.list_standards(),
                    ocr_fields=state.get("ocr_results") or {},
                    rules_opinion=opinion,
                )
                if "error" in ai_review:
                    ai_review = None
            except Exception as e:  # LLM 失败降级为纯规则结论
                logger.warning("llm_review 节点失败，按规则结论处理: %s", e)
                ai_review = None
        final, reasons, confidence = combine_opinions(rules, ai_review)
        return {
            "ai_review": ai_review,
            "final_result": final,
            "final_reasons": reasons,
            "final_confidence": confidence,
        }

    def _node_investigate(self, state: AuditState) -> dict:
        llm_client = getattr(self.llm_reviewer, "client", None)
        if llm_client is None:
            logger.warning("investigate 节点缺少 LLM client，跳过调查并维持人工复核")
            return {
                "investigation": {
                    "conclusion": "support_flag",
                    "summary": "[调查降级：LLM 未配置] 维持存疑，提请人工复核。",
                    "confidence": 0.0,
                    "evidence": [],
                    "degraded": True,
                    "degraded_reason": "llm_not_configured",
                    "steps": 0,
                    "tool_calls": 0,
                    "tokens_used": 0,
                    "grounding_ok": None,
                }
            }
        ctx = {
            "client": self.client,
            "travel_manager": self.travel_manager,
            "retriever": self.retriever,
            "ocr_results": state.get("ocr_results") or {},
            "invoice_index": state.get("invoice_index") or {},
        }
        rules = state["rules"]
        report = investigate(
            state["claim"], state["approvals"], rules,
            state.get("ai_review"), ctx, llm_client,
        )
        ai_review = dict(state.get("ai_review") or {})
        ai_review["investigation"] = report
        try:
            save_investigation_report(
                state["claim"].get("id", ""), report, rules, state.get("final_result", ""),
            )
        except OSError as e:
            logger.warning("调查报告落盘失败: %s", e)
        logger.info(
            "investigate %s: conclusion=%s steps=%s tool_calls=%s grounded=%s degraded=%s",
            state["claim"].get("id", ""), report.get("conclusion"), report.get("steps"),
            report.get("tool_calls"), report.get("grounding_ok"), report.get("degraded"),
        )
        return {"investigation": report, "ai_review": ai_review}

    def _node_adjudicate(self, state: AuditState) -> dict:
        """调查结论裁决：把调查报告接入决策链（审查意见 P0-2）。

        映射是保守方向的——调查只能把结论向更谨慎（FLAG）推进，绝不自动放行/驳回：
        - maintain_rules：不变（分歧单维持 FLAG 交人工）；
        - support_flag / suggest_approve / suggest_reject：调查摘要附加进最终理由；
          若当前结论尚未是 FLAG（防御分支：调查发现新证据而规则与 AI 曾一致），
          升级为 FLAG 提请人工，置信度降 0.5。
        """
        inv = state.get("investigation")
        if not inv:
            return {}
        conclusion = inv.get("conclusion")
        if conclusion not in ("support_flag", "suggest_approve", "suggest_reject"):
            return {}  # maintain_rules：调查支持现有结论，不改写
        summary = (inv.get("summary") or "").strip()
        tag = f"[调查 Agent] {summary}"
        reasons = list(state.get("final_reasons") or [])
        if tag not in reasons:
            reasons.append(tag)
        if state.get("final_result") != "FLAG":
            return {"final_result": "FLAG", "final_reasons": reasons, "final_confidence": 0.5}
        return {"final_reasons": reasons}

    def _node_human_gate(self, state: AuditState) -> dict:
        if not HUMAN_GATE_ENABLED:
            return {}  # 不打断：FLAG 意见照常回写，人工在 ERP 复核队列处理
        decision = interrupt({
            "workflowRunId": state.get("workflow_run_id", ""),
            "claimId": state["claim"].get("id", ""),
            "finalResult": state.get("final_result"),
            "reasons": state.get("final_reasons"),
            "question": "请人工终审：decision = APPROVE / REJECT / FLAG",
        })
        if isinstance(decision, str):
            decision = {"decision": decision}
        return {"human_decision": decision, "awaiting_human": False}

    def _node_write_back(self, state: AuditState) -> dict:
        if not state.get("write_back"):
            return {"write_done": True}
        human = state.get("human_decision")
        if human:
            # 人工终审意见并入回写理由（AI/规则/人工三方留痕）
            reasons = list(state.get("final_reasons") or [])
            reasons.append(f"人工终审决定：{human.get('decision')}")
            if human.get("comment"):
                reasons.append(f"人工终审意见：{human['comment']}")
            effective_result = human.get("decision") or state.get("final_result")
            original_result = state.get("final_result")
            payload = {
                "claimId": state["claim"].get("id", ""),
                "result": effective_result,
                "reasons": reasons,
                "confidence": state.get("final_confidence"),
                "violations": [v for v in (state["rules"].get("violations") or [])
                               if v in JSON_WHITELIST] if effective_result == original_result else [],
                "humanDecision": human,
            }
            self.write_back_fn(payload)
            return {"write_done": True, "final_result": effective_result, "final_reasons": reasons}
        payload = {
            "claimId": state["claim"].get("id", ""),
            "result": state.get("final_result"),
            "reasons": state.get("final_reasons") or [],
            "confidence": state.get("final_confidence"),
            "violations": [v for v in (state["rules"].get("violations") or [])
                           if v in JSON_WHITELIST],
        }
        self.write_back_fn(payload)
        return {"write_done": True}

    # ---------- 图 ----------

    def _build(self):
        g = StateGraph(AuditState)
        g.add_node("llm_review", self._node_llm_review)
        g.add_node("investigate", self._node_investigate)
        g.add_node("adjudicate", self._node_adjudicate)
        g.add_node("human_gate", self._node_human_gate)
        g.add_node("write_back", self._node_write_back)
        g.add_edge(START, "llm_review")
        g.add_conditional_edges(
            "llm_review",
            lambda s: "investigate" if need_investigation(s) else "human_gate",
            {"investigate": "investigate", "human_gate": "human_gate"},
        )
        g.add_edge("investigate", "adjudicate")
        g.add_edge("adjudicate", "human_gate")
        g.add_edge("human_gate", "write_back")
        g.add_edge("write_back", END)
        return g.compile(checkpointer=self.checkpointer)

    # ---------- 对外 ----------

    def run_claim(self, claim_detail: dict, approvals: list, ocr_results: dict,
                  invoice_index: dict, rules_result: dict, write_back: bool,
                  workflow_run_id: Optional[str] = None) -> AuditState:
        claim_id = claim_detail.get("id", "")
        run_id = workflow_run_id or self.run_store.create(claim_id)
        self._ACTIVE[run_id] = self
        if len(self._ACTIVE) > 500:  # 防长驻进程内存无界增长
            for k in list(self._ACTIVE)[: len(self._ACTIVE) - 500]:
                self._ACTIVE.pop(k, None)
        state: AuditState = {
            "claim": claim_detail,
            "approvals": approvals,
            "ocr_results": ocr_results,
            "invoice_index": invoice_index,
            "rules": rules_result,
            "write_back": write_back,
            "awaiting_human": False,
            "workflow_run_id": run_id,
        }
        try:
            final = self.graph.invoke(state, {"configurable": {"thread_id": run_id}})
        except Exception:
            self.run_store.mark(run_id, "FAILED")
            self._ACTIVE.pop(run_id, None)
            raise
        final["workflow_run_id"] = run_id
        if final.get("__interrupt__"):
            final["awaiting_human"] = True
            self.run_store.mark(run_id, "AWAITING_HUMAN")
            final["workflow_revision"] = 0
            logger.warning("human_gate 暂停等待人工终审: claim=%s run=%s", claim_id, run_id)
        else:
            self.run_store.mark(run_id, "COMPLETED")
            self._ACTIVE.pop(run_id, None)
        return final

    def resume(self, run_id: str, decision: str, comment: str = "",
               expected_revision: Optional[int] = None) -> Optional[AuditState]:
        """Resume a human gate once.

        ``run_id`` is the durable graph identity. For callers from the 2.0
        endpoint, a claim id is resolved to its latest waiting run as a
        compatibility bridge; new API callers must use ``workflowRunId``.
        """
        record = self.run_store.get(run_id)
        if record is None:
            record = self.run_store.latest_for_claim(run_id)
            if record is None:
                return None
            run_id = record["run_id"]
        revision = record["revision"] if expected_revision is None else expected_revision
        if not self.run_store.claim_decision_revision(run_id, revision):
            return None
        state = self.graph.get_state({"configurable": {"thread_id": run_id}})
        if state is None or not state.values:
            self.run_store.mark(run_id, "FAILED", revision=revision + 1)
            return None
        try:
            final = self.graph.invoke(
                Command(resume={"decision": decision, "comment": comment}),
                {"configurable": {"thread_id": run_id}},
            )
        except Exception:
            self.run_store.mark(run_id, "FAILED", revision=revision + 1)
            raise
        final.pop("__interrupt__", None)
        final["workflow_run_id"] = run_id
        self.run_store.mark(run_id, "COMPLETED", revision=revision + 1)
        self._ACTIVE.pop(run_id, None)
        return final
