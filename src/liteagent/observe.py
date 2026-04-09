"""Observability -- call logging and runtime reporting.

Every LLM call and tool call is logged by default. No external
services required. Export as JSONL for analysis.

The Reporter protocol allows pluggable display (Rich terminal,
JSON stream, silent for tests) without framework coupling.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# -- Call Log --

@dataclass
class LLMCallRecord:
    node: str
    label: str
    messages: list[dict]
    content: str
    thinking: str
    usage: dict
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ToolCallRecord:
    node: str
    tool_name: str
    inputs: dict
    output: str
    label: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PipelineEventRecord:
    """Pipeline-level event (node entry/exit, routing, loop iteration).

    Enables reconstruction of the full pipeline action flow from llm_history.jsonl.
    """
    event_type: str  # "node_enter", "node_exit", "routing", "action"
    node: str
    data: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CallLog:
    """Accumulates LLM and tool call records for a pipeline run.

    Thread-safe for parallel node execution (append is atomic on CPython).
    """

    def __init__(self) -> None:
        self._records: list[LLMCallRecord | ToolCallRecord | PipelineEventRecord] = []

    def log_llm_call(
        self,
        node: str,
        messages: list[dict],
        response: Any,
        *,
        label: str = "",
    ) -> None:
        """Record an LLM call."""
        if isinstance(response, str):
            content, thinking, usage = response, "", {}
        else:
            content = getattr(response, "content", str(response))
            # Check for thinking content from vLLM reasoning parser
            thinking = getattr(response, "thinking", None) or ""
            if not thinking:
                reasoning = getattr(response, "reasoning_content", None) or getattr(response, "reasoning", None)
                if reasoning:
                    thinking = str(reasoning)

            usage_obj = getattr(response, "usage", None)
            if usage_obj and hasattr(usage_obj, "total_tokens"):
                usage = {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
                    "total_tokens": getattr(usage_obj, "total_tokens", 0),
                }
            elif isinstance(usage_obj, dict):
                usage = usage_obj
            else:
                # Fallback: check response_metadata (backward compat)
                meta = getattr(response, "response_metadata", {}) or {}
                usage = meta.get("token_usage", {})

        self._records.append(LLMCallRecord(
            node=node,
            label=label,
            messages=messages,
            content=content,
            thinking=thinking,
            usage=usage,
        ))

    def log_tool_call(
        self,
        node: str,
        tool_name: str,
        inputs: Any,
        output: Any,
        *,
        label: str = "",
    ) -> None:
        """Record a tool call."""
        out_str = str(output)
        if len(out_str) > 5000:
            out_str = out_str[:5000] + "... (truncated)"

        self._records.append(ToolCallRecord(
            node=node,
            tool_name=tool_name,
            inputs=inputs if isinstance(inputs, dict) else {"raw": str(inputs)},
            output=out_str,
            label=label,
        ))

    def log_event(
        self,
        event_type: str,
        node: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record a pipeline event (node entry/exit, routing, action)."""
        self._records.append(PipelineEventRecord(
            event_type=event_type,
            node=node,
            data=data or {},
        ))

    @property
    def records(self) -> list[LLMCallRecord | ToolCallRecord]:
        return list(self._records)

    def save_jsonl(self, path: str | Path) -> None:
        """Save all records as JSONL (one JSON object per line)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for record in self._records:
                f.write(json.dumps(asdict(record), default=str) + "\n")

    def to_dicts(self) -> list[dict]:
        """Export all records as plain dicts (for artifact saving)."""
        return [asdict(r) for r in self._records]

    def total_tokens(self) -> int:
        """Sum total tokens across all LLM calls."""
        return sum(
            r.usage.get("total_tokens", 0)
            for r in self._records
            if isinstance(r, LLMCallRecord)
        )

    def clear(self) -> None:
        self._records.clear()


# -- Reporter Protocol --

@runtime_checkable
class Reporter(Protocol):
    """Protocol for pluggable runtime reporting."""

    def enter_node(self, node_name: str, summary: dict[str, Any] | None = None) -> None: ...
    def log_action(self, action: str, details: dict[str, Any] | None = None) -> None: ...
    def exit_node(self, node_name: str, output: dict[str, Any] | None = None) -> None: ...


class NullReporter:
    """Silent reporter for tests and batch processing."""
    def enter_node(self, node_name: str, summary: dict[str, Any] | None = None) -> None: pass
    def log_action(self, action: str, details: dict[str, Any] | None = None) -> None: pass
    def exit_node(self, node_name: str, output: dict[str, Any] | None = None) -> None: pass
