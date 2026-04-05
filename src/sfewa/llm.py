"""LLM provider factory for Qwen3.5 on vLLM with thinking mode control.

Qwen3.5 has two modes (NOT two models):
  - Thinking mode (enable_thinking=True): generates <think>...</think> chain-of-thought
    before the answer. Use for adversarial review, risk synthesis.
  - Non-thinking mode (enable_thinking=False): direct answer, faster.
    Use for extraction, retrieval, analysis.

Thin wrapper over liteagent.LLMClient and liteagent.LLMRouter.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from liteagent import LLMClient, LLMRouter, SamplingParams

# Re-export LLMResponse from liteagent so existing agent imports still work
from liteagent.llm import LLMResponse  # noqa: F401

ThinkingMode = Literal["thinking", "non_thinking"]

# Map agent roles to thinking modes
ROLE_TO_MODE: dict[str, ThinkingMode] = {
    "retrieval": "non_thinking",
    "extraction": "non_thinking",
    "industry_analyst": "non_thinking",
    "company_analyst": "non_thinking",
    "peer_analyst": "non_thinking",
    "backtest": "non_thinking",
    "adversarial": "thinking",
    "synthesis": "thinking",
}

# Recommended sampling params per Qwen3.5 docs
SAMPLING_PARAMS: dict[ThinkingMode, SamplingParams] = {
    "thinking": SamplingParams(
        temperature=1.0,
        top_p=0.95,
        max_tokens=81920,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
    ),
    "non_thinking": SamplingParams(
        temperature=0.7,
        top_p=0.8,
        max_tokens=32768,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    ),
}


def get_base_url() -> str:
    url = os.environ.get("DEFAULT_BASE_URL", "")
    if not url:
        raise ValueError("DEFAULT_BASE_URL not set in .env")
    return url


def get_model_name() -> str:
    model = os.environ.get("DEFAULT_LLM_MODEL", "")
    if not model:
        raise ValueError("DEFAULT_LLM_MODEL not set in .env")
    return model


@lru_cache(maxsize=2)
def _create_llm(thinking: bool) -> LLMClient:
    """Create an LLMClient instance configured for thinking or non-thinking mode."""
    mode: ThinkingMode = "thinking" if thinking else "non_thinking"
    return LLMClient(
        model=get_model_name(),
        base_url=get_base_url(),
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        sampling=SAMPLING_PARAMS[mode],
    )


def get_llm(thinking: bool = False) -> LLMClient:
    """Get an LLM instance with thinking mode on or off."""
    return _create_llm(thinking)


def get_llm_for_role(role: str) -> LLMClient:
    """Get the LLM instance appropriate for a given agent role.

    Adversarial review and synthesis use thinking mode.
    Everything else uses non-thinking mode for speed.
    """
    mode = ROLE_TO_MODE.get(role, "non_thinking")
    return get_llm(thinking=(mode == "thinking"))
