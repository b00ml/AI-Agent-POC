"""
统一 LLM Client（AI 应用基础工程：LLM API 工程化）

能力：
- 重试：网络错误/5xx 指数退避；429 按 Retry-After 退避
- 超时：连接/读取分层（OpenAI client timeout）
- 结构化输出：JSON 模式 + schema 校验 + 一次修复重试 + None 兜底
- 工具调用：chat() 暴露原生 function calling，供调查 Agent 多轮循环使用
- 全局限流：进程级并发上限 + 请求节流（M2 复核 / M3 巡检 / 调查 Agent 共用）
- 可观测性：结构化日志（trace_id、模型、耗时、token、重试、错误）

M33 增强：
- 调用级 token 统计（prompt_tokens/completion_tokens/total_cost）
- 错误分类重试（网络/5xx 可重试，参数/权限错误不重试）
- 可配置 token 预算（chat 方法支持预算检查）
"""

import json
import os
import time
import logging
import threading
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable

from openai import OpenAI, APIError, APIConnectionError, RateLimitError, APIStatusError

logger = logging.getLogger("llm_client")


@dataclass
class LLMCallStats:
    """单次 LLM 调用统计（M33 增强）"""

    trace_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost: float  # 美元
    duration_ms: int
    ok: bool
    error_type: str = ""
    retries: int = 0


@dataclass(frozen=True)
class LLMChatResult:
    """消息和本次调用的独立统计。

    调用方需要统计一次调用的 token/cost 时必须读取 ``stats``，不能读取
    ``last_usage``；后者仅为历史调用方兼容保留，在线程并发时不具有调用关联性。
    """

    message: Any
    stats: LLMCallStats


def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """粗略估算成本（M33 要求，用于预算控制和成本报表）

    基于 2024 年公开定价，实际应从配置读取或调用计费 API。
    """
    # DeepSeek 价格参考（元/百万token）
    pricing = {
        "deepseek-chat": (0.14, 0.28),  # 输入/输出 人民币/M token
        "deepseek-reasoner": (0.55, 2.19),
    }

    model_key = "deepseek-chat"  # 默认
    for key in pricing:
        if key in model.lower():
            model_key = key
            break

    input_price, output_price = pricing[model_key]
    # 转换为美元（1 USD ≈ 7.2 CNY）
    cost_cny = prompt_tokens / 1_000_000 * input_price + completion_tokens / 1_000_000 * output_price
    return cost_cny / 7.2


def _is_retryable_error(e: Exception) -> bool:
    """判断错误是否可重试（M33 错误分类）

    可重试：网络错误、5xx、429
    不可重试：参数错误、权限错误、4xx（除429）
    """
    if isinstance(e, (APIConnectionError, TimeoutError)):
        return True
    if isinstance(e, RateLimitError):
        return True
    if isinstance(e, APIStatusError):
        # 5xx 可重试，4xx 不可重试（除了 429）
        status = getattr(e, "status_code", 0)
        return status >= 500 or status == 429
    if isinstance(e, APIError):
        # 其他 API 错误，默认不重试
        return False
    # 其他未知错误，保守起见不重试
    return False


class GlobalLimiter:
    """进程级 LLM 并发/速率限制器。

    - 并发上限：env ``LLM_MAX_CONCURRENCY``（默认 4），BoundedSemaphore 实现；
      M2 AI 复核线程池、M3 巡检线程池与调查 Agent 共用一个全局上限，
      并发值需经压测标定（吞吐 = 单均延迟 × 并发），不要拍脑袋调大。
    - 请求节流：env ``LLM_MIN_INTERVAL_MS``（默认 0，毫秒），相邻请求发起的最小间隔，
      用于对服务商 QPS 上限做令牌节流。
    """

    def __init__(
        self, max_concurrency: Optional[int] = None, min_interval_ms: Optional[float] = None
    ) -> None:
        if max_concurrency is None:
            try:
                max_concurrency = int(os.environ.get("LLM_MAX_CONCURRENCY", "4"))
            except ValueError:
                max_concurrency = 4
        if min_interval_ms is None:
            try:
                min_interval_ms = float(os.environ.get("LLM_MIN_INTERVAL_MS", "0"))
            except ValueError:
                min_interval_ms = 0.0
        self.max_concurrency = max(1, int(max_concurrency))
        self.min_interval = max(0.0, float(min_interval_ms)) / 1000.0
        self._sem = threading.BoundedSemaphore(self.max_concurrency)
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self) -> None:
        """先按最小间隔排队（不占并发槽），再取并发槽位。"""
        if self.min_interval > 0:
            with self._lock:
                now = time.monotonic()
                wait = self._next_slot - now
                self._next_slot = max(now, self._next_slot) + self.min_interval
            if wait > 0:
                time.sleep(wait)
        self._sem.acquire()

    def release(self) -> None:
        self._sem.release()

    def __enter__(self) -> "GlobalLimiter":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> bool:
        self.release()
        return False


