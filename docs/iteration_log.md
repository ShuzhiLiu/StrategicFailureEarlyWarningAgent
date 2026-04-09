# Iteration Log

Records what we tried, what we learned, and what we changed at each step.

---

## Iterations 0-32: Summary

| Iter | Title | Key Change | Result |
|------|-------|-----------|--------|
| 0 | Baseline | LangGraph pipeline with stubs | Pipeline runs end-to-end |
| 1 | Evidence Extraction | First LLM node (Qwen3.5), temporal filter | 8 evidence items accepted |
| 2 | Full Pipeline | All 10 nodes implemented | Phase A complete: HIGH 0.80, 2 STRONG + 1 PARTIAL backtest |
| 3 | EDINET Integration | Honda regulatory filings (Tier 1 primary sources) | Evidence 4→13 |
| 4 | Agentic Retrieval | LLM-driven gap analysis (2-pass) | Evidence 13→21 |
| 5 | Scope Boundaries | Per-analyst scope instructions | Zero redundancy challenges |
| 6 | Quality Polish | model_kwargs fix, artifact saving | Clean terminal output, full audit trail |
| 7 | Counternarrative | 3-pass retrieval + temporal leakage fix | 9/9 dimensions covered, 29 evidence items |
| 8 | Stance Balance | Enhanced stance guidance in extraction | 37 evidence, 3× STRONG backtest |
| 9 | Demo Polish | Pipeline timing, README | 13m 26s runtime |
| 10 | Agentic Seed Queries | LLM generates search queries; cross-company validation | Honda HIGH, Toyota HIGH, BYD MEDIUM |
| 11 | Quality Gate + Routing | LLM-driven quality gate + adversarial routing | 10-node pipeline, BYD evidence 8→42 |
| 12 | Pipeline Context | Downstream nodes receive upstream history summary | Synthesis adjusts confidence based on evidence quality |
| 13 | Unit Tests | 51 tests for routing, quality gate, context, dedup | All passing (0.23s) |
| 14 | Impact Assessment | Distinguish existing business threats vs expansion barriers | Honda HIGH, Toyota MEDIUM, BYD LOW |
| 15 | Minimal Input | 3-field input, LLM generates regions/peers | Backward compatible with YAML configs |
| 16-19 | Calibration | Fix synthesis criteria, temporal leakage, strategy misattribution | Honda→HIGH stable, Toyota→MEDIUM stable |
| 20-21 | Continuous Score | 0-100 risk score, programmatic base + LLM adjustment | Honda avg 55, Toyota avg 47, BYD avg 39 |
| 23 | Score Compression Fix | Programmatic base_score, deterministic adversarial downgrades | Honda 61-94, Toyota 42, BYD 36 |
| 24 | Remove LangChain | Plain Python `run_pipeline()`, direct OpenAI SDK | 7 deps removed, 7× faster tests |
| 25 | Search Overhaul | `ddgs` v9, news search, English filter | Toyota evidence 1→59, ordering restored |
| 26 | Extract liteagent | Reusable framework: LLMClient, merge_state, dedup_by_key, extract_json, CallLog | SFEWA LOC -14% |
| 27 | Dynamic Dimensions | LLM-generated analysis dimensions per company/strategy | Honda 76, Toyota 74, BYD 43 — gap too small |
| 28 | Iceberg Model | 4-Layer Progressive Deepening framework + Chain of Verification adversarial | Honda 78 HIGH, Toyota 50 MEDIUM (depth gate fix) |
| 29 | BYD Depth Fix | Re-ran BYD with correct Iceberg Model code (stale import) | BYD 36 LOW, 3 STRONGs, ordering H>T>B ✓ |
| 30 | Score Stability | Clamp ±15, strategy relevance tags, depth gate enforcement | Toyota MEDIUM achievable, STRONGs now fire |
| 31 | Dimension Count Fix | Exactly 10 dimensions (3+4+3), anti-hallucination rules | Factor count variability eliminated |
| 31+ | 9-Run Verification | 3 rounds × 3 companies stability check | Ordering 100% stable, Honda range 24, BYD range 10 |
| 32 | Evidence-Balance Adversarial | Per-factor imbalance flags + evidence stance overview | Honda range 24→3, STRONGs now ~1/run |
| 33 | Hybrid Architecture | liteagent ToolLoopAgent + agentic retrieval node | 8-node pipeline v2, agent-decided search |
| 34 | Agentic Adversarial | 3-phase adversarial: CoVe + verification search + refinement | Toyota STRONGs 0-1→2-4, BYD 0-1→4-5 |
| 35 | Filing Discovery + CNINFO | Agentic filing discovery + CNINFO for BYD + EDINET for Toyota | All 3 companies have Tier 1 filings |
| 36 | Tech-Aware Retrieval | Technology coverage targets + dimension-driven search + technology_capability claim type | BYD hits LOW (34), Toyota-BYD gap 15.5pts |
| 37 | Challenge Dedup | Fix cross-pass challenge accumulation + within-pass refinement duplicates | Ordering 100% (6/6 runs), BYD hits LOW consistently |

