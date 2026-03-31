# Implementation Plan: Strategic Failure Early Warning Agent

## 1. Problem Statement

Strategic failures at public companies are often visible in public data before they are officially recognized. This system answers one question:

> Given a company, a strategic theme, and a cutoff date — can the system construct a sufficiently strong evidence chain to flag the strategy as high-risk, using **only** information available before the cutoff?

**First case**: Honda's EV strategy, cutoff 2025-05-19, backtested against the May 2025 target revision and March 2026 writedown.

**Non-goals**: stock price prediction, trading signals, full-market scanning, general-purpose chatbot.

---

## 2. Architecture Overview

```
                    ┌─────────────────────┐
                    │   Case Config YAML   │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │    Orchestrator      │
                    │  (LangGraph Router)  │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │  Retrieval & Time    │
                    │    Gatekeeper        │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Evidence Extraction  │
                    └──────────┬──────────┘
                               ▼
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
     │   Industry    │ │   Company    │ │     Peer     │
     │   Analyst     │ │  Strategy    │ │  Benchmark   │
     │              │ │  Analyst     │ │  Analyst     │
     └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
            └────────────────┼────────────────┘
                             ▼
                  ┌─────────────────────┐
                  │ Adversarial Reviewer │
                  └──────────┬──────────┘
                             ▼
                  ┌─────────────────────┐
                  │   Risk Synthesis    │
                  │   & Memo Writer     │
                  └──────────┬──────────┘
                             ▼
                  ┌─────────────────────┐
                  │  Backtest Evaluator │
                  └─────────────────────┘
```

**Technology**: LangGraph 2.x StateGraph with conditional edges, fan-out for parallel analysts, and loop-back for adversarial review.

**LLM**: Qwen3.5-27B-GPTQ-Int4 on local vLLM (OpenAI-compatible API). Single model, two modes:
- **Thinking mode** (`enable_thinking=True`): Generates `<think>` CoT reasoning before answer. Used for adversarial review, risk synthesis.
- **Non-thinking mode** (`enable_thinking=False`): Direct answer, faster. Used for extraction, retrieval, analysis.

### 2.1 Agentic Capabilities (aligned to AI Tinkerers event theme)

The event theme is **"Agentic AI in Action"** — the system demonstrates all five
capabilities the event specifically calls out:

| Capability | Implementation |
|---|---|
| **LLM orchestration** | LangGraph StateGraph: 9 nodes, explicit edges, conditional routing, fan-out parallelism |
| **Tool-calling** | Retrieval agent calls `DuckDuckGoSearchResults`, `check_temporal_validity` tools via Qwen3.5 native function calling |
| **State management** | Typed `PipelineState` with `Annotated[list, operator.add]` reducers for safe concurrent accumulation |
| **Multi-step reasoning loop** | Adversarial loop-back: if challenges are strong, re-analyze (max 2 rounds) |
| **Autonomous action** | Pipeline runs end-to-end without human intervention: retrieve → extract → analyze → challenge → synthesize → backtest |

### 2.2 Key Design Patterns Adopted

| Pattern | Source | How We Use It |
|---|---|---|
| Adversarial debate loop | TradingAgents-CN | Adversarial reviewer challenges risk factors; loops back if >50% have strong challenges |
| Dead-loop protection | TradingAgents-CN | Iteration counters prevent infinite extraction or adversarial loops |
| Separated evaluation | Anthropic harness design | Adversarial reviewer is a separate agent, never self-evaluates its own output |
| File-based artifact handoffs | Anthropic harness design | Each run produces auditable JSON/MD artifacts in `outputs/{run_id}/` |
| Objective grading criteria | Anthropic harness design | Risk scoring uses explicit weighted dimensions, not subjective LLM judgment |

---

## 3. LangGraph State Schema

This is the single source of truth flowing through the entire pipeline.

