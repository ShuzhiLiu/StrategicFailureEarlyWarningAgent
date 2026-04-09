# SFEWA Architecture

How SFEWA's multi-agent pipeline produces differentiated risk assessments through autonomous exploration, independent evaluation, and evidence-driven reasoning.

For the underlying framework design, see [liteagent Architecture](liteagent_architecture.md).

---

## 1. System Overview

SFEWA is a Planner-Generator-Evaluator system for strategic failure early warning on public companies. Given a company, strategy theme, and temporal cutoff, it autonomously retrieves evidence, produces risk assessments from three specialist perspectives using the Iceberg Model analytical framework, challenges those assessments adversarially via Chain of Verification, and synthesizes a continuous risk score (0-100).

```
┌──────────────────────────────────────────────────────────────────┐
│                SFEWA: Planner-Generator-Evaluator                │
│                                                                  │
│  PLANNER: Autonomous Information Gathering                       │
│    init_case (LLM generates dimensions, regions, peers)          │
│    agentic_retrieval (ToolLoopAgent: search + filings)           │
│    → evidence_extraction (batched, temporal-filtered)            │
│    Agent decides what to search, when to stop. Derives search   │
│    queries from analysis dimensions. Temporal filter prevents    │
│    information leakage.                                          │
│                                                                  │
│  GENERATOR: Multi-Expert Risk Analysis (Iceberg Model)           │
│    industry | company | peer (parallel, scope-bounded)           │
│    Same evidence, different lenses, LLM-generated dimensions.    │
│    4-Layer Progressive Deepening per dimension.                  │
│    9-12 risk factors across dynamically generated dimensions.    │
│                                                                  │
│  EVALUATOR: Independent Adversarial Review (3-Phase)             │
│    Phase 1: Chain of Verification (thinking mode)                │
│    Phase 2: Independent verification search (ToolLoopAgent)      │
│    Phase 3: Challenge refinement (thinking mode)                 │
│    Can route back for reanalysis if factors fundamentally weak.  │
│                                                                  │
│  SYNTHESIZER + VALIDATOR                                         │
│    risk_synthesis (causal loop analysis + pre-mortem, 0-100)     │
│    -> backtest                                                   │
│                                                                  │
│  Cross-cutting: Pipeline Context Injection, Dead-Loop            │
│  Protection, Temporal Integrity, File-Based Audit Trail          │
└──────────────────────────────────────────────────────────────────┘
```

### How SFEWA Maps to Claude Code's P-G-E

| P-G-E Role | Claude Code (General) | SFEWA (Domain-Specific) |
|---|---|---|
| **Planner** | Expands prompts into specs; decides scope | init_case (LLM generates dimensions) + agentic_retrieval (ToolLoopAgent with dimension-driven search) + evidence_extraction |
| **Generator** | Implements code in sprints | 3 parallel analysts with Iceberg Model framework produce risk factors with progressive depth analysis |
| **Evaluator** | Playwright E2E tests + separate agent grading | Adversarial reviewer (thinking mode, Chain of Verification, 3-level severity) |
| **Sprint contracts** | Generator+Evaluator negotiate criteria | LLM-generated dimensions with structural hints and critical assumptions |
| **Feedback loop** | Failed eval -> Generator retries | "reanalyze" recommendation -> back to extraction/analysts |

**The critical shared insight**: "Tuning a dedicated evaluator to be skeptical is far more tractable than making a generator self-critical."

### What SFEWA Has Beyond P-G-E

- **Temporal integrity** -- Hard cutoff enforcement at retrieval + extraction + prompts. Equivalent to Claude Code's security tools, but for time rather than safety.
- **Multi-expert fan-out** -- Genuine parallel execution via `liteagent.run_parallel()` with `ThreadPoolExecutor`. 3 analysts run concurrently with isolated state copies.
- **Backtest validation** -- Domain-specific ground truth testing. Claude Code uses Playwright; SFEWA matches predictions against real-world events.
- **Agentic depth routing** -- The Iceberg Model framework lets analysts decide HOW DEEP to go per dimension. Benign patterns stop at Layer 2 (LOW); structural risks go to Layer 4 (HIGH/CRITICAL).

---

## 2. Pipeline Flow

