"""Company/Internal Strategy Analyst agent node.

Analyzes the company's internal strategy, execution, and financial positioning.
Dimensions are generated dynamically by init_case based on the strategy theme.
Falls back to hardcoded EV dimensions if not provided.
"""

from __future__ import annotations

from sfewa.agents._analyst_base import run_analyst
from sfewa.prompts.analysis import COMPANY_DIMENSIONS, COMPANY_SCOPE
from sfewa.schemas.state import PipelineState


def company_analyst_node(state: PipelineState) -> dict:
    """Analyze company-specific strategic risk factors."""
    # Use dynamic dimensions if available, else fall back to hardcoded
    dims = state.get("analysis_dimensions", {}).get("internal", {})
    dimensions_desc = dims.get("dimensions_description", COMPANY_DIMENSIONS)
    scope = dims.get("scope_boundary", COMPANY_SCOPE)
    role = dims.get("role_name", "Company Strategy Analyst")

    return run_analyst(
        state,
        node_name="company_analyst",
        role_name=role,
        llm_role="company_analyst",
        dimensions_description=dimensions_desc,
        scope_boundary=scope,
        factor_prefix="COM",
    )
