"""Context window management.

Two concerns:
1. Prevent context overflow (truncation, budget tracking)
2. Inject upstream context into downstream prompts (pipeline context pattern)
"""

from __future__ import annotations

from typing import Any


def truncate(
    text: str,
    max_chars: int = 50_000,
    *,
    keep_ends: bool = True,
) -> str:
    """Truncate text to max_chars, preserving both start and end.

    Claude Code pattern: important information lives at both ends
    of tool output. Truncate from the middle.
    """
    if len(text) <= max_chars:
        return text

    if keep_ends:
        half = max_chars // 2
        return text[:half] + f"\n\n... ({len(text) - max_chars} chars truncated) ...\n\n" + text[-half:]
    else:
        return text[:max_chars] + f"\n... ({len(text) - max_chars} chars truncated)"


class TokenBudget:
    """Track token usage against a budget."""

    def __init__(self, max_tokens: int = 128_000, warn_at: float = 0.85) -> None:
        self.max_tokens = max_tokens
        self.warn_at = warn_at
        self.used = 0

    def add(self, tokens: int) -> None:
        self.used += tokens

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)

    @property
    def utilization(self) -> float:
        return self.used / self.max_tokens if self.max_tokens else 0.0

    @property
    def should_compress(self) -> bool:
        return self.utilization >= self.warn_at


class ContextBuilder:
    """Build pipeline context summaries for injection into prompts.

    Generic version of SFEWA's build_pipeline_context(). You register
    section builders, and it composes them into a summary string.

    Usage:
        ctx = ContextBuilder("PIPELINE CONTEXT (what has happened so far):")
        ctx.add_section("retrieval", lambda s: f"Retrieved {len(s['docs'])} documents")
        ctx.add_section("evidence", lambda s: f"Extracted {len(s['evidence'])} items")

        summary = ctx.build(state)
    """

    def __init__(self, header: str = "CONTEXT:") -> None:
        self._header = header
        self._sections: list[tuple[str, Any]] = []

    def add_section(self, name: str, builder: Any) -> "ContextBuilder":
        """Add a section builder.

        builder(state) should return a string (or None/empty to skip).
        """
        self._sections.append((name, builder))
        return self

    def build(self, state: dict) -> str:
        """Build the context string from current state."""
        parts: list[str] = []
        for name, builder in self._sections:
            try:
                result = builder(state)
                if result:
                    parts.append(str(result))
            except Exception:
                pass  # skip sections that fail -- context is advisory, not critical
        if not parts:
            return ""
        return self._header + "\n" + "\n".join(f"- {p}" for p in parts)