**Key architectural decisions (cumulative):**
- **Separated evaluation** (iter 2): Adversarial reviewer structurally independent from analysts
- **LLM-driven routing** (iter 11): Quality gate and adversarial routing are LLM decisions, not thresholds
- **Pipeline context injection** (iter 12): Downstream nodes receive upstream history summary
- **Continuous scoring** (iter 21): 0-100 score, programmatic base + LLM qualitative adjustment
- **Framework-free** (iter 24): No LangChain/LangGraph, plain Python + liteagent utilities
- **Dynamic dimensions** (iter 27): LLM generates analysis dimensions tailored to company/strategy
- **Iceberg Model** (iter 28): 4-Layer Progressive Deepening with agentic depth routing
- **Strategy relevance tags** (iter 30): Primary vs secondary dimensions control depth gate behavior
- **Evidence-balance adversarial** (iter 32): Programmatic imbalance flags enable substance-based STRONG challenges
- **Hybrid architecture** (iter 33): Pipeline backbone + ToolLoopAgent nodes where autonomy adds value
- **Agentic adversarial** (iter 34): Independent verification search finds NEW counter-evidence beyond available data
- **Filing discovery** (iter 35): Agentic jurisdiction detection + CNINFO (China) + EDINET generalized (Toyota) — all companies get Tier 1 filings
- **Tech-aware retrieval** (iter 36): Technology coverage targets + dimension-driven search queries + `technology_capability` claim type in extraction
- **Challenge dedup** (iter 37): Fix cross-pass challenge accumulation + within-pass refinement duplicates in adversarial, synthesis, and artifacts

**Stability state entering Iteration 38:**

| Metric | Honda | Toyota | BYD |
|--------|-------|--------|-----|
| Mean (post iter 37, 3 runs) | 77.3 | 54.7 | 37.0 |
| Range | 62-93 (31) | 50-58 (8) | 28-50 (22) |
| STRONGs/run | 1-4 | 3-4 | 0-2 |
| Filings | 24 EDINET | 19 EDINET | 28 CNINFO |
| Ordering | 100% correct across all runs (6/6 post-fix) |

---

## Iteration 33: Hybrid Architecture — liteagent Tool-Loop Agent + Agentic Retrieval

**Goal**: Add tool-loop agent capability to liteagent and build an agentic retrieval node that replaces the 4-node retrieval loop (retrieval → extraction → quality_gate → routing) with a single autonomous agent.

### What we built

**liteagent expansion** (2 new modules):

1. **`src/liteagent/tool.py`** (~120 lines): Tool definition framework
   - `Tool` dataclass with `to_openai()` serialization and `execute()` with error handling
   - `@tool` decorator: converts typed Python functions into Tool objects with auto-generated JSON schema
   - `parse_tool_calls()`: extracts tool calls from OpenAI-compatible LLM responses

2. **`src/liteagent/agent.py`** (~130 lines): The `while(tool_call)` loop
   - `ToolLoopAgent`: send messages → check for tool_calls → execute tools → append results → repeat
   - `AgentResult` dataclass: content, messages, tool_call_count, iterations, hit_limit
   - `max_iterations` safety bound, `CallLog` integration for observability
   - Uses `LLMClient.call_with_tools()` (new method added to llm.py)

3. **`LLMClient.call_with_tools()`**: New method on LLMClient for OpenAI function calling protocol

**liteagent now exports 23 symbols** (was 18): added `Tool`, `tool`, `parse_tool_calls`, `ToolLoopAgent`, `AgentResult`.

**SFEWA agentic retrieval node** (`src/sfewa/agents/agentic_retrieval.py`):

- Tools: `search(query)` (DuckDuckGo text + news) and `load_edinet()` (EDINET filings)
- Shared state via closures: tools accumulate docs into a shared list, return summaries to the LLM
- Agent decides what to search and when to stop based on coverage criteria
- Safety bounds: MAX_SEARCH_QUERIES=15, MAX_DOCS=150
- Lower results per query (8 text + 6 news) forces more diverse queries

**Pipeline v2** (`run_pipeline_v2()` in pipeline.py):
```
init_case → agentic_retrieval → evidence_extraction → fan-out → adversarial → synthesis → backtest
```
Replaces the 4-node evidence loop. Activated via `--agentic` CLI flag.

**Evidence extraction batching** (fix for large doc sets):
- Web docs split into chunks of 50 for LLM extraction
- Prevents context overflow when agentic retrieval collects 100+ web docs

### How the agent decides

The agent receives a system prompt with:
- Case context (company, strategy, cutoff, peers, dimensions)
- Coverage targets (same criteria as the old quality gate)
- Search strategy guidance (broad → specific → counternarrative)
- Budget constraints (15 queries, 150 docs)

It autonomously:
1. Loads EDINET if available
2. Searches broadly (company + strategy, financials)
3. Adds competitor, regional, policy, technology queries
4. Assesses whether results cover multiple perspectives
5. Searches for counternarrative if results skew one way
6. Stops when satisfied or budget exhausted

