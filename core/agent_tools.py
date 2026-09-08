"""
调查 Agent 只读工具层（设计文档 3.0 M33：工具增强）

红线：工具层只有只读操作，不存在任何改变 ERP 单据状态的写工具；
「AI 不改状态」在架构层强制，而不依赖提示词约束。

M33 增强：
- ToolCapability：readonly/required_scopes/timeout_ms/max_output_bytes
- JSON Schema 参数校验（jsonschema 库）
- ToolCallRecord：call_id/duration/input_digest/output_digest/error_code
- 拒绝重复注册和未知字段
"""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.logger import get_logger

logger = get_logger("agent_tools")

# 可选依赖：jsonschema 用于参数校验
try:
    import jsonschema
    from jsonschema import ValidationError as JsonSchemaValidationError

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    JsonSchemaValidationError = Exception  # type: ignore


@dataclass
class ToolCapability:
    """工具元数据（M33 工具增强）"""

    readonly: bool = True
    required_scopes: List[str] = field(default_factory=list)
    timeout_ms: int = 30000
    max_output_bytes: int = 1048576  # 1MB


@dataclass
class ToolCallRecord:
    """单次工具调用记录（M33 工具增强）"""

    call_id: str
    tool_name: str
    trace_id: str
    start_time: float
    duration_ms: int
    input_digest: str
    output_digest: str
    ok: bool
    error_code: str = ""


