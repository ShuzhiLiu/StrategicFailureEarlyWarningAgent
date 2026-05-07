# SFEWA Architecture

How SFEWA's multi-agent pipeline produces differentiated risk assessments through autonomous exploration, independent evaluation, evidence-driven reasoning, and an audit envelope that makes every run self-verifiable.

For the underlying framework design, see [liteagent Architecture](liteagent_architecture.md).

---

## 1. System Overview

SFEWA is a Planner-Generator-Evaluator system for strategic-failure early warning on public companies. Given a company and a temporal cutoff (and optionally a strategy theme — auto-discovered if omitted), it autonomously retrieves evidence, produces risk assessments from three specialist perspectives using the Iceberg Model analytical framework, challenges those assessments adversarially via Chain of Verification, and synthesizes a continuous risk score (0-100). The audit envelope wraps the result with proofs that no post-cutoff information leaked, every claim traces back to a source document, and the run is fully reproducible.

```
┌──────────────────────────────────────────────────────────────────┐
│                SFEWA: Planner-Generator-Evaluator                │
│                                                                  │
│  PLANNER: Autonomous Information Gathering                       │
│    strategy_discovery (optional — runs when theme omitted)       │
│    init_case (LLM generates dimensions, regions, peers)          │
│    agentic_retrieval (ToolLoopAgent: search + filings)           │
│    → evidence_extraction (batched, temporal-filtered)            │
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
│           — gated by verifier_corpus on retrospective cases      │
│    Phase 3: Challenge refinement (thinking mode)                 │
│                                                                  │
│  SYNTHESIZER + VALIDATOR                                         │
│    risk_synthesis (programmatic base + causal loop + pre-mortem) │
│    backtest                                                      │
│                                                                  │
│  AUDIT ENVELOPE:                                                 │
│    source_manifest.json   per-doc kept/rejected decisions        │
│    citation_check         every claim → resolvable evidence      │
│    sentence_citations     per-sentence span resolution (L2)      │
│    provenance.json        model + commit + sha + tokens          │
│    case/truth split       physical separation, sentinel test     │
│    report.html            three-pillar static audit report       │
│                                                                  │
│  Cross-cutting: Pipeline Context Injection, Dead-Loop            │
│  Protection, Temporal Integrity (4 layers), File-Based Trail     │
└──────────────────────────────────────────────────────────────────┘
```

### How SFEWA Maps to Claude Code's P-G-E

| P-G-E Role | Claude Code (General) | SFEWA (Domain-Specific) |
|---|---|---|
| **Planner** | Expands prompts into specs; decides scope | init_case (LLM generates dimensions) + agentic_retrieval (ToolLoopAgent with dimension-driven search) + evidence_extraction |
| **Generator** | Implements code in sprints | 3 parallel analysts with Iceberg Model framework produce risk factors with progressive depth analysis |
| **Evaluator** | Playwright E2E tests + separate agent grading | Adversarial reviewer (thinking mode, Chain of Verification, 3-level severity) |
| **Sprint contracts** | Generator+Evaluator negotiate criteria | LLM-generated dimensions with structural hints and critical assumptions |
| **Feedback loop** | Failed eval → Generator retries | "reanalyze" recommendation → back to extraction/analysts |

**The critical shared insight**: "Tuning a dedicated evaluator to be skeptical is far more tractable than making a generator self-critical."

### What SFEWA Has Beyond P-G-E

- **Temporal integrity** — Hard cutoff enforcement at retrieval, extraction, prompts, AND verifier corpus. Equivalent to Claude Code's security tools, but for time rather than safety. See §10.
- **Multi-expert fan-out** — Genuine parallel execution via `liteagent.run_parallel()` with `ThreadPoolExecutor`. 3 analysts run concurrently with isolated state copies.
- **Backtest validation** — Domain-specific ground truth testing. Claude Code uses Playwright; SFEWA matches predictions against real-world events from a separate truth file.
- **Agentic depth routing** — The Iceberg Model framework lets analysts decide HOW DEEP to go per dimension. Benign patterns stop at Layer 2 (LOW); structural risks go to Layer 4 (HIGH/CRITICAL).
- **Audit envelope (L1)** — Every run emits machine-checkable evidence of its own correctness: source manifest, citation resolution, provenance header, HTML report. See §9.

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
                         │  peer_filings (optional, opt-in)     │
                         │  Same FilingProvider Protocol on each│
                         │  peer; capped 3 peers × 6 chunks.    │
                         │  Default OFF. Enable per run via     │
                         │  --enable-peer-filings.              │
                         └──────┬───────────────────────────────┘
                                ▼
                         ┌──────────────────────────────────────┐
                         │  agentic_retrieval (ToolLoopAgent)   │
                         │  Tools: search() + load_filings()    │
                         │  Agent decides queries from dims,    │
                         │  assesses coverage, stops when ready │
                         │  → emits source_manifest entries     │
                         │  (seeds peer_filings into corpus)    │
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
                         └──────┬───────┘
                                ▼
                         ┌─────────────────────────────────────┐
                         │  artifact save (L1 audit envelope)  │
                         │  source_manifest.json + provenance  │
                         │  + risk_factors + evidence + memo   │
                         │  + run_summary (audit_violations)   │
                         │  + report.html                      │
                         └─────────────────────────────────────┘
```

**8 nodes. 1 LLM-driven routing decision. 1 fan-out parallelism point. 2 ToolLoopAgents (retrieval + adversarial Phase 2).**

### Pipeline Executor

The pipeline is a plain Python function (`sfewa/graph/pipeline.py`) using liteagent utilities:

```python
from liteagent import merge_state, run_parallel, ToolLoopAgent

ACC = {"evidence", "risk_factors", "adversarial_challenges", "backtest_events"}

def run_pipeline_v2(state: dict) -> dict:
    state = merge_state(state, init_case_node(state), accumulate=ACC)
    state = merge_state(state, agentic_retrieval_node(state), accumulate=ACC)
    state = merge_state(state, evidence_extraction_node(state), accumulate=ACC)

    for result in run_parallel(analysts, state, on_error=...):
        state = merge_state(state, result, accumulate=ACC)

    for _ in range(MAX_ADVERSARIAL_PASSES):
        state = merge_state(state, adversarial_review_node(state), accumulate=ACC)
        if after_adversarial_review(state) == "risk_synthesis":
            break
        # reanalyze: re-extract + re-run analysts

    state = merge_state(state, risk_synthesis_node(state), accumulate=ACC)
    state = merge_state(state, backtest_node(state), accumulate=ACC)
    return state
