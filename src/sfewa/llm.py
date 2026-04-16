"""LLM provider factory with thinking mode control.

Both Qwen3.5 and Gemma 4 use the same chat_template_kwargs interface:
  - Thinking mode: enable_thinking=True → chain-of-thought in reasoning_content
  - Non-thinking mode: enable_thinking=False → direct answer

vLLM extracts thinking into reasoning_content via --reasoning-parser (qwen3/gemma4).
LLMClient._normalize() reads it from choice.message.reasoning_content.

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

def _build_sampling_params() -> dict[ThinkingMode, SamplingParams]:
    """Build sampling params based on model name."""
    model = os.environ.get("DEFAULT_LLM_MODEL", "")
    model_lower = model.lower()

    if "qwen" in model_lower:
        # Qwen3.5: use chat_template_kwargs for thinking mode
        return {
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
    elif "gemma" in model_lower:
        # Gemma 4: same enable_thinking interface, vLLM --reasoning-parser gemma4
        # Thinking blocks use <|channel>thought\n...<channel|> delimiters
        # skip_special_tokens=false required for parser to see channel delimiters
        return {
            "thinking": SamplingParams(
                temperature=1.0,
                top_p=0.95,
                max_tokens=16384,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": True},
                    "skip_special_tokens": False,
                },
            ),
            "non_thinking": SamplingParams(
                temperature=0.7,
                top_p=0.9,
                max_tokens=8192,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            ),
        }
    else:
        # Generic: no thinking mode, conservative tokens
        return {
            "thinking": SamplingParams(
                temperature=0.7,
                top_p=0.9,
                max_tokens=16384,
            ),
            "non_thinking": SamplingParams(
                temperature=0.7,
                top_p=0.9,
                max_tokens=8192,
            ),
        }


SAMPLING_PARAMS: dict[ThinkingMode, SamplingParams] = _build_sampling_params()


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