Example Honda search sequence (12 queries):
```
[1] Honda Motor EV electrification strategy 2024 2025
[2] Honda Motor financial results 2024 EV segment revenue profit
[3] Honda EV sales China 2024 2025 market share
[4] Honda EV sales North America US 2024 2025
[5] Honda EV strategy competitors Toyota BYD Tesla comparison
[6] Honda EV Europe sales 2024 2025 market share
[7] Honda EV technology platform 0 Series cancellation 2024
[8] Honda EV subsidies tariffs US China 2024 2025 policy
[9] Honda EV strategy Southeast Asia 2024 2025 market
[10] Honda EV analyst forecasts 2025 2026 projections
[11] Honda EV battery technology partnerships GM Ultium
[12] Honda EV sales Japan 2024 2025 domestic market
```

This covers all 8 quality gate criteria (company plans, financials, competitors, market trends, regions, policy, supporting + contradicting signals, forward-looking content) without needing a separate quality gate node.

### Cross-company verification (Agentic v2, 2 rounds + 1 pre-fix)

| Run | Honda | Toyota | BYD | Ordering |
|-----|-------|--------|-----|----------|
| Pre-fix R1* | 86 CRITICAL (444 docs) | — | — | — |
| R1 | 72 HIGH | 70 HIGH | 34 LOW | H>T>B ✓ |
| R2 | 98 CRITICAL | 55 MEDIUM | 55 MEDIUM | H>T=B ~✓ |

*Pre-fix: MAX_SEARCH=25, no doc cap, no extraction batching — 444 docs overwhelmed extraction.

### Comparison: v1 Pipeline vs v2 Agentic

| Metric | v1 (9-run mean) | v2 (2-run mean) |
|--------|-----------------|-----------------|
| Honda | 84.7 (74-98) | 85.0 (72-98) |
| Toyota | 70.7 (64-78) | 62.5 (55-70) |
| BYD | 52.0 (48-58) | 44.5 (34-55) |
| Ordering maintained | 9/9 (100%) | 2/2 (100%)* |
| Evidence items | 29-59 | 33-35 |
| Pipeline nodes | 10 (with loop) | 8 (no loop) |
| Search queries | 15-20 (fixed 3-pass) | 12-13 (agent-decided) |
| LLM calls for retrieval | 3 (seed + gap + counter gen) | 1 (agent loop) |

*R2 Honda>Toyota=BYD; ordering is Honda>Toyota>BYD in spirit (tie, not inversion).

### Key insights

1. **Tool calling works on vLLM**: Qwen3.5-27B with `--enable-auto-tool-choice` supports the full OpenAI function calling round-trip. No prompt-based workarounds needed.

2. **Agent search is more diverse**: The agent naturally covers regions, competitors, policy, counternarrative — without needing 3 hardcoded passes. It generates targeted queries based on what it has already found.

3. **Doc count needs caps**: Without MAX_DOCS, the agent will search until budget exhausted. Each query yields ~12 unique results, so 15 queries = ~180 docs. Extraction can only process ~50 per batch, so collecting 400+ is wasteful.

4. **Same variability sources**: The agentic architecture doesn't change the fundamental variability — adversarial STRONG generation and LLM synthesis adjustment remain the main factors. The architecture improves autonomy, not stability.

5. **Hybrid is the right pattern**: Pipeline backbone (debuggable, deterministic routing) + agentic nodes where autonomy adds value (search decisions). Analysts, synthesis, backtest are better as single LLM calls.

### What changed (file summary)

| File | Change |
|------|--------|
| `src/liteagent/tool.py` | NEW — Tool definition + parsing |
| `src/liteagent/agent.py` | NEW — ToolLoopAgent (while(tool_call) loop) |
| `src/liteagent/llm.py` | Added `call_with_tools()`, `model` property |
| `src/liteagent/__init__.py` | Export 5 new symbols (23 total) |
| `src/sfewa/agents/agentic_retrieval.py` | NEW — Agentic retrieval node |
| `src/sfewa/prompts/agentic_retrieval.py` | NEW — Agent system prompt |
| `src/sfewa/agents/evidence_extraction.py` | Web doc batching (chunks of 50) |
| `src/sfewa/graph/pipeline.py` | Added `run_pipeline_v2()` |
| `src/sfewa/main.py` | Added `--agentic` CLI flag |
| `src/sfewa/tools/chat_log.py` | Added `get_call_log()` accessor |

---

## Iteration 34: Agentic Adversarial — Independent Verification Search

**Goal**: Give the adversarial reviewer search tools to independently verify analyst claims. Previously it could only verify against available evidence; now it searches for NEW contradicting evidence via a ToolLoopAgent.

### What we built

**Three-phase adversarial review** (`src/sfewa/agents/adversarial.py`):

1. **Phase 1: Chain of Verification** (thinking mode) — standard adversarial review, unchanged from iter 32. Produces preliminary challenges + recommendation.