```python
from __future__ import annotations
import operator
from typing import Annotated, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from datetime import date


# ── Pydantic models for structured data ──

class EvidenceItem(BaseModel):
    evidence_id: str
    claim_text: str
    claim_type: Literal[
        "target_statement", "investment_commitment", "product_launch_plan",
        "market_outlook", "risk_disclosure", "competitive_positioning",
        "strategic_revision", "policy_change", "financial_metric"
    ]
    entity: str
    metric_name: str | None = None
    metric_value: str | None = None
    unit: str | None = None
    region: str | None = None
    event_date: date | None = None
    published_at: date
    source_url: str
    source_title: str
    source_type: Literal["company_filing", "company_presentation",
                         "industry_report", "government_policy",
                         "peer_filing", "news_article"]
    span_text: str  # exact quote from source
    stance: Literal["supports_risk", "contradicts_risk", "neutral"]
    relevance_score: float = Field(ge=0.0, le=1.0)
    credibility_tier: Literal["tier1_primary", "tier2_official",
                              "tier3_reputable", "tier4_secondary"]


class RiskFactor(BaseModel):
    factor_id: str
    dimension: Literal[
        "market_timing", "regional_mismatch", "product_portfolio",
        "technology_capability", "capital_allocation", "execution",
        "narrative_consistency", "policy_dependency", "competitive_pressure"
    ]
    title: str
    description: str
    severity: Literal["critical", "high", "medium", "low"]
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str]  # evidence_ids
    contradicting_evidence: list[str]  # evidence_ids
    causal_chain: list[str]  # ordered causal steps
    unresolved_gaps: list[str]


class AdversarialChallenge(BaseModel):
    challenge_id: str
    target_factor_id: str
    challenge_text: str
    counter_evidence: list[str]  # evidence_ids
    severity: Literal["strong", "moderate", "weak"]
    resolution: str | None = None  # how the challenge was addressed


class BacktestEvent(BaseModel):
    event_id: str
    event_date: date
    description: str
    event_type: Literal["target_revision", "capex_reset", "project_cancellation",
                        "asset_writedown", "narrative_shift"]
    matched_factors: list[str]  # factor_ids that predicted this
    match_quality: Literal["strong", "partial", "weak", "miss"]


# ── LangGraph State ──

class PipelineState(TypedDict):
    # Case config (set once at start)
    case_id: str
    company: str
    strategy_theme: str
    cutoff_date: str  # ISO format
    regions: list[str]
    peers: list[str]

    # Accumulating fields (reducers append across nodes)
    evidence: Annotated[list[dict], operator.add]
    risk_factors: Annotated[list[dict], operator.add]
    adversarial_challenges: Annotated[list[dict], operator.add]
    backtest_events: Annotated[list[dict], operator.add]

    # Overwriting fields (last writer wins)
    retrieved_docs: list[dict]
    overall_risk_level: Literal["critical", "high", "medium", "low"] | None
    overall_confidence: float | None
    risk_memo: str | None
    backtest_summary: str | None

    # Control flow
    current_stage: str
    iteration_count: int
    adversarial_pass_count: int
    error: str | None
```

---

## 4. Agent Specifications

### 4.1 Orchestrator (Graph Router)

Not an LLM agent — pure LangGraph routing logic.

- **Input**: Case config YAML
- **Output**: Initialized `PipelineState`
- **Logic**: Load config, validate, set `cutoff_date`, dispatch to Retrieval node
- **Implementation**: `add_conditional_edges` with routing functions

### 4.2 Retrieval & Temporal Gatekeeper

- **Mode**: Non-thinking (direct answers, fast)
- **Tools** (LangChain `@tool` definitions):
  - `DuckDuckGoSearchResults` — web search via DuckDuckGo (no API key needed)
  - `check_temporal_validity(published_date, cutoff_date)` — hard cutoff enforcement
- **Tool calling**: Qwen3.5 supports native function calling via OpenAI tools API.
  vLLM must be launched with `--enable-auto-tool-choice --tool-call-parser qwen3_coder`.
- **Input**: company, strategy_theme, cutoff_date, regions, search_topics
- **Output**: `retrieved_docs` — list of document metadata + snippets
- **Key logic** (tool-calling loop):
  1. LLM generates search queries from case context
  2. Call `DuckDuckGoSearchResults` tool for each query
  3. Deduplicate results by link
  4. For each result, call `check_temporal_validity` tool
  5. **Hard reject** any document with `published_date > cutoff_date`
  6. Collect accepted documents with title, snippet, link, source
- **Why tool-calling matters here** (event alignment):
  - Shows the agent making autonomous decisions about what to search
  - Temporal filter as a tool demonstrates reliability constraint enforcement
  - DuckDuckGo is free and works without API keys — ideal for demos
- **Temporal integrity checks**:
  - Verify `published_date` from document metadata, not from search snippet
  - Flag documents that reference future events (contamination risk)
  - Log all rejected documents with reason to artifact store

### 4.3 Evidence Extraction Agent

- **Mode**: Non-thinking (structured extraction, high throughput)
- **Input**: `retrieved_docs`
- **Output**: `evidence` — list of `EvidenceItem` dicts
- **Key logic**:
  1. For each document, extract structured claims
  2. Classify each claim into `claim_type`
  3. Assign `stance` (supports_risk / contradicts_risk / neutral)
  4. Extract exact `span_text` quotes
  5. Score `relevance_score` and assign `credibility_tier`
- **Constraint**: Output must be valid `EvidenceItem` schema; reject malformed items

### 4.4 Three Domain Analyst Agents (Fan-Out Parallel)

All three run in parallel via LangGraph `Send` API, share the same output schema.

#### 4.4a Industry Analyst
- **Focus**: EV market adoption rates, charging infra, battery costs, consumer sentiment by region
- **Input**: evidence filtered to `source_type in [industry_report, government_policy]`
- **Output**: `risk_factors` for dimensions: `market_timing`, `policy_dependency`

#### 4.4b Company Strategy Analyst
- **Focus**: Honda's EV targets, investment plans, product roadmap, narrative shifts
- **Input**: evidence filtered to `source_type in [company_filing, company_presentation]`
- **Output**: `risk_factors` for dimensions: `capital_allocation`, `narrative_consistency`, `execution`, `product_portfolio`

