"""Adversarial Reviewer agent node.

Three-phase adversarial review with independent verification:
  Phase 1: Chain of Verification (thinking mode) — standard adversarial review
  Phase 2: Independent verification search (ToolLoopAgent) — searches for
           counter-evidence to HIGH/CRITICAL claims with non-STRONG challenges
  Phase 3: Challenge refinement (thinking mode) — upgrades challenge severities
           when verification finds contradicting evidence

Phase 2+3 only run when Phase 1 identifies verifiable claims. If all challenges
are already STRONG, the node behaves exactly as before.
"""

from __future__ import annotations

import json
import re
import time

from liteagent import Tool, ToolLoopAgent, dedup_by_key, extract_json, strip_thinking

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS  # type: ignore[no-redef]

from sfewa import reporting
from sfewa.agents.retrieval import _search_news, _search_web
from sfewa.context import build_pipeline_context
from sfewa.llm import get_llm, get_llm_for_role
from sfewa.prompts.adversarial import (
    ADVERSARIAL_SYSTEM,
    ADVERSARIAL_USER,
    REFINEMENT_SYSTEM,
    REFINEMENT_USER,
    VERIFICATION_SYSTEM,
    VERIFICATION_USER,
    build_evidence_stance_summary,
    format_claims_for_verification,
    format_risk_factors_for_review,
)
from sfewa.prompts.analysis import format_evidence_for_analyst
from sfewa.schemas.state import PipelineState
from sfewa.tools.chat_log import get_call_log, log_llm_call

# ── Constants ──

MAX_VERIFICATION_QUERIES = 8

# Pattern to extract factor IDs (IND001, COM002, PEER003) from LLM output
_FACTOR_ID_RE = re.compile(r"((?:IND|COM|PEER)\d{3})")


def _normalize_factor_id(raw: str) -> str:
    """Extract clean factor ID from LLM output.

    Handles: "[COM001]", "IND001] dimension_name", "PEER002", "COM003".
    """
    m = _FACTOR_ID_RE.search(raw)
    return m.group(1) if m else raw.strip("[]")


# ── Phase 2 helpers ──


def _extract_claims_to_verify(
    challenges: list[dict],
    risk_factors: list[dict],
    max_claims: int = 5,
) -> list[dict]:
    """Extract key claims from HIGH/CRITICAL factors with non-STRONG challenges.

    These are the claims most worth independently verifying — Phase 1 found
    them only moderately or weakly challengeable from available evidence,
    but external search might find stronger counter-evidence.
    """
    factor_severity = {
        rf.get("factor_id", ""): rf.get("severity", "medium").lower()
        for rf in risk_factors
    }

    claims = []
    for c in challenges:
        target_id = c.get("target_factor_id", "")
        factor_sev = factor_severity.get(target_id, "medium")
        challenge_sev = c.get("severity", "weak").lower()
        key_claim = c.get("key_claim_tested", "")

        # Only verify HIGH/CRITICAL factors with non-STRONG challenges
        if factor_sev in ("high", "critical") and challenge_sev != "strong" and key_claim:
            claims.append({
                "challenge_id": c.get("challenge_id", "?"),
                "factor_id": target_id,
                "claim": key_claim,
                "current_severity": challenge_sev,
                "factor_severity": factor_sev,
            })

    # Prioritize: critical before high, weak before moderate
    sev_order = {"critical": 0, "high": 1}
    chal_order = {"weak": 0, "moderate": 1}
    claims.sort(key=lambda x: (
        sev_order.get(x["factor_severity"], 2),
        chal_order.get(x["current_severity"], 2),
    ))

    return claims[:max_claims]


