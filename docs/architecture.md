# Agent Architecture

How SFEWA's multi-agent architecture produces differentiated risk assessments through autonomous exploration, independent evaluation, and evidence-driven reasoning.

---

## 1. Planner-Generator-Evaluator Framework

Modern production agent systems (Claude Code, Anthropic's SWE harness, TradingAgents-CN) converge on a three-role architecture. SFEWA adapts this for domain-specific strategic risk analysis:

```
┌─────────────────────────────────────────────────────────────────────┐
│              SFEWA: Planner-Generator-Evaluator                     │
│              for Strategic Risk Analysis                            │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  PLANNER: Autonomous Information Gathering                    │  │
│  │  "What do I need to know? Do I know enough?"                  │  │
│  │                                                               │  │
│  │  retrieval (3-pass) → extraction → quality_gate (LLM loop)   │  │
│  │  Generates own queries. Evaluates own coverage. Loops until   │  │
│  │  satisfied. Temporal filter prevents information leakage.     │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                    evidence_sufficient?                              │
│                     (LLM decides)                                   │
│                              │                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  GENERATOR: Multi-Expert Risk Analysis                        │  │
│  │  "Three specialists argue from different angles"              │  │
│  │                                                               │  │
│  │  industry ║ company ║ peer (parallel, scope-bounded)          │  │
│  │  Same evidence, different lenses, non-overlapping dimensions. │  │
│  │  9 risk factors across 9 dimensions.                          │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  EVALUATOR: Independent Adversarial Review                    │  │
│  │  "Agents cannot self-evaluate" (Anthropic's key insight)      │  │
│  │                                                               │  │
│  │  Thinking mode. Checks 6 bias types. Grades challenges.      │  │
│  │  Honda: 0 strong → HIGH preserved.                            │  │
│  │  BYD: 3 strong → enables LOW rating.                          │  │
│  │  Can route back for reanalysis if factors fundamentally weak. │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  SYNTHESIZER + VALIDATOR (domain-specific extension)          │  │
│  │  risk_synthesis (continuous 0-100 score) → backtest           │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  Cross-cutting: Pipeline Context Injection, Dead-Loop Protection,  │
│  Temporal Integrity, File-Based Audit Trail                        │
└─────────────────────────────────────────────────────────────────────┘
```

### How SFEWA Maps to Claude Code

| P-G-E Role | Claude Code (General) | SFEWA (Domain-Specific) |
|---|---|---|
| **Planner** | Expands prompts into specs; decides scope | retrieval (3-pass agentic search) + quality_gate (LLM decides evidence sufficiency) |
| **Generator** | Implements code in sprints | 3 parallel analysts with scope boundaries produce risk factors |
| **Evaluator** | Playwright E2E tests + separate agent grading | Adversarial reviewer (thinking mode, 6 bias checks, 3-level severity) |
| **Sprint contracts** | Generator+Evaluator negotiate criteria | Fixed 9-dimension ontology (known in advance for domain-specific task) |
| **Feedback loop** | Failed eval → Generator retries | "reanalyze" recommendation → back to extraction/analysts |

**The critical shared insight**: "Tuning a dedicated evaluator to be skeptical is far more tractable than making a generator self-critical."

### What SFEWA Has Beyond P-G-E

- **Temporal integrity** — Hard cutoff enforcement at retrieval + extraction + prompts. Equivalent to Claude Code's security tools, but for time rather than safety.
- **Multi-expert fan-out** — Genuine parallel execution via LangGraph `Send` API. Claude Code is single-threaded; SFEWA runs 3 analysts concurrently with safe state merging.
- **Backtest validation** — Domain-specific ground truth testing. Claude Code uses Playwright; SFEWA matches predictions against real-world events.

---

## 2. Pipeline Architecture

```
                          ┌──────────────┐
                          │  Case Config │
                          └──────┬───────┘
                                 ▼
                          ┌──────────────┐
                     ┌────│  init_case   │
                     │    └──────┬───────┘
                     │           ▼
                     │    ┌──────────────┐      ┌──────────────────────────────┐
                     │    │  retrieval   │◄─────│  3-pass agentic search:      │
                     │    │  (3-pass)    │      │  seed → gap-fill → counter   │
                     │    └──────┬───────┘      └──────────────────────────────┘
                     │           ▼
                     │    ┌──────────────┐
                     │    │  evidence    │
                     │    │  extraction  │
                     │    └──────┬───────┘
                     │           ▼
  LLM-driven    ─────┤    ┌──────────────┐
  Loop 1             │    │ quality_gate │──── LLM decides: sufficient?
  (evidence          │    └──────┬───────┘     │
   sufficiency)      │      sufficient         insufficient
                     │           │              └──► back to retrieval
                     │           ▼                   with targeted queries
                     │    ┌──────┴───────┐
                     │    │   Fan-out    │
                     │    │  (Send API)  │
                     │    ├──────────────┤
                     │    │  industry    │  company    │  peer       │
                     │    │  analyst     │  analyst    │  analyst    │
                     │    └──────┬───────┘──────┬──────┘──────┬──────┘
                     │           └──────────────┼─────────────┘
                     │                          ▼
  LLM-driven    ─────┤    ┌─────────────────────────────┐
  Loop 2             │    │   adversarial_review        │──── LLM decides: proceed?
  (adversarial       │    │   (INDEPENDENT EVALUATOR)   │     │
   challenge)        │    └──────────────┬──────────────┘     reanalyze
                     │            proceed                      └──► back to extraction
                     │                   ▼
                     │    ┌──────────────┐
                     │    │   synthesis  │
                     │    └──────┬───────┘
                     │           ▼
                     │    ┌──────────────┐
                     └────│   backtest   │
                          └──────────────┘
```

**10 nodes. 2 LLM-driven routing decisions. 1 fan-out parallelism point.**

Every routing decision is made by the LLM reading its own output state — iteration counters are safety bounds, not primary logic.

---

## 3. Five Agentic Capabilities

| Capability | Where It Happens | Evidence from Traces |
|---|---|---|
| **LLM Orchestration** | StateGraph with conditional edges, fan-out | 10 nodes, 3 parallel analysts, 2 feedback loops |
| **Tool Calling** | Retrieval agent calls DuckDuckGo + temporal filter | 100-140 docs retrieved across 3 search passes per company |
| **State Management** | `Annotated[list, operator.add]` reducers | 3 analysts write to `risk_factors` concurrently — no conflicts |
| **Multi-Step Reasoning Loop** | Quality gate + adversarial loop-back | All 3 companies: iteration_count=3 (quality gate looped) |
| **Autonomous Action** | End-to-end without human intervention | Honda 33 evidence → 61/100, BYD 19 evidence → 30/100, same pipeline |

---

## 4. The Independent Evaluator

### Why Separation Matters

The most important architectural insight from Claude Code's leaked design: **agents cannot reliably self-evaluate their own output**. Claude Code's evaluator is structurally separate from its generator. Anthropic's SWE harness uses the same pattern. TradingAgents-CN uses adversarial debate loops.

SFEWA implements this through a **structurally separated adversarial reviewer**:

| Principle | Claude Code | SFEWA |
|---|---|---|
| Structural separation | Separate agent, own context | Separate node, thinking mode, different prompt |
| Never sees generator reasoning | Only sees code output | Only sees risk factors + evidence, not analyst prompts |
| Objective criteria | Playwright tests, weighted rubric | 6 bias checks, 3-level severity grading |
| Feedback loop | Failed eval → Generator retries | "reanalyze" → back to extraction/analysts |
| Access to independent data | Can run its own tests | Sees ALL evidence, not just what analysts cited |

### How It Behaves Differently Per Company

Same 9 challenges for every company, but severity distribution differs across runs:

```
Company    Strong (avg)  Effect on Assessment
─────────  ────────────  ──────────────────────────────────────
Honda        0-3          Fewer downgrades → higher risk score (avg 55/100)
Toyota       0-1          Moderate downgrades → middle score (avg 47/100)
BYD          0-3          More downgrades → lower risk score (avg 39/100)
```

**Honda**: Adversarial finds fewer fundamental flaws — risk factors are well-supported by EDINET filings and external evidence. When strong challenges occur, they target evidence quality (single-source tariff claims), not the underlying risk logic.

**Toyota**: Adversarial catches strategy misattribution (rating hybrid-first company HIGH for low BEV sales) and data category errors. Toyota's strong hybrid business provides legitimate counter-evidence.

**BYD**: Adversarial frequently finds inflated severity (profit growth contradicts "unsustainability"), redundant factors, and mischaracterized strengths (LFP battery reliance = advantage, not weakness).

### The Downgrade Rule

> **Only downgrade a factor's severity if it received a STRONG adversarial challenge.** Moderate and weak challenges are noted in the memo but do NOT change severity.

This prevents over-correction (Honda's 7 moderate challenges don't erode HIGH) while allowing genuine flaws to be corrected (BYD's 3 strong challenges enable LOW).

---

## 5. Design Patterns

### Pattern 1: Separated Evaluation (Anthropic Harness Design)

```
Analysts (non-thinking mode) ──produce──→ Risk Factors
                                              │
Adversarial Reviewer (thinking mode) ──challenges──→ Adjusted Factors
                                              │
Synthesis (thinking mode) ──integrates──→ Final Assessment
```

Thinking/non-thinking mode split is deliberate: analysts need speed and structured output, the reviewer needs deep reasoning.

### Pattern 2: Adaptive Information Gathering (Quality Gate Loop)

```
Pass 1: Broad exploration ──→ Quality Gate evaluates ──→ "Missing China market data"
Pass 2: Targeted gap-fill ──→ Quality Gate evaluates ──→ "Sufficient"
```

Same pattern as Claude Code's iterative tool use: observe state, decide if more information is needed, act.

### Pattern 3: Pipeline Context Injection (Claude Code TODO Injection)

Each downstream node receives a summary of upstream pipeline history:

```
PIPELINE CONTEXT (what has happened so far):
- Retrieved 138 documents (23 edinet, 58 duckduckgo, 31 gap_fill, 26 counter)
- Extracted 29 evidence items (stance: 10 supports, 5 contradicts, 14 neutral)
- Quality gate: evidence sufficient (iteration 3)
```

Claude Code injects TODO state after every tool use via `<system-reminder>` tags. SFEWA's `build_pipeline_context()` does the same for pipeline history.

### Pattern 4: Dead-Loop Protection (TradingAgents-CN)

```python
MAX_ITERATIONS = 3          # quality gate loop limit
MAX_ADVERSARIAL_PASSES = 2  # adversarial loop limit
```

LLM makes the routing decision. Counters fire only if the LLM loops beyond reasonable bounds.

### Pattern 5: Fan-Out Specialization (Multi-Expert Decomposition)

```
Industry Analyst  → market_timing, policy_dependency
Company Analyst   → capital_allocation, narrative_consistency, execution, product_portfolio
Peer Analyst      → competitive_pressure, regional_mismatch, technology_capability
```

Each analyst sees ALL evidence but only assesses its assigned dimensions. Prevents "industry-vs-company confusion" bias.

---

## 6. What Makes This Agentic (Not Just a Pipeline)

| Dimension | Pipeline (Static) | SFEWA (Agentic) |
|---|---|---|
| Search queries | Config-defined topics | LLM generates queries from case context |
| Evidence sufficiency | Fixed threshold (e.g., >10 items) | LLM evaluates coverage, balance, diversity |
| Routing after quality gate | Always proceed | LLM decides: sufficient → proceed, insufficient → loop |
| Adversarial routing | Hardcoded % threshold | LLM recommends: proceed or reanalyze |
| Severity calibration | Fixed rules | LLM weighs evidence for/against, assesses materiality, outputs continuous risk score (0-100) |
| Context awareness | Each node isolated | Pipeline context injected — downstream knows upstream history |

6+ autonomous decisions per run that alter behavior. Different companies trigger different paths through the same architecture.

---

## 7. Event Alignment: AI Tinkerers HK (April 29, 2026)

### Event Profile

- **Format**: 4 demos, 15 min each (10 demo + 5 Q&A), no slides
- **Theme**: "Agentic AI in Action" — LLM orchestration, tool-calling, state management, multi-step reasoning, autonomous action
- **Audience**: Curated builders from AWS, HSBC, HKEX — RAG pipelines, autonomous agents, Python, cloud-native
- **Call**: "Show your messy experiments" — WIP welcomed, technical depth over high-level concepts

### Capability Checklist

| Event Wants | SFEWA Delivers | Strength |
|---|---|---|
| **LLM orchestration** | LangGraph StateGraph, 10 nodes, conditional edges, fan-out | STRONG |
| **Tool-calling reliability** | DuckDuckGo + temporal filter as LangChain tools | ADEQUATE (2 tools, but temporal filter is novel) |
| **State management** | `Annotated[list, operator.add]` concurrent accumulation | STRONG |
| **Multi-step reasoning loops** | Quality gate + adversarial loop (both LLM-driven) | STRONG |
| **Systems that take action** | Fully autonomous retrieve → analyze → challenge → synthesize → backtest | STRONG |
| **Code over decks** | Terminal output, Rich reporting, JSON artifacts | STRONG |
| **Messy experiments** | Temporal leakage, structured output, adversarial calibration | STRONG |

### Gaps Worth Acknowledging in Q&A

| Gap | Honest Answer |
|---|---|
| LLM world knowledge leakage | "We filter documents by date, but can't prevent the model from knowing Honda revised targets. Hardest unsolved problem in temporal backtesting." |
| Structured output reliability | "Qwen3.5 sometimes breaks JSON. We retry with error messages. Production needs schema-constrained decoding." |
| Run-to-run variability | "Continuous risk scores vary ±15 points per run (Honda 45-62, Toyota 44-50, BYD 30-44). Ordering Honda > Toyota > BYD is stable. Production would use ensemble of 3-5 runs, take median." |
| Evaluator is LLM-only | "Claude Code uses Playwright for objective tests. A future version could add programmatic checks alongside LLM judgment." |

### Recommended Demo Narrative

**Min 0-1**: Hook — "Honda wrote down 2.5T yen in March 2026. Could agents have seen it coming?"

**Min 1-4**: Architecture as P-G-E — Show graph code. "Planner decides what to search, Generator runs 3 parallel analysts, Evaluator challenges every conclusion."

**Min 4-6**: Live trace — Quality gate looping, analysts producing severity profiles, adversarial reviewer finding 0 strong challenges for Honda.

**Min 6-8**: Cross-company proof — Same pipeline, same model: Honda 62/100, Toyota 50/100, BYD 30/100. Continuous scores show clear differentiation. Drill into BYD's strong adversarial challenges.

**Min 8-9**: Backtest — Honda STRONG matches on target revision and EV cancellation. "Predicted failure 10 months early."

**Min 9-10**: Honest failures — Three unsolved problems. Invite discussion.

**Min 10-15**: Q&A.
