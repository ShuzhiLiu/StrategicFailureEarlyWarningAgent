"""Module-level chat log accumulator for debugging.

Captures ALL pipeline interactions: LLM calls (prompts + responses + token usage)
and tool calls (search queries + results).

Saved as llm_history.jsonl in the run output directory.

Usage in agent nodes:
    from sfewa.tools.chat_log import log_llm_call, log_tool_call

    response = llm.invoke(messages)
    log_llm_call("node_name", messages, response, label="optional_detail")

    results = search_tool.invoke(query)
    log_tool_call("retrieval", "duckduckgo_search", {"query": query}, results)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_log: list[dict] = []


def log_llm_call(
    node: str,
    messages: list[dict],
    response: Any,
    *,
    label: str = "",
) -> None:
    """Record an LLM call for debugging.

    Args:
        node: Pipeline node name (e.g., "adversarial_review").
        messages: Messages sent to the LLM (list of role/content dicts).
        response: The LangChain AIMessage response object (or raw string).
        label: Optional sub-label (e.g., "seed_queries", "edinet_batch").
    """
    # Extract raw text — accept both AIMessage and plain string
    if isinstance(response, str):
        raw_text = response
        token_usage = {}
        thinking = ""
    else:
        # vLLM with --reasoning-parser qwen3 strips <think> blocks and puts
        # them in msg.reasoning or msg.reasoning_content
        reasoning = (
            getattr(response, "reasoning", None)
            or getattr(response, "reasoning_content", None)
        )
        if reasoning:
            raw_text = f"<think>{reasoning}</think>{response.content}"
            thinking = str(reasoning)
        else:
            raw_text = response.content or ""
            thinking = ""

        # Check for <think> tags in content (non-reasoning-parser setups)
        if not thinking:
            think_match = re.search(r"<think>([\s\S]*?)</think>", raw_text)
            if think_match:
                thinking = think_match.group(1).strip()

        # Extract token usage from response metadata
        meta = getattr(response, "response_metadata", {}) or {}
        usage = meta.get("token_usage", {})
        token_usage = {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }

    _log.append({
        "type": "llm_call",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": node,
        "label": label,
        "messages": messages,
        "raw_response": raw_text,
        "thinking": thinking,
        "token_usage": token_usage,
    })


def log_tool_call(
    node: str,
    tool_name: str,
    inputs: dict,
    outputs: Any,
    *,
    label: str = "",
) -> None:
    """Record a tool call (e.g., DuckDuckGo search) for debugging.

    Args:
        node: Pipeline node name.
        tool_name: Tool identifier (e.g., "duckduckgo_search").
        inputs: Tool input parameters.
        outputs: Raw tool output (will be converted to string if needed).
    """
    # Truncate large outputs to keep log manageable
    if isinstance(outputs, list):
        output_data = outputs[:20]  # cap at 20 results
    elif isinstance(outputs, str) and len(outputs) > 5000:
        output_data = outputs[:5000] + "... (truncated)"
    else:
        output_data = outputs

    _log.append({
        "type": "tool_call",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": node,
        "label": label,
        "tool_name": tool_name,
        "inputs": inputs,
        "outputs": output_data,
    })


def get_log() -> list[dict]:
    """Return accumulated chat log entries."""
    return list(_log)


def clear_log() -> None:
    """Clear accumulated log. Call at pipeline start."""
    _log.clear()
