# Roadmap

This is a harness-expansion roadmap. Each version adds one component to the agent harness, chosen from the surface documented in [docs/harness_engineering.md](docs/harness_engineering.md). Every item has the same shape: **what harness component**, **why now**, **scope**, **success criterion**, **non-goal**.

Dates are notional. Prioritization is driven by measured gaps from the [Claude Code benchmark](docs/claude_code_benchmark.md), not by estimated implementation difficulty.

---

## v0.2 — Persistent memory layer

**Harness component**: Cross-session memory. The capability that lets an agent amortize research cost across runs by surfacing what it learned in prior sessions.

**Why now**: The Claude Code benchmark directly observed memory's value. R2's methodology notes: *"6 Explore sub-agents in two parallel waves, ~120 tool calls, seeded by prior-run memory `sector_auto_ev_risk.md`."* That is direct evidence that a persistence layer `liteagent` doesn't have is compressing research cost for Claude Code. This is the single highest-ROI addition.

**Scope**:
- Minimal `liteagent/memory.py` module (~200 LOC).
- File-backed memory, 4 types: `case` (single-case lessons), `peer` (per-competitor patterns), `jurisdiction` (filing-system-specific rules), `methodology` (harness-level patterns that worked).
- Write after `risk_synthesis` completes: "what pattern did this case exemplify; what evidence would have been worth finding earlier?"
- Read at `init_case`: surface prior cases in the same sector or theme as context, not as authority.

**Success criterion**: Run Honda three times consecutively. The 3rd run should retrieve fewer documents than the 1st (research-cost compression) AND preserve or improve score stability. The compression must not come at the cost of accuracy.

**Non-goals**: Organizational knowledge management, vector DB, cross-user sharing, agentic-memory research experiments. Session-memory for the single user on a single machine. No more.

---

## v0.3 — Skill library

**Harness component**: A discoverable, loadable library of reusable analytical frameworks. The pattern Claude Code uses to distribute domain expertise across cases without hard-coding it into agents.

**Why now**: The Iceberg Model 4-layer routing and the 3-phase adversarial review are currently inline in `src/sfewa/prompts/analysis.py` and `src/sfewa/agents/adversarial.py`. Cross-domain reuse (pharma, cloud strategy) requires factoring them out. Today they cannot be applied to anything but a Honda-shaped case without code duplication.

**Scope**:
- Define a `Skill` primitive in `liteagent`: a named analytical framework with a prompt template, required state fields, and optional programmatic checks.
- Migrate Iceberg Model and 3-phase adversarial into skills.
- Add skill discovery: an agent can see available skills in its system prompt and invoke the one that matches its case.