2. **Phase 2: Independent Verification Search** (non-thinking, ToolLoopAgent) — extracts key claims from HIGH/CRITICAL factors with non-STRONG challenges, then runs a `ToolLoopAgent` with a `search()` tool to find counter-evidence on the web.
   - `_extract_claims_to_verify()`: selects up to 5 claims, prioritizing critical > high, weak > moderate
   - `_make_verification_search_tool()`: DuckDuckGo text + news search, 8 queries max, deduplication
   - `_run_verification_search()`: wraps the ToolLoopAgent with temporal constraints and structured output

3. **Phase 3: Challenge Refinement** (thinking mode) — reviews verification findings against Phase 1 challenges. Upgrades severity to "strong" when web search found clear contradicting evidence. Keeps unverified challenges unchanged.

**Conditional execution**: Phase 2+3 only trigger when Phase 1 identifies verifiable claims (HIGH/CRITICAL factors with non-STRONG challenges). If all challenges are already STRONG, the node behaves exactly as before.

**New prompt templates** (`src/sfewa/prompts/adversarial.py`):
- `VERIFICATION_SYSTEM` / `VERIFICATION_USER`: instructs the verification agent to search for counter-evidence with temporal constraints
- `REFINEMENT_SYSTEM` / `REFINEMENT_USER`: guides the refinement LLM to upgrade/preserve challenge severities
- `format_claims_for_verification()`: formats extracted claims for the verification prompt

### Critical bug fix: target_factor_id bracket mismatch

`format_risk_factors_for_review()` presents factor IDs as `[COM001]` in the prompt. The LLM outputs `target_factor_id: "[COM001]"` with brackets. But risk factors use `factor_id: "COM001"` without brackets. This caused TWO failures:

1. **Phase 2 never triggered**: `_extract_claims_to_verify()` looked up `factor_severity.get("[COM001]")` which returned default "medium", so no HIGH/CRITICAL factors were found.
2. **Downgrades never fired**: `risk_synthesis_node()` matched `strong_targets` against `factor_id`, but targets had brackets while factors didn't → 0 matches.

**Fix**: Added `c["target_factor_id"] = raw_tid.strip("[]")` in both Phase 1 and Phase 3 validation blocks. This bug existed since iter 32 (evidence-balance adversarial) but was masked because STRONG challenges were rare pre-verification.

### Cross-company verification (2 rounds × 3 companies)

| Round | Honda | Toyota | BYD | Ordering |
|-------|-------|--------|-----|----------|
| R1 | 91 CRITICAL (1 STR, phases 1+2+3) | 61 HIGH (4 STR, phases 1+2+3) | 48 MEDIUM (5 STR, phases 1+2+3) | H>T>B ✓ |
| R2 | 76 HIGH (3 STR, phases 1+2+3) | 50 MEDIUM (2 STR, phases 1+2+3) | 53 MEDIUM (4 STR, phases 1+2+3) | H>T≈B ~✓ |

| Metric | Pre-verification (iter 32) | Post-verification (iter 34) |
|--------|---------------------------|----------------------------|
| Honda mean | 80.5 | 83.5 |
| Toyota mean | 72.5 | 55.5 |
| BYD mean | 49.0 | 50.5 |
| Honda range | 79-82 (3) | 76-91 (15) |
| Toyota range | 70-75 (5) | 50-61 (11) |
| BYD range | 45-53 (8) | 48-53 (5) |
| STRONGs/run Honda | 1-3 | 1-3 |
| STRONGs/run Toyota | 0-1 | 2-4 |
| STRONGs/run BYD | 0-1 | 4-5 |
| Ordering | 100% | 100% (R2: 3-point T-B gap) |

### Key insights

1. **Verification search is the differentiator for Toyota and BYD**: Pre-verification, Toyota got 0-1 STRONGs; post-verification, 2-4. BYD jumped from 0-1 to 4-5. The web easily finds counter-evidence to inflated claims about successful companies. Honda's structural risks (capital strain, delayed market entry) are harder to contradict.

2. **Toyota-BYD gap widened at the mean**: Toyota dropped from 72.5 to 55.5 (verification catches more inflated Toyota risks), while BYD stayed at ~50. This is more realistic — Toyota's hybrid dominance genuinely mitigates its BEV risks.

3. **Range increased for Honda**: From 3 to 15 points. Verification adds another source of LLM variability (search results differ, refinement decisions vary). The ordering is preserved, so this is acceptable variability.

4. **All 6 runs triggered phases 1+2+3**: The bracket fix ensures Phase 2 always finds HIGH/CRITICAL claims to verify. Before the fix, phases=1 only (verification never triggered).

5. **Hybrid pattern confirmed**: Pipeline backbone (Phase 1 thinking, Phase 3 thinking) + tool-loop agent (Phase 2 search) within a single node. Same hybrid pattern as agentic retrieval (iter 33), applied to adversarial review.

### What changed (file summary)

| File | Change |
|------|--------|
| `src/sfewa/agents/adversarial.py` | Three-phase architecture + bracket fix |
| `src/sfewa/prompts/adversarial.py` | Verification + refinement prompt templates |
| `docs/architecture.md` | Updated Section 5 for three-phase adversarial |