def _make_verification_search_tool() -> Tool:
    """Create a search tool for adversarial verification.

    Simpler than the retrieval search tool — no doc accumulation for
    downstream extraction, just returns snippets for the LLM to interpret.
    """
    ddgs = DDGS()
    call_count = [0]
    seen_links: set[str] = set()

    def search(query: str) -> str:
        """Search the web for counter-evidence to a claim."""
        call_count[0] += 1
        if call_count[0] > MAX_VERIFICATION_QUERIES:
            return (
                f"Search budget exhausted ({MAX_VERIFICATION_QUERIES} queries). "
                f"Summarize your findings now."
            )

        if call_count[0] > 1:
            time.sleep(3)

        results: list[dict] = []
        try:
            web = _search_web(query, max_results=5, ddgs_instance=ddgs)
            results.extend(web)
        except Exception as e:
            reporting.log_action("Verification web search failed", {
                "query": query[:60],
                "error": str(e)[:120],
            })

        time.sleep(2)

        try:
            news = _search_news(query, max_results=3, ddgs_instance=ddgs)
            results.extend(news)
        except Exception as e:
            reporting.log_action("Verification news search failed", {
                "query": query[:60],
                "error": str(e)[:120],
            })

        # Deduplicate by link
        unique: list[dict] = []
        for r in results:
            link = r.get("href") or r.get("url") or r.get("link") or ""
            if link and link not in seen_links:
                seen_links.add(link)
                unique.append(r)

        reporting.log_action(f"Verification [{call_count[0]}]: {query[:60]}", {
            "results": len(unique),
        })

        if not unique:
            return f"No results found for: {query}"

        lines = [f"Found {len(unique)} results:"]
        for r in unique[:6]:
            title = (r.get("title") or "")[:80]
            body = (r.get("body") or "")[:200]
            lines.append(f"- {title}")
            if body:
                lines.append(f"  {body}")

        return "\n".join(lines)

    return Tool(
        name="search",
        description=(
            "Search the web for counter-evidence to a specific claim. "
            "Use targeted queries that seek CONTRADICTING evidence."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query targeting counter-evidence",
                },
            },
            "required": ["query"],
        },
        fn=search,
    )


def _run_verification_search(
    claims: list[dict],
    company: str,
    theme: str,
    cutoff: str,
) -> str:
    """Phase 2: Run independent verification search agent.

    Returns the agent's findings summary (free-form text).
    """
    cutoff_year = int(cutoff[:4])
    prior_year = cutoff_year - 1

    claims_text = format_claims_for_verification(claims)
    system_prompt = VERIFICATION_SYSTEM.format(
        company=company,
        strategy_theme=theme,
        claims_text=claims_text,
        prior_year=prior_year,
        cutoff_year=cutoff_year,
        cutoff_date=cutoff,
        max_queries=MAX_VERIFICATION_QUERIES,
    )

    llm = get_llm(thinking=False)  # non-thinking for tool calling
    search_tool = _make_verification_search_tool()

    agent = ToolLoopAgent(
        llm=llm,
        tools=[search_tool],
        system_prompt=system_prompt,
        max_iterations=MAX_VERIFICATION_QUERIES + 3,
        call_log=get_call_log(),
        node_name="adversarial_verification",
    )

    reporting.log_action("Starting verification search", {
        "claims": len(claims),
        "budget": MAX_VERIFICATION_QUERIES,
    })

    result = agent.run(VERIFICATION_USER)

    # Classify how the verification loop terminated so downstream analysis
    # can distinguish "searched hard, found nothing" from "agent gave up early"
    # from "agent crashed against the iteration cap".
    if result.hit_limit:
        stop_reason = "max_iterations"
    elif result.tool_call_count == 0:
        stop_reason = "no_search_attempted"
    elif result.tool_call_count >= MAX_VERIFICATION_QUERIES:
        stop_reason = "budget_exhausted"
    else:
        stop_reason = "agent_satisfied"

    reporting.log_action("Verification search complete", {
        "queries": result.tool_call_count,
        "iterations": result.iterations,
        "stop_reason": stop_reason,
    })

    return result.content


# ── Phase 3 helper ──


def _refine_challenges(
    challenges: list[dict],
    recommendation: dict,
    findings: str,
    company: str,
    theme: str,
) -> tuple[list[dict], str]:
    """Phase 3: Refine challenges based on verification findings.

    Returns (refined_challenges, refined_recommendation_action).
    """
    system_msg = REFINEMENT_SYSTEM.format(
        company=company,
        strategy_theme=theme,
    )

    original_challenges_json = json.dumps(challenges, indent=2, ensure_ascii=False)
    original_recommendation_json = json.dumps(recommendation, indent=2, ensure_ascii=False)

    user_msg = REFINEMENT_USER.format(
        original_challenges_json=original_challenges_json,
        original_recommendation_json=original_recommendation_json,
        verification_findings=findings,
    )

    llm = get_llm(thinking=True)  # thinking mode for refinement

    try:
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        response = llm.invoke(messages)
        log_llm_call("adversarial_review", messages, response, label="refinement")
        raw_text = strip_thinking(response.content)

        parsed = extract_json(raw_text)

        if isinstance(parsed, dict):
            refined_challenges = parsed.get("challenges")
            if not isinstance(refined_challenges, list):
                reporting.log_action("Refinement: 'challenges' not a list — using Phase 1", {
                    "got_type": type(refined_challenges).__name__,
                })
                refined_challenges = challenges
            rec = parsed.get("recommendation", recommendation)
            if isinstance(rec, dict):
                return refined_challenges, rec.get("action", "proceed")
            return refined_challenges, "proceed"
        elif isinstance(parsed, list):
            return parsed, "proceed"
        else:
            reporting.log_action("Refinement returned unexpected type — using Phase 1", {
                "got_type": type(parsed).__name__,
            })

    except Exception as e:
        reporting.log_action("Refinement parse failed — using Phase 1 results", {
            "error": str(e)[:200],
        })

    # Fallback: return originals
    rec_action = recommendation.get("action", "proceed") if isinstance(recommendation, dict) else "proceed"
    return challenges, rec_action


