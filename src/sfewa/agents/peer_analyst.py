"""Peer Benchmark Analyst agent node.

Analyzes competitor positioning and relative strategic gaps.
"""

from __future__ import annotations

from sfewa.agents._analyst_base import run_analyst
from sfewa.prompts.analysis import PEER_DIMENSIONS
from sfewa.schemas.state import PipelineState


def peer_analyst_node(state: PipelineState) -> dict:
    """Analyze peer-relative risk factors.

    Focus: Competitor positioning, cost advantages, time-to-market, software capability.
    Dimensions: competitive_pressure, regional_mismatch, technology_capability
    """
    return run_analyst(
        state,
        node_name="peer_analyst",
        role_name="Peer Benchmark Analyst",
        llm_role="peer_analyst",
        dimensions_description=PEER_DIMENSIONS,
        factor_prefix="PEER",
    )