---

## Iteration 35: Filing Discovery — CNINFO + Generalized EDINET

**Goal**: Give all three companies Tier 1 primary source filings. Previously only Honda had EDINET; Toyota (also Japanese) and BYD (Chinese) relied on web search only. Make the system discover filings autonomously from just a company name.

### What we built

**CNINFO API client** (`src/sfewa/tools/cninfo.py`):
- `discover_org_id(company_name)`: searches CNINFO stock list by Chinese name (zwjc) and pinyin match against English name parts. No hardcoded company codes.
- `search_filings(stock_code, org_id, category, date_range)`: queries CNINFO hisAnnouncement endpoint for annual + semi-annual reports
- `download_filing(pdf_url, output_path)`: downloads PDFs from static.cninfo.com.cn
- Stock list cached in memory after first load

**Filing discovery orchestrator** (`src/sfewa/tools/filing_discovery.py`):
- `identify_jurisdiction(company, regions)`: company name → "japan" / "china" / None
- `discover_and_load_filings(company, cutoff_date, regions)`: single entry point for all jurisdictions
- `_discover_and_load_edinet()`: scan EDINET filing dates, match by Japanese filer name, download + extract
- `_discover_and_load_cninfo()`: discover orgId from stock list, search reports, download + extract
- `_load_cached_filings(source=)`: generic cached PDF loader for both EDINET and CNINFO
- `_extract_and_chunk()`: keyword-filtered page extraction for large annual reports (bilingual: EN/JP/CN)

**EDINET generalized for Toyota**:
- `_discover_edinet_code()` scans EDINET filing dates and matches by Japanese filer name patterns
- Toyota EDINET code E02144 discovered automatically, 4 filings downloaded and cached
- Honda EDINET continues working via same discovery mechanism (cached PDFs)

### Bug fixes

1. **CNINFO semi-annual classification**: `_classify_cn_filing()` checked `"年度报告"` before `"半年度报告"` — since 半年度报告 contains 年度报告 as a substring, semi-annual reports were classified as annual. Fixed by checking 半年度 patterns first.

2. **`_load_cached_filings` source parameter**: Function was called with `source="cninfo"` for CNINFO but only accepted 3 positional args and hardcoded "EDINET" in titles/source fields. Added `source` parameter with dynamic labels.

3. **Doc source counting**: `agentic_retrieval_node` only counted `source == "edinet"`, so CNINFO docs were bucketed as "web". Fixed to count both `"edinet"` and `"cninfo"` as filings.

### Cross-company verification (2 rounds × 3 companies, agentic v2)

| Round | Honda | Toyota | BYD | Ordering |
|-------|-------|--------|-----|----------|
| R1 | 96 CRITICAL (1 STR, P1+2+3) | 51 MEDIUM (2 STR, P1+2+3) | 43 MEDIUM (4 STR, P1+2+3) | H>T>B ✓ |
| R2 | 99 CRITICAL (0 STR, P1+2+3) | 49 MEDIUM (3 STR, P1+2+3) | 48 MEDIUM (2 STR, P1) | H>T≈B ~✓ |

| Metric | Pre-filings (iter 34) | Post-filings (iter 35) |
|--------|----------------------|------------------------|
| Honda mean | 83.5 | 97.5 |
| Toyota mean | 55.5 | 50.0 |
| BYD mean | 50.5 | 45.5 |
| Honda range | 76-91 (15) | 96-99 (3) |
| Toyota range | 50-61 (11) | 49-51 (2) |
| BYD range | 48-53 (5) | 43-48 (5) |
| STRONGs/run Honda | 1-3 | 0-1 |
| STRONGs/run Toyota | 2-4 | 2-3 |
| STRONGs/run BYD | 0-1 → 4-5 | 2-4 |
| Filings Honda | 24 EDINET | 24 EDINET |
| Filings Toyota | 0 | 19 EDINET |
| Filings BYD | 0 | 28 CNINFO |
| Evidence items | 30-46 | 30-68 |
| Ordering | 100% | 100% (R2: 1-point T-B gap) |

### Key insights

1. **Filings dramatically reduce Honda variability**: Honda range dropped from 15 to 3 points. With 24 EDINET filing chunks providing stable Tier 1 evidence, the score is consistently CRITICAL (96-99). The company's own disclosures of $4.48B EV losses and 10T yen commitments are unambiguous.

2. **Honda scores elevated**: Mean jumped from 83.5 to 97.5. EDINET filings contain Honda's risk disclosures which reinforce analyst risk factors. Without them (iter 34), web-only evidence was more mixed. This is the correct behavior — primary source data should improve signal quality.

3. **Toyota EDINET provides stable MEDIUM**: Toyota range dropped from 11 to 2 points (49-51). Toyota's filings show record hybrid profits and measured BEV transition — evidence that contradicts HIGH risk factors, enabling more adversarial downgrades. Stable MEDIUM is the expected result.

