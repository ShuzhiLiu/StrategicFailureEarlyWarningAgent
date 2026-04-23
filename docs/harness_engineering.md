# Harness Engineering

The thesis document. What an agent harness is, what this project's harness implements, and what it deliberately omits — with direct references to the production systems (Claude Code, Hermes) that define the current ceiling.

---

## 1. Definition

> **Agent = Model + Harness.** The model provides intelligence; the harness provides hands, eyes, memory, and safety boundaries.

The *agent harness* is the infrastructure around the model: the controlled tool-loop, the tool registry, the state machine, memory systems, permission model, context management strategy, observability, and the analytical scaffolding that turns raw LLM calls into reliable autonomous behavior. Prompt engineering is one of its duties; the harness is a larger architecture that encompasses prompts, tool execution, result handling, state management, and cross-session persistence.

This framing is now standard. [OpenAI coined the discipline of "harness engineering"](https://www.decodingai.com/p/agentic-harness-engineering) after shipping ~1M lines of production code with a small team behind a carefully engineered Codex harness. [Martin Fowler frames harness engineering as the primary driver of agent performance variance](https://martinfowler.com/articles/harness-engineering.html). [Parallel Web Systems' definition](https://parallel.ai/articles/what-is-an-agent-harness) makes the point cleanly: the model provides intelligence, the harness provides everything else.

Why it matters: **models are commoditizing; harnesses aren't.** The differentiating asset in an agentic system is increasingly the architecture around the model, not the model itself. A measured result: a controlled experiment across 15 software-engineering tasks found that structured pre-configuration (the harness layer) produced a +60% average quality improvement (49.5 → 79.3), a 15/15 win rate, and a −32% variance reduction — with effectiveness scaling with task complexity.

---

## 2. State of the art — the ceiling this project measures against

Two production harnesses set the reference bar for what an agent harness can do today. `liteagent + sfewa` is a minimal reference that intentionally implements less, so that what it does build is observable and auditable.

### 2.1 Claude Code (Anthropic)

A coding agent harness with ~512K lines of TypeScript wrapping the core `while(tool_call)` loop. The loop itself is ~65 lines; the 512K exist for production hardening. Key harness components:

- **Tool system** — 66+ tools, unified `Tool<Input, Output, P>` interface, fail-closed defaults (`isConcurrencySafe: false`, `isReadOnly: false`, `checkPermissions: allow`). Adding a tool requires zero changes to the execution pipeline.
- **Two-layer loop architecture** — `QueryEngine` (session lifecycle, billing, slash commands) vs `query()` (per-turn loop, tool execution, compression).
- **Streaming with parallel tool execution** — `StreamingToolExecutor` executes read-only tools *during* model generation, hiding tool latency inside the 5–30s generation window.
- **Progressive error recovery** — 4+ distinct strategies (`collapse_drain_retry`, `reactive_compact_retry`, `max_output_tokens_escalate`, `max_output_tokens_recovery`). Errors are withheld from the user until all recovery fails.
- **5-stage context compression** — snip → microcompact → collapse → autocompact → hard reset. Cheap recovery first.
- **Hook system** — 27 distinct event types for policy enforcement (pre-tool, post-tool, pre-compact, pre-stop, etc.).
- **Permission model** — 7 layers, per-tool authorization, session-scoped overrides.
- **Persistent memory** — auto-writes memory files scoped by project and topic; surfaces them into system prompt at session start.
- **Skill library** — discoverable skills, auto-surfaced based on context.

### 2.2 Hermes Agent (Nous Research)

A platform integration harness (~11,000 lines) designed for Slack, Discord, and 16+ other chat platforms. Key harness components:

- **Monolithic `AIAgent` class** with `run_conversation()` loop; `IterationBudget` (thread-safe counter, default max 90 turns) prevents runaway loops.
- **Tool registry with AST-based auto-discovery** — self-registering modules, no manual manifest.
- **54+ tools** spanning web search, code execution, platform-specific actions.
- **7-stage error classification** mapping API errors to 14 `FailoverReason` categories, each with recovery hints.
- **Ordered LLM fallback chain** — per-turn failover between backup providers.
- **Gateway streaming** — `StreamConsumer` bridges sync agent callbacks to async platform delivery, with overflow handling at natural boundaries.

Source: [docs/essays/agentic_architecture_research.md](essays/agentic_architecture_research.md) has a much deeper comparison of both systems.

---

## 3. This project's harness — what's built

`liteagent` (~1,000 LOC, 1 external dep) + `sfewa` (domain application) implement a minimal but deliberate subset of the harness surface. Every component is a specific design choice with a rationale in [docs/iteration_log.md](iteration_log.md).

### 3.1 Core loop layer (liteagent)

| Component | Module | What it does |
|---|---|---|
| `ToolLoopAgent` | `liteagent/agent.py` | The `while(tool_call)` loop. ~30 LOC core. Ends when LLM returns no tool calls or `max_iterations` hit. |
| `Tool` + `@tool` decorator | `liteagent/tool.py` | Tool definition, auto-generated JSON schema from Python type hints, OpenAI-format serialization, fail-closed error handling (errors returned as strings, not raised). |
| `LLMClient` | `liteagent/llm.py` | Wrapper over OpenAI SDK with response normalization (handles vLLM's `reasoning_content` for thinking-mode). Token-usage tracking via `TokenUsage` dataclass. |
| `parse_tool_calls` | `liteagent/tool.py` | Extracts tool calls from LLM responses. Works with raw OpenAI or normalized `LLMResponse`. |

### 3.2 Pipeline orchestration layer (liteagent)

| Component | Module | What it does |
|---|---|---|
| `merge_state(state, updates, accumulate={...})` | `liteagent/pipeline.py` | Explicit state merging. Accumulating fields extend; others overwrite. No implicit reducers — every accumulation is visible at the call site. |
| `run_parallel(nodes, state)` | `liteagent/pipeline.py` | Parallel fan-out via ThreadPoolExecutor. Each node receives an isolated state copy. |
| `loop_until(state, steps, done, max_iterations)` | `liteagent/pipeline.py` | LLM-driven loop with safety bound. The LLM makes the routing decision (sets a state field); the counter is a backstop. |
| `dedup_by_key(items, key, keep="last")` | `liteagent/state.py` | Post-loop cleanup of accumulating fields. Solves the loop-induced duplication problem that frustrates `Annotated[list, operator.add]` users in LangGraph. |

### 3.3 Observability layer (liteagent)

| Component | Module | What it does |
|---|---|---|
| `CallLog` | `liteagent/observe.py` | Accumulates `LLMCallRecord`, `ToolCallRecord`, `PipelineEventRecord`. Saves to JSONL. No vendor coupling. |
| `Reporter` protocol | `liteagent/observe.py` | Pluggable runtime reporting (Rich terminal, JSON stream, silent). |
| `PipelineEventRecord` | `liteagent/observe.py` | Node enter/exit, routing decisions, parallel fan-out markers. Interleaved with LLM/tool records so a single `llm_history.jsonl` reconstructs the full pipeline flow graph. |

### 3.4 Robustness layer (liteagent)

| Component | Module | What it does |
|---|---|---|
| `extract_json`, `parse_llm_json` | `liteagent/parse.py` | Handles raw JSON, markdown code blocks, `<think>` prefixes, bracket-matching fallback. `parse_llm_json` retries with error feedback appended. |
| `NodeError`, `retry`, `with_fallback` | `liteagent/errors.py` | Structured errors (nodes return `NodeError` rather than raising), exponential backoff with jitter, ordered fallback chain. |
| `truncate`, `TokenBudget`, `ContextBuilder` | `liteagent/context.py` | Middle-cut truncation (preserves both ends; Claude Code pattern), token budget tracking, pipeline-history section composer. |

### 3.5 Analytical scaffolding (sfewa) — domain-specific harness

| Component | Where | What it does |
|---|---|---|
| **Temporal integrity gates** | 3 layers | (1) `sfewa/tools/temporal_filter.py` rejects `published_at > cutoff`. (2) Extraction filter on evidence items. (3) Prompt-level `"Do NOT use knowledge after {cutoff_date}"`. |
| **Iceberg Model 4-layer routing** | `sfewa/prompts/analysis.py` | LLM decides analytical depth per risk dimension. Benign patterns stop at Layer 2; structural risks descend to Layer 4 with pre-mortem assumption challenge. |
| **3-phase adversarial review** | `sfewa/agents/adversarial.py` | Chain of Verification (thinking mode) → independent web-search verification (ToolLoopAgent) → challenge refinement. Structurally separated from analysts. |
| **7 programmatic consistency flags** | `sfewa/agents/_analyst_base.py` | `[DEPTH_SEVERITY_MISMATCH]`, `[MISSING_FORCES]`, `[MISSING_ASSUMPTION]`, `[PHANTOM_CITATION]`, `[STANCE_MISMATCH]`, `[THIN_EVIDENCE]`, `[EVIDENCE IMBALANCE]`. Deterministic checks injected as STRONG-challenge triggers. |
| **Self-consistency sampling (N=3)** | `_analyst_base.py` | Modal severity + median depth across N independent samples. Dynamic early-stop when first N−1 agree. |
| **Empirical confidence** | `graph/pipeline.py` | HHI severity concentration + ordinal range across analyst outputs. Injected into synthesis prompt in place of LLM-verbalized confidence. |
| **Evidence-gated severity adjustment** | `agents/risk_synthesis.py` | STRONG challenges only downgrade factors with weak supporting-evidence quality (`valid_sup < 3`, excluding phantom + stance-mismatched citations). |
| **Agentic retrieval** | `agents/agentic_retrieval.py` | `ToolLoopAgent` with search + filing-discovery tools. Derives queries from dimensions, self-assesses coverage against 9 criteria, stops when satisfied. Budgeted at 15 queries / 150 docs. |
| **Filing discovery** | `sfewa/tools/filing_discovery.py` | Jurisdiction-agnostic primary-source retrieval. Japan → EDINET, China → CNINFO, discovered via company name + pinyin match. No company codes hardcoded. |

---

## 4. What's deliberately not in this harness — and what each omission costs

The scope is explicit. Every omission is tracked with a concrete motivation on [ROADMAP.md](../ROADMAP.md).

| Component | Claude Code has | This harness has | What the omission costs |
|---|:---:|:---:|---|
| **Persistent memory across runs** | ✓ | ✗ | No research-cost compression across sessions. Claude Code benchmark R2 used ~120 tool calls *seeded by prior-run memory `sector_auto_ev_risk.md`*. Direct empirical evidence memory has value. **Highest-ROI next addition.** [v0.2] |
| **Skill library** | ✓ | ✗ | Iceberg Model + 3-phase adversarial are SFEWA-specific. Factoring them as loadable skills enables cross-domain reuse (pharma pipeline, cloud strategy). [v0.3] |
| **Permission model / sandbox** | ✓ (7 layers) | ✗ | Fine for local single-user trust. Required once the tool catalog grows to external writes. [v0.4] |
| **Hook system** (27 event types) | ✓ | ✗ | No policy enforcement. Pre/post-tool hooks are the standard extensibility pattern for production harnesses. [v0.4] |
| **Progressive context compression** (5 stages) | ✓ | partial | `truncate()` only. Long multi-turn sessions will hit the context wall before compressing. [v0.5] |
| **Prompt-cache optimization** | ✓ | ✗ | Vital for production economics; not the bottleneck at vLLM-local development scale. |
| **Streaming with parallel tool execution** | ✓ | ✗ | Pipeline is batch, not interactive. Streaming unlocks the "hide tool latency inside generation window" trick. |
| **Multi-LLM fallback chain** | ✓ (Hermes) | ✗ | Single-provider. Fine for research; a production deployment wants per-turn provider failover. |
| **Auto-discovery of tools via AST** | ✓ (Hermes) | ✗ | Tools are manually registered. Fine at 3 tools; problematic at 50. |

---

## 5. Design rules — the non-negotiables

The harness is built under five rules, enforced by `CLAUDE.md` and the test suite. Every PR that violates them is rejected.

1. **No company-specific logic.** Zero `if company == "honda": ...`. The same harness, same prompts, same model must produce different results for different cases through evidence-driven reasoning.
2. **LLM-driven routing, not hardcoded thresholds.** Iteration counters are safety bounds only. `if len(evidence) < 10: loop_back()` is not allowed.
3. **Separated evaluation.** When a new quality problem emerges, prefer adding or strengthening an independent evaluator over asking the generator to self-critique.
4. **Evidence-driven, not knowledge-driven.** Conclusions emerge from retrieved evidence. Never use LLM world knowledge as the basis for a severity assessment.
5. **Temporal integrity is non-negotiable.** Any new retrieval or extraction path must enforce the cutoff at the published-date filter, the extraction filter, and the prompt. Adding a fourth leak is worse than fixing the LLM's output.

And two delegation rules that shape what goes where:

6. **Delegate counting to code; delegate reasoning to the LLM.** Citation existence, stance alignment, depth-severity consistency — deterministic. Causal-loop identification, severity judgment, strategic narrative — LLM.
7. **Hierarchy of interventions: structural > reasoning framework > prompt tuning.** When results are wrong, change architecture first, reasoning frameworks second, prompt language last.

---

## 6. How this harness compares empirically

The [Claude Code benchmark](claude_code_benchmark.md) is the empirical check on whether omitting these harness components actually matters. Honda ordering agrees between this project's minimal harness and Claude Code's full-featured harness — the core signal transfers. Where they disagree (Toyota vs BYD ordering; absolute severity magnitude), Claude Code's additional features (memory-seeded context, sub-agent parallelism, Plan Mode) may be doing work this harness can't.

That observation drives the roadmap: **each next version adds one harness component and measures its effect on behavior.** Not "what can I build," but "what demonstrably changes when I add it?"

---

## 7. References

Foundational and canonical treatments of the agent-harness concept:

- [Martin Fowler — *Harness engineering for coding agent users*](https://martinfowler.com/articles/harness-engineering.html)
- [Parallel Web Systems — *What is an agent harness in the context of large-language models?*](https://parallel.ai/articles/what-is-an-agent-harness)
- [Decoding AI — *Agentic Harness Engineering: LLMs as the New OS*](https://www.decodingai.com/p/agentic-harness-engineering)
- [Frank's World — *The Art and Science of Harness Engineering*](https://www.franksworld.com/2026/04/20/the-art-and-science-of-harness-engineering-redefining-ai-agent-performance/)
- [preprints.org — *Agent Harness for Large Language Model Agents: A Survey* (2026)](https://www.preprints.org/manuscript/202604.0428/v1)

In-repo:

- [essays/agentic_architecture_research.md](essays/agentic_architecture_research.md) — Full comparison of Claude Code and Hermes production systems.
- [essays/framework_anti_patterns.md](essays/framework_anti_patterns.md) — Why this project does not build on LangChain/LangGraph.
- [liteagent_architecture.md](liteagent_architecture.md) — Detailed module map and patterns encoded.
- [iteration_log.md](iteration_log.md) — The 40-iteration audit trail of every harness-layer change and its measured effect.