#### 4.4c Peer Benchmark Analyst
- **Focus**: Competitor positioning, relative speed, cost advantages
- **Input**: evidence filtered to `source_type in [peer_filing, company_filing]` + peer list
- **Output**: `risk_factors` for dimensions: `competitive_pressure`, `regional_mismatch`, `technology_capability`

Each analyst must:
1. Map findings to risk ontology dimensions
2. Construct `causal_chain` for each risk factor
3. List `unresolved_gaps`

### 4.5 Adversarial Reviewer

- **Mode**: Thinking (CoT reasoning for deep multi-step analysis)
- **Input**: all `risk_factors` + all `evidence`
- **Output**: `adversarial_challenges` — list of `AdversarialChallenge` dicts
- **Key logic**:
  1. For each risk factor, attempt to find contradicting evidence
  2. Check for selection bias (over-reliance on single source?)
  3. Check for industry-vs-company confusion (is this Honda-specific or industry-wide?)
  4. Check for temporal bias (using hindsight framing on pre-cutoff data?)
  5. Rate each challenge as strong/moderate/weak
- **Loop control**: Runs once by default. If >50% of factors have "strong" challenges, triggers re-analysis loop (max 2 iterations via `adversarial_pass_count`)

### 4.6 Risk Synthesis & Memo Writer

- **Mode**: Thinking (CoT reasoning for synthesis and judgment)
- **Input**: `risk_factors`, `adversarial_challenges`, `evidence`
- **Output**: `overall_risk_level`, `overall_confidence`, `risk_memo`
- **Key logic**:
  1. Score each risk dimension (weighted average of factor severities, adjusted by adversarial challenges)
  2. Compute overall risk level and confidence
  3. Generate structured memo with sections:
     - Executive Summary
     - Risk Factor Table (dimension | severity | confidence | key evidence)
     - Causal Narrative (the "failure mechanism" story)
     - Adversarial Challenges & Resolutions
     - Evidence Gaps & Uncertainty
     - Conclusion with explicit confidence bounds

### 4.7 Backtest Evaluator

- **Mode**: Non-thinking (structured matching, fast)
- **Input**: `risk_factors`, `risk_memo`, ground truth events from config
- **Output**: `backtest_events`, `backtest_summary`
- **Key logic**:
  1. Load ground truth events (post-cutoff actual outcomes)
  2. Match each event to predicted risk factors
  3. Score match quality: strong / partial / weak / miss
  4. Compute precision (% of predicted risks that materialized) and recall (% of actual events that were predicted)
  5. Generate backtest report

---

## 5. LangGraph Wiring

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

workflow = StateGraph(PipelineState)

# Nodes
workflow.add_node("init_case", init_case_node)
workflow.add_node("retrieval", retrieval_node)
workflow.add_node("evidence_extraction", evidence_extraction_node)
workflow.add_node("industry_analyst", industry_analyst_node)
workflow.add_node("company_analyst", company_analyst_node)
workflow.add_node("peer_analyst", peer_analyst_node)
workflow.add_node("adversarial_review", adversarial_review_node)
workflow.add_node("risk_synthesis", risk_synthesis_node)
workflow.add_node("backtest", backtest_node)

# Linear edges
workflow.add_edge(START, "init_case")
workflow.add_edge("init_case", "retrieval")
workflow.add_edge("retrieval", "evidence_extraction")

# Fan-out: evidence_extraction -> 3 analysts in parallel
def fan_out_to_analysts(state: PipelineState) -> list[Send]:
    return [
        Send("industry_analyst", state),
        Send("company_analyst", state),
        Send("peer_analyst", state),
    ]

workflow.add_conditional_edges("evidence_extraction", fan_out_to_analysts,
                                ["industry_analyst", "company_analyst", "peer_analyst"])

# All analysts -> adversarial review
workflow.add_edge("industry_analyst", "adversarial_review")
workflow.add_edge("company_analyst", "adversarial_review")
workflow.add_edge("peer_analyst", "adversarial_review")

# Adversarial review -> synthesis or loop back
def after_adversarial(state: PipelineState) -> str:
    strong_challenges = sum(
        1 for c in state.get("adversarial_challenges", [])
        if c.get("severity") == "strong"
    )
    total_factors = len(state.get("risk_factors", []))
    if (total_factors > 0
        and strong_challenges / total_factors > 0.5
        and state.get("adversarial_pass_count", 0) < 2):
        return "evidence_extraction"  # re-analyze with adversarial feedback
    return "risk_synthesis"

workflow.add_conditional_edges("adversarial_review", after_adversarial, {
    "evidence_extraction": "evidence_extraction",
    "risk_synthesis": "risk_synthesis",
})

workflow.add_edge("risk_synthesis", "backtest")
workflow.add_edge("backtest", END)