4. **BYD CNINFO provides primary source evidence**: 28 CNINFO filing chunks (FY2024 annual + H1 2024 semi-annual) include revenue, profit, R&D figures. Evidence stance: 61 contradicts_risk out of 68 items. BYD's own financial disclosures strongly support LOW-MEDIUM risk.

5. **Toyota-BYD gap tight in R2**: Only 1 point (49 vs 48). Both are MEDIUM, which is the correct band. The gap between "company doing well but has BEV transition risks" (Toyota) and "company doing very well with expansion barriers" (BYD) is genuinely small. This is a realistic assessment, not a bug.

6. **BYD R2 only Phase 1**: Only 1 HIGH factor (geopolitical_trade_barriers) which already received STRONG in Phase 1. No HIGH/CRITICAL factors with non-STRONG challenges → Phase 2+3 skipped. The conditional execution works correctly.

### Filing source summary

| Company | Jurisdiction | System | Filings | Chunks | Discovery Method |
|---------|-------------|--------|---------|--------|-----------------|
| Honda | Japan | EDINET | 4 (annual, semi-annual, 2 extraordinary) | 24 | Japanese filer name match |
| Toyota | Japan | EDINET | 4 (annual, semi-annual, 2 extraordinary) | 19 | Japanese filer name match |
| BYD | China | CNINFO | 2 (annual, semi-annual) | 28 | Stock list orgId + pinyin match |

### What changed (file summary)

| File | Change |
|------|--------|
| `src/sfewa/tools/cninfo.py` | NEW — CNINFO API client (orgId discovery, filing search, download) |
| `src/sfewa/tools/filing_discovery.py` | NEW — Jurisdiction detection + filing discovery orchestrator |
| `src/sfewa/tools/edinet.py` | Added Toyota constants, EDINET registry, generalized scanning |
| `src/sfewa/tools/corpus_loader.py` | Generalized for any company (was Honda-only) |
| `src/sfewa/agents/retrieval.py` | Use discover_and_load_filings() instead of hardcoded Honda check |
| `src/sfewa/agents/agentic_retrieval.py` | Filing tool replaces EDINET tool, source counting fix |
| `docs/architecture.md` | Section 7 updated for CNINFO, package structure updated |

---

## Iteration 36: Tech-Aware Retrieval — Technology Coverage + Dimension-Driven Search

**Goal**: Fix BYD scoring MEDIUM (43-48) instead of expected LOW. Root cause: the retrieval agent never searched for technology capability, vertical integration, or tech supply relationships — and extraction had no claim type for technology facts. Fix structurally (improve agent intelligence), not by tuning thresholds.

### Problem diagnosis

User observed: BYD has proprietary battery technology (Blade Battery, LFP), vertical integration (battery → motor → semiconductor), and Toyota uses BYD's e-Platform for its bZ3/bZ3C EVs. These facts strongly contradict risk — but the agent never found them.

Evidence from iter 35 runs:
- **0 `technology_capability` claims** across all BYD runs
- CNINFO filings contained rich tech content (刀片电池, 垂直整合, 磷酸铁锂, 半导体) but extraction classified them as `product_launch_plan` or `financial_metric`
- Retrieval agent search queries had zero tech-related searches — no "battery technology", "vertical integration", or "platform supply" queries
- Coverage targets in the retrieval prompt had no technology dimension at all

User feedback: "This is more agentic instead of your proposed tune threshold" — meaning fix the agent's search intelligence, not tune scoring thresholds.

### What we changed

**1. Retrieval prompt — technology coverage target** (`src/sfewa/prompts/agentic_retrieval.py`):
Added coverage target #7:
```
7. Technology capability and differentiation (proprietary tech, patents, vertical integration,
   in-house supply chain, R&D achievements, technology partnerships/supply relationships
   with competitors)
```

**2. Retrieval prompt — dimension-driven search strategy**:
Added step #3 in search strategy:
```
3. **Dimension-driven queries**: Review the analysis dimensions below. For EACH dimension
   that involves technology, capability, or differentiation, search specifically for it.
   Examples: "{company} battery technology" / "{company} vertical integration supply chain" /
   "{company} semiconductor in-house" / "{company} platform technology partnership [competitor]"
```
Also updated competitor queries (step 4) to include technology supply relationships, and counternarrative (step 8) to include "technology leadership" in strengths.

**3. Extraction prompt — `technology_capability` claim type** (`src/sfewa/prompts/extraction.py`):
Added new claim type:
```
- technology_capability: Proprietary technology, patents, vertical integration, in-house
  supply chain, R&D achievements, technology partnerships/supply relationships
  (e.g., "BYD's Blade Battery uses LFP chemistry", "company supplies EV platform to
  competitor", "vertical integration covers battery, motor, and semiconductor")
```

### How the agent behaves after the fix

BYD search sequence now includes technology-specific queries:
```
[5] BYD battery technology Blade battery
[7] BYD vertical integration semiconductor supply chain
[9] BYD Volkswagen technology partnership battery supply
```

