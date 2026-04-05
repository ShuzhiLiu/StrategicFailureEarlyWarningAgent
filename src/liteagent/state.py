"""State management helpers for pipeline agents.

State is a plain dict. These helpers add safety without adding abstraction.
"""

from __future__ import annotations

from typing import Any


def dedup_by_key(
    items: list[dict],
    key: str,
    *,
    keep: str = "last",
) -> list[dict]:
    """Deduplicate a list of dicts by a key field.

    When pipeline loops cause duplicate entries (e.g., risk factors from
    re-analysis), keep only one per key value.

    Args:
        items: List of dicts to deduplicate.
        key: Field name to deduplicate by (e.g., "dimension").
        keep: "last" (default) keeps the latest entry; "first" keeps the earliest.
    """
    seen: dict[str, dict] = {}
    for item in items:
        k = item.get(key, "")
        if keep == "last" or k not in seen:
            seen[k] = item
    return list(seen.values())


def ensure_field(state: dict, field: str, default: Any) -> Any:
    """Get a field from state, setting default if missing."""
    if field not in state:
        state[field] = default
    return state[field]


def snapshot(state: dict, exclude: set[str] | None = None) -> dict:
    """Create a shallow snapshot of state for debugging/logging.

    Optionally exclude large fields (e.g., retrieved_docs) from the snapshot.
    """
    exc = exclude or set()
    return {k: v for k, v in state.items() if k not in exc}


def count_by(items: list[dict], field: str) -> dict[str, int]:
    """Count items grouped by a field value.

    Useful for computing distributions:
        count_by(evidence, "stance")  -> {"supports_risk": 10, "neutral": 5, ...}
        count_by(factors, "severity") -> {"high": 3, "medium": 4, ...}
    """
    counts: dict[str, int] = {}
    for item in items:
        val = str(item.get(field, "unknown"))
        counts[val] = counts.get(val, 0) + 1
    return counts