# ── Main node ──


def adversarial_review_node(state: PipelineState) -> dict:
    """Three-phase adversarial review with independent verification.

    Phase 1: Standard Chain of Verification (thinking mode)
      Produces preliminary challenges + recommendation.
    Phase 2: Independent verification search (non-thinking, ToolLoopAgent)
      Searches for counter-evidence to HIGH/CRITICAL claims.
      Only runs when Phase 1 has verifiable claims.
    Phase 3: Challenge refinement (thinking mode)
      Upgrades challenge severities based on verification findings.
      Only runs when Phase 2 finds relevant evidence.
    """
    raw_risk_factors = state.get("risk_factors", [])
    evidence = state.get("evidence", [])
    company = state["company"]
    theme = state["strategy_theme"]
    cutoff = state["cutoff_date"]
    pass_count = state.get("adversarial_pass_count", 0) + 1

    # Deduplicate: keep latest factor per dimension (handles multi-pass accumulation)
    risk_factors = dedup_by_key(raw_risk_factors, "dimension")

    reporting.enter_node("adversarial_review", {
        "risk_factors": len(risk_factors),
        "evidence_items": len(evidence),
        "pass": f"{pass_count}/2",
    })

    if not risk_factors:
        reporting.log_action("No risk factors to challenge")
        reporting.exit_node("adversarial_review", {"challenges": 0})
        return {
            "adversarial_challenges": [],
            "adversarial_pass_count": pass_count,
            "current_stage": "adversarial_review",
        }

    # Extract dimension_relevance for depth gate check
    dimension_relevance: dict[str, str] = {}
    analysis_dims = state.get("analysis_dimensions", {})
    for group in analysis_dims.values():
        if isinstance(group, dict) and "dimension_relevance" in group:
            dimension_relevance.update(group["dimension_relevance"])

    # ── Phase 1: Standard Chain of Verification (thinking mode) ──
    reporting.log_action("Phase 1: Chain of Verification (thinking mode)")

    rf_text = format_risk_factors_for_review(risk_factors, dimension_relevance, evidence)
    evidence_text = format_evidence_for_analyst(evidence)
    evidence_stance_summary = build_evidence_stance_summary(evidence, risk_factors)
    pipeline_context = build_pipeline_context(state)

    system_msg = ADVERSARIAL_SYSTEM.format(
        company=company,
        strategy_theme=theme,
    )
    if pipeline_context:
        system_msg += f"\n\n{pipeline_context}"
    user_msg = ADVERSARIAL_USER.format(
        risk_factors_text=rf_text,
        evidence_text=evidence_text,
        evidence_stance_summary=evidence_stance_summary,
    )

    llm = get_llm_for_role("adversarial")

    challenges: list[dict] = []
    adversarial_recommendation = "proceed"
    recommendation_obj: dict = {"action": "proceed", "reasoning": ""}

    try:
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        response = llm.invoke(messages)
        log_llm_call("adversarial_review", messages, response, label="phase1")
        raw_text = strip_thinking(response.content)

        try:
            parsed = extract_json(raw_text)
        except json.JSONDecodeError:
            parsed = {}

        if isinstance(parsed, dict):
            if isinstance(parsed.get("challenges"), list):
                challenges = parsed["challenges"]
            rec = parsed.get("recommendation", {})
            if isinstance(rec, dict):
                recommendation_obj = rec
                adversarial_recommendation = rec.get("action", "proceed")
                reporting.log_action("Phase 1 recommendation", {
                    "action": adversarial_recommendation.upper(),
                    "reasoning": rec.get("reasoning", "")[:120],
                })
        elif isinstance(parsed, list):
            challenges = parsed

    except Exception as e:
        reporting.log_action("Phase 1 LLM call failed", {"error": str(e)[:200]})
        return {
            "adversarial_challenges": [],
            "adversarial_pass_count": pass_count,
            "adversarial_recommendation": "proceed",
            "current_stage": "adversarial_review",
        }

    # Validate Phase 1 challenges
    valid_challenges: list[dict] = []
    for c in challenges:
        required = ["challenge_id", "target_factor_id", "challenge_text", "severity"]
        if all(c.get(f) for f in required):
            # Normalize target_factor_id: LLM outputs varied formats like
            # "[COM001]", "IND001] dimension_name", "PEER002". Extract the
            # factor ID prefix (IND/COM/PEER + digits) for consistent matching.
            raw_tid = c["target_factor_id"]
            c["target_factor_id"] = _normalize_factor_id(raw_tid)
            if not isinstance(c.get("counter_evidence"), list):
                c["counter_evidence"] = []
            if "resolution" not in c:
                c["resolution"] = None
            valid_challenges.append(c)

    phase1_severity = {"strong": 0, "moderate": 0, "weak": 0}
    for c in valid_challenges:
        sev = c.get("severity", "weak")
        if sev in phase1_severity:
            phase1_severity[sev] += 1

    reporting.log_action("Phase 1 challenges", phase1_severity)

    # ── Phase 2: Independent verification search ──
    claims = _extract_claims_to_verify(valid_challenges, risk_factors)
    phases_run = "1"

    if claims:
        reporting.log_action("Phase 2: Independent verification search", {
            "claims_to_verify": len(claims),
            "factors": [c["factor_id"] for c in claims],
        })
        findings = _run_verification_search(claims, company, theme, cutoff)
        phases_run = "1+2"

        # ── Phase 3: Challenge refinement ──
        if findings and findings.strip():
            reporting.log_action("Phase 3: Challenge refinement (thinking mode)")
            refined_challenges, refined_rec = _refine_challenges(
                valid_challenges, recommendation_obj, findings, company, theme,
            )
            phases_run = "1+2+3"

            # Validate refined challenges
            final_challenges: list[dict] = []
            for c in refined_challenges:
                required = ["challenge_id", "target_factor_id", "challenge_text", "severity"]
                if all(c.get(f) for f in required):
                    raw_tid = c["target_factor_id"]
                    c["target_factor_id"] = _normalize_factor_id(raw_tid)
                    if not isinstance(c.get("counter_evidence"), list):
                        c["counter_evidence"] = []
                    if "resolution" not in c:
                        c["resolution"] = None
                    final_challenges.append(c)

            if final_challenges:
                valid_challenges = final_challenges
                adversarial_recommendation = refined_rec
            else:
                reporting.log_action("Refinement produced invalid output — using Phase 1")
        else:
            reporting.log_action("Phase 2 found nothing — skipping refinement")
    else:
        reporting.log_action("No claims to verify — skipping Phase 2+3")

    # ── Dedup challenges by target_factor_id ──
    # Phase 3 refinement can sometimes return duplicates (both original + refined).
    # Keep the LAST challenge per target factor (the refined version).
    valid_challenges = dedup_by_key(valid_challenges, "target_factor_id")

    # ── Final severity counts ──
    severity_counts = {"strong": 0, "moderate": 0, "weak": 0}
    for c in valid_challenges:
        sev = c.get("severity", "weak")
        if sev in severity_counts:
            severity_counts[sev] += 1

    # Log severity changes from verification
    if phases_run == "1+2+3" and phase1_severity != severity_counts:
        reporting.log_action("Verification changed severities", {
            "phase1": phase1_severity,
            "final": severity_counts,
        })

    reporting.log_action("Final challenges", severity_counts)
    for c in valid_challenges:
        reporting.log_challenge(
            c["challenge_id"],
            c["target_factor_id"],
            c["severity"],
            c["challenge_text"][:80],
        )

    # Validate recommendation: override to "proceed" if max passes reached
    if pass_count >= 2 and adversarial_recommendation == "reanalyze":
        adversarial_recommendation = "proceed"
        reporting.log_action("Max adversarial passes — overriding to proceed")

    next_node = (
        "risk_synthesis"
        if adversarial_recommendation == "proceed"
        else "evidence_extraction (reanalyze)"
    )

    reporting.exit_node("adversarial_review", {
        "challenges": len(valid_challenges),
        "strong": severity_counts["strong"],
        "moderate": severity_counts["moderate"],
        "weak": severity_counts["weak"],
        "phases": phases_run,
        "llm_recommendation": adversarial_recommendation,
    }, next_node=next_node)

    return {
        "adversarial_challenges": valid_challenges,
        "adversarial_pass_count": pass_count,
        "adversarial_recommendation": adversarial_recommendation,
        "current_stage": "adversarial_review",
    }