class ToolRegistry:
    """OpenAI function calling 格式的只读工具注册表（M33 增强版）"""

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._call_records: List[ToolCallRecord] = []

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable[..., Any],
        capability: Optional[ToolCapability] = None,
    ) -> None:
        """注册工具，M33 增强：拒绝重复注册、校验 parameters 结构"""
        if name in self._tools:
            raise ValueError(f"工具 {name} 已注册，禁止重复注册")

        # 校验 parameters 必须是合法 JSON Schema object
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ValueError(f"工具 {name} 的 parameters 必须是 type=object 的 JSON Schema")

        # 检查未知字段
        allowed_keys = {"type", "properties", "required", "description", "additionalProperties"}
        unknown = set(parameters.keys()) - allowed_keys
        if unknown:
            logger.warning("工具 %s 的 parameters 包含未知字段: %s", name, unknown)
        if not isinstance(parameters.get("properties", {}), dict):
            raise ValueError(f"工具 {name} 的 properties 必须是 object")
        # OpenAI function schema 若未声明 additionalProperties，jsonschema 默认允许
        # 任意未知字段；工具边界默认拒绝，调用方必须显式声明例外。
        parameters = dict(parameters)
        parameters.setdefault("additionalProperties", False)

        if capability is None:
            capability = ToolCapability()

        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
            "capability": capability,
        }
        logger.info(
            "工具注册: %s (readonly=%s, timeout=%dms, max_output=%d)",
            name,
            capability.readonly,
            capability.timeout_ms,
            capability.max_output_bytes,
        )

    @property
    def names(self) -> List[str]:
        return list(self._tools)

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in self._tools.values()
        ]

    def dispatch(
        self,
        name: str,
        args_json: str,
        call_id: str = "",
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """执行工具并包装结果（M33 增强：schema 校验、调用记录、超时、输出截断）"""
        t0 = time.time()
        tool = self._tools.get(name)

        if tool is None:
            return self._error_result(
                name,
                call_id,
                trace_id,
                t0,
                "unknown_tool",
                f"未知工具: {name}",
                args_json,
            )

        capability: ToolCapability = tool["capability"]

        # 1. JSON 解析
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError as e:
            return self._error_result(
                name,
                call_id,
                trace_id,
                t0,
                "invalid_json",
                f"参数 JSON 非法: {e}",
                args_json,
            )

        # 2. JSON Schema 参数校验（M33 要求）
        if JSONSCHEMA_AVAILABLE:
            try:
                jsonschema.validate(instance=args, schema=tool["parameters"])
            except JsonSchemaValidationError as e:
                return self._error_result(
                    name,
                    call_id,
                    trace_id,
                    t0,
                    "schema_validation_error",
                    f"参数校验失败: {e.message}",
                    args_json,
                )
        else:
            # 依赖缺失时不能静默跳过边界校验；至少执行 object/required/未知字段
            # 三项不依赖第三方库的检查，并以稳定错误码暴露能力降级。
            schema = tool["parameters"]
            if not isinstance(args, dict):
                return self._error_result(
                    name,
                    call_id,
                    trace_id,
                    t0,
                    "schema_validation_unavailable",
                    "参数必须是 JSON object",
                    args_json,
                )
            required = set(schema.get("required", []))
            missing = required - set(args)
            unknown = set(args) - set(schema.get("properties", {}))
            if missing or (schema.get("additionalProperties") is False and unknown):
                return self._error_result(
                    name,
                    call_id,
                    trace_id,
                    t0,
                    "schema_validation_unavailable",
                    "参数不符合已注册 schema",
                    args_json,
                )

        # 3. 执行工具（捕获所有异常，不中断 Agent 循环）
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-tool")
        future = executor.submit(tool["func"], **args)
        try:
            data = future.result(timeout=max(0, capability.timeout_ms) / 1000.0)
            result = {"ok": True, "data": data, "call_id": call_id, "tool": name}
            error_code = ""
        except FutureTimeoutError:
            future.cancel()
            return self._error_result(
                name,
                call_id,
                trace_id,
                t0,
                "TOOL_TIMEOUT",
                f"工具执行超过 {capability.timeout_ms}ms",
                args_json,
            )
        except Exception as e:
            logger.warning("工具 %s 执行失败: %s", name, e, exc_info=True)
            error_msg = str(e)[:300]
            result = {"ok": False, "error": error_msg, "call_id": call_id, "tool": name}
            error_code = type(e).__name__
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        duration_ms = int((time.time() - t0) * 1000)

        # 4. 输出截断（M33 要求）
        output_str = json.dumps(result, ensure_ascii=False)
        if len(output_str.encode("utf-8")) > capability.max_output_bytes:
            original_len = len(output_str)
            if result.get("ok") and "data" in result:
                result["data"] = {"_truncated": True, "_original_size": original_len}
                result["_output_truncated"] = True
                output_str = json.dumps(result, ensure_ascii=False)
                logger.warning(
                    "工具 %s 输出超过 %d 字节，已截断（原始 %d 字节）",
                    name,
                    capability.max_output_bytes,
                    original_len,
                )

        # 5. 记录调用（M33 要求）
        record = ToolCallRecord(
            call_id=call_id,
            tool_name=name,
            trace_id=trace_id,
            start_time=t0,
            duration_ms=duration_ms,
            input_digest=self._digest(args_json),
            output_digest=self._digest(output_str),
            ok=result.get("ok", False),
            error_code=error_code,
        )
        self._call_records.append(record)

        logger.info(
            "tool_call trace=%s tool=%s call=%s ms=%d ok=%s error=%s",
            trace_id,
            name,
            call_id,
            duration_ms,
            result.get("ok"),
            error_code or "none",
        )

        return result

    def _error_result(
        self,
        name: str,
        call_id: str,
        trace_id: str,
        t0: float,
        error_code: str,
        error_msg: str,
        args_json: str,
    ) -> Dict[str, Any]:
        """统一错误结果构造"""
        duration_ms = int((time.time() - t0) * 1000)
        result = {"ok": False, "error": error_msg, "call_id": call_id, "tool": name}

        record = ToolCallRecord(
            call_id=call_id,
            tool_name=name,
            trace_id=trace_id,
            start_time=t0,
            duration_ms=duration_ms,
            input_digest=self._digest(args_json),
            output_digest=self._digest(json.dumps(result, ensure_ascii=False)),
            ok=False,
            error_code=error_code,
        )
        self._call_records.append(record)

        logger.warning(
            "tool_call trace=%s tool=%s call=%s ms=%d error=%s",
            trace_id,
            name,
            call_id,
            duration_ms,
            error_code,
        )
        return result

    @staticmethod
    def _digest(s: str) -> str:
        """SHA256 摘要（M33 要求，用于输入输出去重和审计）"""
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

    def get_call_records(self) -> List[ToolCallRecord]:
        """获取所有调用记录（M33 要求）"""
        return self._call_records.copy()

    def clear_call_records(self) -> None:
        """清空调用记录（用于批量处理间隔清理）"""
        self._call_records.clear()

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)


def _kb_keywords(query: str) -> set:
    from core.retrieval import QUERY_KEYWORDS

    return {tag for key, tag in QUERY_KEYWORDS.items() if key in query}


