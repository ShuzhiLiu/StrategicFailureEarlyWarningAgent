"""Company Strategy Analyst agent node.

Analyzes Honda's EV strategy, targets, investments, and narrative shifts.
"""

from __future__ import annotations

from sfewa.agents._analyst_base import run_analyst
from sfewa.prompts.analysis import COMPANY_DIMENSIONS
from sfewa.schemas.state import PipelineState


def company_analyst_node(state: PipelineState) -> dict:
    """Analyze company-specific strategic risk factors.

    Focus: EV targets, investment plans, product roadmap, narrative consistency.
    Dimensions: capital_allocation, narrative_consistency, execution, product_portfolio
    """
    return run_analyst(
        state,
        node_name="company_analyst",
        role_name="Company Strategy Analyst",
        llm_role="company_analyst",
        dimensions_description=COMPANY_DIMENSIONS,
        factor_prefix="COM",
    )
