"""大模型统一封装（OpenAI 兼容）：普通对话、流式输出、工具调用（Function Calling）。

通过统一接口封装 OpenAI / DeepSeek 等任何 OpenAI 兼容服务，运行时由配置中心
动态读取 base_url / api_key / model，支持热切换。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 调用异常。"""


class LLMClient:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str | list[str],
        timeout: float = 120.0,
        max_retries: int = 1,
    ) -> None:
        if not api_key:
            raise LLMError("未配置大模型 API Key，请在「系统设置」中填写后重试")
        self.api_base = api_base
        self.api_key = api_key
        # 模型列表（按顺序访问，前一个失败/额度耗尽后自动切换到下一个）
        models = list(model) if isinstance(model, (list, tuple)) else [model]
        self._models: list[str] = [str(m).strip() for m in models if str(m).strip()]
        if not self._models:
            raise LLMError("未配置大模型名称")
        self.model = self._models[0]
        # 单次请求超时（秒），避免慢请求长时间占用连接
        self.timeout = max(1.0, float(timeout))
        # 单模型重试次数（0 表示不重试）
        self.max_retries = max(0, int(max_retries))
        # 最近一次流式调用收集到的工具调用（无工具时为 [])
        self.last_tool_calls: list[dict] = []

    def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(base_url=self.api_base, api_key=self.api_key, timeout=self.timeout)

    def _build_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        tools: list[dict[str, Any]] | None,
        max_tokens: int | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = dict(
            model=model, messages=messages, temperature=temperature, stream=stream
        )
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def _create_with_retry(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        tools: list[dict[str, Any]] | None,
        max_tokens: int | None,
    ):
        """单个模型带退避重试的补全请求，失败抛出最后一次异常。"""
        kwargs = self._build_kwargs(model, messages, temperature, tools, max_tokens)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._client().chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - 超时/上游错误等一律重试
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                delay = 2 ** attempt  # 指数退避：1s / 2s ...
                logger.warning(
                    "LLM 模型 %s 调用失败，%.1fs 后重试(%d/%d): %s",
                    model, delay, attempt + 1, self.max_retries, exc,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def _to_result(self, resp) -> dict:
        msg = resp.choices[0].message
        tool_calls: list[dict] = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                )

        content = msg.content or ""
        usage: dict[str, int] = {}
        if getattr(resp, "usage", None) is not None:
            usage = {
                "input": int(getattr(resp.usage, "prompt_tokens", 0) or 0),
                "output": int(getattr(resp.usage, "completion_tokens", 0) or 0),
                "total": int(getattr(resp.usage, "total_tokens", 0) or 0),
            }
        return {
            "role": msg.role,
            "content": content,
            "tool_calls": tool_calls,
            "usage": usage,
        }

    async def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """非流式补全，返回 {role, content, tool_calls, usage}。

        按配置的模型顺序访问：当前模型上游错误/额度耗尽时自动切换下一个模型。
        """
        start = time.perf_counter()
        last_error: Exception | None = None
        for model in self._models:
            try:
                resp = await self._create_with_retry(
                    model, messages, temperature, tools, max_tokens
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("LLM 模型 %s 调用失败，切换至下一模型: %s", model, exc)
                continue
            result = self._to_result(resp)
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "LLM 补全完成: model=%s, 输出长度=%d, 工具调用=%d, 耗时=%dms",
                model,
                len(result["content"]),
                len(result["tool_calls"]),
                latency_ms,
            )
            return result
        raise LLMError(f"全部模型调用失败: {last_error}")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """流式补全，逐段产出增量文本。

        若提供 tools，模型可能在流式过程中发起工具调用；流结束后
        工具调用会聚合到 self.last_tool_calls（无工具调用时为 []）。
        """
        self.last_tool_calls = []
        kwargs: dict[str, Any] = dict(
            model=self.model, messages=messages, temperature=temperature, stream=True
        )
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        start = time.perf_counter()
        stream = await self._client().chat.completions.create(**kwargs)
        tool_calls: dict[int, dict] = {}
        total_len = 0
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                total_len += len(delta.content)
                yield delta.content
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = tc.index
                    entry = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function and tc.function.name:
                        entry["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        entry["arguments"] += tc.function.arguments

        self.last_tool_calls = [tool_calls[i] for i in sorted(tool_calls)]
        latency_ms = int((time.perf_counter() - start) * 1000)
        if self.last_tool_calls:
            logger.debug(
                "LLM 流式调用产出工具调用: %s",
                [tc["name"] for tc in self.last_tool_calls],
            )
        logger.info(
            "LLM 流式生成完成: model=%s, 输出长度=%d, 工具调用=%d, 耗时=%dms",
            self.model,
            total_len,
            len(self.last_tool_calls),
            latency_ms,
        )


def build_llm(cfg: dict[str, str]) -> LLMClient:
    """由运行时配置构建 LLM 客户端。

    - 模型优先读取 `llm_models`（逗号分隔的多个模型名），按顺序兜底切换；
    - 未配置时回退到 `llm_model`。
    """
    api_base = str(cfg.get("llm_api_base", "")).strip() or "https://api.deepseek.com"
    api_key = str(cfg.get("llm_api_key", "")).strip()
    models = [
        m.strip()
        for m in str(cfg.get("llm_models", "")).split(",")
        if m.strip()
    ]
    if not models:
        single = str(cfg.get("llm_model", "")).strip() or "deepseek-chat"
        models = [single]
    try:
        timeout = float(cfg.get("llm_timeout", "") or "120")
    except ValueError:
        timeout = 120.0
    try:
        max_retries = int(cfg.get("llm_max_retries", "") or "1")
    except ValueError:
        max_retries = 1
    logger.info("大模型准备：LLM 客户端已构建 (models=%s, base=%s)", models, api_base)
    return LLMClient(
        api_base=api_base, api_key=api_key, model=models,
        timeout=timeout, max_retries=max_retries,
    )