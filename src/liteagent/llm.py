"""Provider-agnostic LLM client via OpenAI-compatible API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    """Normalized LLM response.

    All provider-specific quirks (vLLM reasoning_content, Anthropic thinking blocks)
    are normalized into this single type. Agent code never touches raw API responses.
    """
    content: str
    thinking: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class SamplingParams:
    """LLM sampling configuration."""
    temperature: float = 0.7
    max_tokens: int = 32768
    top_p: float = 0.8
    extra_body: dict = field(default_factory=dict)


class LLMClient:
    """Thin wrapper around OpenAI SDK.

    Why wrap at all? Three reasons:
    1. Normalize responses (vLLM puts thinking in .reasoning_content, not .content)
    2. Consistent interface for observation hooks
    3. Clean separation between provider config and call-site code

    The wrapper is ~40 lines of real logic. If it ever fights you, drop to
    self.client directly -- that's the escape hatch.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "not-needed",
        sampling: SamplingParams | None = None,
    ) -> None:
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._sampling = sampling or SamplingParams()

    def call(
        self,
        messages: list[dict[str, str]],
        *,
        sampling: SamplingParams | None = None,
    ) -> LLMResponse:
        """Call the LLM. Returns normalized response."""
        p = sampling or self._sampling
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=p.temperature,
            max_tokens=p.max_tokens,
            top_p=p.top_p,
            extra_body=p.extra_body or None,
        )
        return self._normalize(resp)

    def call_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        sampling: SamplingParams | None = None,
    ) -> LLMResponse:
        """Call the LLM with tool definitions (OpenAI function calling).

        The response may contain tool_calls instead of (or in addition to)
        content. Use ``parse_tool_calls()`` from ``liteagent.tool`` to extract them.
        """
        p = sampling or self._sampling
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": p.temperature,
            "max_tokens": p.max_tokens,
            "top_p": p.top_p,
        }
        if tools:
            kwargs["tools"] = tools
        if p.extra_body:
            kwargs["extra_body"] = p.extra_body
        resp = self._client.chat.completions.create(**kwargs)
        return self._normalize(resp)

    # Backward-compatible alias used by SFEWA agents
    def invoke(self, messages: list[dict]) -> LLMResponse:
        """Alias for call() -- backward compatible with SFEWA agent nodes."""
        return self.call(messages)

    def _normalize(self, resp: Any) -> LLMResponse:
        """Normalize provider-specific response into LLMResponse."""
        choice = resp.choices[0]
        content = choice.message.content or ""

        # vLLM with --reasoning-parser puts thinking in .reasoning_content
        # or .reasoning (vLLM 0.19+), or in model_extra dict
        thinking = getattr(choice.message, "reasoning_content", None)
        if thinking is None:
            thinking = getattr(choice.message, "reasoning", None)
        if thinking is None and hasattr(choice.message, "model_extra"):
            thinking = (choice.message.model_extra or {}).get("reasoning")

        usage = resp.usage
        token_usage = TokenUsage(
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )

        return LLMResponse(
            content=content,
            thinking=thinking,
            usage=token_usage,
            raw=resp,
        )

    @property
    def client(self) -> OpenAI:
        """Escape hatch: access the raw OpenAI client."""
        return self._client

    @property
    def model(self) -> str:
        """The model name/id."""
        return self._model


class LLMRouter:
    """Maps role names to LLMClient instances.

    Replaces SFEWA's ROLE_TO_MODE + get_llm_for_role pattern with a
    generic, configurable version.

    Usage:
        router = LLMRouter(
            clients={"thinking": thinking_llm, "fast": fast_llm},
            role_map={"adversarial": "thinking", "extraction": "fast"},
            default="fast",
        )
        llm = router.get("adversarial")  # returns thinking_llm
    """

    def __init__(
        self,
        clients: dict[str, LLMClient],
        role_map: dict[str, str],
        default: str = "default",
    ) -> None:
        self._clients = clients
        self._role_map = role_map
        self._default = default

    def get(self, role: str) -> LLMClient:
        """Get the LLM client for a given role."""
        client_key = self._role_map.get(role, self._default)
        client = self._clients.get(client_key)
        if client is None:
            raise KeyError(
                f"No LLM client for role={role!r} (mapped to {client_key!r}). "
                f"Available: {list(self._clients)}"
            )
        return client
