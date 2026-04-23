# Strategic Failure Early Warning Agent

## Project Overview

**An agent-harness engineering study.** The project frame: *Agent = Model + Harness*. Models commoditize; harnesses don't. This repo is a hands-on reference implementation of an agent harness (`liteagent`, ~1,000 LOC, 1 external dep) plus a domain application (`sfewa`) that pressure-tests the harness on a real prediction task — flagging a public company's strategic failure from timestamped pre-cutoff evidence.

The architectural pattern is Planner-Generator-Evaluator. The domain task uses Qwen3.5-27B on local vLLM for reasoning, with strict evidence-driven analysis and three-layer temporal-integrity enforcement. See `docs/harness_engineering.md` for the thesis document; `docs/architecture.md` for the pipeline design; `docs/iteration_log.md` for the 40-iteration audit trail.

**Case studies** (all cutoff 2025-05-19):
- **Honda** → HIGH-CRITICAL risk, mean 76.7 (ground truth: May 2025 target revision + March 2026 writedown)
- **Toyota** → MEDIUM-HIGH risk, mean 56.0 (control: weak BEV execution but strong hybrid position)
- **BYD** → MEDIUM risk, mean 44.7 (control: world's largest NEV maker, strategy succeeding)

**Demos**: pre-cached runs for Honda, Toyota, BYD available in `demo/` (self-contained HTML reports, no setup required).

**Status**: 40 iterations complete. Pipeline v2 (agentic retrieval + 3-phase adversarial) is the primary path (`--agentic` flag). Iter 39 added self-consistency sampling (N=3), Toulmin-structured output, programmatic depth-severity + citation flags, analyst agreement confidence, and evidence-gated downgrades. Iter 40 was an open-source readiness pass with a fresh stability re-run — see `docs/iteration_log.md` for the full audit trail.

## Tech Stack
- **Agent framework**: `liteagent` (in-house, ~800 lines, plain Python + OpenAI SDK)
- **LLM**: Qwen3.5-27B-GPTQ-Int4 on local vLLM (OpenAI-compatible API, no cloud dependency)
- **Modes**: Thinking mode for adversarial + synthesis; non-thinking mode for extraction + analysis
- **Package manager**: uv
- **Testing**: pytest (51 tests)
- **Linting**: ruff
- **Type checking**: pyright

## Code Style
- Use Python type hints everywhere (TypedDict for state, Pydantic for data models)
- Use `from __future__ import annotations` in all files
- Imports: stdlib > third-party > local, separated by blank lines
- Naming: snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants
- One agent per file in `src/sfewa/agents/`
- Prompts live in `src/sfewa/prompts/` as separate .py files, not inline strings
- Config files in YAML under `configs/`

## Architecture Rules

### Pipeline v2 (8 nodes, 1 LLM-driven routing decision) — activated via `--agentic`
```
init_case → agentic_retrieval (ToolLoopAgent) → evidence_extraction
  → [industry|company|peer]_analyst (parallel fan-out, N=3 self-consistency, Toulmin output)
  → analyst_agreement computation → programmatic depth-severity + citation flags
  → adversarial_review (3-phase: CoVe + verification search + refinement)
    ──(LLM: proceed)──→ risk_synthesis → backtest → END
    ──(LLM: reanalyze)──→ evidence_extraction (rare)
```

### Pipeline v1 (10 nodes, 2 LLM-driven routing decisions) — without `--agentic`
```
init_case → retrieval (3-pass) → evidence_extraction → quality_gate
  ──(LLM: sufficient)──→ [industry|company|peer]_analyst (parallel fan-out)
  ──(LLM: insufficient)──→ retrieval (follow-up loop)
→ adversarial_review
  ──(LLM: proceed)──→ risk_synthesis → backtest → END
  ──(LLM: reanalyze)──→ evidence_extraction (rare)
```

### Core invariants
- Every evidence object must have a `published_at` timestamp and pass cutoff validation
- Never use data published after the case's `cutoff_date`
- Agent outputs must be structured (TypedDict/Pydantic), not free-form prose
- All high-level conclusions must reference `evidence_id` list
- State flows as a plain dict through `run_pipeline()`; no global mutable state
- Use `merge_state(accumulate={"evidence", "risk_factors", ...})` for accumulating state fields
- Use `dedup_by_key()` from liteagent when loop-back creates duplicates

### Temporal integrity (enforced at 3 levels)
1. **Retrieval**: `published_at > cutoff_date` → hard reject
2. **Extraction**: temporal filter on evidence items
3. **Prompts**: "Do NOT use knowledge about events after {cutoff_date}" in all retrieval prompt templates

### LLM-driven routing (not hardcoded thresholds)
- **Quality gate**: LLM evaluates evidence sufficiency (count, stance balance, source diversity, dimension coverage). Routes to retrieval or fan-out.
- **Adversarial review**: LLM recommends "proceed" or "reanalyze". Dead-loop counters (`MAX_ITERATIONS=3`, `MAX_ADVERSARIAL_PASSES=2`) are safety bounds only.

### Independent evaluator (Anthropic's key insight)
- Adversarial reviewer is structurally separated from analysts
- Uses thinking mode for deep reasoning (analysts use non-thinking mode)
- Sees ALL evidence, not just what analysts cited
- Only STRONG challenges trigger severity downgrades in synthesis, gated by evidence quality (≥3 valid supporting citations resist)
- **Three-phase architecture** (v2): Phase 1 Chain of Verification (thinking) → Phase 2 independent web verification search (ToolLoopAgent, conditional) → Phase 3 challenge refinement (thinking, conditional)
- Phase 2+3 only trigger when Phase 1 identifies HIGH/CRITICAL factors with non-STRONG challenges
- **Programmatic flags** (iter 39): 7 flag types ([DEPTH_SEVERITY_MISMATCH], [MISSING_FORCES], [MISSING_ASSUMPTION], [PHANTOM_CITATION], [STANCE_MISMATCH], [THIN_EVIDENCE], [EVIDENCE IMBALANCE]) injected into adversarial prompt as STRONG challenge triggers
- **Toulmin-structured input**: Analysts provide `claim`, `warrant`, `strongest_counter` per factor — adversarial uses claim field directly instead of extracting from description

### Self-consistency sampling + analyst agreement
- Analysts run N=3 independent LLM calls per node, consensus via modal severity + median depth
- Dynamic early-stop when first 2 samples agree on all dimensions (saves ~33% calls)
- `_compute_analyst_agreement()` after fan-out: HHI concentration, ordinal range, summary text
- Agreement signal injected into synthesis prompt to calibrate confidence empirically

### Filing discovery
- `discover_and_load_filings()` identifies jurisdiction from company name, discovers company ID via filing system API, downloads and caches PDFs
- Japan → EDINET (Honda, Toyota); China → CNINFO (BYD)
- Cached in `data/corpus/{company}/{system}/` — download once, reuse across runs
- Tier 1 primary source filings dramatically reduce score variability

### Pipeline context injection
- Downstream nodes receive a summary of upstream pipeline history via `build_pipeline_context()`
- Enables synthesis to adjust confidence based on evidence quality, adversarial to factor in retrieval coverage

### Risk factor deduplication
- `risk_factors` accumulates across passes via `merge_state(accumulate=...)`
- On adversarial loop-back, analysts produce duplicates
- Adversarial, synthesis, backtest, and artifacts all call `dedup_by_key(factors, "dimension")` (latest per dimension wins)

## Development Rules

### Principle: Improve through design, not through rules
When the system produces wrong results, fix the **architecture and agent design** — not the prompt wording. The hierarchy of interventions:

1. **Structural fix** (best) — Add a new node, change routing logic, restructure information flow. Example: adding the quality gate node fixed evidence insufficiency across all companies at once.
2. **Reasoning framework** — Give agents better decision frameworks that generalize. Example: the impact assessment framework (existing business threat vs expansion barrier) helps analysts reason about ANY company, not just Honda.
3. **Prompt tuning** (last resort) — Adjust specific prompt language. Only when the structural design is correct but the LLM needs clearer instructions to follow it.

Never add company-specific rules, hardcoded thresholds, or conditional logic targeting specific outcomes. Same pipeline, same prompts, same model must produce different results for different companies through evidence-driven reasoning.

### Dynamic routing over static pipelines
Every control flow decision should be LLM-driven, not hardcoded:
- **Wrong**: `if len(evidence) < 10: loop_back()`
- **Right**: LLM evaluates evidence sufficiency considering count, stance balance, source diversity, and dimension coverage — then decides

When routing produces wrong behavior, improve what information the routing LLM receives (pipeline context injection), not the routing threshold. Iteration counters are safety bounds only.

### Separated evaluation over self-assessment
When agent output quality is poor, add or strengthen an independent evaluator — don't ask the same agent to "try harder":
- Analysts assess risk → adversarial reviewer challenges independently
- Quality gate evaluates evidence → separate from the extraction agent that produced it
- If a new quality problem emerges, consider whether a new evaluation node is the right fix

### Evidence-driven, not knowledge-driven
The system's conclusions must emerge from retrieved evidence, not LLM world knowledge:
- Retrieval generates its own search queries from case context (no hand-tuned topics)
- Quality gate decides when evidence is sufficient (no fixed count thresholds)
- Analysts weigh supporting vs contradicting evidence (not prior beliefs)
- Adversarial reviewer checks for evidence imbalance (not outcome expectations)

When results seem "too correct," suspect temporal leakage — the LLM may be using post-cutoff knowledge rather than reasoning from evidence.

### LLM structured output strategy
Qwen3.5 may break Pydantic schemas. Each LLM-calling node should:
1. Request structured output via explicit JSON schema in prompt
2. On parse failure, retry once with the validation error appended
3. On second failure, log the error, set `state["error"]`, and return partial results rather than crashing

## Stability Testing Protocol

After any significant change, run the **full cross-company stability test**: 3 rounds × 3 companies (9 runs total). This is the primary validation method — not unit tests, not single runs.

### How to run

Run companies **sequentially** (DuckDuckGo rate limits cause evidence loss when companies run concurrently):
```bash
# Round 1
python -m sfewa.main --case configs/cases/honda_ev_pre_reset.yaml --agentic
python -m sfewa.main --case configs/cases/toyota_ev_strategy.yaml --agentic
python -m sfewa.main --case configs/cases/byd_ev_strategy.yaml --agentic
# Repeat for rounds 2 and 3
```

### Expected baselines (post iteration 39)

| Metric | Honda | Toyota | BYD |
|--------|-------|--------|-----|
| **Mean** | ~77 | ~56 | ~45 |
| **Level** | HIGH-CRITICAL | MEDIUM-HIGH | MEDIUM |
| **Range** | 64-88 | 50-68 | 43-46 |
| **STRONGs/run** | 4-6 | 1-4 | 4-7 |
| **Resisted/run** | 4-6 | 0-3 | 0-2 |
| **Adv. phases** | P1+2+3 | P1+2+3 | P1+2+3 |

**Pass criteria**: H>T>B ordering in ALL 3 rounds. A single inversion means the change introduced a regression.

### What to check in raw outputs

After each run completes, **always inspect raw output files** — don't just look at the final score. Each run saves artifacts to `outputs/{case_id}_{timestamp}/`:

**1. `run_summary.json`** — Score, level, confidence, evidence count, adversarial pass count
```bash
# Quick cross-run comparison
for dir in outputs/*/; do python3 -c "
import json; s=json.load(open('${dir}run_summary.json'))
print(f\"{s['company']:30s} score={s['risk_score']:3d} {s['overall_risk_level']:8s} ev={s['evidence_count']} passes={s['adversarial_pass_count']}\")
"; done
```

**2. `challenges.json`** — Check STRONG count, target_factor_id format, severity distribution
```bash
python3 -c "
import json; c=json.load(open('outputs/DIRNAME/challenges.json'))
for x in c: print(f\"{x.get('challenge_id','')} -> {x.get('target_factor_id','')} severity={x.get('severity','?')}\")
"
```
- **Look for**: Malformed `target_factor_id` (brackets, trailing text) — these prevent STRONG downgrades from firing
- **Look for**: Duplicate challenges (same target_factor_id appearing twice) — dedup may have failed
- **Look for**: STRONG count vs score — if STRONGs are high but score is also high, downgrades may not be matching

**3. `risk_factors.json`** — Check factor count (should be 10), severity distribution, depth_of_analysis
```bash
python3 -c "
import json; f=json.load(open('outputs/DIRNAME/risk_factors.json'))
print(f'Factors: {len(f)}')
for x in f: print(f\"{x.get('factor_id','')} {x.get('dimension',''):40s} {x.get('severity',''):8s} depth={x.get('depth_of_analysis','?')}\")
"
```
- **Look for**: Factor count != 10 — init_case dimension generation intermittent issue
- **Look for**: Depth distribution — Honda should have more depth-4, BYD more depth-2

**4. `llm_history.jsonl`** — Pipeline events, LLM calls, tool calls (interleaved timeline)
```bash
# Count pipeline events
python3 -c "
import json
log = [json.loads(l) for l in open('outputs/DIRNAME/llm_history.jsonl')]
events = [r for r in log if r.get('event_type')]
print(f'Events: {len(events)}')
for e in events:
    if e['event_type'] in ('routing','parallel_start','parallel_end'):
        print(f\"  {e['event_type']:16s} {e['node']:20s} {e.get('data',{})}\")
"
```
- **Look for**: Routing decisions (proceed vs reanalyze)
- **Look for**: Adversarial phase actions (Phase 1/2/3 triggers, "No claims to verify — skipping P2+3")

### Diagnosing common failures

**Ordering inversion (e.g., Toyota < BYD)**:
1. Check base_score in terminal output — if base scores are correct but final scores inverted, the problem is LLM synthesis adjustment
2. Check challenge counts — inflated challenge counts (>10) from dedup failure distort the synthesis LLM
3. Check `target_factor_id` format in challenges.json — malformed IDs prevent STRONG downgrades

**Score too high for BYD (>40)**:
1. Check STRONG count — should be 1-3. If 0, check if Phase 2+3 triggered or if factor IDs are malformed
2. Check evidence stance distribution — BYD should have high contradicts_risk ratio
3. Check if `technology_capability` claims are present — if 0, retrieval missed tech evidence

**Score too low for Honda (<75)**:
1. Check STRONG count — should be 0-1. If >2, adversarial is being too aggressive
2. Check if EDINET filings were loaded — Honda's own disclosures drive the CRITICAL signal
3. Check factor severity distribution — Honda should have 5+ HIGH/CRITICAL factors

**All companies clustering at same level**:
- All HIGH → evaluator too weak (not generating STRONG challenges for weak factors)
- All MEDIUM → analysts lack reasoning framework to distinguish severity (check Iceberg Model depth)
- All LOW → evidence gathering insufficient (check evidence counts and stance balance)

The fix is always a **design improvement that generalizes** (structural fix > reasoning framework > prompt tuning), never a rule that targets one company.

### Recording iterations

After confirming stability, update `docs/iteration_log.md`:
1. Add a row to the summary table (iter number, title, key change, result)
2. Add the full iteration entry at the bottom (goal, what changed, pre/post stability tables, key insights, file summary)
3. Update the "Stability state entering Iteration N" table with new baselines
4. Commit with a descriptive message summarizing the change

## Git Workflow
- Branch naming: `feature/*`, `fix/*`, `docs/*`
- Commit messages: imperative mood, concise
- Keep PRs focused on one concern

@docs/architecture.md
@docs/liteagent_architecture.md
@docs/cross_company_results.md
@docs/iteration_log.md
@.env