```
                         ┌──────────────┐
                         │  Case Config │
                         │  (3 fields)  │
                         └──────┬───────┘
                                ▼
                         ┌──────────────┐
                         │  init_case   │ LLM expands regions + peers
                         │              │ + generates analysis dimensions
                         └──────┬───────┘
                                ▼
                         ┌──────────────────────────────────────┐
                         │  agentic_retrieval (ToolLoopAgent)   │
                         │  Tools: search() + load_filings()    │
                         │  Agent decides queries from dims,    │
                         │  assesses coverage, stops when ready │
                         └──────┬───────────────────────────────┘
                                ▼
                         ┌──────────────┐
                         │  evidence    │  Batched extraction
                         │  extraction  │  + temporal filter
                         └──────┬───────┘
                                ▼
                         ┌──────────────────────────────────────┐
                         │  Parallel fan-out (ThreadPoolExecutor)│
                         │  Iceberg Model: 4-Layer Progressive  │
                         │  Deepening per dimension              │
                         ├──────────────┬───────────┬───────────┤
                         │  industry    │  company  │  peer     │
                         │  analyst     │  analyst  │  analyst  │
                         └──────┬───────┘─────┬─────┘─────┬─────┘
                                └─────────────┼───────────┘
                                              ▼
  LLM-driven   ──────    ┌─────────────────────────────┐
  Loop                   │   adversarial_review        │── LLM decides: proceed?
  (adversarial           │   3-Phase: CoVe + search    │     │
   challenge)            │   + refinement              │     reanalyze
                         └──────────────┬──────────────┘     └──> back to extraction
                                 proceed
                                        ▼
                         ┌──────────────┐
                         │   synthesis  │  Programmatic base score
                         │              │  + causal loop analysis
                         │              │  + pre-mortem check
                         └──────┬───────┘
                                ▼
                         ┌──────────────┐
                         │   backtest   │
                         └──────────────┘
```

**8 nodes. 1 LLM-driven routing decision. 1 fan-out parallelism point. 2 ToolLoopAgents (retrieval + adversarial Phase 2).**

### Pipeline Executor

The pipeline is a plain Python function (`sfewa/graph/pipeline.py`) using liteagent utilities:

```python
from liteagent import merge_state, run_parallel, ToolLoopAgent

ACC = {"evidence", "risk_factors", "adversarial_challenges", "backtest_events"}

def run_pipeline_v2(state: dict) -> dict:
    state = merge_state(state, init_case_node(state), accumulate=ACC)

    # Agentic retrieval (ToolLoopAgent decides what to search)
    state = merge_state(state, agentic_retrieval_node(state), accumulate=ACC)
    state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)

    # Parallel analyst fan-out
    for result in run_parallel(analysts, state, on_error=...):
        state = merge_state(state, result, accumulate=ACC)

    # Adversarial loop (3-phase: CoVe + verification search + refinement)
    for _ in range(MAX_ADVERSARIAL_PASSES):
        state = merge_state(state, adversarial_review_node(state), accumulate=ACC)
        if after_adversarial_review(state) == "risk_synthesis":
            break
        # Reanalyze: re-extract + re-run analysts
        ...

    state = merge_state(state, risk_synthesis_node(state), accumulate=ACC)
    state = merge_state(state, backtest_node(state), accumulate=ACC)
    return state
```

No graph compilation, no conditional edge DSL. The entire flow is visible in one function.

The agentic retrieval node wraps search functions as tools and runs a `ToolLoopAgent`:
- `search(query)`: DuckDuckGo text + news search
- `load_regulatory_filings()`: Discover jurisdiction and load official filings (EDINET for Japan, CNINFO for China)

The agent derives search queries from analysis dimensions (e.g., a dimension named `blade_battery_technology_moat` triggers searches for "Blade Battery technology" and industry benchmarks). It also searches for technology supply relationships between companies and their competitors, and gathers industry-level comparative data so analysts can assess whether a company is leading, keeping pace, or falling behind.

Safety bounds: 15 queries max, 150 docs max.

**Hybrid design**: Pipeline backbone stays debuggable (node-by-node execution, explicit state). Tool-loop agents are used inside specific nodes where autonomy adds value (search decisions in retrieval, verification search in adversarial). Both v1 (3-pass retrieval + quality gate loop) and v2 (agentic retrieval) coexist -- activated via `--agentic` CLI flag.

---

## 3. Node Contracts

Every node follows the same contract:

```python
def node_name(state: dict) -> dict:
    """Takes pipeline state, returns state updates (partial dict)."""
```

Nodes never mutate the input state directly. They return a dict of updates, which `merge_state()` applies. Accumulating fields (evidence, risk_factors, adversarial_challenges, backtest_events) are extended; all others are overwritten.

### Node Summary