def build_default_registry(ctx: Dict[str, Any]) -> ToolRegistry:
    """按运行上下文构建默认工具集。

    ctx 需要提供：
      client           QihengClient（只读 API 封装）
      travel_manager   TravelDataManager（已 load_data）
      retriever        PolicyRetriever（制度知识库）
      ocr_results      {attachment_id: OCR 要素 dict}（本次批次缓存）
      invoice_index    {code/no: [claimId]}（全量发票索引）
    """
    registry = ToolRegistry()

    registry.register(
        "query_travel_standards",
        "查询指定职级与城市档次的差旅标准（住宿/伙食/市内交通上限与舱位标准）",
        {
            "type": "object",
            "properties": {
                "job_level": {"type": "string", "description": "职级，如 STAFF/MANAGER"},
                "city_tier": {"type": "string", "description": "城市档次，如 TIER1/TIER2/TIER3"},
            },
            "required": ["job_level", "city_tier"],
        },
        lambda job_level, city_tier: ctx["travel_manager"].get_standard(job_level, city_tier),
        capability=ToolCapability(readonly=True, timeout_ms=1000, max_output_bytes=4096),
    )

    def _search_kb(query: str, top_k: int = 5) -> Dict[str, Any]:
        chunks = ctx["retriever"].retrieve(
            query_text=query,
            keywords=_kb_keywords(query),
            top_k=max(1, min(top_k, 10)),
        )
        return {
            "clauses": [
                {
                    "id": c.get("id", ""),
                    "doc": c.get("metadata", {}).get("doc", ""),
                    "article": c.get("metadata", {}).get("article", ""),
                    "content": c.get("content", ""),
                }
                for c in chunks
            ],
        }

    registry.register(
        "search_policy_kb",
        "检索公司制度知识库（报销管理办法/发票合规指引/审批权限矩阵/供应商管理办法），"
        "返回带出处的条款原文。引用条款必须来自本工具返回内容。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言问题描述"},
                "top_k": {"type": "integer", "description": "返回条款数，默认 5"},
            },
            "required": ["query"],
        },
        _search_kb,
        capability=ToolCapability(readonly=True, timeout_ms=5000, max_output_bytes=65536),
    )

    registry.register(
        "get_approval_records",
        "查询报销单的审批记录（含特批 SPECIAL_APPROVE 与事前审批环节）",
        {
            "type": "object",
            "properties": {"claim_id": {"type": "string", "description": "报销单 ID"}},
            "required": ["claim_id"],
        },
        lambda claim_id: ctx["client"].approvals_for_claim(claim_id),
        capability=ToolCapability(readonly=True, timeout_ms=3000, max_output_bytes=32768),
    )

    def _get_invoice_ocr(attachment_id: str) -> Dict[str, Any]:
        data = (ctx.get("ocr_results") or {}).get(attachment_id)
        if data is None:
            return {"found": False, "note": "该附件无 OCR 缓存（可能未迁移或非票据）"}
        return {"found": True, "fields": data}

    registry.register(
        "get_invoice_ocr",
        "查询发票附件的 OCR 票面要素（购方名称/税号/票面金额），仅文本要素",
        {
            "type": "object",
            "properties": {"attachment_id": {"type": "string", "description": "附件 ID"}},
            "required": ["attachment_id"],
        },
        _get_invoice_ocr,
        capability=ToolCapability(readonly=True, timeout_ms=1000, max_output_bytes=8192),
    )

    def _check_invoice_ledger(invoice_code: str, invoice_no: str) -> Dict[str, Any]:
        key = f"{(invoice_code or '').strip()}/{(invoice_no or '').strip()}"
        claim_ids = (ctx.get("invoice_index") or {}).get(key, [])
        return {
            "key": key,
            "usageCount": len(claim_ids),
            "claimIds": sorted(set(claim_ids)),
            "duplicate": len(claim_ids) > 1,
        }

    registry.register(
        "check_invoice_ledger",
        "按发票代码+号码查全量台账：该发票共被多少张报销单使用（重复报销核查）",
        {
            "type": "object",
            "properties": {
                "invoice_code": {"type": "string"},
                "invoice_no": {"type": "string"},
            },
            "required": ["invoice_code", "invoice_no"],
        },
        _check_invoice_ledger,
        capability=ToolCapability(readonly=True, timeout_ms=1000, max_output_bytes=8192),
    )

    return registry