# Compile
graph = workflow.compile()
```

---

## 6. Risk Ontology

Nine first-level dimensions, each with concrete indicators:

| Dimension | Key Indicators |
|---|---|
| **market_timing** | EV adoption rate vs company forecast, demand curve slope, inventory buildup |
| **regional_mismatch** | Revenue concentration vs growth geography, market share trajectory by region |
| **product_portfolio** | Model count vs competitors, price band coverage, launch timeline gaps |
| **technology_capability** | SDV maturity, ADAS level, E/E architecture generation, OTA capability |
| **capital_allocation** | Total EV investment vs revenue base, ROI assumptions, capex flexibility |
| **execution** | JV complexity, supply chain readiness, platform development stage, production ramp timeline |
| **narrative_consistency** | Target revision frequency, messaging pivot count, tone shift analysis |
| **policy_dependency** | Subsidy exposure, regulatory assumption in planning, tariff sensitivity |
| **competitive_pressure** | Cost gap vs leaders, time-to-market delta, feature parity gap |

---

## 7. Data Strategy

### 7.1 Document Sources (prioritized for Honda case)

**Tier 1 — Company primary** (highest credibility):
- Honda IR library: annual reports, earnings presentations, business briefings
- Honda newsroom: strategy announcements, product launches
- SEC EDGAR: 20-F filings

**Tier 2 — Official/institutional**:
- IEA Global EV Outlook
- US DOE/EPA regulatory documents
- ACEA, CAAM statistics

**Tier 3 — Peer primary**:
- Toyota, BYD, Tesla, Hyundai, VW, GM, Ford IR materials

**Tier 4 — Secondary**:
- Reuters, FT, Bloomberg, Nikkei articles

### 7.2 Data Acquisition Approach

For the demo, we use a **curated document corpus** rather than live crawling:

1. **Manual curation**: Pre-download 30-50 key documents into `data/corpus/`
2. **Metadata index**: `data/corpus_index.yaml` with full metadata per document
3. **Chunk & embed**: Process into chunks with section boundaries preserved
4. **Vector store**: Local ChromaDB or FAISS for semantic search
5. **Hybrid retrieval**: Keyword (BM25) + semantic + metadata filters

This avoids dependency on live web scraping for the demo while maintaining the architecture for future live retrieval.

### 7.3 Document Schema

```yaml
# data/corpus_index.yaml entry
- doc_id: "honda_business_briefing_2025"
  title: "Summary of 2025 Honda Business Briefing"
  source_url: "https://global.honda/en/newsroom/news/2025/c250520eng.html"
  source_type: "company_presentation"
  publisher: "Honda Motor Co., Ltd."
  published_at: "2025-05-20"
  language: "en"
  region: "global"
  credibility_tier: "tier1_primary"
  file_path: "data/corpus/honda/honda_business_briefing_2025.pdf"
  topics: ["ev_strategy", "investment", "target_revision", "hev_transition"]
```

---

## 8. Configuration System

### 8.1 Case Config

```yaml
# configs/cases/honda_ev_pre_reset.yaml
case_id: "honda_ev_pre_reset_2025"
company: "Honda Motor Co., Ltd."
ticker: "7267.T"
strategy_theme: "EV electrification strategy"
cutoff_date: "2025-05-19"  # day before business briefing
regions:
  - "north_america"
  - "china"
  - "global"
peers:
  - "Toyota Motor Corporation"
  - "BYD Company Limited"
  - "Tesla, Inc."
  - "Hyundai Motor Company"
  - "Volkswagen AG"
  - "General Motors Company"
  - "Ford Motor Company"

# Evidence universe constraints
allowed_source_types:
  - "company_filing"
  - "company_presentation"
  - "industry_report"
  - "government_policy"
  - "peer_filing"
  - "news_article"
excluded_domains: []

# Ground truth for backtest
ground_truth_events:
  - event_id: "gt_001"
    event_date: "2025-05-20"
    description: "Honda revises 2030 EV sales ratio from ~30% to ~20%, cuts EV/software investment from 10T to 7T yen, emphasizes HEV transition"
    event_type: "target_revision"
  - event_id: "gt_002"
    event_date: "2026-03-12"
    description: "Honda cancels multiple NA EV models, records 820B-1.12T yen operating expense, up to 2.5T yen total loss"
    event_type: "project_cancellation"

# Ontology version
ontology_version: "v1"

# Thinking mode overrides (see configs/models.yaml for defaults)
# By default: adversarial + synthesis use thinking mode, rest use non-thinking
thinking_mode_overrides: {}
```

### 8.2 Model Config (Thinking Mode Control)

Single model (Qwen3.5-27B-GPTQ-Int4 on vLLM) with two modes:

```yaml
# configs/models.yaml
model:
  name: "Qwen/Qwen3.5-27B-GPTQ-Int4"
  provider: "vllm"

role_modes:
  retrieval: "non_thinking"       # direct answer, fast
  extraction: "non_thinking"
  industry_analyst: "non_thinking"
  company_analyst: "non_thinking"
  peer_analyst: "non_thinking"
  backtest: "non_thinking"
  adversarial: "thinking"         # CoT reasoning
  synthesis: "thinking"

sampling:
  thinking:
    temperature: 1.0
    top_p: 0.95
    max_tokens: 81920
  non_thinking:
    temperature: 0.7
    top_p: 0.8
    max_tokens: 32768