| Node | Role | Mode | Key Inputs | Key Outputs |
|---|---|---|---|---|
| `init_case` | Planner | Non-thinking | Case config (3 fields) | Expanded regions, peers, case_id, **analysis_dimensions** |
| `agentic_retrieval` | Planner | Non-thinking (ToolLoopAgent) | Case context, **dimensions** | retrieved_docs (80-150 per run) |
| `evidence_extraction` | Planner | Non-thinking | retrieved_docs | evidence items (temporal-filtered, batched) |
| `industry_analyst` | Generator | Non-thinking | evidence, **dimensions** | risk_factors (LLM-generated external dimensions) |
| `company_analyst` | Generator | Non-thinking | evidence, **dimensions** | risk_factors (LLM-generated internal dimensions) |
| `peer_analyst` | Generator | Non-thinking | evidence, **dimensions** | risk_factors (LLM-generated comparative dimensions) |
| `adversarial_review` | Evaluator | Thinking + Tool-loop | risk_factors, evidence | adversarial_challenges, adversarial_recommendation |
| `risk_synthesis` | Synthesizer | Thinking | risk_factors, challenges, evidence | risk_score, risk_level, confidence, memo |
| `backtest` | Validator | Non-thinking | risk_factors, ground_truth_events | backtest_events |

**v1 additional nodes** (activated without `--agentic` flag): `retrieval` (3-pass), `quality_gate` (LLM-driven sufficiency check). These form a 4-node evidence loop that v2's agentic retrieval replaces.

**Thinking/non-thinking mode split**: Analysts need speed and clean JSON (non-thinking). Adversarial reviewer (Phase 1+3) and synthesis need deep reasoning chains (thinking mode). Phase 2 verification uses non-thinking mode for tool calling compatibility.

---

## 4. Analytical Framework: Iceberg Model

### Why a Framework Matters

Without structure, LLMs either produce shallow analysis ("company doing well → LOW") or go equally deep on everything (over-penalizing companies for trade-offs of their chosen strategy). The Iceberg Model provides **agentic depth routing** — the model decides HOW DEEP to go per dimension based on what it finds.

### 4-Layer Progressive Deepening

For EACH assigned dimension, analysts apply layers progressively, stopping when appropriate:

```
Layer 1 — EVIDENCE MAPPING (always required)
  What does the evidence LITERALLY say about this dimension?
  Separate company claims from external observations.
  Note evidence gaps.

Layer 2 — PATTERN RECOGNITION (always required)
  What TREND does the evidence reveal? Improving/worsening/stable?
  STEP-BACK: What does success vs failure typically look like
  for this type of strategic challenge?
  → BENIGN pattern: assign LOW severity. STOP. (2 layers)

  ── STRATEGY-RELATIVE DEPTH GATE ──
  Before Layer 3: Does this risk threaten the PRIMARY strategy?
  - PRIMARY strategy risk → Proceed to Layer 3.
  - SECONDARY domain trade-off → MEDIUM severity. STOP.

Layer 3 — STRUCTURAL ANALYSIS (concerning pattern + primary risk)
  Identify REINFORCING LOOPS (vicious cycles) and BALANCING LOOPS
  (stabilizing forces).
  COMPETING HYPOTHESES: Argue both risk case AND resilience case.
  → Balancing loops dominate: assign MEDIUM. STOP. (3 layers)
  → Reinforcing loops dominate: proceed to Layer 4.

Layer 4 — ASSUMPTION CHALLENGE (structurally reinforcing risks only)
  What ASSUMPTION must hold true for the strategy to work?
  PRE-MORTEM: Imagine it is 3 years from now and the strategy FAILED.
  What went wrong? Is there evidence the assumption is already failing?
  → Assign HIGH or CRITICAL. (4 layers)
```

### Severity Emerges from Depth

| Depth Reached | Severity | Meaning |
|---|---|---|
| Layer 2 | LOW | Benign pattern, company executing well |
| Depth Gate | MEDIUM | Secondary domain trade-off, not a primary strategy risk |
| Layer 3 | MEDIUM | Balancing forces dominate; concerning but manageable |
| Layer 4 | HIGH | Reinforcing loops + assumption under threat |
| Layer 4 | CRITICAL | Reinforcing loops + assumption ALREADY failing |

### Strategy-Relative Depth Gate

Prevents false HIGH ratings for companies being judged against strategies they didn't adopt:
- Hybrid-first company losing BEV market share → SECONDARY trade-off → MEDIUM
- Hybrid-first company losing HYBRID market share → PRIMARY risk → Layer 3-4
- BEV-committed company with mounting EV losses → PRIMARY risk → Layer 3-4

### Composite Frameworks

The Iceberg Model integrates techniques from multiple domains:

| Technique | Source | Applied At |
|---|---|---|
| Step-Back Prompting | Google DeepMind 2024 | Layer 2 (identify high-level principles) |
| Competing Hypotheses | Richards Heuer (CIA) | Layer 3 (risk case vs resilience case) |
| Causal Loop Analysis | Systems Thinking | Layer 3 (reinforcing vs balancing loops) |
| Pre-Mortem Analysis | Gary Klein (CIA) | Layer 4 (imagine failure, trace cause) |
| Chain of Verification | Meta AI, ACL 2024 | Adversarial review (4-step verification) |