```

No graph compilation, no conditional edge DSL. The entire flow is visible in one function.

### Hybrid Design (v1 vs v2)

Both pipelines coexist:
- **v1** (`run_pipeline`): 10 nodes including a 3-pass retrieval and a separate quality_gate loop. Default behavior.
- **v2** (`run_pipeline_v2`): 8 nodes; the agentic retrieval ToolLoopAgent self-assesses coverage and replaces the quality-gate loop. Activated via `--agentic` CLI flag (the canonical path post-iter 33).

Pipeline backbone stays debuggable (node-by-node execution, explicit state). Tool-loop agents are used inside specific nodes where autonomy adds value (search decisions in retrieval, verification search in adversarial).

Safety bounds: 15 search queries max, 150 docs max for the retrieval agent.

---

## 3. State Management

### PipelineState

State flows as a plain `dict` through the pipeline. `PipelineState` (TypedDict in `sfewa/schemas/state.py`) documents the expected fields.

**Case config fields** (set at init by `main.build_initial_state_from_case()` via `load_case_and_truth()`):
- `case_id`, `company`, `strategy_theme`, `cutoff_date`, `regions`, `peers`
- `case_type` — `"retrospective"` (truth file required) or `"forward"` (truth file forbidden)
- `audit_meta` — `{"jurisdiction", "ticker", "allowed_sources", "doc_types", "verifier_corpus"}` from the case YAML; threaded into agents that need it (filing discovery, adversarial verifier)
- `ground_truth_events` — loaded ONLY from `configs/truth/{case_id}.yaml`, NEVER from the case YAML. Read by the backtest path; static + runtime sentinel tests guard against leakage into agent-visible prompts. See §9 for the full split.

**Generated** (set by init_case):
- `analysis_dimensions` — LLM-generated dimensions per analyst perspective

**Accumulating** (extended via `merge_state(accumulate=...)` across nodes):
- `evidence` — list of evidence item dicts
- `risk_factors` — list of risk factor dicts (includes `depth_of_analysis`, `structural_forces`, `key_assumption_at_risk`, Toulmin fields: `claim`, `warrant`, `strongest_counter`)
- `adversarial_challenges` — list of challenge dicts (includes `key_claim_tested`, `verification_result`)
- `backtest_events` — list of backtest match dicts

**Computed after fan-out**:
- `analyst_agreement` — cross-analyst consistency metrics (HHI severity concentration, ordinal range, depth spread, summary text)

**Overwriting** (latest value wins):
- `retrieved_docs`, `risk_score`, `overall_risk_level`, `overall_confidence`, `risk_memo`, `backtest_summary`
- `source_manifest` — doc-level audit log built by the retrieval node; saved as `source_manifest.json` (see §9)

**Routing** (set by one node, read by routing functions):
- `evidence_sufficient` (v1 quality gate decision), `follow_up_queries`, `adversarial_recommendation`

**Loop counters** (safety bounds): `iteration_count` (max 3), `adversarial_pass_count` (max 2)

### Deduplication Pattern

When loops cause re-execution, accumulating fields grow with duplicates. The standard pattern uses `liteagent.dedup_by_key`:

```python
factors = dedup_by_key(state["risk_factors"], "dimension")
```

Applied in: adversarial review, risk synthesis, backtest, artifact saving.

---

## 4. Node Contracts

Every node follows the same contract:

```python
def node_name(state: dict) -> dict:
    """Takes pipeline state, returns state updates (partial dict)."""
```

Nodes never mutate the input state directly. They return a dict of updates, which `merge_state()` applies. Accumulating fields are extended; all others are overwritten.

### Node Summary

| Node | Role | Mode | Key Inputs | Key Outputs |
|---|---|---|---|---|
| `init_case` | Planner | Non-thinking | Case config | regions, peers, case_id, **analysis_dimensions** |
| `peer_filings` (optional) | Planner | None (Protocol-only) | peers, audit_meta | **peer_filings** (Tier-1 chunks from each resolved peer; opt-in via `audit_meta.fetch_peer_filings` or `--enable-peer-filings`) |
| `agentic_retrieval` | Planner | Non-thinking (ToolLoopAgent) | Case context, dimensions, peer_filings | retrieved_docs, **source_manifest** |
| `evidence_extraction` | Planner | Non-thinking | retrieved_docs | evidence (temporal-filtered, batched) |
| `industry_analyst` | Generator | Non-thinking (N=3 self-consistency) | evidence, dimensions | risk_factors (LLM-generated external dimensions, Toulmin-structured) |
| `company_analyst` | Generator | Non-thinking (N=3 self-consistency) | evidence, dimensions | risk_factors (internal dimensions) |
| `peer_analyst` | Generator | Non-thinking (N=3 self-consistency) | evidence, dimensions | risk_factors (comparative dimensions) |
| `adversarial_review` | Evaluator | Thinking + Tool-loop | risk_factors, evidence | adversarial_challenges, adversarial_recommendation |
| `risk_synthesis` | Synthesizer | Thinking | risk_factors, challenges, evidence | risk_score, risk_level, confidence, memo |
| `backtest` | Validator | Non-thinking | risk_factors, ground_truth_events | backtest_events |

**v1 adds**: `retrieval` (3-pass), `quality_gate` (LLM-driven sufficiency check) — replaced by v2's agentic retrieval.

**Thinking/non-thinking split**: Analysts need speed and clean JSON (non-thinking). Adversarial Phase 1+3 and synthesis need deep reasoning chains (thinking). Phase 2 verification uses non-thinking for tool-calling compatibility.

### Dynamic Dimension Generation (init_case detail)

Hardcoded dimensions (e.g., `market_timing`, `policy_dependency`) are EV-specific and miss important factors for other industries. `init_case` uses the LLM to generate 9-12 dimensions tailored to the case, organized into three analyst perspectives:

| Perspective | Analyst | Example Dimensions (Honda EV case) |
|---|---|---|
| **External** | Industry | `china_ev_policy_volatility`, `global_battery_supply_chain_concentration`, `regulatory_hybrid_phaseout_timeline` |
| **Internal** | Company | `0_series_platform_architecture_risk`, `software_talent_acquisition_gap`, `joint_venture_alignment_friction` |
| **Comparative** | Peer | `battery_technology_gap_analysis`, `charging_ecosystem_partnership_leverage`, `brand_perception_ev_premium` |

Each dimension carries: `name` (snake_case), `description`, `structural_hint` (drives Layer 3 reasoning), `critical_assumption` (drives Layer 4 reasoning). Analysts fall back to hardcoded EV dimensions if dynamic generation fails.

---

## 5. Evidence Retrieval

### Regulatory Filing Discovery

Before web search begins, the pipeline discovers and loads official regulatory filings based on the company's jurisdiction. Four jurisdictions sit behind a uniform `FilingProvider` Protocol (`sfewa/tools/filing_provider.py`):

```
1. Identify jurisdiction from company name + regions + explicit case.jurisdiction
   Honda Motor Co.    → Japan
   BYD Company Ltd.   → China
   Country Garden     → Hong Kong  (explicit jurisdiction wins over name patterns)
   The Boeing Company → United States  (resolved via case.ticker = "BA")