```

Thinking mode is controlled via vLLM's `chat_template_kwargs`:
```python
extra_body={"chat_template_kwargs": {"enable_thinking": True}}  # or False
```

**Tool calling**: Qwen3.5 supports native function calling (OpenAI tools API format).
vLLM must be started with these additional flags:
```bash
--enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3
```
Tool calling works in both thinking and non-thinking modes. Use `llm.bind_tools([...])` in LangChain.

### 8.3 LLM Factory

```python
# src/sfewa/llm.py — single model, mode switching via enable_thinking
def get_llm_for_role(role: str) -> ChatOpenAI:
    mode = ROLE_TO_MODE.get(role, "non_thinking")
    return get_llm(thinking=(mode == "thinking"))
```

### 8.4 Runtime Reporting

Every agent node outputs structured progress to the terminal via `src/sfewa/reporting.py` (Rich-based). This serves three purposes:

1. **Debugging**: See exactly what each node received, did, and produced — compare against `docs/golden_run_honda.md` to spot divergence
2. **Demo**: Audience sees the pipeline working in real-time, not just final results
3. **Audit**: Temporal rejections, routing decisions, and adversarial outcomes are printed with reasons

Each node emits three types of output:

| Event | What it shows | Example |
|---|---|---|
| `enter_node` | Node name, input summary | `[2/9] retrieval — company: Honda, cutoff: 2025-05-19` |
| `log_action` | Key actions and decisions | `Temporal filter: 22 accepted, 3 rejected` |
| `exit_node` | Output summary + routing | `-> Next: evidence_extraction (22 docs retrieved)` |

Specialized log functions exist for risk factors (`log_risk_factor`), adversarial challenges (`log_challenge`), backtest matches (`log_backtest_match`), and temporal rejections (`log_rejection`).

Sample terminal output:

```
━━━ [2/9] retrieval ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  company: Honda Motor Co., Ltd.
  cutoff_date: 2025-05-19
  Search queries
    count: 10
  DuckDuckGo results
    raw_results: 40
    query_failures: 0
  Deduplication
    before: 40
    after: 25
  Temporal filter
    accepted: 22
    rejected: 3
    x "Honda revises 2030 EV target" — rejected: published after cutoff (2025-05-20)
    x ...
  Output:
    retrieved_docs: 22
  -> Next: evidence_extraction

━━━ [5/9] adversarial_review ━━━━━━━━━━━━━━━━━━━━━━
  Input: 7 risk factors, 35 evidence items
  Challenges generated
    AC001 -> RF002  STRONG    Policy risk speculative, not Honda-specific
    AC002 -> RF003  MODERATE  Capital ratio not unprecedented
    AC003 -> RF004  MODERATE  0 Series timeline was always 2026
    AC004 -> RF005  MODERATE  JV risk generic
  Output:
    challenges: 4 (1 strong, 3 moderate)
  -> Next: risk_synthesis (strong/total = 1/7 = 14.3% < 50%)
```

After the pipeline completes, `print_risk_summary_table()` renders a Rich table and `print_final_result()` shows the overall assessment.

---

## 9. Directory Structure

```
StrategicFailureEarlyWarningAgent/
├── CLAUDE.md                          # Claude Code project config
├── README.md                          # Project overview & demo narrative
├── LICENSE
├── pyproject.toml                     # uv/pip package config
├── .env.example                       # API keys template
├── .gitignore
│
├── .claude/
│   ├── settings.json                  # Claude Code permissions
│   └── rules/
│       └── agents.md                  # Rules for agent code
│
├── configs/
│   ├── cases/
│   │   └── honda_ev_pre_reset.yaml    # Honda case config
│   ├── models.yaml                    # LLM model configs
│   ├── ontology_v1.yaml              # Risk ontology definition
│   └── prompts/                       # Versioned prompt configs
│       ├── evidence_extraction.yaml
│       ├── industry_analyst.yaml
│       ├── company_analyst.yaml
│       ├── peer_analyst.yaml
│       ├── adversarial_reviewer.yaml
│       └── risk_synthesis.yaml
│
├── data/
│   ├── corpus/                        # Pre-curated documents
│   │   ├── honda/                     # Honda primary sources
│   │   ├── peers/                     # Peer company sources
│   │   ├── industry/                  # Industry reports
│   │   └── policy/                    # Policy documents
│   ├── corpus_index.yaml             # Document metadata index
│   └── ground_truth/                  # Backtest ground truth
│       └── honda_ev_events.yaml
│
├── src/
│   └── sfewa/                         # Main package
│       ├── __init__.py
│       ├── main.py                    # CLI entry point
│       ├── llm.py                     # LLM provider factory (vLLM/OpenAI-compatible)
│       │
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── state.py               # PipelineState TypedDict
│       │   ├── evidence.py            # EvidenceItem, RiskFactor, etc.
│       │   └── config.py              # Case/model config Pydantic models
│       │
│       ├── graph/
│       │   ├── __init__.py
│       │   ├── pipeline.py            # Main StateGraph assembly & compile
│       │   └── routing.py             # Conditional edge functions
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── init_case.py           # Case initialization node
│       │   ├── retrieval.py           # Retrieval & temporal gatekeeper
│       │   ├── evidence_extraction.py # Structured evidence extraction
│       │   ├── industry_analyst.py    # Industry/market analysis
│       │   ├── company_analyst.py     # Company strategy analysis
│       │   ├── peer_analyst.py        # Peer benchmarking
│       │   ├── adversarial.py         # Adversarial reviewer
│       │   ├── risk_synthesis.py      # Risk scoring & memo generation
│       │   └── backtest.py            # Backtest evaluator
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── search.py              # Document search (hybrid retrieval)
│       │   ├── document_loader.py     # PDF/HTML parsing
│       │   ├── temporal_filter.py     # Cutoff date enforcement
│       │   └── artifacts.py           # File-based artifact handoffs (audit trail)
│       │
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── extraction.py
│       │   ├── analysis.py
│       │   ├── adversarial.py
│       │   └── synthesis.py
│       │
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── processor.py           # Document processing pipeline
│       │   ├── chunker.py             # Section-aware chunking
│       │   └── embedder.py            # Embedding generation
│       │
│       └── evaluation/
│           ├── __init__.py
│           ├── backtest_scorer.py     # Precision/recall scoring
│           └── evidence_auditor.py    # Evidence quality checks
│
├── tests/
│   ├── conftest.py
│   ├── test_agents/
│   │   ├── test_evidence_extraction.py
│   │   ├── test_analysts.py
│   │   └── test_adversarial.py
│   ├── test_schemas/
│   │   └── test_evidence_models.py
│   ├── test_tools/
│   │   └── test_temporal_filter.py
│   └── test_integration/
│       └── test_pipeline.py
│
├── notebooks/
│   └── demo.ipynb                     # Interactive demo notebook
│
└── docs/
    └── implementation_plan.md          # This file