### Depth as Cross-Company Differentiator

The depth distribution across companies reveals how the framework allocates analytical effort:

```
Honda:   ████████████████████████████████████████ 5×depth-3 + 5×depth-4   (ALL deep)
Toyota:  ██████████ ████████████ ████████████████ 3×depth-2 + 3×depth-3 + 4×depth-4  (mixed)
BYD:     ████████████████ ██████████████████ ████ 4×depth-2 + 5×depth-3 + 1×depth-4  (mostly shallow)
```

Honda's analysts found concerning patterns at EVERY dimension. Toyota's were mixed — shallow on secondary trade-offs, deep on primary risks. BYD's dimensions mostly stop early (market leader executing well).

---

## 5. The Independent Evaluator (Three-Phase Adversarial Review)

### Why Separation Matters

The most important architectural insight from Claude Code: **agents cannot reliably self-evaluate their own output.** SFEWA implements this through a structurally separated adversarial reviewer with three phases:

| Principle | Implementation |
|---|---|
| Structural separation | Separate node, thinking mode, different prompt |
| Never sees generator reasoning | Only sees risk factors + evidence, not analyst prompts |
| Objective criteria | Chain of Verification (4-step), 3-level severity grading |
| **Independent verification** | **Phase 2 searches the web for NEW counter-evidence** |
| Feedback loop | "reanalyze" -> back to extraction/analysts |
| Access to independent data | Sees ALL evidence + can find MORE via search |
| Depth-aware | HIGH factor with shallow analysis (no structural forces) → STRONG challenge |

### Three-Phase Architecture

```
Phase 1: Chain of Verification (thinking mode)
  Standard adversarial review — identify key claims, verify against
  available evidence, assess depth, grade challenges.
  Produces preliminary challenges + recommendation.

Phase 2: Independent Verification Search (ToolLoopAgent, non-thinking)
  Extracts key claims from HIGH/CRITICAL factors with non-STRONG
  challenges — the claims most worth independently verifying.
  ToolLoopAgent searches the web for COUNTER-EVIDENCE.
  Budget: 8 queries max. Runs text + news search per query.
  Only triggers when Phase 1 has verifiable claims.

Phase 3: Challenge Refinement (thinking mode)
  Reviews verification findings against Phase 1 challenges.
  Upgrades challenge severity to "strong" when web search found
  clear contradicting evidence. Keeps unverified challenges unchanged.
  Only triggers when Phase 2 finds relevant evidence.
```

**Conditional execution**: Phase 2+3 only run when Phase 1 identifies HIGH/CRITICAL factors with non-STRONG challenges. If all challenges are already STRONG (or all factors are LOW/MEDIUM), the node behaves exactly as the single-phase version.

### Phase 1: Chain of Verification (CoVe)

For EACH risk factor, the adversarial reviewer performs:

1. **IDENTIFY** the key claim that determines severity
2. **VERIFY** against ALL available evidence independently
3. **ASSESS** analytical depth (did analyst go deep enough for the severity assigned?)
4. **GRADE** the challenge (strong / moderate / weak)

### Phase 2: Independent Verification Search

The verification agent is a `ToolLoopAgent` with a single `search()` tool. It receives the key claims from Phase 1 and autonomously searches for contradicting evidence:

```python
claims = _extract_claims_to_verify(challenges, risk_factors, max_claims=5)
# Selects: HIGH/CRITICAL factors with non-STRONG challenges
# Prioritizes: critical before high, weak before moderate

agent = ToolLoopAgent(
    llm=llm,                    # non-thinking for tool calling
    tools=[search_tool],        # DuckDuckGo text + news
    system_prompt=...,          # "search for COUNTER-EVIDENCE"
    max_iterations=11,          # 8 queries + headroom
)
findings = agent.run("Begin searching...")
```

The search tool reuses `_search_web()` and `_search_news()` from the retrieval module, with its own DDGS instance and deduplication state.

### Phase 3: Challenge Refinement

A thinking-mode LLM receives the original challenges plus verification findings. Refinement rules:
- Verification found **contradicting** evidence → append finding to `challenge_text`, upgrade severity to `"strong"`
- Verification found **nothing** → severity unchanged
- Challenges **not covered** by verification (LOW/MEDIUM factors) → kept as-is

### The Downgrade Rule

> **Only downgrade a factor's severity if it received a STRONG adversarial challenge.** Moderate and weak challenges are noted but do NOT change severity.