2. Dispatch to the appropriate FilingProvider:
   Japan          → EdinetProvider     (FSA Electronic Disclosure)
   China          → CninfoProvider     (巨潮资讯网, A-share market)
   Hong Kong      → HkexProvider       (HKEXnews via DDG site search + URL auto-promotion)
   United States  → SecEdgarProvider   (SEC EDGAR JSON API)

3. Each provider implements four methods:
   search()                discover filings matching ticker/date/type/language
   download()              fetch PDF/HTML to local cache
   extract()               parse to ExtractedDocument (full text +
                           page-anchored EvidenceChunks with global +
                           page-local char offsets)
   emit_manifest_entry()   produce one row of source_manifest.json with
                           the cutoff_decision (kept | rejected_post_cutoff
                           | rejected_doc_type | rejected_language)

4. Cache layout:
   data/corpus/{company}/{system}/{filename}.pdf
   On subsequent runs, cached files load directly without API calls.
```

The `FilingProvider` Protocol abstraction is the value-add — it lets EDINET, CNINFO, HKEX, and SEC EDGAR drop into the pipeline behind one interface, and the audit primitives (manifest, claim citation, provenance) operate uniformly across jurisdictions. Each adapter is intentionally *thin* — it wraps the legacy per-system module without deep refactoring.

### Jurisdiction Status

| System | Status | Discovery | Notes |
|---|---|---|---|
| EDINET (JP) | ✅ live | Scan filing dates in June/Nov windows, match by Japanese filer name, download via document API | Used live for Honda, Toyota |
| CNINFO (CN) | ✅ live | orgId from active stock list (Chinese name or pinyin match), search annual + semi-annual by category | Used live for BYD |
| HKEXnews (HK) | ✅ live | DDG `site:hkexnews.hk filetype:pdf` queries surface the direct PDF URL pattern, which is publicly downloadable. URLs the agent surfaces during normal search are also auto-promoted to Tier-1 evidence. **Iter 44 broadened the query set** with doc-type variants (annual report, interim report, annual results, interim results, results announcement) × year × ticker-anchored queries; aggregates across the full query list rather than stopping at first hit. Optional Playwright fallback for cases DDG hasn't indexed. | Used live for Country Garden (10 filings, 92 CRITICAL), AIA (12 filings, forward case via broadened queries), HSBC (1 filing — per-issuer DDG indexing varies). |
| SEC EDGAR (US) | ✅ live | Ticker → CIK via `company_tickers.json`, walk `submissions/` feed, filter by date + form type (10-K → annual_report, 10-Q → interim_report, 8-K → inside_information, DEF 14A → circulars). Free JSON API, no auth. | Used live for Boeing (8 filings, 76 HIGH) |

### Page-Anchored EvidenceChunks

Every filing chunk records both:
- `global_char_start` / `global_char_end` — offsets within the full document text (always present; round-trip invariant: `text[start:end] == chunk.text`)
- `page` + `page_char_start` / `page_char_end` — offsets within a specific PDF page (when page metadata is available)

This dual-offset design lets two UI surfaces work without retrofit: PDF page view (page-local) vs full-text HTML highlight (global). The L1 claim-citation invariant only requires global offsets resolve; sentence-level citation against page-local offsets is L2.

### Three-Pass Retrieval (v1)

The v1 retrieval agent (`sfewa/agents/retrieval.py`) performs autonomous multi-pass information gathering:

```
Pass 1 — Seed Search
  Regulatory filings loaded via filing discovery.
  LLM generates up to 15 search queries from case context
  + site-specific archival queries (Reuters, Bloomberg, FT, etc.)
  DuckDuckGo text + news search per query.

Pass 2 — Gap Analysis
  LLM analyzes retrieved docs, identifies missing dimensions/regions.
  Generates targeted follow-up queries.

Pass 3 — Counternarrative
  LLM reads company claims from Pass 1-2 evidence.
  Generates queries seeking contradicting evidence.
  Prevents confirmation bias in the evidence base.
