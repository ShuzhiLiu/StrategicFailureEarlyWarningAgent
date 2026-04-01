"""LLM provider factory for Qwen3.5 on vLLM with thinking mode control.

Qwen3.5 has two modes (NOT two models):
  - Thinking mode (enable_thinking=True): generates <think>...</think> chain-of-thought
    before the answer. Use for adversarial review, risk synthesis.
  - Non-thinking mode (enable_thinking=False): direct answer, faster.
    Use for extraction, retrieval, analysis.

Qwen3.5 also supports native tool calling (function calling) via the standard
OpenAI tools API. vLLM must be started with:
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3

Tool calling works in both thinking and non-thinking modes.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from langchain_openai import ChatOpenAI


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
SAMPLING_PARAMS: dict[ThinkingMode, dict] = {
    "thinking": {
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": 81920,
    },
    "non_thinking": {
        "temperature": 0.7,
        "top_p": 0.8,
        "max_tokens": 32768,
    },
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
def _create_llm(thinking: bool) -> ChatOpenAI:
    """Create a ChatOpenAI instance configured for thinking or non-thinking mode.

    Uses lru_cache so we reuse the same client across calls.
    """
    mode: ThinkingMode = "thinking" if thinking else "non_thinking"
    params = SAMPLING_PARAMS[mode]

    return ChatOpenAI(
        model=get_model_name(),
        base_url=get_base_url(),
        temperature=params["temperature"],
        max_tokens=params["max_tokens"],
        top_p=params["top_p"],
        extra_body={
            "chat_template_kwargs": {"enable_thinking": thinking},
        },
        api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
    )


def get_llm(thinking: bool = False) -> ChatOpenAI:
    """Get an LLM instance with thinking mode on or off.

    Args:
        thinking: If True, enables Qwen3.5's chain-of-thought reasoning.
                  If False, direct answer mode (faster).

    Tool calling: Use llm.bind_tools([tool1, tool2]) to enable tool calling.
    Qwen3.5 supports tool calling in both modes.
    """
    return _create_llm(thinking)


def get_llm_for_role(role: str) -> ChatOpenAI:
    """Get the LLM instance appropriate for a given agent role.

    Adversarial review and synthesis use thinking mode.
    Everything else uses non-thinking mode for speed.
    """
    mode = ROLE_TO_MODE.get(role, "non_thinking")
    return get_llm(thinking=(mode == "thinking"))