```

---

## 10. Implementation Phases

### Phase 1: Foundation (Day 1-2)

**Goal**: Runnable pipeline skeleton with mock data.

1. Set up `pyproject.toml` with all dependencies
2. Implement `schemas/` — all Pydantic models and PipelineState
3. Implement `graph/pipeline.py` — full StateGraph wiring with stub nodes
4. Implement `configs/` — case config, model config, ontology
5. Implement `main.py` — CLI entry point that loads config and runs graph
6. Verify: `uv run python -m sfewa.main --case configs/cases/honda_ev_pre_reset.yaml` runs end-to-end with stubs

**Key files**: `schemas/state.py`, `schemas/evidence.py`, `graph/pipeline.py`, `main.py`

### Phase 2: Data Layer (Day 3-4)

**Goal**: Curated Honda corpus loaded, chunked, and searchable.

1. Curate 30-50 documents into `data/corpus/` (Honda IR, IEA, peer filings)
2. Build `data/corpus_index.yaml` with metadata
3. Implement `ingestion/processor.py` — PDF/HTML parsing with section detection
4. Implement `ingestion/chunker.py` — section-aware chunking (document > section > span)
5. Implement `ingestion/embedder.py` — embed chunks into ChromaDB/FAISS
6. Implement `tools/search.py` — hybrid retrieval (BM25 + semantic + metadata filter)
7. Implement `tools/temporal_filter.py` — hard cutoff enforcement

**Key files**: `ingestion/`, `tools/search.py`, `tools/temporal_filter.py`

### Phase 3: Core Agents (Day 5-8)

**Goal**: All agents produce structured output from real data.

1. Implement `agents/retrieval.py` — query generation + temporal gatekeeper
2. Implement `agents/evidence_extraction.py` — structured claim extraction
3. Implement `agents/industry_analyst.py` — market/policy risk analysis
4. Implement `agents/company_analyst.py` — Honda strategy analysis
5. Implement `agents/peer_analyst.py` — competitive benchmarking
6. Implement `prompts/` — all prompt templates with schema enforcement
7. Wire real agents into `graph/pipeline.py`
8. Test each agent independently with sample docs

**Key files**: `agents/`, `prompts/`

### Phase 4: Adversarial & Synthesis (Day 9-10)

**Goal**: Full analytical pipeline with quality control.

1. Implement `agents/adversarial.py` — challenge generation and bias detection
2. Implement `agents/risk_synthesis.py` — scoring aggregation and memo generation
3. Implement loop-back logic in `graph/routing.py`
4. End-to-end run with Honda case

**Key files**: `agents/adversarial.py`, `agents/risk_synthesis.py`, `graph/routing.py`

### Phase 5: Backtest & Evaluation (Day 11-12)

**Goal**: Quantifiable results comparing prediction vs reality.

1. Implement `agents/backtest.py` — ground truth matching
2. Implement `evaluation/backtest_scorer.py` — precision/recall metrics
3. Implement `evaluation/evidence_auditor.py` — citation accuracy checks
4. Build ground truth dataset in `data/ground_truth/honda_ev_events.yaml`
5. Generate full backtest report

**Key files**: `agents/backtest.py`, `evaluation/`

### Phase 6: Demo Polish (Day 13-14)

**Goal**: 15-minute demo ready (10 min demo + 5 min Q&A).

1. Build `notebooks/demo.ipynb` — interactive walkthrough
2. Write README with project narrative
3. Create workflow visualization (Mermaid diagram)
4. Prepare sample outputs (evidence table, risk memo, backtest comparison)
5. Optimize for demo speed (cache intermediate results via artifacts)
6. Prepare for Q&A: anticipated questions about temporal integrity, adversarial review, vLLM setup
7. Test full demo flow on local vLLM to confirm latency is acceptable

---

## 11. Dependencies

```toml
[project]
dependencies = [
    "langgraph>=0.4",
    "langchain>=0.3",
    "langchain-openai>=0.3",           # OpenAI-compatible API (vLLM)
    "langchain-community>=0.3",
    "langchain-text-splitters>=0.3",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "chromadb>=0.5",
    "rank-bm25>=0.2",
    "pypdf>=4.0",
    "beautifulsoup4>=4.12",
    "httpx>=0.27",
    "rich>=13.0",
    "typer>=0.12",
]
```

`langchain-openai` talks to vLLM via its OpenAI-compatible API. No cloud API keys needed.

---

## 12. Key Design Decisions

### 12.1 Why curated corpus over live retrieval?

- **Reproducibility**: Same input = same output across runs
- **Temporal integrity**: No risk of accidentally fetching post-cutoff content
- **Demo reliability**: No dependency on network/API availability
- **Auditability**: Every document is version-controlled

Live retrieval is architecturally supported but not used in v1.

### 12.2 Why fan-out analysts instead of one big analyst?

- **Testability**: Each analyst can be tested independently
- **Parallelism**: LangGraph runs them concurrently
- **Specialization**: Different evidence types need different analysis frames
- **Demo value**: Shows genuine multi-agent orchestration, not prompt-splitting theater

### 12.3 Why adversarial review as a separate agent?

- **Structural guarantee**: The review happens regardless of analyst quality
- **Separated evaluation**: Anthropic's harness design shows agents cannot reliably self-evaluate; an external evaluator is dramatically more effective
- **Demonstrable**: Clear before/after showing the system challenges itself

### 12.4 Why not vector-only retrieval?

Financial documents need metadata-aware search:
- "Honda's 2024 EV target" requires filtering by entity + date + topic
- Pure semantic search would return similar-sounding but wrong documents
- Hybrid (BM25 + semantic + metadata) catches what each method alone misses

---

## 13. Demo Script (15 Minutes: ~10 min demo + ~5 min Q&A)

### Event alignment checklist

The event theme is **"Agentic AI in Action"**. They explicitly want to see:

| Event wants | How we deliver |
|---|---|
| **LLM orchestration** | LangGraph StateGraph with fan-out, conditional edges, loop-back |
| **Tool-calling reliability** | Retrieval agent uses LangChain tools (search, parse, temporal filter); structured output via Pydantic |
| **State management** | Typed `PipelineState` with accumulating fields (`Annotated[list, operator.add]`); show state flowing between agents |
| **Multi-step reasoning loops** | Adversarial loop-back: if >50% factors challenged, re-analyze (max 2 rounds) |
| **Systems that take action** | Pipeline autonomously retrieves docs, extracts evidence, runs 3 parallel analysts, challenges itself, writes risk memo |
| **Code over decks** | Every demo segment shows code in terminal/editor, zero slides |
| **Messy experiments** | Show honest failures, what the system got wrong, unsolved challenges |

### Demo flow

**Minute 0:00-1:00 — Hook: Why This Matters**
> "Strategic failures are visible in public data before they are officially recognized.
> I built an agentic system that autonomously finds those signals — and I can prove
> it works by backtesting against real events."

One sentence on Honda: "Honda wrote down 2.5 trillion yen in March 2026. Could agents
have flagged the risk using only pre-announcement public data?"

No slides. Show the case config YAML to ground the problem concretely.

**Minute 1:00-3:30 — The Agent Pipeline: How It Works (core of the demo)**

This is the most important section. The audience wants to see **orchestration,
tool-calling, and state management** — not domain analysis.

Show `graph/pipeline.py` in editor. Walk through:

1. **StateGraph wiring** — show the actual code that builds the graph.
   Highlight: nodes, edges, the `Send` API for parallel fan-out.
   > "This is a LangGraph StateGraph. Nine nodes. Three run in parallel."

2. **State management** — show `schemas/state.py`.
   Highlight: `Annotated[list[dict], operator.add]` for accumulating evidence
   across agents. Explain how each agent appends to shared state without
   overwriting what others wrote.
   > "This is the key state management pattern. Accumulating fields use
   > reducers — each agent adds evidence, the graph merges them."

3. **Tool-calling in retrieval agent** — show the retrieval agent calling
   search + temporal filter tools. Show the tool definitions.
   > "The retrieval agent calls tools — search, document parse, temporal
   > filter. Every document goes through a hard cutoff check. If it was
   > published after the cutoff date, it's rejected. This is how we
   > prevent information leakage."

4. **Adversarial loop-back** — show `graph/routing.py`.
   > "After the adversarial reviewer runs, this routing function decides:
   > are there too many strong challenges? If yes, loop back and re-analyze.
   > Max 2 rounds. This is a multi-step reasoning loop — the system
   > argues with itself until the evidence is solid."

5. **Thinking mode switching** — show `llm.py`.
   > "One model, two modes. Extraction agents use non-thinking mode for
   > speed. Adversarial review uses thinking mode — Qwen3.5 generates
   > chain-of-thought reasoning before answering. Same model, different
   > reasoning depth."

**Minute 3:30-5:30 — Live Run: Watch the Agents Work**
> "Let's run it."

Show terminal output streaming:
1. Case config loaded, cutoff date set
2. Retrieval agent: documents fetched, temporal rejections logged
   > "See this? Three documents rejected — published after cutoff."
3. Evidence extraction: structured JSON claims appearing
4. Three analysts dispatched in parallel (show LangGraph trace)
5. Adversarial reviewer output: a specific challenge with counter-evidence

If live run is slow, use pre-cached run but show real streaming output.
The audience should see agents **taking action** autonomously.

**Minute 5:30-7:00 — Output: Evidence Chain Drill-Down**
> "The system found 7 high-risk factors. Let me show you the evidence chain."

Pick ONE risk factor. Show:
1. The risk factor with severity, confidence, causal chain
2. Click into supporting evidence: exact `span_text` quote, source URL, publication date
3. The adversarial challenge against it and how it was resolved
> "Every conclusion traces to a specific quote in a specific document
> published before the cutoff. Nothing is hallucinated — or if it is,
> the adversarial reviewer catches it."

**Minute 7:00-8:00 — Backtest: Did It Work?**
> "Ground truth: Honda revised targets in May 2025, cancelled EV models in March 2026."

Show backtest table: predicted risk factors vs actual events, match quality.
> "6 of 7 predicted factors matched. Here's what we missed and why."

Show an honest failure — something the system got wrong.

**Minute 8:00-9:00 — Technical Challenges (the "messy experiments" part)**

> "Three unsolved problems I'm still working on:"

1. **LLM world knowledge leakage** — even with temporal filtering on documents,
   the LLM itself knows about 2025-2026 events. How do you prevent the model
   from using knowledge it shouldn't have? (Open question for audience.)

2. **Structured output reliability** — Qwen3.5 sometimes breaks Pydantic schemas.
   Current workaround: retry with error message. Better solution needed.

3. **Adversarial reviewer quality** — sometimes rubber-stamps, sometimes
   over-challenges. Calibrating the threshold is hard.

This section shows intellectual honesty and invites engagement.

**Minute 9:00-10:00 — Extensibility & Wrap**
> "New company = new YAML config. Same pipeline, different target."

Show: 5-line config change to analyze a different company/strategy.
> "This is a framework for strategic risk research automation, not a Honda-specific tool."

**Minute 10:00-15:00 — Q&A**

Likely questions from this audience:
- **Tool-calling**: "How do you handle tool failures?" (retry, fallback, structured error propagation)
- **State management**: "Why LangGraph over CrewAI / AutoGen?" (typed state, explicit graph, deterministic routing)
- **Hallucination**: "How do you verify the span_text quotes are real?" (post-hoc audit against source)
- **Latency**: "How long does a full run take on local vLLM?" (give real numbers)
- **Finance application**: "Could this work for credit research / due diligence?" (yes, config-driven)
- **Scaling**: "What if you need 500 documents?" (chunking strategy, embedding search, retrieval agent tool loop)

---

## 14. Risk Mitigation

| Risk | Mitigation |
|---|---|
| Temporal leakage (biggest risk) | Hard cutoff filter at retrieval + evidence extraction; log all rejected docs; audit trail |
| LLM hallucinating evidence | Require `span_text` exact quotes; post-hoc verification against source |
| Single-source bias | Track source diversity per risk factor; flag if >60% evidence from one source |
| Adversarial reviewer rubber-stamping | Separated evaluation (Anthropic harness pattern); explicit prompt to find contradictions; score challenge quality |
| Industry-vs-company confusion | Peer benchmark agent provides baseline; adversarial reviewer checks specificity |
| Demo time overrun | Pre-cache full run; demo shows cached results with option to re-run specific nodes; 15 min slot gives more room |
| LLM cost during development | vLLM local inference eliminates API costs; thinking mode only for reasoning-heavy tasks |
| Dead loops in agent chains | Iteration counters on extraction and adversarial loops (TradingAgents-CN pattern) |

---

## 15. Success Criteria

### For the demo (15 min slot at AI Tinkerers HK, April 29, 2026):
- System produces structured risk factors with traceable evidence before cutoff
- Adversarial reviewer generates meaningful challenges (not rubber stamps)
- Backtest shows >=70% recall on ground truth events
- Full pipeline runs on local vLLM (no cloud API dependency)
- Audience can click through evidence chain from conclusion to source quote
- Show honest failures and messy experiments (event explicitly values this)
- Prepared for deep technical Q&A from finance AI engineers

### For the repo:
- Clean, typed, tested code that another engineer could extend
- Configuration-driven (new case = new YAML, not new code)
- All conclusions traceable to timestamped evidence
- Runs on local LLM (vLLM + Qwen) — no API key needed
- File-based artifacts for every run (audit trail)
- README tells a clear technical story