```

When the v1 quality gate routes back to retrieval, the three-pass flow is skipped — only the gate's `follow_up_queries` are run.

### Agentic Retrieval (v2)

The v2 agentic retrieval agent has `load_regulatory_filings()` and `search()` as tools. The agent decides when to call each based on its own assessment of coverage.

**Coverage targets** (9 criteria the agent self-evaluates against):
1. Company strategic plans + financial results
2. Financial performance indicators
3. Competitive landscape (2+ named competitors)
4. Market/industry trends
5. Regional data (2+ geographic markets)
6. Policy/regulatory environment
7. Technology capability + competitive positioning (proprietary tech, vertical integration, industry benchmarks)
8. Both supporting AND contradicting signals
9. Forward-looking content (forecasts, roadmaps)

**Dimension-driven search**: The agent derives queries from its analysis dimensions. For technology dimensions, it searches both the company's own capabilities AND industry benchmarks. Domain-agnostic — works for EV battery tech, cloud infrastructure, pharma R&D, etc.

**Temporal integrity at retrieval**: prompts include `Do NOT use knowledge about events after {cutoff_date}`; the temporal filter hard-rejects post-cutoff documents. See §10.

---

## 6. Analytical Framework: Iceberg Model

### Why a Framework Matters

Without structure, LLMs either produce shallow analysis ("company doing well → LOW") or go equally deep on everything (over-penalizing trade-offs of a chosen strategy). The Iceberg Model provides **agentic depth routing** — the model decides HOW DEEP to go per dimension based on what it finds.

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
  PRE-MORTEM: Imagine 3 years from now and the strategy FAILED.
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

### Programmatic Depth-Severity Enforcement

The Iceberg Model is prompt-driven (analysts decide depth), but consistency is verified programmatically via `check_depth_consistency()` in `_analyst_base.py`. Violations are injected as flags into the adversarial prompt:

| Check | Flag | Trigger |
|---|---|---|
| Depth ≤ 2 but severity HIGH/CRITICAL | `[DEPTH_SEVERITY_MISMATCH]` | Layer 2 analysis should not produce HIGH+ |
| Depth ≥ 4 but no `key_assumption_at_risk` | `[MISSING_ASSUMPTION]` | Layer 4 requires pre-mortem assumption challenge |
| Depth ≥ 3 but no structural forces | `[MISSING_FORCES]` | Layer 3 requires loop identification |

These flags are **STRONG challenge triggers** for the adversarial reviewer — they bypass qualitative judgment and ensure the Iceberg Model's invariants are enforced even when the LLM doesn't follow instructions perfectly. See §7 for the full flag taxonomy.

### Toulmin-Structured Output

Analysts produce structured argumentation fields for each risk factor:

| Field | Purpose | Consumed By |
|---|---|---|
| `claim` | The KEY factual claim that determines severity | Adversarial Phase 1 uses it directly |
| `warrant` | WHY does the evidence support the claim? | Adversarial checks if the warrant's logic holds |
| `strongest_counter` | The BEST counter-argument against this risk factor | Adversarial uses it as a starting point for challenges |

This replaces the previous pattern where adversarial had to extract claims from free-form `description` text. Structured claims enable more precise verification and reduce hallucination.

### Self-Consistency Sampling

Each analyst runs N=3 independent LLM calls (same prompt, different sampling). Consensus is computed per dimension via modal severity + median depth; the sample factor closest to consensus is selected as the analyst's output.

**Dynamic early-stop**: if the first 2 samples agree on severity for ALL dimensions, the 3rd is skipped — saves ~33% of analyst LLM calls when the model is confident. Configured via `ANALYST_SAMPLES = 3` constant.

### Composite Frameworks

The Iceberg Model integrates techniques from multiple domains:

| Technique | Source | Applied At |
|---|---|---|
| Step-Back Prompting | Google DeepMind 2024 | Layer 2 (high-level principles) |
| Competing Hypotheses | Richards Heuer (CIA) | Layer 3 (risk vs resilience case) |
| Causal Loop Analysis | Systems Thinking | Layer 3 (reinforcing vs balancing loops) |
| Pre-Mortem Analysis | Gary Klein (CIA) | Layer 4 (imagine failure, trace cause) |
| Chain of Verification | Meta AI, ACL 2024 | Adversarial review (4-step verification) |
| Toulmin Argumentation | Stephen Toulmin 1958 | Analyst output (claim → warrant → rebuttal) |
| Self-Consistency | Wang et al., ICLR 2023 | Analyst sampling (N=3, modal severity) |

### Depth as Cross-Company Differentiator

The depth distribution across companies reveals how the framework allocates analytical effort:

```
Honda:   ████████████████████████████████████████ 5×depth-3 + 5×depth-4   (all deep)
Toyota:  ██████████ ████████████ ████████████████ 3×d-2 + 3×d-3 + 4×d-4   (mixed)
BYD:     ████████████████ ██████████████████ ████ 4×d-2 + 5×d-3 + 1×d-4   (mostly shallow)
```

Honda's analysts found concerning patterns at EVERY dimension. Toyota's were mixed — shallow on secondary trade-offs, deep on primary risks. BYD's dimensions mostly stop early (market leader executing well).

---

## 7. The Independent Evaluator (Three-Phase Adversarial Review)

### Why Separation Matters

The most important architectural insight from Claude Code: **agents cannot reliably self-evaluate their own output.** SFEWA implements this through a structurally separated adversarial reviewer with three phases:

| Principle | Implementation |
|---|---|
| Structural separation | Separate node, thinking mode, different prompt |
| Never sees generator reasoning | Only sees risk factors + evidence, not analyst prompts |
| Objective criteria | Chain of Verification (4-step), 3-level severity grading |
| **Independent verification** | **Phase 2 searches the web for NEW counter-evidence** |
| Feedback loop | "reanalyze" → back to extraction/analysts |
| Access to independent data | Sees ALL evidence + can find MORE via search |
| Depth-aware | HIGH factor with shallow analysis → STRONG challenge |

### Three-Phase Architecture

```
Phase 1: Chain of Verification (thinking mode)
  Standard adversarial review — identify key claims, verify against
  available evidence, assess depth, grade challenges.
  Produces preliminary challenges + recommendation.

Phase 2: Independent Verification Search (ToolLoopAgent, non-thinking)
  GATED by case.verifier_corpus:
    - "open_web"             → Phase 2 runs (DDGS text + news)
    - "allowed_sources_only" → Phase 2 SKIPPED (retrospective default)
  When running: extracts key claims from HIGH/CRITICAL factors with
  non-STRONG challenges, searches for counter-evidence. 8 queries max.

Phase 3: Challenge Refinement (thinking mode)
  Reviews verification findings against Phase 1 challenges.
  Upgrades challenge severity to "strong" when web search found
  clear contradicting evidence. Keeps unverified challenges unchanged.
  Only triggers when Phase 2 ran and found relevant evidence.
