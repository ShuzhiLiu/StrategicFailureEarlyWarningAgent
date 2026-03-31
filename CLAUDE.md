# Strategic Failure Early Warning Agent

## Project Overview
A time-bounded multi-agent system for strategic failure early warning on public companies.
Uses LangGraph for orchestration, Claude/OpenAI for reasoning, and evidence-driven analysis with temporal integrity.

**First case study**: Honda EV strategy backtesting (cutoff: 2025-05-19)

## Tech Stack
- **Agent framework**: LangGraph 2.x + LangChain
- **Package manager**: uv
- **Testing**: pytest
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
- Every evidence object must have a `published_at` timestamp and pass cutoff validation
- Never use data published after the case's `cutoff_date`
- Agent outputs must be structured (TypedDict/Pydantic), not free-form prose
- All high-level conclusions must reference `evidence_id` list
- State flows through LangGraph StateGraph; no global mutable state
- Use `Annotated[list, operator.add]` for accumulating state fields

## Development Iteration Rules

### Build order: follow the pipeline
Implement nodes in pipeline topological order. Each node can only be properly tested when its upstream nodes produce real output.

```
init_case → retrieval → evidence_extraction → [industry|company|peer]_analyst → adversarial_review → risk_synthesis → backtest
```

### Per-node development cycle
For each node, complete these steps before moving to the next:
1. **Implement** the node (LLM call + structured output + reporting calls)
2. **Unit test** with fixture input (no LLM dependency)
3. **Integration test** run pipeline from START to current node with real LLM
4. **Validate** compare reporting output against `docs/golden_run_honda.md` — check for structural divergence (wrong routing, missing dimensions, unexpected counts), not exact value match
5. **Commit** the working node

### End-to-end first, polish second
- **Phase A (flow)**: Get all 9 nodes producing valid structured output in one full pipeline run. Prompt quality can be mediocre — the goal is pipeline connectivity and schema compliance.
- **Phase B (quality)**: Once the pipeline flows end-to-end, go back and iterate on individual prompts, evidence quality, and risk factor depth.
- Do NOT spend time tuning prompts until Phase A is complete.

### LLM structured output strategy
Qwen3.5 may break Pydantic schemas. Each LLM-calling node should:
1. Request structured output via `with_structured_output()` or explicit JSON schema in prompt
2. On parse failure, retry once with the validation error appended to the prompt
3. On second failure, log the error via `reporting.log_action()`, set `state["error"]`, and return partial results rather than crashing the pipeline

### Debugging against golden run
- `docs/golden_run_honda.md` is a **reference**, not a spec — actual output will differ in counts and content
- **Structural checks**: Did retrieval produce documents? Did extraction produce evidence with all required fields? Did analysts cover the expected dimensions? Did adversarial review generate challenges? Did routing decisions match expected conditions?
- **Temporal integrity is the hardest bug**: If results look too good, check whether post-cutoff information leaked through LLM world knowledge or improperly filtered documents
- **Runtime reporting** (`sfewa.reporting`) prints structured progress from every node — compare this output against the golden run to spot where behavior diverges

## Git Workflow
- Branch naming: `feature/*`, `fix/*`, `docs/*`
- Commit messages: imperative mood, concise
- Keep PRs focused on one concern
- Commit after each node passes integration test — do not batch multiple nodes

@docs/implementation_plan.md
@docs/golden_run_honda.md
@docs/iteration_log.md
@.env