STRONG challenges are applied programmatically in `risk_synthesis` (deterministic), not by LLM (non-deterministic). This ensures consistent downgrade behavior across runs.

### How It Behaves Per Company

Same 10 challenges for every company, but STRONG distribution differs due to independent verification:

| Company | STRONGs/run | Phases Run | Effect |
|---|---|---|---|
| Honda | 1-3 | 1+2+3 | Few downgrades → HIGH preserved |
| Toyota | 2-4 | 1+2+3 | Moderate downgrades → MEDIUM confirmed |
| BYD | 4-5 | 1+2+3 | Many downgrades → LOW enabled |

The verification search is the key differentiator: BYD's analyst claims (e.g., "domestic price war is unsustainable") are easily contradicted by web evidence of 34% profit growth. Honda's structural risks (e.g., $4.48B EV losses) are harder to contradict.

---

## 6. Dynamic Dimension Generation

### Why Dynamic

Hardcoded dimensions (e.g., `market_timing`, `policy_dependency`) are EV-specific and miss important factors for other industries. Dynamic generation works for any company and strategy.

### How It Works

The `init_case` node uses the LLM to generate 9-12 analysis dimensions organized into 3 analyst perspectives:

| Perspective | Analyst | Example Dimensions (Honda) |
|---|---|---|
| **External** | Industry Analyst | china_ev_policy_volatility, global_battery_supply_chain_concentration, regulatory_hybrid_phaseout_timeline |
| **Internal** | Company Analyst | 0_series_platform_architecture_risk, software_talent_acquisition_gap, hybrid_cannibalization_vs_funding, joint_venture_alignment_friction |
| **Comparative** | Peer Analyst | battery_technology_gap_analysis, charging_ecosystem_partnership_leverage, brand_perception_ev_premium |

Each dimension includes:
- **name**: snake_case identifier
- **description**: What to analyze, what data to look for
- **structural_hint**: What structural forces might drive risk (guides Layer 3)
- **critical_assumption**: What assumption the strategy depends on (guides Layer 4)

Analysts fall back to hardcoded EV dimensions if dynamic dimensions are not available.

---

## 7. Evidence Retrieval

### Regulatory Filing Discovery

Before web search begins, the pipeline discovers and loads official regulatory filings based on the company's jurisdiction (`sfewa/tools/filing_discovery.py`):

```
1. Identify jurisdiction from company name + case regions
   Honda Motor Co. → Japan, BYD Company Limited → China

2. Search the filing system for the company
   Japan → EDINET API (scan filing dates, match by filer name)
   China → CNINFO API (discover orgId from stock list, search by category)

3. Find key filings before cutoff
   Annual report, semi-annual report, extraordinary reports

4. Download PDFs to local cache (data/corpus/{company}/{system}/)
   Cached files are reused across runs — download only once

5. Extract text, filter for strategy-relevant pages, chunk
   Annual reports (200+ pages): keyword-filtered for relevant sections
   Smaller reports: full text extraction
```

**Jurisdiction support**:
- **Japan → EDINET** (FSA Electronic Disclosure): Scan filing dates in June/November windows, match by Japanese filer name, download via document API. Supports Honda, Toyota, and other Japanese companies.
- **China → CNINFO** (巨潮资讯网, Shenzhen Securities Information): Discover company orgId from stock list (matches by Chinese name or pinyin), search annual + semi-annual reports by category, download PDFs. Supports BYD and other A-share companies.

**Fully agentic discovery**: No company codes are hardcoded. Given only a company name, the system identifies jurisdiction from name patterns, discovers the company's identifier via the filing system's API, finds key filings before cutoff, and loads them. The same `discover_and_load_filings()` function works for any supported jurisdiction.

**Caching**: Downloaded PDFs persist in `data/corpus/{company}/{system}/` (e.g., `data/corpus/honda/edinet/`, `data/corpus/byd/cninfo/`). On subsequent runs, cached files are loaded directly without API calls. This makes demo runs fast while keeping the discovery process fully agentic for new companies.

### Three-Pass Retrieval (v1)

The v1 retrieval agent (`sfewa/agents/retrieval.py`) performs autonomous multi-pass information gathering:

```
Pass 1: Seed Search
  Regulatory filings loaded via filing discovery (if jurisdiction supported)
  LLM generates up to 15 search queries from case context
  + site-specific archival queries (Reuters, Bloomberg, FT, etc.)
  DuckDuckGo text + news search (both run per query)

Pass 2: Gap Analysis
  LLM analyzes retrieved docs
  Identifies missing dimensions, regions, perspectives
  Generates targeted follow-up queries

Pass 3: Counternarrative
  LLM reads company claims from Pass 1-2 evidence
  Generates queries seeking challenging/contradicting evidence
  Prevents confirmation bias in the evidence base
```