_global_limiter = GlobalLimiter()


def get_global_limiter() -> GlobalLimiter:
    return _global_limiter


def set_global_limiter(limiter: GlobalLimiter) -> None:
    """替换进程级限制器（测试或运行时动态调整用）。"""
    global _global_limiter
    _global_limiter = limiter


class LLMClient:
    """OpenAI 兼容的统一 LLM 调用封装"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        max_retries: int = 3,
        timeout: float = 90.0,
        openai_client: Any = None,
        limiter: Optional[GlobalLimiter] = None,
        token_budget: Optional[int] = None,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        # openai_client 仅供测试注入假实现
        self.client = (
            openai_client
            if openai_client is not None
            else OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
            )
        )
        self.limiter = limiter or get_global_limiter()
        self._stats_lock = threading.Lock()
        self.stats = {"calls": 0, "retries": 0, "failures": 0}
        self.last_usage: Any = None  # 最近一次 chat 的 usage（调查 Agent token 预算用）
        # M33 增强
        self.token_budget = token_budget
        self.tokens_used = 0
        self.call_stats_history: List[LLMCallStats] = []

    def _bump(self, key: str) -> None:
        with self._stats_lock:
            self.stats[key] += 1

    def _record_success(self, *, trace_id: str, usage: Any, duration_ms: int, retries: int) -> LLMCallStats:
        """原子记录一次成功调用，并返回调用级不可变统计。"""
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = prompt_tokens + completion_tokens
        call_stat = LLMCallStats(
            trace_id=trace_id,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            total_cost=_calculate_cost(self.model, prompt_tokens, completion_tokens),
            duration_ms=duration_ms,
            ok=True,
            retries=retries,
        )
        with self._stats_lock:
            # 兼容旧调用方；新调用方必须使用 LLMChatResult.stats。
            self.last_usage = usage
            self.tokens_used += total_tokens
            self.call_stats_history.append(call_stat)
            self.stats["calls"] += 1
        return call_stat

    def _record_failure(self, *, trace_id: str, duration_ms: int, error: Exception, retries: int) -> None:
        """原子记录一个已终止的调用；中间重试不记为独立失败。"""
        call_stat = LLMCallStats(
            trace_id=trace_id,
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            total_cost=0.0,
            duration_ms=duration_ms,
            ok=False,
            error_type=type(error).__name__,
            retries=retries,
        )
        with self._stats_lock:
            self.call_stats_history.append(call_stat)
            self.stats["failures"] += 1

    @staticmethod
    def _retry_delay(error: Exception, attempt: int) -> float:
        if isinstance(error, RateLimitError):
            retry_after = getattr(error, "retry_after", None)
            if retry_after is not None:
                try:
                    return max(0.0, float(retry_after))
                except (TypeError, ValueError):
                    pass
            return min(2.0 * (2**attempt), 60.0)
        return min(0.5 * (2**attempt), 8.0)

    def chat_json(
        self,
        prompt: str,
        validator: Optional[Callable[[Dict[str, Any]], bool]] = None,
        trace_id: str = "",
        repair_hint: str = "输出必须是符合要求的 JSON 对象，请修正后重新输出。",
    ) -> Optional[Dict[str, Any]]:
        """JSON 模式对话 + 结构校验；失败返回 None。

        传输错误按 ``max_retries`` 退避；模型内容解析或契约校验失败只允许
        一次修复请求，不把内容问题误判成网络故障而反复调用供应商。
        """
        messages = [{"role": "user", "content": prompt}]
        network_retries = 0
        repair_used = False
        while True:
            t0 = time.time()
            try:
                with self.limiter:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.1,
                    )
            except Exception as error:
                duration_ms = int((time.time() - t0) * 1000)
                retryable = _is_retryable_error(error)
                if not retryable or network_retries >= self.max_retries:
                    self._record_failure(
                        trace_id=trace_id,
                        duration_ms=duration_ms,
                        error=error,
                        retries=network_retries,
                    )
                    logger.warning(
                        "llm_call trace=%s model=%s ok=0 ms=%d err=%s",
                        trace_id,
                        self.model,
                        duration_ms,
                        str(error)[:200],
                    )
                    return None
                self._bump("retries")
                wait = self._retry_delay(error, network_retries)
                logger.info(
                    "llm_call trace=%s retry=%d/%d error=%s wait=%.1fs",
                    trace_id,
                    network_retries + 1,
                    self.max_retries,
                    type(error).__name__,
                    wait,
                )
                network_retries += 1
                time.sleep(wait)
                continue

            content = response.choices[0].message.content or ""
            call_stat = self._record_success(
                trace_id=trace_id,
                usage=response.usage,
                duration_ms=int((time.time() - t0) * 1000),
                retries=network_retries,
            )
            parsed = self._parse_json(content)
            if parsed is not None and (validator is None or validator(parsed)):
                logger.info(
                    "llm_call trace=%s model=%s ok=1 ms=%d in=%s out=%s retries=%d",
                    trace_id,
                    self.model,
                    int((time.time() - t0) * 1000),
                    call_stat.prompt_tokens,
                    call_stat.completion_tokens,
                    network_retries,
                )
                return parsed

            content_error = ValueError("JSON 解析失败" if parsed is None else "结构校验未通过")
            if repair_used:
                self._record_failure(
                    trace_id=trace_id,
                    duration_ms=int((time.time() - t0) * 1000),
                    error=content_error,
                    retries=network_retries,
                )
                logger.warning(
                    "llm_call trace=%s model=%s ok=0 ms=%d err=%s",
                    trace_id,
                    self.model,
                    int((time.time() - t0) * 1000),
                    content_error,
                )
                return None

            repair_used = True
            self._bump("retries")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": repair_hint})
            network_retries = 0

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        trace_id: str = "",
        check_budget: bool = True,
    ) -> Any:
        """兼容旧接口，仅返回 assistant message。"""
        return self.chat_with_stats(
            messages,
            tools=tools,
            trace_id=trace_id,
            check_budget=check_budget,
        ).message

    def chat_with_stats(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        trace_id: str = "",
        check_budget: bool = True,
    ) -> LLMChatResult:
        """原生对话调用，返回消息及本次调用的独立统计。"""
        if check_budget and self.token_budget is not None:
            with self._stats_lock:
                if self.tokens_used >= self.token_budget:
                    raise RuntimeError(f"Token budget exhausted: {self.tokens_used}/{self.token_budget}")

        network_retries = 0
        while True:
            t0 = time.time()
            try:
                with self.limiter:
                    kwargs: Dict[str, Any] = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.1,
                    }
                    if tools:
                        kwargs["tools"] = tools
                    response = self.client.chat.completions.create(**kwargs)
            except Exception as error:
                duration_ms = int((time.time() - t0) * 1000)
                retryable = _is_retryable_error(error)
                if not retryable or network_retries >= self.max_retries:
                    self._record_failure(
                        trace_id=trace_id,
                        duration_ms=duration_ms,
                        error=error,
                        retries=network_retries,
                    )
                    logger.warning(
                        "llm_chat trace=%s model=%s ms=%d error=%s%s",
                        trace_id,
                        self.model,
                        duration_ms,
                        type(error).__name__,
                        " (non-retryable)" if not retryable else " (max retries)",
                    )
                    raise
                self._bump("retries")
                wait = self._retry_delay(error, network_retries)
                logger.info(
                    "llm_chat trace=%s retry=%d/%d error=%s wait=%.1fs",
                    trace_id,
                    network_retries + 1,
                    self.max_retries,
                    type(error).__name__,
                    wait,
                )
                network_retries += 1
                time.sleep(wait)
                continue

            duration_ms = int((time.time() - t0) * 1000)
            call_stat = self._record_success(
                trace_id=trace_id,
                usage=response.usage,
                duration_ms=duration_ms,
                retries=network_retries,
            )
            logger.info(
                "llm_chat trace=%s model=%s ms=%d in=%d out=%d total=%d cost=%.6f retries=%d",
                trace_id,
                self.model,
                duration_ms,
                call_stat.prompt_tokens,
                call_stat.completion_tokens,
                call_stat.total_tokens,
                call_stat.total_cost,
                network_retries,
            )
            return LLMChatResult(response.choices[0].message, call_stat)

    def get_call_stats(self) -> List[LLMCallStats]:
        """获取调用统计历史（M33 要求）"""
        with self._stats_lock:
            return self.call_stats_history.copy()

    def get_budget_status(self) -> Dict[str, Any]:
        """获取预算使用状态（M33 要求）"""
        with self._stats_lock:
            return {
                "budget": self.token_budget,
                "used": self.tokens_used,
                "remaining": self.token_budget - self.tokens_used if self.token_budget else None,
                "utilization": self.tokens_used / self.token_budget if self.token_budget else None,
            }

    @staticmethod
    def _parse_json(content: str) -> Optional[Dict[str, Any]]:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
