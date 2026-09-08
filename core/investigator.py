"""
分歧/FLAG 单调查 Agent（设计文档 2.0 §3.2）

ReAct 工具循环：LLM 决定调用哪些只读工具取证，证据充分后输出 InvestigationReport。
- 预算封顶：max_steps（LLM 轮次）/ max_tool_calls / token 预算 / 墙钟超时
- Grounding 校验：证据引用的数字与条款 ref 必须能在对应工具调用的返回中找到，
  全部证据不落地的报告降级为「未取证，维持存疑」
- 降级链：LLM 调用失败/预算耗尽 → 降级报告（conclusion=support_flag），绝不抛出中断批量审核

M33 增强：证据必须绑定 source_id + field_path + call_id 三元组，LLM 统计纳入报告
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from core.agent_tools import build_default_registry
from core.contracts import InvestigationReport
from core.logger import get_logger

logger = get_logger("investigator")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "5"))
# 实测标定（BX-005693，2 步 + 6 次工具调用 ≈ 2.5 万 token）：默认 3 万，防失控仍留余量
DEFAULT_TOKEN_BUDGET = int(os.environ.get("AGENT_TOKEN_BUDGET", "30000"))
DEFAULT_WALL_TIMEOUT = float(os.environ.get("AGENT_WALL_TIMEOUT", "90"))


def _load(name: str) -> str:
    with open(os.path.join(REPO_ROOT, "data", "prompts", name), "r", encoding="utf-8") as f:
        return f.read()


def _load_skill() -> str:
    path = os.path.join(REPO_ROOT, "doc", "skills", "m2-claim-review", "SKILL.md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


_PROMPT_CACHE: Dict[str, str] = {}


def _get_system_prompt() -> str:
    """懒加载系统提示词（含 SKILL 注入）：模块导入期不读文件，缺文件不在 import 时崩。"""
    if "system" not in _PROMPT_CACHE:
        _PROMPT_CACHE["system"] = _load("investigation_system.txt").replace(
            "{skill_content}",
            _load_skill(),
        )
    return _PROMPT_CACHE["system"]


def _assistant_message(msg: Any) -> Dict[str, Any]:
    """把 SDK/假实现的 assistant message 转成可回传的 dict"""
    if hasattr(msg, "model_dump"):
        return msg.model_dump()
    tool_calls = getattr(msg, "tool_calls", None) or []
    return {
        "role": "assistant",
        "content": getattr(msg, "content", None),
        "tool_calls": [
            tc.model_dump()
            if hasattr(tc, "model_dump")
            else {
                "id": getattr(tc, "id", ""),
                "type": "function",
                "function": {
                    "name": getattr(getattr(tc, "function", None), "name", ""),
                    "arguments": getattr(getattr(tc, "function", None), "arguments", "") or "{}",
                },
            }
            for tc in tool_calls
        ],
    }


def _degraded(reason: str, detail: str, steps: int, tool_calls: int, tokens_used: int = 0) -> Dict[str, Any]:
    report = InvestigationReport(
        conclusion="support_flag",
        summary=f"[调查降级：{reason}] {detail}"[:500],
        confidence=0.0,
        degraded=True,
        degraded_reason=reason,
        steps=steps,
        tool_calls=tool_calls,
        tokens_used=tokens_used,
        grounding_ok=None,
        total_cost=0.0,
    )
    return report.model_dump()


def _build_task_brief(
    claim_detail: dict, approvals: list, rules_opinion: dict, ai_review: Optional[dict], tool_names: List[str]
) -> str:
    trip = claim_detail.get("trip") or {}
    lines = []
    for ln in claim_detail.get("lines", []):
        inv = ln.get("invoice") or {}
        att = ln.get("attachment") or {}
        lines.append(
            f"- 行{ln.get('lineNo')} {ln.get('expenseType')} {ln.get('description', '')}"
            f" 金额{ln.get('amountFen', 0) / 100:.2f}元"
            f" 发票{inv.get('invoiceCode', '')}/{inv.get('invoiceNo', '')}"
            f" 附件{att.get('id', '（无）')}"
        )
    approvals_text = (
        "；".join(
            f"{a.get('action', '')}({a.get('stage', '') or a.get('comment', '')})" for a in (approvals or [])
        )
        or "（无审批记录）"
    )
    brief = [
        f"单据：{claim_detail.get('claimNo', claim_detail.get('id', ''))}"
        f" 职级{claim_detail.get('jobLevel', '')} 部门{claim_detail.get('departmentName', '')}"
        f" 类型{claim_detail.get('claimType', '')}"
        f" 出差{trip.get('city', '（无）')} {trip.get('nights', 0)}晚",
        "费用行：\n" + ("\n".join(lines) or "（无）"),
        f"审批记录：{approvals_text}",
        f"规则引擎初审：{json.dumps(rules_opinion, ensure_ascii=False)}",
    ]
    if ai_review:
        brief.append(f"AI 复核意见：{json.dumps(ai_review, ensure_ascii=False)}")
    else:
        brief.append("AI 复核意见：无（规则引擎自行标记 FLAG）")
    brief.append("可用工具：" + "、".join(tool_names))
    return "\n\n".join(brief)


def _parse_report(content: str) -> Optional[InvestigationReport]:
    """从 LLM 输出中解析 InvestigationReport；校验失败返回 None"""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return InvestigationReport.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError):
        return None
    except Exception:
        return None


def _check_field_exists(data: Any, source_id: str, field_path: str) -> bool:
    """检查数据中是否存在指定的 source_id 和 field_path（M33 增强）

    Args:
        data: 工具返回的数据（通常在 result["data"] 中）
        source_id: 数据源ID（如 claim_id "BX-001", attachment_id 等），应该是数据中某个标识符字段的值
        field_path: 字段路径（如 "amount", "usageCount", "clauses[0].content"）

    Returns:
        True 如果 source_id 和 field_path 都在数据中能找到

    注意：source_id 是数据中实体的标识符值，不是工具名。当 source_id 或 field_path 为空时，只验证非空的那个。
    """
    if not data:
        return False

    # 简化实现：检查 source_id 和 field_path 是否在数据的 JSON 字符串中
    data_str = json.dumps(data, ensure_ascii=False)

    # 验证 source_id（如果非空）
    if source_id and source_id not in data_str:
        return False

    # 验证 field_path（如果非空）
    if field_path:
        # 提取基础字段名（去掉数组索引和嵌套路径）
        base_field = field_path.split("[")[0].split(".")[0]
        if base_field and base_field not in data_str:
            return False

    return True


def _verify_grounding_v2(
    report: InvestigationReport,
    transcript: List[Dict[str, Any]],
) -> InvestigationReport:
    """M33 增强：证据必须绑定 source_id + field_path + call_id 三元组

    分层校验：
    1. 证据必须有 source_id 和 call_id
    2. call_id 必须在工具调用记录中
    3. source_id 和 field_path 必须在对应工具返回中能验证
    """
    failed = 0

    for ev in report.evidence:
        # 第一层：必须有 source_id 和 call_id
        if not ev.source_id or not ev.call_id:
            ev.grounded = False
            failed += 1
            continue

        # 第二层：call_id 必须对应真实的工具调用
        result = next((t for t in transcript if t.get("call_id") == ev.call_id), None)
        if not result or not result.get("result", {}).get("ok"):
            ev.grounded = False
            failed += 1
            continue

        # 第三层：验证 source_id 和 field_path 在返回数据中
        data = result.get("result", {}).get("data")
        ev.grounded = _check_field_exists(data, ev.source_id, ev.field_path)
        if not ev.grounded:
            failed += 1

    report.grounding_failed_count = failed
    report.grounding_ok = (failed == 0) if report.evidence else None
    return report


def _ground_check(report: InvestigationReport, transcript: List[dict]) -> None:
    """分层 grounding：防幻觉而不扼杀跨工具综合证据。

    - call_id 必须能在工具调用记录中找到（找不到 = 编造证据）；
    - finding 中的数字串（≥2 位）必须能在【本调用返回】或【全部工具返回并集】中找到；
    - ref 为知识库条款 id（含 #）时，其文档前缀必须出现在全部工具返回并集中。
    """
    by_call = {t["call_id"]: t for t in transcript}
    union_text = json.dumps([t.get("result") for t in transcript], ensure_ascii=False) if transcript else ""
    if not report.evidence:
        report.grounding_ok = None
        return
    any_grounded = False
    for ev in report.evidence:
        t = by_call.get(ev.call_id)
        grounded = t is not None
        if grounded:
            digits = re.findall(r"\d{2,}", ev.finding or "")
            if digits and not all(d in union_text for d in digits):
                grounded = False
            ref = ev.ref or ""
            if "#" in ref:
                doc_part = ref.split("#", 1)[0].strip()
                if doc_part and doc_part not in union_text:
                    grounded = False
        ev.grounded = grounded
        any_grounded = any_grounded or grounded
    report.grounding_ok = any_grounded
    if not any_grounded:
        # 全部证据不落地 → 降级为「未取证，维持存疑」
        report.conclusion = "support_flag"
        report.summary = f"[证据未落地] {report.summary}"[:500]


def investigate(
    claim_detail: dict,
    approvals: list,
    rules_opinion: dict,
    ai_review: Optional[dict],
    ctx: Dict[str, Any],
    llm_client: Any,
    max_steps: Optional[int] = None,
    token_budget: Optional[int] = None,
    wall_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """调查 Agent 入口；异常一律捕获并降级，保障批量审核不中断。

    Args:
        claim_detail: 完整单据数据
        approvals: 审批历史
        rules_opinion: 规则引擎初审结果（含 flags）
        ai_review: AI 复核意见（若存在分歧）
        ctx: 运行上下文（含数据提供者、审核器等）
        llm_client: LLM 客户端
        max_steps / token_budget / wall_timeout: 可选预算覆盖

    Returns:
        InvestigationReport 的 dict（已回填运行时字段）
    """
    try:
        return _investigate_impl(
            claim_detail,
            approvals,
            rules_opinion,
            ai_review,
            ctx,
            llm_client,
            max_steps,
            token_budget,
            wall_timeout,
        )
    except Exception as e:
        logger.exception("调查内部错误，降级处理")
        return _degraded("internal_error", str(e)[:200], 0, 0)


def _investigate_impl(
    claim_detail: dict,
    approvals: list,
    rules_opinion: dict,
    ai_review: Optional[dict],
    ctx: Dict[str, Any],
    llm_client: Any,
    max_steps: Optional[int],
    token_budget: Optional[int],
    wall_timeout: Optional[float],
) -> Dict[str, Any]:
    registry = build_default_registry(ctx)
    trace_id = claim_detail.get("id", "")
    max_steps = max_steps or DEFAULT_MAX_STEPS
    token_budget = token_budget or DEFAULT_TOKEN_BUDGET
    wall_timeout = wall_timeout if wall_timeout is not None else DEFAULT_WALL_TIMEOUT

    system = _get_system_prompt()  # 提示词内含 JSON 花括号示例，故用 replace 而非 str.format
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": _build_task_brief(
                claim_detail,
                approvals,
                rules_opinion,
                ai_review,
                registry.names,
            ),
        },
    ]

    transcript: List[dict] = []
    tools_schema = registry.to_openai_tools()
    steps = 0
    tool_calls = 0
    tokens_used = 0
    total_cost_usd = 0.0
    t0 = time.time()
    repair_rounds = 0

    while steps < max_steps and tool_calls < 2 * max_steps + 4 and time.time() - t0 < wall_timeout:
        if tokens_used >= token_budget:
            return _degraded("token_budget_exceeded", f"used≈{tokens_used}", steps, tool_calls, tokens_used)
        try:
            chat_with_stats = getattr(llm_client, "chat_with_stats", None)
            if callable(chat_with_stats):
                invocation = chat_with_stats(messages, tools=tools_schema, trace_id=trace_id)
                msg = invocation.message
                tokens_used += invocation.stats.total_tokens
                total_cost_usd += invocation.stats.total_cost
            else:
                # 兼容历史 fake/第三方客户端；生产 LLMClient 走调用级统计。
                msg = llm_client.chat(messages, tools=tools_schema, trace_id=trace_id)
                usage = getattr(llm_client, "last_usage", None)
                if usage is not None:
                    tokens_used += (getattr(usage, "prompt_tokens", 0) or 0) + (
                        getattr(usage, "completion_tokens", 0) or 0
                    )
        except Exception as e:
            return _degraded("llm_call_failed", str(e)[:200], steps, tool_calls, tokens_used)
        steps += 1
        if tokens_used >= token_budget:
            return _degraded("token_budget_exceeded", f"used≈{tokens_used}", steps, tool_calls, tokens_used)

        tool_calls_msg = getattr(msg, "tool_calls", None)
        if tool_calls_msg:
            messages.append(_assistant_message(msg))
            for tc in tool_calls_msg:
                call_id = getattr(tc, "id", "") or f"call_{tool_calls}"
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", "")
                args_json = getattr(fn, "arguments", "") or "{}"
                result = registry.dispatch(name, args_json, call_id=call_id, trace_id=trace_id)
                tool_calls += 1
                transcript.append({"call_id": call_id, "tool": name, "args": args_json, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False)[:2500],
                    }
                )
            continue

        content = getattr(msg, "content", "") or ""
        report = _parse_report(content)
        if report is None:
            if repair_rounds >= 1:
                return _degraded("invalid_final_output", content[:200], steps, tool_calls, tokens_used)
            repair_rounds += 1
            messages.append({"role": "assistant", "content": content[:2000]})
            messages.append(
                {
                    "role": "user",
                    "content": "输出不符合契约。请只输出一个符合 InvestigationReport schema 的 JSON 对象。",
                }
            )
            continue

        report.steps = steps
        report.tool_calls = tool_calls
        report.tokens_used = tokens_used
        report.total_cost = total_cost_usd
        report.wall_time_ms = int((time.time() - t0) * 1000)

        # M33: 使用新的 grounding 校验
        report = _verify_grounding_v2(report, transcript)

        # 保留原有降级逻辑兼容性
        if report.grounding_ok is False and report.conclusion != "support_flag":
            report.conclusion = "support_flag"
            report.summary = f"[证据未落地] {report.summary}"[:500]

        return report.model_dump()

    return _degraded(
        "budget_exhausted", f"steps={steps} tool_calls={tool_calls}", steps, tool_calls, tokens_used
    )


def save_investigation_report(claim_id: str, report: dict, rules_opinion: dict, final_result: str) -> str:
    """审计落盘：output/reports/agent_investigations/{claim_id}.json"""
    reports_dir = os.path.join(REPO_ROOT, "output", "reports", "agent_investigations")
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"{claim_id}.json")
    payload = {
        "claimId": claim_id,
        "savedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "rulesOpinion": rules_opinion,
        "finalResult": final_result,
        "investigation": report,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
