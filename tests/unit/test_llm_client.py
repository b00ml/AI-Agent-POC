"""LLM Client 全局限流器与调用行为测试（假 OpenAI 客户端，无网络）。"""

import threading
import time
from types import SimpleNamespace

from core.llm_client import GlobalLimiter, LLMClient, _is_retryable_error


class FakeCompletions:
    """记录并发峰值与调用参数的假 completions 实现。"""

    def __init__(self, contents=None, delay=0.03, fail_first=0):
        self.contents = contents or ['{"ok": 1}']
        self.delay = delay
        self.fail_first = fail_first
        self.calls = 0
        self.kwargs_seen = {}
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def create(self, **kwargs):
        with self._lock:
            self.calls += 1
            self.kwargs_seen.update(kwargs)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self._lock:
            self.active -= 1
        if self.calls <= self.fail_first:
            raise TimeoutError("simulated network error")
        idx = min(self.calls, len(self.contents)) - 1
        content = self.contents[idx]
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


def make_client(fake, limiter):
    return LLMClient(
        api_key="x", base_url="http://x", model="m",
        openai_client=SimpleNamespace(chat=SimpleNamespace(completions=fake)),
        limiter=limiter,
    )


def test_limiter_bounds_global_concurrency():
    limiter = GlobalLimiter(max_concurrency=2)
    fake = FakeCompletions(delay=0.05)
    client = make_client(fake, limiter)
    threads = [
        threading.Thread(target=lambda i=i: client.chat_json(f"q{i}"))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert fake.max_active <= 2
    assert client.stats["calls"] == 8
    assert client.stats["failures"] == 0


def test_limiter_reads_env_with_fallback(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "1")
    assert GlobalLimiter().max_concurrency == 1
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "not-a-number")
    assert GlobalLimiter().max_concurrency == 4  # 非法值回退默认
    monkeypatch.delenv("LLM_MAX_CONCURRENCY", raising=False)
    assert GlobalLimiter().max_concurrency == 4


def test_min_interval_paces_requests(monkeypatch):
    monkeypatch.setenv("LLM_MIN_INTERVAL_MS", "40")
    limiter = GlobalLimiter(max_concurrency=4)
    fake = FakeCompletions(delay=0.0)
    client = make_client(fake, limiter)
    t0 = time.monotonic()
    for i in range(4):
        client.chat_json(f"q{i}")
    elapsed = time.monotonic() - t0
    # 下界容忍 Windows sleep 轻微欠冲；上界证明节流确实生效（无节流时 <10ms）
    assert 0.09 <= elapsed <= 1.0


def test_chat_json_parse_failure_returns_none_and_counts():
    fake = FakeCompletions(contents=["这不是 JSON"])
    client = make_client(fake, GlobalLimiter(max_concurrency=1))
    assert client.chat_json("hi") is None
    assert client.stats["failures"] == 1


def test_chat_json_validator_repair_then_pass():
    fake = FakeCompletions(contents=['{"bad": 1}', '{"result": "APPROVE"}'])
    client = make_client(fake, GlobalLimiter(max_concurrency=1))

    def validator(d):
        return d.get("result") == "APPROVE"

    out = client.chat_json("hi", validator=validator)
    assert out == {"result": "APPROVE"}
    assert client.stats["retries"] >= 1
    assert fake.calls == 2


def test_chat_json_retries_on_exception_then_succeeds():
    fake = FakeCompletions(fail_first=1)
    client = make_client(fake, GlobalLimiter(max_concurrency=1))
    out = client.chat_json("hi")
    assert out == {"ok": 1}
    assert client.stats["retries"] == 1
    assert client.stats["calls"] == 1


def test_chat_passes_tools_through():
    fake = FakeCompletions()
    client = make_client(fake, GlobalLimiter(max_concurrency=1))
    tools = [{"type": "function", "function": {"name": "t1"}}]
    client.chat([{"role": "user", "content": "hi"}], tools=tools, trace_id="t")
    assert fake.kwargs_seen.get("tools") == tools


def test_chat_with_stats_binds_usage_to_message():
    fake = FakeCompletions()
    fake.create = lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[]))],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=5),
    )
    client = make_client(fake, GlobalLimiter(max_concurrency=1))
    result = client.chat_with_stats([{"role": "user", "content": "hi"}], trace_id="bound")
    assert result.message.tool_calls == []
    assert result.stats.trace_id == "bound"
    assert result.stats.total_tokens == 12
    assert client.get_budget_status()["used"] == 12


def test_retry_classifier_rejects_unknown_errors():
    assert _is_retryable_error(RuntimeError("bad request")) is False
    assert _is_retryable_error(TimeoutError("network")) is True


def test_chat_json_does_not_retry_unknown_error():
    fake = FakeCompletions(contents=["not json"])
    client = make_client(fake, GlobalLimiter(max_concurrency=1))
    assert client.chat_json("hi", repair_hint="fix") is None
    # 内容错误只允许一次修复请求，不按网络故障重试到 max_retries。
    assert fake.calls == 2


def test_chat_json_strictly_rejects_wrapped_json():
    fake = FakeCompletions(contents=["前缀 {\"ok\": 1} 后缀"])
    client = make_client(fake, GlobalLimiter(max_concurrency=1),)
    assert client.chat_json("hi") is None