**Follow-up mode**: When the quality gate routes back to retrieval, the three-pass flow is skipped entirely. Only the gate's `follow_up_queries` are run as direct web searches to fill specific gaps.

### Agentic Retrieval (v2)

The v2 agentic retrieval agent has `load_regulatory_filings()` as a tool alongside `search()`. The agent decides when to call each tool based on its assessment of evidence coverage.

**Coverage targets** (9 criteria the agent self-evaluates against):
1. Company strategic plans + financial results
2. Financial performance indicators
3. Competitive landscape (2+ named competitors)
4. Market/industry trends
5. Regional data (2+ geographic markets)
6. Policy/regulatory environment
7. Technology capability + competitive positioning (proprietary tech, vertical integration, industry benchmarks — is the company leading, keeping pace, or falling behind?)
8. Both supporting AND contradicting signals
9. Forward-looking content (forecasts, roadmaps)

**Dimension-driven search**: The agent derives search queries from its analysis dimensions. For technology-related dimensions, it searches for both the company's own capabilities AND industry benchmarks/comparative data. This is domain-agnostic — the same mechanism works for EV battery technology, cloud infrastructure, pharmaceutical R&D pipelines, or any other strategy.

**Temporal integrity**: All prompts include `Do NOT use knowledge about events after {cutoff_date}`. The temporal filter hard-rejects documents published after the cutoff.

---

## 8. Risk Scoring

### Continuous Score (0-100)

Replaces discrete HIGH/MEDIUM/LOW to eliminate boundary effects. Two-stage computation:

**Stage 1 -- Programmatic base score** (deterministic):
```python
SEVERITY_POINTS = {"critical": 25, "high": 15, "medium": 8, "low": 2}
# STRONG adversarial challenges downgrade severity one level
DOWNGRADE = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}

# Apply downgrades, compute points, normalize against HIGH (15) as denominator
base_score = round(total_points / (15 * num_factors) * 100)
```

**Stage 2 -- LLM qualitative adjustment** (thinking mode):
- Causal loop analysis: count reinforcing vs balancing loops across all factors
  - REINFORCING pattern (+5 to +10): risks compound through shared mechanisms
  - MIXED pattern (+0): roughly balanced
  - SCATTERED pattern (-5 to -10): independent concerns, no shared cause
