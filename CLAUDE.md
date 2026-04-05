# Strategic Failure Early Warning Agent

## Project Overview
A time-bounded multi-agent system (Planner-Generator-Evaluator) for strategic failure early warning on public companies. Built on `liteagent` (a minimal agent framework -- utilities, not a runtime) with Qwen3.5-27B on local vLLM for reasoning, and evidence-driven analysis with temporal integrity.

**Case studies** (all cutoff 2025-05-19):
- **Honda** → HIGH risk (ground truth: May 2025 target revision + March 2026 writedown)
- **Toyota** → MEDIUM risk (control: weak BEV execution but strong hybrid position)
- **BYD** → LOW risk (control: world's largest NEV maker, strategy succeeding)

**Demo**: AI Tinkerers HK at AWS, April 29, 2026. Pre-cached runs in `demo/`.

**Status**: Phase A (pipeline flow) and Phase B (prompt quality) complete. All 10 nodes produce valid structured output. Cross-company discrimination achieved through evidence-driven reasoning, not config tuning.

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

### Pipeline (10 nodes, 2 LLM-driven routing decisions)
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
- Only STRONG challenges trigger severity downgrades in synthesis

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

### Cross-company discrimination as design validation
Run all three cases after significant changes. Expected: Honda → HIGH, Toyota → MEDIUM, BYD → LOW.

If companies cluster at the same risk level, the problem is **architectural**, not prompt-level:
- All HIGH → evaluator too weak (not generating strong challenges for weak factors)
- All MEDIUM → analysts lack a reasoning framework to distinguish severity levels
- All LOW → evidence gathering insufficient (quality gate not looping enough)

The fix is always a design improvement that generalizes, never a rule that targets one company.

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

### Debugging
- `docs/cross_company_results.md` is a **reference**, not a spec — actual output will differ
- **Structural checks**: Did quality gate route correctly? Did analysts cover expected dimensions? Did adversarial generate meaningful (not rubber-stamp) challenges? Did routing decisions reflect evidence state?
- **Temporal integrity is the hardest bug**: If results look too good, check for post-cutoff information leakage
- **Runtime reporting** (`sfewa.reporting`) prints structured progress from every node — compare against cross-company results to spot divergence

## Git Workflow
- Branch naming: `feature/*`, `fix/*`, `docs/*`
- Commit messages: imperative mood, concise
- Keep PRs focused on one concern

@docs/architecture.md
@docs/liteagent_architecture.md
@docs/cross_company_results.md
@docs/iteration_log.md
@.env
