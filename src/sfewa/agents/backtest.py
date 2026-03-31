"""Backtest Evaluator agent node.

Matches predicted risk factors against ground truth post-cutoff events.
Uses LLM to assess match quality between predictions and actual outcomes.
"""

from __future__ import annotations

import json
import re

from sfewa import reporting
from sfewa.llm import get_llm_for_role
from sfewa.prompts.adversarial import format_risk_factors_for_review
from sfewa.schemas.state import PipelineState

BACKTEST_SYSTEM = """\
You are a Backtest Evaluator. Your job is to objectively assess how well the predicted risk factors match the actual outcomes (ground truth events).

For each ground truth event, determine which predicted risk factors (if any) anticipated it, and rate the match quality:
- strong: The risk factor clearly predicted this specific outcome
- partial: The risk factor captured the general risk area but missed specifics
- weak: Only tangential connection between the prediction and the outcome
- miss: No risk factor predicted this outcome

Be fair and objective. Don't over-credit vague predictions, but also recognize when a risk factor captured the essence of what happened even if the details differ.
"""

BACKTEST_USER = """\
PREDICTED RISK FACTORS:
{risk_factors_text}

GROUND TRUTH EVENTS (what actually happened after cutoff):
{ground_truth_text}

For each ground truth event, return a JSON array of match objects:
- event_id: string (from ground truth)
- event_date: string (from ground truth)
- description: string (brief summary)
- event_type: string (from ground truth)
- matched_factors: list of factor_id strings that predicted this event
- match_quality: string ("strong", "partial", "weak", or "miss")

After the matches, also compute:
- precision_note: how many predicted risk factors actually matched events
- recall_note: how many ground truth events had matching predictions

Return a JSON object with:
- matches: the array of match objects
- backtest_summary: string (2-3 sentence summary of backtest results)

Respond with ONLY the JSON object.
"""


def _format_ground_truth(events: list[dict]) -> str:
    """Format ground truth events for the backtest prompt."""
    parts = []
    for e in events:
        figures = ""
        for fig in e.get("key_figures", []):
            if fig.get("old_value") and fig.get("new_value"):
                figures += f"\n    {fig['metric']}: {fig['old_value']} → {fig['new_value']}"
            elif fig.get("value"):
                figures += f"\n    {fig['metric']}: {fig['value']}"

        parts.append(
            f"[{e.get('event_id', '?')}] {e.get('event_date', '?')} — "
            f"{e.get('event_type', '?')}\n"
            f"  {e.get('description', '?')}"
            f"{figures}"
        )
    return "\n\n".join(parts)


def backtest_node(state: PipelineState) -> dict:
    """Evaluate the analysis by backtesting against ground truth events.

    Uses LLM to:
    1. Match each ground truth event to predicted risk factors
    2. Score match quality (strong/partial/weak/miss)
    3. Generate backtest summary
    """
    risk_factors = state.get("risk_factors", [])
    gt_events = state.get("ground_truth_events", [])

    reporting.enter_node("backtest", {
        "risk_factors": len(risk_factors),
        "ground_truth_events": len(gt_events),
    })

    if not gt_events or not risk_factors:
        reporting.log_action("Missing risk factors or ground truth — skipping backtest")
        reporting.exit_node("backtest")
        return {
            "backtest_events": [],
            "backtest_summary": "Backtest skipped: insufficient data.",
            "current_stage": "backtest",
        }

    # Format prompt
    rf_text = format_risk_factors_for_review(risk_factors)
    gt_text = _format_ground_truth(gt_events)

    # Call LLM
    llm = get_llm_for_role("backtest")
    reporting.log_action("Calling LLM for backtest evaluation")

    backtest_events: list[dict] = []
    backtest_summary = "Backtest failed."

    try:
        response = llm.invoke([
            {"role": "system", "content": BACKTEST_SYSTEM},
            {"role": "user", "content": BACKTEST_USER.format(
                risk_factors_text=rf_text,
                ground_truth_text=gt_text,
            )},
        ])
        raw_text = response.content
        raw_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()

        # Parse JSON
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
        if match:
            raw_text = match.group(1).strip()
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1:
            raw_text = raw_text[start : end + 1]

        parsed = json.loads(raw_text)
        matches = parsed.get("matches", [])
        backtest_summary = parsed.get("backtest_summary", "")

        for m in matches:
            if m.get("event_id") and m.get("match_quality"):
                backtest_events.append(m)
                reporting.log_backtest_match(
                    m["event_id"],
                    m["match_quality"],
                    m.get("matched_factors", []),
                    m.get("description", "")[:80],
                )

    except Exception as e:
        reporting.log_action("LLM call failed", {"error": str(e)[:200]})
        backtest_summary = f"Backtest failed: {str(e)[:100]}"

    reporting.log_action("Backtest summary", {"result": backtest_summary[:150]})
    reporting.exit_node("backtest", {
        "events_matched": len(backtest_events),
    })

    return {
        "backtest_events": backtest_events,
        "backtest_summary": backtest_summary,
        "current_stage": "backtest",
    }