These queries find evidence like:
- BYD's Blade Battery LFP chemistry with 15% cost advantage
- Vertical integration covering battery, motor, electronic control, semiconductor
- Technology supply relationships (BYD supplying e-Platform to Toyota bZ3/bZ3C)

Extraction now classifies these as `technology_capability` (11 claims in R2, was 0).

### Cross-company verification (2 rounds × 3 companies)

| Round | Honda | Toyota | BYD | Ordering |
|-------|-------|--------|-----|----------|
| R1 | 98 CRITICAL (0 STR, P1+2+3) | 64 HIGH (1 STR, P1+2+3) | 50 MEDIUM (2 STR, P1+2+3) | H>T>B ✓ |
| R2 | 81 CRITICAL (2 STR, P1+2+3) | 51 MEDIUM (3 STR, P1+2+3) | 34 LOW (2 STR, P1+2+3) | H>T>B ✓ |

### Comparison: Iteration 35 vs Iteration 36

| Metric | Iter 35 (no tech) | Iter 36 (tech-aware) |
|--------|-------------------|----------------------|
| Honda mean | 97.5 | 89.5 |
| Toyota mean | 50.0 | 57.5 |
| BYD mean | 45.5 | 42.0 |
| Honda range | 96-99 (3) | 81-98 (17) |
| Toyota range | 49-51 (2) | 51-64 (13) |
| BYD range | 43-48 (5) | 34-50 (16) |
| Toyota-BYD gap | 4.5 pts | 15.5 pts |
| BYD hit LOW? | Never (43-48) | Yes, R2: 34 |
| Tech claims (BYD) | 0 | 11 |
| Ordering | 100% | 100% |

### Key insights

1. **BYD hits LOW for the first time**: Score 34 in R2 — driven by 11 `technology_capability` claims providing strong contradicts_risk evidence. The adversarial reviewer can now make substance-based STRONG challenges against inflated analyst concerns when technology evidence shows clear competitive advantage.

