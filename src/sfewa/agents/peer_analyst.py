"""Peer/Comparative Analyst agent node.

Analyzes competitive positioning, technology gaps, and market coverage.
Dimensions are generated dynamically by init_case based on the strategy theme.
Falls back to hardcoded EV dimensions if not provided.
"""

from __future__ import annotations

from sfewa.agents._analyst_base import run_analyst
from sfewa.prompts.analysis import PEER_DIMENSIONS, PEER_SCOPE
from sfewa.schemas.state import PipelineState


def peer_analyst_node(state: PipelineState) -> dict:
    """Analyze comparative/competitive risk factors."""
    # Use dynamic dimensions if available, else fall back to hardcoded
    dims = state.get("analysis_dimensions", {}).get("comparative", {})
    dimensions_desc = dims.get("dimensions_description", PEER_DIMENSIONS)
    scope = dims.get("scope_boundary", PEER_SCOPE)
    role = dims.get("role_name", "Peer Benchmark Analyst")

    return run_analyst(
        state,
        node_name="peer_analyst",
        role_name=role,
        llm_role="peer_analyst",
        dimensions_description=dimensions_desc,
        scope_boundary=scope,
        factor_prefix="PEER",
    )
