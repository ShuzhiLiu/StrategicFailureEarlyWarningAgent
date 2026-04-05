"""Module-level chat log accumulator for debugging.

Thin wrapper over liteagent.CallLog. Maintains the same module-level
API that all SFEWA agent nodes use (log_llm_call, log_tool_call, get_log,
clear_log) while delegating to a liteagent CallLog instance.
"""

from __future__ import annotations

from typing import Any

from liteagent import CallLog

# Module-level singleton -- same API as before
_call_log = CallLog()


def log_llm_call(
    node: str,
    messages: list[dict],
    response: Any,
    *,
    label: str = "",
) -> None:
    """Record an LLM call for debugging."""
    _call_log.log_llm_call(node, messages, response, label=label)


def log_tool_call(
    node: str,
    tool_name: str,
    inputs: dict,
    outputs: Any,
    *,
    label: str = "",
) -> None:
    """Record a tool call for debugging."""
    _call_log.log_tool_call(node, tool_name, inputs, outputs, label=label)


def get_log() -> list[dict]:
    """Return accumulated chat log entries as dicts."""
    return _call_log.to_dicts()


def clear_log() -> None:
    """Clear accumulated log. Call at pipeline start."""
    _call_log.clear()