```

**Conditional execution**: Phase 2+3 only run when Phase 1 identifies HIGH/CRITICAL factors with non-STRONG challenges AND the verifier corpus permits open-web search. If all challenges are already STRONG (or retrospective audit envelope), the node behaves as Phase 1 only. See §10 for the verifier corpus gate.

### Programmatic Flags (Pre-Adversarial Validation)

Before the adversarial reviewer sees risk factors, programmatic checks inject flags that serve as objective STRONG challenge triggers. The reviewer is instructed to trust these — they are deterministic checks, not judgment calls.

**Depth-severity flags** (from §6's `check_depth_consistency()`):
- `[DEPTH_SEVERITY_MISMATCH]`: depth ≤ 2 but severity HIGH/CRITICAL → STRONG
- `[MISSING_FORCES]`: depth ≥ 3 but no structural forces → minimum moderate
- `[MISSING_ASSUMPTION]`: depth = 4 but no key assumption articulated → minimum moderate

**Citation cross-validation flags** (`validate_citations()`):
- `[PHANTOM_CITATION]`: cited evidence_id does not exist in evidence → STRONG
- `[STANCE_MISMATCH]`: evidence cited as supporting actually has `contradicts_risk` stance → STRONG (proportional: >50% mismatched)
- `[THIN_EVIDENCE]`: HIGH/CRITICAL severity with < 2 supporting citations → minimum moderate

**Evidence balance flag**:
- `[EVIDENCE IMBALANCE]`: supporting count ≤ contradicting count for HIGH/CRITICAL → STRONG

Flags appear inline with each factor in the adversarial prompt:
```
[COM001] capital_allocation | HIGH | conf=0.85 | depth=2 | [DEPTH_SEVERITY_MISMATCH: depth=2 but severity=high]
```

### Phase 1 — Chain of Verification (CoVe)

For EACH risk factor, the adversarial reviewer performs:

1. **IDENTIFY** the key claim (uses the Toulmin `claim` field directly when available)
2. **VERIFY** against ALL available evidence independently
3. **ASSESS** analytical depth (did the analyst go deep enough for the assigned severity?)
4. **GRADE** the challenge (strong / moderate / weak) — programmatic flags override grading for flagged factors

### Phase 2 — Independent Verification Search

The verification agent is a `ToolLoopAgent` with a single `search()` tool that reuses `_search_web()` and `_search_news()` from the retrieval module. It receives Phase 1's key claims and autonomously searches for contradicting evidence. Selection prioritizes critical-before-high and weak-before-moderate. Budget: 8 queries.

**Skipped** when the case envelope is `allowed_sources_only` (retrospective default) — visible in the audit log as `Phase 2 skipped — verifier_corpus=allowed_sources_only`.

### Phase 3 — Challenge Refinement

A thinking-mode LLM receives the original challenges plus verification findings. Refinement rules:
- Verification found **contradicting** evidence → append to `challenge_text`, upgrade severity to `"strong"`
- Verification found **nothing** → severity unchanged
- Challenges **not covered** by verification (LOW/MEDIUM factors) → kept as-is

### The Evidence-Gated Downgrade Rule

> **STRONG challenges only downgrade factors with WEAK evidence support.** Well-supported factors (≥3 valid supporting citations) resist — the challenge is noted in the memo but does not mechanically reduce severity.

A "valid" supporting citation must (1) exist in the evidence base and (2) not have `contradicts_risk` stance. STRONG downgrades are applied programmatically in `risk_synthesis` (deterministic), not by LLM. The evidence gate prevents Toulmin-driven STRONG inflation from over-penalizing companies with genuinely strong evidence.

### How It Behaves Per Company

Same prompt and same logic for every company. STRONG counts are high across the board (Toulmin makes adversarial precise), but **evidence quality** determines which downgrades fire:

| Company | STRONGs/run | Resisted/run | Effect |
|---|---|---|---|
| Honda | 4-6 | 4-6 (all) | EDINET evidence has 0 mismatches → all resist → HIGH/CRITICAL preserved |
| Toyota | 1-4 | 0-3 (partial) | Mixed evidence quality → some resist, some downgrade → MEDIUM |
| BYD | 4-7 | 0-2 (few) | 40-50% stance mismatches → most downgrades fire → lowest scores |

The evidence gate is the key cross-company differentiator: Honda's EDINET filings provide high-quality supporting evidence with zero stance mismatches; BYD's analysts frequently cite `contradicts_risk` evidence as "supporting", so after filtering, BYD factors have too few valid citations to resist.

---

## 8. Risk Scoring

### Continuous Score (0-100)

Replaces discrete HIGH/MEDIUM/LOW to eliminate boundary effects. Three-stage computation:

**Stage 1 — Evidence-gated programmatic base score** (deterministic):

```python
SEVERITY_POINTS = {"critical": 25, "high": 15, "medium": 8, "low": 2}
DOWNGRADE = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}

# Evidence-gated downgrades: STRONG challenges only fire on weak evidence.
for each STRONG-challenged factor:
    valid_sup = count citations that (exist in evidence AND stance != contradicts_risk)
    if valid_sup >= 3:               # well-supported → resist
        keep original severity
    else:                            # weak evidence → fire downgrade
        severity = DOWNGRADE[severity]