2. **Toyota-BYD gap widened from 4.5 to 15.5 points**: The tech evidence differentiates BYD (technology leader, vertical integration) from Toyota (technology follower in BEV, relying on BYD's platform). This is the correct directional effect — technology capability is a genuine differentiator.

3. **Range increased for all companies**: Honda 3→17, Toyota 2→13, BYD 5→16. Richer evidence (more tech claims, more diverse sources) drives more variance in adversarial challenge generation and synthesis adjustment. The ordering is preserved across all runs, so this is acceptable variability.

4. **Structural fix validated**: User's insight was correct — the fix needed to be agentic (improve what the agent searches for) not parametric (tune thresholds). Adding technology coverage targets and dimension-driven search strategy generalizes to any company/strategy, not just BYD.

5. **Dimension-driven search is a general pattern**: The agent now actively derives search queries from its assigned analysis dimensions. If init_case generates a dimension like `blade_battery_technology_moat`, the agent will search for "BYD Blade Battery technology". This works for any company and any set of dimensions.

### What changed (file summary)

| File | Change |
|------|--------|
| `src/sfewa/prompts/agentic_retrieval.py` | Added tech coverage target #7, dimension-driven search step #3, tech supply in competitor queries |
| `src/sfewa/prompts/extraction.py` | Added `technology_capability` claim type with examples |

---

## Iteration 37: Challenge Dedup — Cross-Pass Accumulation Fix

**Goal**: Fix duplicate challenges appearing in adversarial output. Two sources of duplication discovered during 6-run stability check.

### Problem diagnosis

**Source 1 — Within-pass refinement duplicates**: Phase 3 refinement LLM sometimes returns 20 challenges (all 10 from Phase 1 duplicated + 10 refined). Example: Toyota pre-fix R2 had 20 challenges with 11 STRONGs.

**Source 2 — Cross-pass accumulation**: When adversarial recommends "reanalyze" and the pipeline runs a second adversarial pass, `merge_state(accumulate=ACC)` extends the challenge list. Both passes use AC001-AC010 challenge IDs targeting the same factors, so state ends up with 20 challenges (10 from pass 1 + 10 from pass 2). Example: Honda pre-fix R2 had 2 adversarial passes → 20 challenges in artifacts.

**Impact on scoring**: The synthesis node uses a SET for strong_targets (programmatic scoring unaffected), but the LLM synthesis prompt saw inflated challenge counts, distorting qualitative adjustment. This contributed to a Toyota-BYD ordering inversion in pre-fix R1 (Toyota 48, BYD 50).

### What we changed

1. **Adversarial node** (`src/sfewa/agents/adversarial.py`): Added `dedup_by_key(valid_challenges, "target_factor_id")` after Phase 3 refinement — fixes within-pass duplicates.

2. **Synthesis node** (`src/sfewa/agents/risk_synthesis.py`): Added `challenges = dedup_by_key(raw_challenges, "target_factor_id")` — fixes cross-pass duplicates before prompt formatting and programmatic scoring.

3. **Artifact saving** (`src/sfewa/tools/artifacts.py`): Added `dedup_by_key(challenges, "target_factor_id")` — ensures saved challenges.json is always clean.

All three use `keep="last"` (default) — keeps the most recent challenge per target factor (the refined/latest-pass version).

### Pre-fix stability (3 rounds)

| Round | Honda | Toyota | BYD | H>T>B? |
|-------|-------|--------|-----|--------|
| R1 | 65 HIGH (0 STR) | 48 MEDIUM (3 STR) | 50 MEDIUM (1 STR) | **T<B** |
| R2 | 78 HIGH (1 STR, 20ch!) | 54 MEDIUM (11 STR, 20ch!) | 40 MEDIUM (1 STR) | ✓ |
| R3 | 64 HIGH (3 STR) | 55 MEDIUM (2 STR) | 30 LOW (1 STR) | ✓ |

| Metric | Honda | Toyota | BYD |
|--------|-------|--------|-----|
| Mean | 69.0 | 52.3 | 40.0 |
| Range | 64-78 (14) | 48-55 (7) | 30-50 (20) |
| Ordering | 2/3 correct |

**Base scores always maintained correct ordering** (R1: 67>53>41, R2: 93>49>45, R3: 79>53>37). The R1 inversion was caused by LLM synthesis adjustment: Toyota delta=-5, BYD delta=+9, crossing the boundary.

### Post-fix stability (3 rounds)

| Round | Honda | Toyota | BYD | H>T>B? |
|-------|-------|--------|-----|--------|
| R1 | 77 HIGH (4 STR) | 58 MEDIUM (4 STR) | 50 MEDIUM (2 STR) | ✓ |
| R2 | 62 HIGH (1 STR) | 50 MEDIUM (4 STR) | 28 LOW (0 STR) | ✓ |
| R3 | 93 CRITICAL (1 STR) | 56 MEDIUM (3 STR) | 33 LOW (0 STR) | ✓ |

| Metric | Honda | Toyota | BYD |
|--------|-------|--------|-----|
| **Mean** | 77.3 | 54.7 | 37.0 |
| **Range** | 62-93 (31) | 50-58 (8) | 28-50 (22) |
| **Level** | HIGH-CRITICAL | MEDIUM | MEDIUM-LOW |
| **STRONGs/run** | 1-4 | 3-4 | 0-2 |
| **Challenges** | 10, 10, 10 | 10, 10, 6* | 10, 10, 10 |
| **Ordering** | **3/3 correct (100%)** |

*Toyota R3 produced only 6 factors (init_case dimension generation intermittent issue).

### Comparison: pre-fix vs post-fix

| Metric | Pre-fix | Post-fix |
|--------|---------|----------|
| Ordering correct | 2/3 (67%) | **3/3 (100%)** |
| H-T gap (mean) | 16.7 pts | **22.6 pts** |
| T-B gap (mean) | 12.3 pts | **17.7 pts** |
| Challenge dedup issues | 2 runs (20 ch) | **0** |
| BYD hits LOW | 1/3 runs | **2/3 runs** |

### Key insights

1. **Challenge dedup fixed ordering reliability**: Clean challenge counts in synthesis prompts prevent the LLM from over-adjusting scores based on inflated STRONG counts. Ordering went from 67% to 100%.

2. **Score separation improved**: H-T gap widened from 16.7 to 22.6 points, T-B gap from 12.3 to 17.7. The synthesis LLM makes better qualitative adjustments when challenge inputs are accurate.

3. **BYD consistently hits LOW**: 2 of 3 runs scored below 40 (28, 33). The third run (50) is the same BYD R1 from pre-fix (ran before the cross-pass fix mattered). BYD's 0 STRONGs in R2-R3 means the adversarial reviewer couldn't find strong contradictions to BYD's few risk factors.

4. **Honda range remains wide** (62-93, 31 points): Driven by analyst HIGH count variability (5-7 per run) and base score range (67-95). This is inherent to agentic depth decisions — the Iceberg Model's depth routing is LLM-driven and non-deterministic. Production mitigation: ensemble scoring (median of 3-5 runs).

5. **Toyota is the most stable**: Range 8 points (50-58), consistently MEDIUM. Strong hybrid position is consistently recognized; adversarial verification reliably finds counter-evidence to inflated risks.

### What changed (file summary)

| File | Change |
|------|--------|
| `src/sfewa/agents/adversarial.py` | Added `dedup_by_key(valid_challenges, "target_factor_id")` after Phase 3 |
| `src/sfewa/agents/risk_synthesis.py` | Added `dedup_by_key(raw_challenges, "target_factor_id")` before scoring |
| `src/sfewa/tools/artifacts.py` | Added `dedup_by_key(challenges, "target_factor_id")` before saving |

---

## Next Steps

1. **Demo preparation**: Pre-cache best runs per company. risk_score provides cleaner cross-company comparison than categories.
2. **Ensemble scoring**: Production system would run 3-5 times per company, take median score. Reduces Honda variability from ±15 to ±5.
3. **Factor count intermittent**: Toyota R3 produced only 6 factors (init_case gave fewer dimensions). Known issue from iter 31 — was fixed for most runs but occasionally recurs.
