# Changelog

Summarized from `docs/iteration_log.md`. Versions are assigned retroactively.

## [0.2.0] — 2026-04 — Agentic adversarial + evidence-gated scoring

Iterations 33–39. Major qualitative upgrade to the reasoning pipeline.

- **v2 pipeline (`--agentic`)**: replaces v1's 4-node evidence loop with a single `ToolLoopAgent` in `agentic_retrieval`. Agent derives queries from dimensions and stops when coverage criteria are met. 8 nodes total, 1 LLM-driven routing decision.
- **3-phase adversarial review**: Phase 1 Chain of Verification → Phase 2 independent web search via ToolLoopAgent → Phase 3 challenge refinement. Phase 2+3 only trigger when Phase 1 has verifiable HIGH/CRITICAL claims.
- **Filing discovery**: jurisdiction-agnostic `discover_and_load_filings()` with EDINET (Japan) and CNINFO (China) clients. No company codes hardcoded.
- **Technology-aware retrieval**: coverage target #7 (proprietary tech, vertical integration, tech supply relationships) and `technology_capability` claim type added.
- **Self-consistency sampling (N=3)**: modal severity + median depth consensus per dimension, with dynamic early-stop.
- **Toulmin-structured analyst output**: `claim`, `warrant`, `strongest_counter` fields; adversarial reviewer uses `claim` directly.
- **Programmatic consistency flags**: 7 flag types (depth-severity, missing forces, missing assumption, phantom citation, stance mismatch, thin evidence, evidence imbalance) act as STRONG challenge triggers.
- **Evidence-gated downgrades**: STRONG challenges only downgrade factors with `valid_sup < 3` (excludes phantom + stance-mismatched citations).
- **Analyst agreement as empirical confidence**: HHI severity concentration + ordinal range injected into synthesis prompt. Replaces LLM-verbalized confidence.
- **Factor ID normalization**: regex-based extraction (`(?:IND|COM|PEER)\d{3}`) handles all observed LLM output formats. Prior `strip("[]")` silently broke STRONG downgrades on malformed IDs.
- **Pipeline event logging**: `PipelineEventRecord` in liteagent interleaves node enter/exit, routing, and parallel fan-out events with LLM/tool calls in `llm_history.jsonl`. Enables flow-graph reconstruction.

**Stability state (3 rounds × 3 companies post iter 39):** Honda 76.7 (64–88) HIGH–CRITICAL · Toyota 56.0 (50–68) MEDIUM–HIGH · BYD 44.7 (43–46) MEDIUM · H>T>B ordering 9/9.

## [0.1.0] — 2026-03 — Framework separation and continuous scoring

Iterations 1–32. Established the pipeline architecture and design principles.

- Planner–Generator–Evaluator structure with 10-node v1 pipeline.
- EDINET Tier 1 primary source integration (Honda).
- LLM-driven quality gate replacing hardcoded evidence thresholds.
- 3-pass retrieval (seed + gap + counternarrative) with LLM-generated search queries.
- Continuous 0–100 risk score: programmatic base + LLM qualitative adjustment.
- LangChain/LangGraph removal — `~/src/liteagent` (~1,000 LOC) as replacement utility layer with 1 external dependency (openai).
- Iceberg Model 4-layer progressive deepening with agentic depth routing and strategy-relative depth gate.
- Score stability improvements: factor count fixed at 10, scope boundaries per-analyst, cross-pass challenge dedup.

See `docs/iteration_log.md` for the full per-iteration record with stability tables and design rationale.
