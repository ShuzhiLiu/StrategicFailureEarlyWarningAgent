"""Industry Analyst agent node.

Analyzes EV market adoption, policy environment, and macro trends.
"""

from __future__ import annotations

from sfewa.agents._analyst_base import run_analyst
from sfewa.prompts.analysis import INDUSTRY_DIMENSIONS
from sfewa.schemas.state import PipelineState


def industry_analyst_node(state: PipelineState) -> dict:
    """Analyze industry-level risk factors.

    Focus: EV adoption rates, charging infra, battery costs, policy changes.
    Dimensions: market_timing, policy_dependency
    """
    return run_analyst(
        state,
        node_name="industry_analyst",
        role_name="Industry & Market Analyst",
        llm_role="industry_analyst",
        dimensions_description=INDUSTRY_DIMENSIONS,
        factor_prefix="IND",
    )
