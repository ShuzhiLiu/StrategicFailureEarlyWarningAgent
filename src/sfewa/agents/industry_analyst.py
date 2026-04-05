"""Industry/External Environment Analyst agent node.

Analyzes market dynamics, policy environment, and external forces.
Dimensions are generated dynamically by init_case based on the strategy theme.
Falls back to hardcoded EV dimensions if not provided.
"""

from __future__ import annotations

from sfewa.agents._analyst_base import run_analyst
from sfewa.prompts.analysis import INDUSTRY_DIMENSIONS, INDUSTRY_SCOPE
from sfewa.schemas.state import PipelineState


def industry_analyst_node(state: PipelineState) -> dict:
    """Analyze external environment risk factors."""
    # Use dynamic dimensions if available, else fall back to hardcoded
    dims = state.get("analysis_dimensions", {}).get("external", {})
    dimensions_desc = dims.get("dimensions_description", INDUSTRY_DIMENSIONS)
    scope = dims.get("scope_boundary", INDUSTRY_SCOPE)
    role = dims.get("role_name", "Industry & Market Analyst")

    return run_analyst(
        state,
        node_name="industry_analyst",
        role_name=role,
        llm_role="industry_analyst",
        dimensions_description=dimensions_desc,
        scope_boundary=scope,
        factor_prefix="IND",
    )
