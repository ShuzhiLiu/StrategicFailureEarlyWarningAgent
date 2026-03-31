# Iteration Log

Records what we tried, what we learned, and what we changed at each step.
This document captures the concrete approach that led to the final result.

---

## Iteration 0: Baseline — Can the pipeline run at all?

**Goal**: Run the current pipeline with stubs to verify graph compilation and execution.

**Bugs found and fixed**:
1. `ddgs` package missing — `langchain-community` expects `ddgs` (not just `duckduckgo-search`). Installed both.
2. Fan-out wiring wrong — `fan_out_analysts` was registered as a node returning `Send` objects. LangGraph requires `Send` to come from conditional edge functions. Fixed by merging fan-out into `route_after_extraction()` conditional edge.
3. Parallel analyst concurrent write conflict — all 3 analyst stubs wrote `current_stage` (a last-writer-wins field). LangGraph rejects concurrent writes to non-reducer fields. Fix: removed `current_stage` from parallel analyst return dicts.

**Result**: Pipeline runs end-to-end with stubs. Empty results but correct flow.

---

## Iteration 1: Evidence Extraction — First LLM node

**Goal**: Get evidence_extraction to produce structured EvidenceItem objects from retrieved docs using Qwen3.5.

**What we built**:
- `src/sfewa/prompts/extraction.py` — System/user prompt templates
- `src/sfewa/agents/evidence_extraction.py` — LLM call, JSON parsing, validation, temporal filter
- Fixed `.env` loading (added `dotenv.load_dotenv()` to main.py)
- Added `search_topics` from case config to PipelineState

**Bugs found and fixed**:
1. `.env` not loaded — `DEFAULT_LLM_MODEL` not set error. Added `load_dotenv()` to main.py.
2. First run: all 10 items post-cutoff → 0 accepted. Switched to using all 15 `search_topics` from case config.

**Result**: 8 evidence items extracted and accepted through temporal filter. DuckDuckGo results heavily biased toward recent post-cutoff articles. Non-thinking mode produces clean JSON without parse failures.

---

## Iteration 2: Analyst Nodes + Adversarial + Synthesis + Backtest — Full Pipeline

**Goal**: Implement all remaining nodes to complete Phase A (end-to-end flow).

**What we built**:
- `src/sfewa/prompts/analysis.py` — Shared analyst prompt template with per-analyst dimension descriptions
- `src/sfewa/agents/_analyst_base.py` — Shared analyst implementation (LLM call, JSON parse, validation, reporting)
- Updated `industry_analyst.py`, `company_analyst.py`, `peer_analyst.py` to use shared base
- `src/sfewa/prompts/adversarial.py` — Adversarial reviewer prompt (bias detection, counter-evidence)
- `src/sfewa/agents/adversarial.py` — Full implementation with thinking mode
- `src/sfewa/prompts/synthesis.py` — Risk synthesis prompt
- `src/sfewa/agents/risk_synthesis.py` — Full implementation with thinking mode, JSON parsing
- `src/sfewa/agents/backtest.py` — Full implementation with LLM-based matching
- Added `ground_truth_events` to PipelineState and initial state

**Full pipeline run result**:
```
init_case → retrieval (59 docs) → evidence_extraction (4 accepted, 12 rejected)
  → [industry(2 RF) | company(4 RF) | peer(3 RF)] in parallel
  → adversarial_review (5 challenges: 2 strong, 3 moderate)
  → risk_synthesis (HIGH, confidence 0.80)
  → backtest (gt_001: STRONG, gt_002: STRONG, gt_003: PARTIAL)
```

**Key metrics**:
- 9 risk factors across 8 dimensions
- Adversarial reviewer correctly challenged 2 factors as "strong" (policy dependency too speculative, execution severity inflated)
- Routing worked: 2/9 = 22.2% strong challenges < 50% → no loop back
- Risk synthesis correctly assessed HIGH risk at 0.80 confidence
- Backtest: 2 STRONG matches + 1 PARTIAL match against 3 ground truth events
- Risk memo is well-structured with all required sections

**What works well**:
- LangGraph fan-out + convergence runs correctly with parallel LLM calls
- Temporal filter catches post-cutoff articles (2025-05-20, 2026-03-12, etc.)
- Adversarial review is not rubber-stamping — it meaningfully challenges weak factors
- Thinking mode produces deeper analysis for adversarial + synthesis
- JSON parsing is robust — no failures across any node
- Reporting gives clear visibility into every pipeline step

**Known issues (Phase B)**:
1. Only 4 pre-cutoff evidence items — DuckDuckGo results are biased toward recent articles
2. Some evidence items may have incorrect dates (E003 references "reducing 10T yen plan" which is pre-cutoff knowledge but the source article may be post-cutoff)
3. UserWarning about `model_kwargs` parameters — cosmetic, should pass `top_p` and `extra_body` differently
4. Evidence items thin on China market data, peer comparisons — need more diverse search queries
5. Two risk factors share dimension "execution" (COM003, COM004) — should have unique dimensions per factor

**Phase A Status**: COMPLETE — Full pipeline flows end-to-end with real LLM calls, structured output, temporal filtering, adversarial review, and backtesting.

---

## Next Steps (Phase B — Quality Improvement)

Priority order:
1. **More pre-cutoff evidence**: Better search queries, possibly fetch full document content
2. **LLM world knowledge leakage**: E003 references investment cuts that may be from post-cutoff knowledge — need prompt engineering to constrain LLM to only snippet content
3. **Fix model_kwargs warning**: Move `top_p` and `extra_body` to explicit params in ChatOpenAI
4. **Prompt tuning**: Improve evidence extraction depth, analyst specificity
5. **Artifact saving**: Save run outputs to `outputs/{run_id}/` for audit trail