- Strategy-relative assessment (is the company being judged against a strategy it didn't adopt?)
- Executed mitigations (current revenue/profit) vs announced plans (future products)
- Pre-mortem check: "if this assessment is completely wrong, what's the blind spot?"

**Score bands** (derived from score, not vice versa):
- 80-100: CRITICAL
- 60-79: HIGH
- 40-59: MEDIUM
- 0-39: LOW

Note: The synthesis prompt uses a 5-band scale (including 0-19 MINIMAL) as a calibration anchor for the LLM, but the code maps all scores below 40 to "low".

---

## 9. State Management

### PipelineState

State flows as a plain `dict` through the pipeline. `PipelineState` (TypedDict) documents the expected fields:

**Case config fields** (set at init, read-only):
- `company`, `strategy_theme`, `cutoff_date`, `case_id`, `regions`, `peers`, `ground_truth_events`

**Generated fields** (set by init_case):
- `analysis_dimensions` -- LLM-generated dimensions per analyst perspective

**Accumulating fields** (grow across nodes via `merge_state(accumulate=...)`):
- `evidence` -- list of evidence item dicts
- `risk_factors` -- list of risk factor dicts (includes `depth_of_analysis`, `structural_forces`, `key_assumption_at_risk`)
- `adversarial_challenges` -- list of challenge dicts (includes `key_claim_tested`, `verification_result`)
- `backtest_events` -- list of backtest match dicts

**Overwriting fields** (latest value wins):
- `retrieved_docs`, `risk_score`, `overall_risk_level`, `overall_confidence`, `risk_memo`, `backtest_summary`

**Routing fields** (set by one node, read by routing functions):
- `evidence_sufficient` -- quality gate decision
- `follow_up_queries` -- targeted queries for retrieval follow-up
- `adversarial_recommendation` -- "proceed" or "reanalyze"

**Loop counters** (safety bounds):
- `iteration_count` -- quality gate loop counter (max 3)
- `adversarial_pass_count` -- adversarial loop counter (max 2)

### Deduplication

When loops cause re-execution, accumulating fields grow with duplicates. The pattern:

```python
from liteagent import dedup_by_key
# Keep latest risk factor per dimension
factors = dedup_by_key(state["risk_factors"], "dimension")
```

Applied in: adversarial review, risk synthesis, backtest, artifact saving.

---

## 10. Cross-Cutting Concerns

### Temporal Integrity (enforced at 3 levels)

1. **Retrieval**: `published_at > cutoff_date` -> hard reject in temporal filter
2. **Extraction**: temporal filter on evidence items, fiscal year validation
3. **Prompts**: "Do NOT use knowledge about events after {cutoff_date}" in all prompt templates

### Pipeline Context Injection

Each downstream node receives a summary of upstream pipeline history via `build_pipeline_context()`:

```
PIPELINE CONTEXT (what has happened so far):
- Retrieved 138 documents (23 edinet, 58 duckduckgo, 31 gap_fill, 26 counter)
- Extracted 29 evidence items (stance: 10 supports, 5 contradicts, 14 neutral)
- Quality gate: evidence sufficient (iteration 3)
```

This enables synthesis to adjust confidence based on evidence quality, and adversarial to factor in retrieval coverage.

### LLM-Driven Routing

Routing decisions are made by the LLM, not hardcoded thresholds:

**Agentic retrieval** (v2): The ToolLoopAgent self-assesses evidence coverage against 9 criteria and stops when satisfied. No separate quality gate needed — the agent's stop decision replaces the v1 quality gate loop.

**Quality gate** (v1 only, `route_after_quality_gate`): LLM evaluates evidence sufficiency (count, stance balance, source diversity, dimension coverage). Sets `evidence_sufficient` in state. Routing function reads it and returns `"fan_out"` or `"retrieval"`.

**Adversarial review** (`after_adversarial_review`): LLM recommends `"proceed"` or `"reanalyze"`. Routing function reads `adversarial_recommendation` from state.

Dead-loop counters (`MAX_ADVERSARIAL_PASSES=2`) are safety bounds only -- the LLM makes the actual decision.

### Observability

- **Runtime reporting**: Rich console output via `sfewa/reporting.py` (enter/log/exit per node). Dual-write: all events also persisted to CallLog.
- **Call logging**: All LLM calls, tool calls, and pipeline events recorded via `liteagent.CallLog`, saved as `llm_history.jsonl`
- **Pipeline events**: `PipelineEventRecord` captures node entry/exit, routing decisions, parallel fan-out, and actions. ~80 events per run interleaved with LLM/tool records. Enables flow graph reconstruction.
- **Artifacts**: Evidence, risk factors, challenges, backtest, memo, and run summary saved to `outputs/{case_id}_{timestamp}/`

---

## 11. What Makes This Agentic (Not Just a Pipeline)

| Dimension | Static Pipeline | SFEWA (Agentic) |
|---|---|---|
| Analysis dimensions | Hardcoded ontology | LLM generates dimensions from case context |
| Filing sources | Hardcoded per company | Jurisdiction discovery: company → country → filing system → company ID → filings |
| Search queries | Config-defined topics | Agent derives queries from dimensions + case context |
| Technology coverage | No tech-specific search | Agent reads dimension names, searches for company tech + industry benchmarks + competitive positioning |
| Evidence sufficiency | Fixed threshold (e.g., >10 items) | Agent self-assesses coverage against 9 criteria, stops when satisfied |
| **Analysis depth** | **Same depth for every dimension** | **Iceberg Model: LLM decides depth (2-4 layers) per dimension** |
| Adversarial verification | Review available evidence only | Phase 2 ToolLoopAgent independently searches web for counter-evidence |
| Severity calibration | Fixed rules | Emerges from analytical depth + structural forces |
| Risk scoring | Categorical labels | Programmatic base + LLM causal loop analysis (0-100) |
| Context awareness | Each node isolated | Pipeline context injected -- downstream knows upstream history |

10+ autonomous decisions per run that alter behavior. Different companies trigger different paths and different analytical depths through the same architecture.

---

## 12. Package Structure

```
src/sfewa/
  main.py                 CLI entry point (Typer)
  llm.py                  LLM factory (wraps liteagent.LLMClient)
  context.py              Domain-specific pipeline context builder
  reporting.py             Rich console reporter

  graph/
    pipeline.py           Pipeline executor (uses liteagent.merge_state, run_parallel)
    routing.py            LLM-driven routing functions + dead-loop constants

  agents/
    init_case.py          Case expansion (LLM generates regions, peers, dimensions)
    retrieval.py          3-pass agentic retrieval (DDGS + EDINET) [v1]
    agentic_retrieval.py  Tool-loop agent retrieval (ToolLoopAgent) [v2]
    evidence_extraction.py  LLM extraction + temporal filter (batched for large inputs)
    quality_gate.py       Evidence sufficiency gate (LLM-driven) [v1 only]
    _analyst_base.py      Shared analyst implementation (Iceberg Model validation)
    industry_analyst.py   External dimensions (dynamic or fallback)
    company_analyst.py    Internal dimensions (dynamic or fallback)
    peer_analyst.py       Comparative dimensions (dynamic or fallback)
    adversarial.py        Independent evaluator (thinking mode, Chain of Verification)
    risk_synthesis.py     Programmatic + LLM scoring (causal loop analysis)
    backtest.py           Ground truth matching

  prompts/
    init_case.py          Case expansion + dimension generation prompts
    retrieval.py          Seed, gap analysis, counternarrative prompts [v1]
    agentic_retrieval.py  Tool-loop agent system prompt + coverage criteria [v2]
    extraction.py         Evidence extraction + stance guidance
    analysis.py           Iceberg Model framework, dimension defs, scope boundaries
    adversarial.py        Chain of Verification, severity grading
    synthesis.py          Scoring guidelines, calibration anchors, pre-mortem

  schemas/
    config.py             CaseConfig, GroundTruthEvent (Pydantic)
    state.py              PipelineState (TypedDict)
    evidence.py           EvidenceItem, RiskFactor, AdversarialChallenge, BacktestEvent

  tools/
    chat_log.py           Wrapper around liteagent.CallLog
    artifacts.py          File-based artifact saving
    filing_discovery.py   Jurisdiction detection + filing discovery + loading
    cninfo.py             CNINFO API client (China A-share filings)
    corpus_loader.py      Legacy EDINET PDF loader (used by filing_discovery)
    edinet.py             EDINET API client (Japan FSA filings)
    temporal_filter.py    Date comparison utilities
```

### Dependencies

SFEWA depends on `liteagent` for generic agent patterns and adds domain-specific dependencies:

| Dependency | Purpose |
|---|---|
| `liteagent` | LLM client, pipeline utilities, state helpers, parsing, observability |
| `openai` | OpenAI-compatible API (via liteagent) |
| `pydantic` | Schema definitions (CaseConfig, evidence models) |
| `pyyaml` | Case config loading |
| `python-dotenv` | `.env` file loading (LLM endpoint, API keys) |
| `ddgs` | DuckDuckGo web + news search |
| `pdfplumber` | EDINET PDF text extraction |
| `pypdf` | PDF parsing fallback |
| `beautifulsoup4` | HTML content extraction |
| `httpx` | EDINET API HTTP client |
| `rich` | Terminal reporting |
| `typer` | CLI interface |

---

## 13. Event Alignment: AI Tinkerers HK (April 29, 2026)

### Capability Checklist

| Event Wants | SFEWA Delivers | Strength |
|---|---|---|
| **LLM orchestration** | Plain Python pipeline, 10 nodes, parallel fan-out, 2 LLM-driven loops | STRONG |
| **Tool-calling** | DuckDuckGo + EDINET + CNINFO + temporal filter | STRONG |
| **State management** | `merge_state()` with explicit accumulation, `dedup_by_key()` | STRONG |
| **Multi-step reasoning loops** | Quality gate + adversarial loop (both LLM-driven) | STRONG |
| **Analytical framework** | Iceberg Model with 4-layer progressive deepening + Chain of Verification | STRONG |
| **Systems that take action** | Fully autonomous: retrieve -> analyze -> challenge -> synthesize -> backtest | STRONG |
| **Code over decks** | Terminal output, Rich reporting, JSON artifacts | STRONG |
| **Framework-free design** | No LangChain/LangGraph -- plain Python + liteagent utilities | STRONG |

### Recommended Demo Narrative

**Min 0-1**: Hook -- "Honda wrote down 2.5T yen in March 2026. Could agents have seen it coming?"

**Min 1-4**: Architecture -- Show `run_pipeline()` function. "No framework, no graph DSL. Planner decides what to search, Generator runs 3 parallel analysts with the Iceberg Model, Evaluator challenges every conclusion via Chain of Verification."

**Min 4-6**: Live trace -- Agentic retrieval deriving queries from dimensions, analysts producing depth profiles (Layer 2-4), adversarial reviewer Phase 2 searching for counter-evidence.

**Min 6-8**: Cross-company proof -- Same pipeline, same model: Honda ~90/100 (CRITICAL), Toyota ~58/100 (MEDIUM), BYD ~42/100 (MEDIUM-LOW). Show depth distributions and STRONG challenge counts.

**Min 8-9**: Backtest -- Honda 3x STRONG matches on target revision, EV cancellation, and Afeela restructuring.

**Min 9-10**: Honest failures -- Temporal leakage, structured output reliability, run variability. Invite discussion.