base_score = round(total_points / (15 * num_factors) * 100)
```

The `valid_sup` count excludes phantom citations and stance-mismatched citations (reusing `validate_citations()` from `_analyst_base.py`).

**Stage 2 — LLM qualitative adjustment** (thinking mode, clamped to ±15 of base):
- Causal loop analysis across all factors:
  - REINFORCING pattern (+5 to +10): risks compound through shared mechanisms
  - MIXED pattern (+0): roughly balanced
  - SCATTERED pattern (-5 to -10): independent concerns, no shared cause
- Strategy-relative assessment (is the company being judged against a strategy it didn't adopt?)
- Executed mitigations (current revenue/profit) vs announced plans (future products)
- Pre-mortem check: "if this assessment is completely wrong, what's the blind spot?"

**Stage 3 — Analyst agreement confidence calibration** (empirical):

After fan-out, `_compute_analyst_agreement()` injects:
- **Severity concentration** (Herfindahl, 0-1): high concentration (≥0.7) increases confidence; low (<0.5) decreases
- **Ordinal range**: max severity ordinal − min. Range ≥ 2 → synthesis MUST lower confidence below 0.7
- **Depth spread**: max depth − min depth across all factors

This replaces verbalized confidence (analysts self-rating). The synthesis prompt is told: "this is an empirical signal — do NOT override it with narrative reasoning."

### Score Bands

Derived from score, not vice versa:

| Score | Level |
|---|---|
| 80-100 | CRITICAL |
| 60-79 | HIGH |
| 40-59 | MEDIUM |
| 0-39 | LOW |

The synthesis prompt uses a 5-band scale (including 0-19 MINIMAL) as a calibration anchor for the LLM, but the code maps everything below 40 to "low".

---

## 9. Audit Architecture

The audit envelope turns SFEWA from "an agent that produces a score" into "an audit-grade agent that produces a self-auditable bundle". Six primitives are computed end-to-end on every run; all live under `sfewa/tools/`:

```
filing_provider.py     FilingRef, EvidenceChunk, ManifestEntry, FilingProvider Protocol
providers/             EdinetProvider, CninfoProvider, HkexProvider, SecEdgarProvider
manifest.py            build_manifest_from_docs, assert_manifest_clean, manifest_summary
citation_check.py      validate_top_level_claims, citation_summary  (L1: per-factor)
sentence_citation.py   validate_sentence_citations                  (L2.3: per-sentence)
provenance.py          build_provenance (model + git + sha + tokens + manifest counts)
html_report.py         render_report → outputs/{run_id}/report.html
```

### The Audit Primitives

| Primitive | Artifact | Invariant | Where computed |
|---|---|---|---|
| **Source manifest** | `source_manifest.json` | Zero entries with `cutoff_decision == "kept"` AND `release_time > cutoff_date` | Built by retrieval node; assertion in `manifest.assert_manifest_clean()`; violations recorded in `run_summary.json` |
| **Claim citation (per-factor)** | `risk_factors.json` + `evidence.json` | Every top-level claim references ≥1 `evidence_id` that resolves to evidence with a real `source_url` / `doc_id` / (`source_title`+`published_at`) | `citation_check.validate_top_level_claims()`; violations recorded as data |
| **Sentence citation (L2.3)** | `sentence_citations.json` | Each sentence in a factor's `claim`+`description` is fuzzy-matched against the cited evidence's text; resolved spans get `(doc_id, char_start, char_end)`, unresolved sentences logged | `sentence_citation.validate_sentence_citations()`; soft enforcement (data, not exception) |
| **Provenance** | `provenance.json` | Records model id + git commit + dirty flag + case-config sha256 + truth-config sha256 + token totals + wall-clock + manifest counts | `provenance.build_provenance()` runs at end-of-pipeline |
| **Verifier corpus** | adversarial Phase 2 log | Retrospective cases default to `allowed_sources_only` (no open-web verification); forward defaults to `open_web` | `apply_verifier_corpus_default()` at load + Phase 2 gate in `adversarial_review_node` |
| **Case/truth split** | `configs/cases/*.yaml` ↔ `configs/truth/*.yaml` | Truth content (sentinel + ground-truth events) MUST NOT appear in any agent-visible prompt or state field | Static grep + runtime sentinel test (defense in depth) |

### Source Manifest Detail

Doc-level audit log built at retrieval time. Each row carries:
```
ticker, issuer_name, title, doc_type, language, release_time, url,
content_sha256, cutoff_decision, source
```

`cutoff_decision` is one of:
- `kept` — passes all gates
- `rejected_post_cutoff` — `release_time > cutoff_date`
- `rejected_doc_type` — not in `case.allowed_doc_types`
- `rejected_language` — not in `case.allowed_languages`

The production invariant (`assert_manifest_clean`) requires zero `kept` rows with `release_time > cutoff_date`. Fixture-level invariant (per-provider tests) requires at least one `rejected_post_cutoff` row to prove the gate exists.

### Claim-Citation Enforcement

Two layers, in increasing strictness:

**Per-factor (L1)** — `validate_top_level_claims()` walks each `risk_factor.supporting_evidence` list and resolves each id against the evidence index. A factor passes when at least one cited id resolves to evidence carrying a real document reference. Violation modes: `phantom` (cited id not in evidence), `no_doc_ref` (resolves but no source reference), `empty` (no citations at all).

**Per-sentence (L2.3-4)** — `validate_sentence_citations()` splits each factor's `claim` + `description` into sentences, then runs **two matchers in series**: (1) **token-overlap (primary, iter 44)** — content-token coverage with stopword filtering; requires ≥3 distinct hit tokens AND ≥0.55 ratio against the sentence's content tokens; locates the tightest evidence window via word-boundary scan. (2) **`difflib` longest-block (fallback, iter 43)** — looks for the longest contiguous matching block (≥25% of sentence length, ≥12 chars). Matched sentences record a `(doc_id, char_start, char_end)` span; unresolved sentences land in `audit_violations.sentence_citations_unresolved`. This remains *soft enforcement* — both paths are fuzzy by design (analysts paraphrase rather than quote verbatim) and data is logged for the audit trail rather than raising. **Iter 44 lifts paraphrase recall from ~0% to >66% on English↔English smoke corpora**; JP/CN evidence vs English claims is still bottlenecked by the language gap (next-step CJK character-bigram tokens). Production resolution rates of 1-10% remain typical for cross-language cases (Honda EDINET, Toyota EDINET, BYD CNINFO); the value is honest signal about how traceable each conclusion is.

### Provenance Header

`provenance.json` records:
- `case_id`, `case_type`, `cutoff_date`, `started_at_utc`, `elapsed_seconds`
- `model.{provider, model_id, base_url}` from environment
- `git.{commit (12-char hex), branch, dirty}`
- `case_config.{path, sha256}`, `truth_config.{path, sha256}`
- `audit_meta` (jurisdiction, ticker, allowed_sources, doc_types, verifier_corpus)
- `manifest.{total_entries, kept, rejected_post_cutoff}`
- `tokens.{prompt, completion, total}`

Two runs with identical provenance hashes will produce identical artifacts (modulo LLM sampling variance).

### Verifier Corpus Propagation

A subtle leakage path: SFEWA's adversarial Phase 2 searches the open web. Without this gate, retrospective runs could theoretically use post-cutoff news to verify pre-cutoff claims — much harder to spot than retrieval-side leakage.

`apply_verifier_corpus_default()` runs at load time and applies the default:
- Retrospective → `allowed_sources_only` (Phase 2 web-search disabled)
- Forward → `open_web`

Cases can override explicitly. The existing Honda/Toyota/BYD configs pin `verifier_corpus: open_web` to preserve the iter-41 baseline; new retrospective cases (Country Garden, Boeing) get the stricter default automatically.

When the gate fires, the adversarial node logs `Phase 2 skipped — verifier_corpus=allowed_sources_only` to the audit trail.

### Case/Truth Split

`configs/cases/{name}.yaml` is **agent-visible**: every field can flow into prompts.
`configs/truth/{case_id}.yaml` is **evaluation-only**: read by `backtest.py` and the loader only.

Two layers of leakage detection (`tests/test_integration/test_label_leakage.py`):

1. **Static grep**: scans `src/sfewa/agents/*.py`, `src/sfewa/prompts/*.py`, `src/sfewa/tools/*.py` for forbidden tokens (`configs/truth`, `TruthConfig`, `load_truth`, `load_case_and_truth`). Allowlist: `backtest.py` is the only sanctioned reader.
2. **Runtime sentinel**: each truth YAML carries a unique `__TRUTH_SENTINEL_<case_id>_xxxxxx__`. The runtime test calls `build_initial_state_from_case()` and walks every string in the resulting state — the sentinel must not appear anywhere except inside the truth file. Verified to fail loudly when leakage is injected (negative-case test).

The `load_case_and_truth()` loader enforces:
- `case_type: forward` + truth file present → fail loudly (label-leakage hazard)
- `case_type: retrospective` + truth file missing → fail loudly (validation impossible)
- truth file `case_id` mismatch → fail loudly

### Audit Violations Are Data, Not Exceptions

Assertions inside `save_run_artifacts` would kill 30+ minute runs after scoring already completed, losing all artifacts. The audit primitives instead record violations as data:

```python
{
    "audit_violations": {
        "manifest_kept_post_cutoff":      [...],   # empty when clean
        "citations_unresolved":           [...],   # empty when clean
        "sentence_citations_unresolved":  [...]    # honest fuzzy-match signal
    }
}
```

The CI gate becomes a separate test that reads `run_summary.json`. Pipeline runs always complete; the audit trail is always saved. The standalone `assert_manifest_clean()` and `assert_claim_citations()` functions remain available — used by unit tests and as the post-hoc CI gate.

### The HTML Report

`outputs/{run_id}/report.html` is a single-file static report (embedded CSS, no external dependencies) with three pillars visible above the fold:

- **Evidence trace**: every top-level claim shows its citation IDs as anchor links (`#ev-E001`) to corresponding evidence cards below
- **Provenance**: model id, git commit (with dirty flag), case-config sha256, cutoff date
- **Controls applied**: temporal-gate kept/rejected counts, verifier corpus pill, adversarial STRONG/MODERATE counts, adversarial pass count

Forward cases display `"Forward surveillance case. Not a retrospective validation."` as a banner above the verdict — the report cannot be mistaken for retrospective validation.

### Known Limitations

- **DDG-driven HKEX coverage is partial.** When DuckDuckGo's index doesn't surface a company's HKEX PDFs, the optional Playwright fallback kicks in if installed; otherwise HK runs fall back to web-search-only evidence. Coverage varies per issuer — Country Garden ✓, others may not surface depending on DDG's index state.
- **Sentence-level matcher is fuzzy.** Iter 44 added a token-overlap primary path that lifts paraphrase recall on English↔English claim/evidence pairs (smoke corpora >66%). The `difflib` longest-block fallback still handles verbatim quotes and CJK. Cross-language pairs (English claims vs JP/CN evidence) remain the dominant source of low production resolution rates — bridging requires either CJK character-bigram tokens, embedding similarity, or asking the analyst LLM to emit explicit sentence→evidence_id maps.

---

## 10. Cross-Cutting Concerns

### Temporal Integrity (4 layers)

1. **Retrieval**: `published_at > cutoff_date` → hard reject in temporal filter; rejection recorded in `source_manifest.json` as `cutoff_decision: rejected_post_cutoff`
2. **Extraction**: temporal filter on evidence items, fiscal year validation
3. **Prompts**: "Do NOT use knowledge about events after {cutoff_date}" in all prompt templates
4. **Adversarial verifier**: when `case.verifier_corpus == "allowed_sources_only"` (retrospective default), Phase 2 web-search is **skipped entirely** — no open-web verification can introduce post-cutoff news. See §9 for the full gate.

### Pipeline Context Injection

Each downstream node receives a summary of upstream pipeline history via `build_pipeline_context()`:

```
PIPELINE CONTEXT (what has happened so far):
- Retrieved 138 documents (23 edinet, 58 duckduckgo, 31 gap_fill, 26 counter)
- Extracted 29 evidence items (stance: 10 supports, 5 contradicts, 14 neutral)
- Quality gate: evidence sufficient (iteration 3)
```

Synthesis can adjust confidence based on evidence quality; adversarial factors in retrieval coverage.

### LLM-Driven Routing

Routing decisions are LLM, not hardcoded thresholds:

- **Agentic retrieval (v2)**: ToolLoopAgent self-assesses coverage against 9 criteria, stops when satisfied. No separate quality gate needed.
- **Quality gate (v1 only, `route_after_quality_gate`)**: LLM evaluates evidence sufficiency. Sets `evidence_sufficient` in state; routing function returns `"fan_out"` or `"retrieval"`.
- **Adversarial review (`after_adversarial_review`)**: LLM recommends `"proceed"` or `"reanalyze"`. Routing function reads `adversarial_recommendation`.

Dead-loop counters (`MAX_ADVERSARIAL_PASSES=2`) are safety bounds only — the LLM makes the actual decision.

### Observability

- **Runtime reporting**: Rich console output via `sfewa/reporting.py` (enter/log/exit per node). Dual-write: every event also persisted to CallLog.
- **Call logging**: All LLM calls, tool calls, and pipeline events recorded via `liteagent.CallLog`, saved as `llm_history.jsonl`.
- **Pipeline events**: `PipelineEventRecord` captures node entry/exit, routing decisions, parallel fan-out, actions. ~80 events per run interleaved with LLM/tool records. Enables flow-graph reconstruction.
- **Artifacts**: 11 files saved to `outputs/{case_id}_{timestamp}/` (evidence, risk_factors, challenges, backtest, memo, run_summary, run_metadata, source_manifest, provenance, llm_history, report.html).

---

## 11. What Makes This Agentic (Not Just a Pipeline)

| Dimension | Static Pipeline | SFEWA (Agentic) |
|---|---|---|
| **Strategy theme** | **User must author** | **Optional — `strategy_discovery` agent reads filings + light web search and proposes 1-3 candidate themes ranked by scrutiny target** |
| Analysis dimensions | Hardcoded ontology | LLM generates dimensions from case context |
| Filing sources | Hardcoded per company | Jurisdiction routing through `FilingProvider` Protocol (JP/CN/HK/US) |
| **Peer filings** | **Web search only** | **Optional `peer_filings_node` resolves each case peer through the same Protocol; opt-in via `--enable-peer-filings`. Honda+peer demo: 18 peer chunks from Toyota EDINET + BYD CNINFO + Tesla/Ford/GM SEC EDGAR seeded as Tier-1.** |
| **HK filing discovery** | **Manual PDF staging** | **DDG `site:hkexnews.hk` site search + URL auto-promotion + iter-44 broadened query templates (doc-type variants × ticker-anchored × wider year window): any HKEX URL the agent surfaces during normal search becomes Tier-1 evidence transparently** |
| Search queries | Config-defined topics | Agent derives queries from dimensions + case context |
| Technology coverage | No tech-specific search | Agent reads dimension names, searches for company tech + industry benchmarks |
| Evidence sufficiency | Fixed threshold | Agent self-assesses against 9 criteria, stops when satisfied |
| **Analysis depth** | **Same depth for every dimension** | **Iceberg Model: LLM decides 2-4 layers per dimension** |
| Adversarial verification | Review available evidence only | Phase 2 ToolLoopAgent independently searches (when corpus permits) |
| Severity calibration | Fixed rules | Emerges from depth + structural forces + programmatic flags |
| Analyst reliability | Single LLM call per analyst | Self-consistency sampling (N=3, modal severity, dynamic early-stop) |
| Citation integrity | Trust analyst citations | Programmatic cross-validation: per-factor phantom/stance-mismatch + per-sentence span resolution |
| Confidence calibration | Verbalized confidence | Empirical analyst agreement (HHI concentration, ordinal range) |
| Risk scoring | Categorical labels | Programmatic base + LLM causal-loop adjustment (0-100) |
| Context awareness | Each node isolated | Pipeline context injected — downstream knows upstream history |
| **Audit envelope** | **No machine-checkable proof** | **Manifest + per-factor citation + per-sentence citation + provenance + verifier corpus + case/truth split** |

12+ autonomous decisions per run that alter behavior. Different companies trigger different paths and different analytical depths through the same architecture, and every run produces machine-checkable evidence that the temporal gate held and every claim is traceable to a source document.

---

## 12. Package Structure

```
src/sfewa/
  main.py                 CLI entry + build_initial_state_from_case()
  llm.py                  LLM factory (wraps liteagent.LLMClient)
  context.py              Domain-specific pipeline context builder
  reporting.py            Rich console reporter

  graph/
    pipeline.py           Pipeline executor (run_pipeline + run_pipeline_v2)
    routing.py            LLM-driven routing functions + dead-loop constants

  agents/
    init_case.py             Case expansion (LLM generates regions, peers, dimensions)
    strategy_discovery.py    Optional pre-step: infer 1-3 candidate themes when YAML omits one
    peer_filings.py          Optional pre-step: peer-side FilingProvider Protocol (opt-in default-off)
    retrieval.py             3-pass agentic retrieval (DDGS + filings) [v1]
    agentic_retrieval.py     Tool-loop agent retrieval (ToolLoopAgent, HKEX URL auto-promote) [v2]
    evidence_extraction.py   LLM extraction + temporal filter (batched)
    quality_gate.py          Evidence sufficiency gate (LLM-driven) [v1 only]
    _analyst_base.py         Shared analyst implementation, depth/citation validation
    industry_analyst.py      External dimensions
    company_analyst.py       Internal dimensions
    peer_analyst.py          Comparative dimensions
    adversarial.py           Independent evaluator (3-phase, verifier-corpus-gated)
    risk_synthesis.py        Programmatic + LLM scoring (causal loop analysis)
    backtest.py              Ground truth matching (only reader of truth files)

  prompts/
    init_case.py             Case expansion + dimension generation
    strategy_discovery.py    Discovery agent system + user prompts
    retrieval.py             Seed, gap analysis, counternarrative [v1]
    agentic_retrieval.py     Tool-loop agent system prompt + 9 coverage criteria [v2]
    extraction.py            Evidence extraction + stance guidance
    analysis.py              Iceberg Model framework, dimension defs, scope boundaries
    adversarial.py           Chain of Verification, severity grading
    synthesis.py             Scoring guidelines, calibration anchors, pre-mortem

  schemas/
    config.py             CaseConfig, TruthConfig, load_case_and_truth (case/truth split)
    state.py              PipelineState (case_type, audit_meta, source_manifest)
    evidence.py           EvidenceItem, RiskFactor, AdversarialChallenge, BacktestEvent

  tools/
    # Core pipeline support
    chat_log.py             Wrapper around liteagent.CallLog
    artifacts.py            File-based artifact saving (manifest + citations + provenance + report)
    temporal_filter.py      Date comparison utilities

    # Audit primitives
    manifest.py             Source manifest builder + production invariant
    citation_check.py       Per-factor claim → resolvable evidence (L1)
    sentence_citation.py    Per-sentence span resolution + audit-violation logging (L2.3)
    provenance.py           Run provenance header
    html_report.py          Single-file static HTML report (three-pillar)

    # FilingProvider Protocol
    filing_provider.py      FilingRef, EvidenceChunk, ManifestEntry, FilingProvider Protocol,
                            decide_cutoff(), chunk_with_offsets()
    filing_discovery.py     Jurisdiction detection + dispatch (JP→EDINET, CN→CNINFO,
                            HK→HKEX live, US→SEC EDGAR)
    hkex_live_discovery.py  HKEXnews live: DDG `site:hkexnews.hk` queries +
                            URL auto-promotion + optional Playwright fallback
    providers/
      edinet_provider.py    Japan adapter (live discovery)
      cninfo_provider.py    China adapter (live discovery)
      hkex_provider.py      HK adapter (live via DDG; manual cache also supported)
      sec_edgar_provider.py US adapter (live via data.sec.gov JSON API)

    # Per-system clients (legacy modules wrapped by providers)
    edinet.py               EDINET API client (Japan FSA)
    cninfo.py               CNINFO API client (China A-share)
    hkex.py                 HKEXnews helpers (issuer resolver, taxonomy, TZ, parser)
    sec_edgar.py            SEC EDGAR client (CIK lookup, submissions feed, HTML extract)
    corpus_loader.py        Legacy EDINET PDF loader

configs/
  cases/                  Agent-visible case YAMLs (case_id, jurisdiction, ticker,
                          allowed_sources, doc_types, verifier_corpus, ...)
  truth/                  EVAL-ONLY truth YAMLs (sentinel, known_outcome,
                          ground_truth_events). Read by backtest path only.
```

### Dependencies

SFEWA depends on `liteagent` for generic agent patterns and adds domain-specific dependencies:

| Dependency | Purpose |
|---|---|
| `liteagent` | LLM client, pipeline utilities, state helpers, parsing, observability |
| `openai` | OpenAI-compatible API (via liteagent) |
| `pydantic` | Schema definitions (CaseConfig, TruthConfig, evidence models) |
| `pyyaml` | Case + truth config loading |
| `python-dotenv` | `.env` file loading (LLM endpoint, API keys) |
| `ddgs` | DuckDuckGo web + news search |
| `pdfplumber` | PDF text extraction |
| `pypdf` | PDF parsing fallback |
| `beautifulsoup4` | HTML content extraction (HKEXnews, CNINFO) |
| `httpx` | HTTP client (EDINET, CNINFO, HKEX, SEC future) |
| `rich` | Terminal reporting |
| `typer` | CLI interface |