**Success criterion**: Adding a new analytical framework (e.g., Porter's Five Forces as a skill) requires only a new skill file, no changes to the pipeline.

**Non-goals**: Auto-generated skills, cross-agent skill composition, an agent-authored skills mechanism (that's closer to v0.5+).

---

## v0.4 — Permission model and hook system

**Harness component**: Authorization boundaries for tool calls + policy-enforcement hooks. Claude Code's 7-layer permission model and 27-event hook system are the canonical reference.

**Why now**: At v0.1, the only tools are read-only web search and read-only filing loaders. Trust is implicit. As the roadmap adds write-capable tools (memory writes, skill writes, artifact uploads), permission becomes non-optional. Hooks enable both policy enforcement and clean extensibility (logging, rate limiting, audit).

**Scope**:
- `liteagent/permissions.py`: per-tool authorization annotations (`isReadOnly`, `isConcurrencySafe`, `checkPermissions`), fail-closed defaults (borrowed from Claude Code).
- `liteagent/hooks.py`: pre-tool, post-tool, pre-compact, pre-stop, post-extraction event types. Handler chain with short-circuit on deny.
- Wire hooks through `ToolLoopAgent` and the pipeline executor.

**Success criterion**: A new tool with no annotations is treated as dangerous and serial. Adding a rate-limit policy to DuckDuckGo search is one hook registration, not a pipeline edit.

**Non-goals**: A full sandbox (filesystem jail, subprocess isolation). Single-user local execution stays single-user.

---

## v0.5 — Progressive context compression

**Harness component**: Multi-stage context compression. Claude Code's 5-stage pipeline (snip → microcompact → collapse → autocompact → hard reset) is the reference. Cheap recovery first, expensive only when necessary.

**Why now**: Current harness uses `truncate()` with middle-cut. Adequate for 8-node batch pipelines with Qwen3.5's 32K context. Insufficient for longer-horizon multi-session research that v0.2 memory will enable.

**Scope**:
- Layer 1 — `snip`: remove verbose tool-result preambles but preserve claims.
- Layer 2 — `microcompact`: summarize individual tool results inline.
- Layer 3 — `collapse`: fold full evidence-retrieval turns into one-line summaries.
- Layer 4 — `autocompact`: LLM-generated session summary, discard raw turns.
- Layer 5 — `reset`: hard reset with memory re-injection.

**Success criterion**: A Honda run with 300 retrieved documents (~2× current max) completes without context overflow, with no measurable score degradation.

**Non-goals**: Streaming with parallel tool execution — that's an orthogonal feature (v0.6+).

---

## v0.6 — Cross-domain portability test

**Harness component**: Not a new component — a portability experiment for the existing harness.

**Why now**: Everything in this project has been tested on EV-strategy cases for automotive companies. The architecture was designed to generalize, but it has not been stress-tested outside its training domain. A legitimate harness engineering claim requires this test.

**Scope**:
- One case in a capital-intensive non-auto domain: candidates include pharma pipeline execution, cloud-platform strategic bet, or an M&A integration.
- Fresh ground-truth events; same 9-run stability protocol.
- Identify which parts of the pipeline need adaptation (e.g., filing discovery is jurisdiction-keyed; pharma needs FDA / EMA sources; cloud has no equivalent Tier-1 filing).
- Migrate any non-portable assumption into a loadable skill (interacts with v0.3).

**Success criterion**: Cross-company ordering preserved within a new 3-case set (2 controls + 1 failure-target); no iteration-level regression on the EV baseline.

**Non-goals**: Multi-domain unified ontology; a general-purpose risk model.

---

## v0.7 — Multi-backend portability study

**Harness component**: Not a new component — a backend-portability experiment.

**Why now**: Results have been benchmarked on Qwen3.5-27B and Claude Code (indirectly). Unknown: how do depth routing, adversarial severity grading, and self-consistency sampling behave on GPT-4o, Claude Sonnet, Gemini 2.5?

**Scope**:
- Run the full 9-run protocol on at least 2 additional backends.
- Measure: ordering stability, STRONG challenge generation rate, depth distribution, run-to-run range.
- Write up which design choices are backend-dependent (likely: tool-calling reliability, thinking-mode behavior) vs backend-agnostic (likely: temporal integrity, adversarial separation, evidence-gated downgrades).

**Success criterion**: A published comparison table with 3+ backends, each with a 9-run stability test, disclosing honest regressions where they exist.

**Non-goals**: A routing / ensembling layer that picks the best backend per turn. Out of scope for a research harness.

---

## Unscheduled but tracked

| Item | Reason for tracking |
|---|---|
| **Ensemble scoring** (median of 5 runs) | Known to reduce variance; doubles cost. A production deployment feature, not a research feature. |
| **Additional jurisdictions** (SEC EDGAR, ESMA, DART) | Each is a `filing_discovery.py` adapter. Straightforward implementation, incremental value. |
| **Streaming output** | Interactive UX. Currently batch. |
| **TaskCreate-style planner node** | Claude Code has an explicit plan tool; this harness's agentic retrieval is implicit. Converting to explicit plans may improve auditability. |
| **BYD variance mitigation** | Today's 3-round stability test showed BYD's run-to-run range is 22 pts vs Honda 17 and Toyota 3. Candidates: tighten `valid_sup ≥ 4` for non-Tier-1 evidence, or add stance-diversity requirement (`contradicting / supporting < 0.4`). Structural change, not tuning. Deferred until the cause is confirmed across more samples. |

---

## Out of scope

- Production risk-scoring service, SaaS, hosted API.
- Real-time market data integration.
- Forecast of stock price, earnings, or other quantitative outcomes — this project scores strategic-execution risk, not equity price.
- Fine-tuning the base model. This is a harness engineering project; the model is a dependency.

---

## How to propose a roadmap item

See [CONTRIBUTING.md](CONTRIBUTING.md). A roadmap addition must be grounded in either (a) a concrete observation from an existing run or benchmark — not "it would be cool to add X" — or (b) a specific harness-layer gap relative to [docs/harness_engineering.md](docs/harness_engineering.md).
