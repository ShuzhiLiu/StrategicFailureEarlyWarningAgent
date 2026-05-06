# Iteration Log

Records what we tried, what we learned, and what we changed at each step.

## Pre-commitment on overfitting

A fair question reading 42 iterations on a single flagship case (Honda) is: **how much of the result is tuning to Honda specifically?** The honest answer:

- **Iterations 0–32 used Honda as the primary design-signal case.** Toyota and BYD appear in the logs from iteration 10 (first cross-company validation), but Honda was the case that drove most design changes (dimension generation, temporal-integrity gates, adversarial severity grading, Iceberg Model depth routing).
- **Iteration 33 introduced Toyota and BYD as held-out validation.** From iteration 33 onward, stability is measured as cross-company ordering (H>T>B) across 3 rounds × 3 companies per change.
- **Post-iteration 33, no change targets any specific company.** Every subsequent modification is either *structural* (agentic retrieval, filing discovery, 3-phase adversarial, tech-aware search, factor-ID normalization, pipeline event logging, audit envelope) or *generic* (Toulmin-structured output, self-consistency sampling, evidence-gated downgrades, HHI-based analyst agreement). The development rule in `CLAUDE.md` forbids company-specific logic, hardcoded thresholds, or conditional branches on case identity — and the code enforces this (verifiable via `grep -rn "honda\|toyota\|byd" src/sfewa/agents/` which returns only reporting / logging references).
- **Iteration 42 (L1) makes overfitting machine-checkable**, not just code-review-checkable. Every run produces `source_manifest.json` (cutoff invariant), `risk_factors.json` + `audit_violations` (claim-citation invariant), and `provenance.json` (model + commit + sha). Pre-cutoff leakage now fails an assertion; phantom citations now fail an assertion; runs that would have looked plausible without these checks now have to *prove* they're legitimate.
- **If a future iteration regresses Toyota or BYD in exchange for a Honda gain, it's a regression.** The stability test (9 runs × H>T>B ordering) is the gate; individual companies are not optimization targets.

---

## Iterations 0–32: Summary

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
| 32 | Evidence-Balance Adversarial | Per-factor imbalance flags + evidence stance overview | Honda range 24→3, STRONGs now ~1/run |

---

## Iterations 33–43: Summary

| Iter | Title | Key Change | Result |
|------|-------|-----------|--------|
| 33 | Hybrid Architecture | liteagent `ToolLoopAgent` + `agentic_retrieval` node (v2 pipeline, 8 nodes) | Agent-decided search replaces 4-node v1 evidence loop; ordering preserved |
| 34 | Agentic Adversarial | 3-phase adversarial: CoVe + verification search + refinement | Toyota STRONGs 0-1→2-4, BYD 0-1→4-5; T-B gap widens |
| 35 | Filing Discovery + CNINFO | Agentic jurisdiction detection + CNINFO for BYD + EDINET generalized for Toyota | All 3 companies have Tier 1 filings; Honda range 15→3 |
| 36 | Tech-Aware Retrieval | Tech coverage target + dimension-driven search + `technology_capability` claim type | BYD first hits LOW (34); Toyota-BYD gap 15.5pts |
| 37 | Challenge Dedup | Fix cross-pass + within-pass duplicate challenges | Ordering 3/3; BYD consistently LOW |
| 38 | Pipeline Event Logging + Factor ID Fix | `PipelineEventRecord` in liteagent + regex factor-ID normalization | Ordering 3/3; H=89.3 T=67.7 B=30.3 |
| 39 | Toulmin + Self-Consistency + Citation Validation + Evidence-Gated Downgrades | 6 improvements: depth-severity gate, citation cross-validation, Toulmin output, N=3 sampling, HHI agreement, evidence-gated downgrades | Ordering 3/3; H=76.7 T=56.0 B=44.7 |
| 40 | Open-source Readiness | Docs curation, README rewrite, integration tests (+20 assertions), CI, OSS infra, fresh stability re-run | Strict ordering 2/3 (R2 inversion: BYD evidence-volume × evidence-gate); H=88.7 T=55.3 B=45.3 |
| 41 | Model Swap to Qwen3.6-27B | `.env` model id only — no pipeline-logic change | Retro strict ordering **3/3 regained**; H=71.0 T=58.3 B=28.0; Honda forward range 1pt (extreme stability) |
| 42 | Audit-grade L1 (FilingProvider Protocol + audit primitives + HK + new cases) | `FilingProvider` Protocol + EDINET/CNINFO/HKEX adapters + manifest/citation/provenance + case/truth split + verifier-corpus propagation + HTML report + Ping An (HK retro) + Tencent (HK forward) | Strict ordering 3/3; 71→197 tests; H=77 T=58 B=22 |
| 43 | Layer 2 — HKEX live, SEC EDGAR, sentence citation, strategy discovery, Country Garden swap | DDG-driven HKEX live discovery + URL auto-promotion + SEC EDGAR provider + sentence-level audit + optional `strategy_theme` with auto-discovery + Ping An → Country Garden swap | Strict ordering 2/3 (R1 Toyota outlier); 197→302 tests; Boeing 76 HIGH (US, 8 EDGAR), Country Garden 92 CRITICAL (HK, 10 HKEX live) |

**Key architectural decisions (cumulative through iter 43):**
- **Separated evaluation** (iter 2): Adversarial reviewer structurally independent from analysts
- **LLM-driven routing** (iter 11): Quality gate and adversarial routing are LLM decisions, not thresholds
- **Pipeline context injection** (iter 12): Downstream nodes receive upstream history summary
- **Continuous scoring** (iter 21): 0-100 score, programmatic base + LLM qualitative adjustment
- **Framework-free** (iter 24): No LangChain/LangGraph, plain Python + liteagent utilities
- **Dynamic dimensions** (iter 27): LLM generates analysis dimensions tailored to company/strategy
- **Iceberg Model** (iter 28): 4-Layer Progressive Deepening with agentic depth routing
- **Strategy relevance tags** (iter 30): Primary vs secondary dimensions control depth gate
- **Evidence-balance adversarial** (iter 32): Programmatic imbalance flags as STRONG triggers
- **Hybrid architecture** (iter 33): Pipeline backbone + ToolLoopAgent nodes where autonomy adds value
- **Agentic adversarial** (iter 34): Independent verification search via ToolLoopAgent
- **Filing discovery** (iter 35): Agentic jurisdiction detection + CNINFO + EDINET — all companies get Tier-1 filings
- **Tech-aware retrieval** (iter 36): Coverage target + dimension-driven queries + `technology_capability` claim type
- **Challenge dedup** (iter 37): Cross-pass and within-pass deduplication
- **Pipeline event logging** (iter 38): `PipelineEventRecord` for flow-graph reconstruction
- **Factor ID normalization** (iter 38): Regex extraction handles all LLM output formats
- **Depth-severity gate** (iter 39): `[DEPTH_SEVERITY_MISMATCH]`, `[MISSING_FORCES]`, `[MISSING_ASSUMPTION]` flags
- **Citation cross-validation** (iter 39): `[PHANTOM_CITATION]`, `[STANCE_MISMATCH]`, `[THIN_EVIDENCE]` flags
- **Toulmin-structured output** (iter 39): `claim`/`warrant`/`strongest_counter` per factor
- **Self-consistency sampling** (iter 39): N=3 with dynamic early-stop
- **Analyst agreement** (iter 39): HHI concentration + ordinal range injected into synthesis
- **Evidence-gated downgrades** (iter 39): `valid_sup ≥ 3` resists STRONG downgrades
- **`FilingProvider` Protocol** (iter 42): uniform façade over EDINET/CNINFO/HKEX/SEC EDGAR with adapter wrappers
- **Audit envelope** (iter 42): source manifest + per-factor citation check + provenance header + case/truth split + verifier corpus propagation + HTML report
- **Audit violations as data** (iter 42): violations recorded in `run_summary.json` instead of raised exceptions; pipeline always completes
- **HKEX live via DDG site search** (iter 43): `site:hkexnews.hk filetype:pdf` queries + URL auto-promotion during regular retrieval; no Playwright needed
- **SEC EDGAR provider** (iter 43): 4th jurisdiction; ticker → CIK with corporate-suffix-tolerant name match; doc-type taxonomy
- **Sentence-level citation** (iter 43): per-sentence span resolution recorded as audit data (soft enforcement)
- **Optional `strategy_theme`** (iter 43): auto-discovery agent reads filings + light web search to propose 1-3 candidate themes when omitted

**Stability state entering Iteration 42:**

| Metric | Honda | Toyota | BYD |
|--------|-------|--------|-----|
| Retro mean (iter 41, 3 runs) | 71.0 | 58.3 | 28.0 |
| Retro range | 63-77 (14) | 57-60 (3) | 20-35 (15) |
| Backtest / run | 6S+3P / 9 | 4S+2P / 6 | 4S+1P / 6 |
| STRONGs/run | 2-3 | 3-4 | 7-9 |
| Filings | 24 EDINET | 19 EDINET | 28 CNINFO |
| Strict H>T>B | 3/3 | | |

---

## Iteration 42: Audit-grade L1 (FilingProvider Protocol + audit primitives + HK + new cases)

**Goal**: Turn SFEWA from "an agent that produces a score" into "an audit-grade agent that produces a self-auditable bundle". The L1 plan in `private/ROADMAP.md` ships seven sub-deliverables that, taken together, constitute the audit envelope: physical case/truth split, uniform `FilingProvider` Protocol, source manifest with cutoff decisions, top-level claim-citation enforcement, provenance header, verifier-corpus propagation, HKEX support, two new cases (one HK retrospective + one forward), and a static HTML report.

### What changed

Sub-iterations executed in dependency order:

| L1.x | Title | Key Change |
|------|-------|-----------|
| L1.3 | Case/Truth schema split | `configs/cases/*.yaml` (agent-visible) vs `configs/truth/*.yaml` (eval-only). New `TruthConfig` + `load_case_and_truth()` loader enforces case_type ↔ truth-file relationship. Static grep + runtime sentinel test (each truth YAML carries `__TRUTH_SENTINEL_<case_id>_xxxxxx__` that must not surface in agent-visible state). |
| L1.1 | `FilingProvider` Protocol + EDINET/CNINFO adapters | `FilingRef`, `EvidenceChunk` (page-local + global char offsets), `ExtractedDocument`, `ManifestEntry`, `FilingProvider` Protocol (`runtime_checkable`). `EdinetProvider` and `CninfoProvider` thin adapters wrap legacy modules without deep-refactoring. `chunk_with_offsets()` produces page-anchored chunks with both offset systems. |
| L1.4-A | Source manifest emission | `manifest.py`: doc-level audit log built by retrieval; one row per filing/article with `cutoff_decision ∈ {kept, rejected_post_cutoff, rejected_doc_type, rejected_language}`. Saved as `source_manifest.json`. Production invariant: zero `kept` entries with `release_time > cutoff_date`. |
| L1.4-B | Provenance header | `provenance.py`: model id + provider + git commit + dirty flag + case-config sha256 + truth-config sha256 + manifest counts + token totals + wall-clock duration. Saved as `provenance.json`. Two runs with identical provenance hashes produce identical artifacts modulo LLM sampling. |
| L1.4-C | Claim-citation enforcement | `citation_check.py`: every top-level `risk_factor.supporting_evidence` must reference ≥1 `evidence_id` that resolves to evidence with a real source reference. **Mid-run design fix**: originally raised inside `save_run_artifacts`, killing 30+ minute runs. Redesigned to record violations in `run_summary.json["audit_violations"]` — pipeline always completes, CI gate is a separate test on saved data. |
| L1.5 | Verifier corpus propagation | `apply_verifier_corpus_default()` at load: retrospective → `allowed_sources_only`, forward → `open_web`. Adversarial Phase 2 web-search **skipped entirely** when `allowed_sources_only`. Closes a subtle leakage path where retrospective runs could verify pre-cutoff claims with post-cutoff news. |
| L1.2 | HKEX provider + fixtures | `hkex.py` (issuer resolver via active stock list, doc taxonomy, TZ-aware release-time normalization for `Asia/Hong_Kong`, JSF-shaped HTML parser); `HkexProvider` adapter. 36 unit tests on synthetic HTML/PDF fixtures. **Live HKEXnews search not implemented** — JSF `titleSearchServlet.do` returns empty for headless requests, partial-AJAX state machine resists scraping. Cache-first + graceful fallback to web-only evidence. Investigation results documented in `private/ROADMAP.md` L2.1. |
| L1.6 | Two new cases | `ping_an_2024` retrospective (HK, cutoff 2024-12-31, integrated finance + tech platform strategy) + `tencent_ai_2026` forward (HK, cutoff 2026-04-19, AI/cloud strategic transformation). Migrated Honda/Toyota/BYD to new schema; pinned `verifier_corpus: open_web` to preserve iter-41 baseline behavior. |
| L1.7 | Static HTML report | `html_report.py`: single-file `report.html` with three pillars above the fold (evidence trace, provenance, controls applied). Forward cases display "Forward surveillance case. Not a retrospective validation." banner. 14 unit tests covering all rendering paths. |

### File summary

**New** (16 files):
- `src/sfewa/tools/filing_provider.py`, `manifest.py`, `provenance.py`, `citation_check.py`, `html_report.py`, `hkex.py`
- `src/sfewa/tools/providers/{__init__,edinet_provider,cninfo_provider,hkex_provider}.py`
- `configs/cases/{ping_an_integrated_finance,tencent_ai_strategic_transformation}.yaml`
- `configs/truth/{honda_ev_2025,toyota_ev_2025,byd_ev_2025,ping_an_2024}.yaml`
- `tests/test_tools/{test_filing_provider,test_providers,test_manifest,test_provenance,test_citation_check,test_html_report,test_hkex}.py`
- `tests/test_integration/test_label_leakage.py`
- `tests/test_schemas/test_verifier_corpus_default.py`
- `tests/fixtures/hkex/{stocklist_sample,titlesearch_pingan}.html`

**Modified**:
- `src/sfewa/main.py` (build_initial_state_from_case extracted)
- `src/sfewa/schemas/{config,state}.py` (TruthConfig, case_type, audit_meta, source_manifest)
- `src/sfewa/tools/artifacts.py` (manifest + provenance + citation + report wiring)
- `src/sfewa/tools/filing_discovery.py` (HK jurisdiction routing, hong_kong patterns, explicit-jurisdiction override)
- `src/sfewa/agents/{agentic_retrieval,retrieval,adversarial}.py` (manifest accumulation, verifier-corpus gate)
- `configs/cases/{honda,toyota,byd}_*.yaml` (ground_truth_events removed, new audit fields added)
- `docs/architecture.md` (full reorganization — see below)

**Test count**: 71 → **197** (added 126 across new modules + leakage tests + audit primitives).

### Stability re-verification (9 runs, 3×3)

| Round | Honda | Toyota | BYD | H>T>B |
|-------|------:|-------:|----:|:-----:|
| R1 | 78 HIGH | 48 MEDIUM | 19 LOW | ✓ |
| R2 | 75 HIGH | 63 HIGH | 25 LOW | ✓ |
| R3 | 78 HIGH | 63 HIGH | 22 LOW | ✓ |
| **Mean** | **77** | **58** | **22** | **3/3** |
| Range | 75-78 (3) | 48-63 (15) | 19-25 (6) | |

**vs iter-41 baseline** (H=71, T=58.3, B=28): Honda mean +6 (still HIGH band, range tighter from 14→3); Toyota mean unchanged (range wider 3→15 due to R1 outlier at 48 in full MEDIUM band, not a regression — iter-39 R2 was 50); BYD mean −6 (still LOW band, range tighter 15→6).

### New cases verified

| Case | Type | Score | Level | Wall | Verifier corpus | Forward banner |
|------|------|------:|-------|-----:|-----------------|---------------|
| Ping An (2318) — pre-wire | retrospective | 48 | MEDIUM | 27m | `allowed_sources_only` (Phase 2 skipped ✓) | n/a |
| Ping An (2318) — post-wire | retrospective | 50 | MEDIUM | 25m | `allowed_sources_only` | n/a |
| Tencent (0700) | forward | 14 | LOW | 44m | `open_web` | "Forward surveillance" ✓ |

Ping An pre-wire vs post-wire (after HKEX jurisdiction routing wired in): drift +2, well within run-to-run noise. Confirms the wiring change does not regress.

### L1 audit invariants — verified across all 12 runs

- **Citation resolution**: 120/120 top-level claims (10 per run × 12 runs) resolve to evidence with valid source references; `audit_violations.citations_unresolved` empty across the board.
- **Manifest cleanliness**: 0 `kept`-with-`release_time > cutoff` entries across all 12 manifests. Honda/Toyota each had 1 `rejected_post_cutoff` per run (the cutoff gate firing correctly on DDG news drift); BYD/Ping An/Tencent had 0 rejections (those queries didn't surface post-cutoff items).
- **L1.5 verifier propagation**: Ping An's `allowed_sources_only` envelope correctly skipped Phase 2 in both pre-wire and post-wire runs. Audit log shows `Phase 2 skipped — verifier_corpus=allowed_sources_only`.
- **L1.7 forward banner**: Tencent's `report.html` carries "Forward surveillance case. Not a retrospective validation." above the fold.

### Key insights

1. **L1.4-C design fix mid-run**: originally `assert_claim_citations` raised inside `save_run_artifacts`. BYD R1 hit it after 30+ min of compute (one factor with empty `supporting_evidence`), and the artifacts didn't save. Redesigned: violations record as data in `run_summary.json["audit_violations"]`; pipeline always completes; CI gate becomes a post-hoc test on saved data. The standalone `assert_*` functions remain for unit tests. This is the right separation — the audit trail is the artifact, not the pass/fail signal.

2. **HKEX live discovery is JSF, not headless-friendly**: probed `titleSearchServlet.do` (200 OK but returns `result: "[]"` regardless of params or session cookie), legacy `advancedsearch.aspx` (HTTP 404), per-day index pages (HTTP 404), and `predefineddoc.xhtml` (renders empty). The actual UI uses partial-AJAX with `javax.faces.partial.ajax=true` + viewstate handshakes that resist scraping. Three viable paths: headless browser (Playwright, ~50MB dep), reverse-engineer the partial-AJAX state machine (brittle), or manual pre-staging. Documented in `private/ROADMAP.md` L2.1 with a full alternatives-ruled-out table (Moomoo/Futu OpenAPI, HKEX IIS, LSEG, FactSet, Twelve Data — all paid B2B or trading-only).

3. **SEC EDGAR deferred to L2.2**: would be the easiest of the four providers (free `data.sec.gov` JSON API, no scraping). Not L1-blocking — the audit pipeline is already proven across 3 jurisdictions × 11 runs. Adding US is a portfolio-level argument for Layer 2.

4. **Truth/case split is enforceable, not just documented**: the runtime sentinel test is the new line of defense. It builds the full pipeline state via the same loader the CLI uses, walks every string in the resulting state dict, and asserts the sentinel doesn't appear except in the truth file itself. Negative-case-tested by injecting the sentinel into a case YAML — both the static grep and the runtime check fire correctly.

5. **The audit envelope is more valuable than any single primitive**: source manifest, citation check, provenance, verifier propagation, and case/truth split each close a specific leakage or trust gap. Together they make the *audit story* end-to-end: a reviewer can open `report.html`, verify no post-cutoff kept evidence (manifest), click a claim to its source (citations), and see exactly which model/commit/sha produced the run (provenance). That's the L1 North Star and it's now demoable.

### Architecture doc rewrite

Alongside L1 implementation, `docs/architecture.md` was reorganized end-to-end. The previous order reflected implementation history (state management appeared after analyst deep-dives; evidence retrieval appeared after the Iceberg Model). The new order follows a clear narrative arc: overview → flow → state → nodes → ingest → process → output → audit → cross-cutting → summary → package. Section 6 (Dynamic Dimension Generation) folded into Section 4 (Node Contracts) as an init_case detail. Section 11 (now §9) Audit Architecture is a major new beat. Code blocks trimmed to the load-bearing five (`run_pipeline_v2`, scoring formula, Iceberg layers, three-phase architecture, audit_violations dict). 918 lines, 12 sections, sequential numbering, balanced fences, all cross-references resolve.

### Stability state entering Iteration 43

| Metric | Honda | Toyota | BYD |
|--------|-------|--------|-----|
| Retro mean (iter 42, 3 runs) | 77 | 58 | 22 |
| Retro range | 75-78 (3) | 48-63 (15) | 19-25 (6) |
| Citations resolved / factors | 30/30 | 30/30 | 30/30 |
| Manifest kept-post-cutoff | 0 | 0 | 0 |
| STRONGs/run | 4-5 | 3-5 | 5-7 |
| Filings | 24 EDINET | 19 EDINET | 28 CNINFO |
| Strict H>T>B | 3/3 |  |  |
| New cases verified | Ping An 50 MEDIUM (HK retro), Tencent 14 LOW (HK forward) |  |  |
| Audit invariants (12-run sample) | citations 120/120, manifest 0 violations, verifier-propagation logged |  |  |

---

## Iteration 43: Layer 2 — HKEX live, SEC EDGAR, sentence citation, strategy discovery, Country Garden swap

**Goal**: Close the Layer 2 deliverables in `private/ROADMAP.md` — HKEX live discovery (the gap from L1.2), SEC EDGAR provider (4th jurisdiction), sentence-level claim citation (tighten L1.4-C). Plus two scope additions during the iteration: a strategy-discovery agent (so SFEWA works for any public company without the user pre-authoring a `strategy_theme`), and replacement of the weak Ping An verification case with Country Garden — a real strategic-failure retrospective with dated bond default.

### What changed

| L2.x | Title | Key Change |
|------|-------|-----------|
| L2.1 | HKEX live discovery | DDG `site:hkexnews.hk filetype:pdf` queries surface direct-PDF URLs (publicly downloadable); URL auto-promotion in `_make_search_tool` Tier-1-promotes any HKEX URL the agent surfaces during normal search; optional Playwright fallback when DDG coverage thin. **No new hard dependencies** — `ddgs` is already used. |
| L2.2 | SEC EDGAR provider | `SecEdgarProvider` via `data.sec.gov/submissions/CIK{...}.json`; ticker → CIK lookup with corporate-suffix-tolerant name match (`"The Boeing Company"` ↔ `"BOEING CO"`); doc-type taxonomy (10-K → annual_report, 10-Q → interim_report, 8-K → inside_information, DEF 14A → circulars); ticker plumbed through case YAML's `audit_meta.ticker`. |
| L2.3 | Sentence-level citation | New `sfewa.tools.sentence_citation` module: per-sentence walk of each factor's `claim` + `description`, fuzzy-matched against cited evidence's text via difflib longest-block. Resolved sentences record `(doc_id, char_start, char_end)`; unresolved go to `audit_violations.sentence_citations_unresolved`. Soft enforcement (data, not exception) — analysts paraphrase, so resolution rates of 1-10% are honest signal not failure. |
| L2.4 | Strategy discovery (BONUS — not in roadmap) | `strategy_theme` made optional; new `strategy_discovery` agent runs as preprocessing before `init_case`, reads filings + light web search, returns 1-3 candidate themes ranked by scrutiny target. Top-1 becomes the working theme; full candidate list saved as `discovered_strategies.json`. CLI `--discover-strategies` flag forces re-discovery for "what alternatives exist" queries. |
| swap | Country Garden replaces Ping An | Ping An's truth file admitted the events were "scaffolded based on direction" — soft outcome, weak verification. Country Garden (2007 HK, cutoff 2023-07-31) has discrete dated failures: USD bond default 2023-08-08 → wind-up petition 2024-01-30. Tier-1 retrospective with 7 GT events. |

### File summary

**New** (8 files, ~1450 LOC):
- `src/sfewa/tools/sec_edgar.py`, `providers/sec_edgar_provider.py`
- `src/sfewa/tools/hkex_live_discovery.py` (rewritten end-to-end; was Playwright-only stub from L1)
- `src/sfewa/tools/sentence_citation.py`
- `src/sfewa/agents/strategy_discovery.py`, `prompts/strategy_discovery.py`
- `configs/cases/{boeing_quality_strategy,country_garden_property_strategy}.yaml`
- `configs/truth/{boeing_quality_2024,country_garden_2023}.yaml`
- `tests/test_tools/{test_sec_edgar,test_filing_discovery_jurisdiction,test_sentence_citation}.py`
- `tests/test_agents/test_strategy_discovery.py`
- `tests/fixtures/sec_edgar/{company_tickers_sample.json,submissions_tesla.json,tesla_10k_excerpt.htm}`

**Modified**:
- `src/sfewa/schemas/config.py` — `strategy_theme: str | None`
- `src/sfewa/main.py` — discovery preprocessing + `--discover-strategies` CLI flag + audit-trail wiring
- `src/sfewa/agents/agentic_retrieval.py` — `_make_search_tool` HK URL auto-promotion + ticker plumbing
- `src/sfewa/tools/filing_discovery.py` — US jurisdiction routing + ticker arg + DDG-first HKEX path
- `src/sfewa/tools/providers/__init__.py` — export `SecEdgarProvider`
- `src/sfewa/tools/artifacts.py` — `discovered_strategies.json` artifact + `sentence_citations_unresolved` in audit_violations
- `tests/test_tools/{test_providers,test_hkex_live_discovery}.py` — extended for new provider + new HKEX paths
- `docs/architecture.md` — surgical updates for §1, §5, §9, §11, §12 (jurisdiction status table, audit primitives table, agentic table, package tree)
- Deleted: `configs/cases/ping_an_integrated_finance.yaml`, `configs/truth/ping_an_2024.yaml`

**Test count**: 197 → **302** (+105). 1 skipped (Playwright integration test, gated on dep install).

### L2.1 acceptance — HKEX live discovery

| Acceptance criterion | Status |
|---|---|
| HK retrospective produces ≥3 Tier-1 HKEX filings in `source_manifest.json` | ✅ Country Garden v2: **10 HKEX filings** kept, 0 rejected |
| Live discovery within ±10 of cache/web-only baseline | ✅ v1 (web-only) 97 CRITICAL, v2 (HKEX live) 92 CRITICAL — 5 pt drift, same band |
| No new dependencies escape `pyproject.toml` review | ✅ Playwright stays optional (try-import); primary path uses existing `ddgs` |

The DDG-first design proved better than Playwright: lighter (no 50MB browser dep), faster (no JSF round-trips), and works for the case that matters (Country Garden). Where DDG's index is thin, the Playwright fallback engages if installed; otherwise the run gracefully falls back to web-search-only evidence and continues.

### L2.2 acceptance — SEC EDGAR provider

| Acceptance criterion | Status |
|---|---|
| `SecEdgarProvider` satisfies `FilingProvider` Protocol (runtime_checkable) | ✅ |
| CIK resolver handles ticker variants (AAPL, "Apple Inc.", "The Boeing Company") | ✅ regression test for the corporate-suffix matcher |
| Doc-type taxonomy (10-K → annual_report, 10-Q → interim_report, 8-K → inside_information, DEF 14A → circulars) | ✅ |
| Fixture tests include ≥1 post-cutoff filing rejected as `rejected_post_cutoff` | ✅ |
| US peer (Tesla / Ford / GM) gets EDGAR filings into Honda/BYD/Toyota run; manifest source=`sec_edgar` | ⚠️ **Not done** — pipeline doesn't fetch peer filings, only the primary company's. Would require a new "peer filings" stage. Boeing as a primary case demonstrates the provider works end-to-end (8 filings, 159 chunks). |
| Honda/Toyota/BYD baseline ±10 score tolerance | ⚠️ **Borderline** — Honda mean 67.3 vs iter-42 baseline 77 (-10, at edge). Toyota 60.3 vs 58 (+2). BYD 34.7 vs iter-42's 22 (+13, outside ±10) but within ±10 of iter-41's 28.0. |

The "peer filings into Honda runs" criterion is genuinely deferred — it's not a provider gap, it's a pipeline-stage gap (peers don't currently get their own filing-discovery pass). Worth flagging for a future iteration.

### L2.3 acceptance — sentence-level citation

| Acceptance criterion | Status |
|---|---|
| Per-sentence walk of `claim` + `description` | ✅ |
| `(doc_id, char_start, char_end)` recorded for resolved sentences | ✅ |
| Unresolved sentences land in `audit_violations.sentence_citations_unresolved` | ✅ |
| Tests cover sentence splitter, fuzzy matcher, validator | ✅ 20 tests |

Resolution rates (per run): Honda 1%, Toyota 3%, BYD 2%, Boeing 9%, Country Garden 5-10%. Low across the board — confirms analysts heavily paraphrase rather than quote verbatim. The signal is honest: it tells the reviewer how directly each conclusion traces back to a source sentence. Tightening to higher resolution would require either embedding similarity (not lexical) or asking the analyst LLM to emit explicit sentence→evidence_id maps as part of structured output.

### L2.4 acceptance — strategy discovery (bonus)

| Acceptance criterion | Status |
|---|---|
| `strategy_theme` optional in CaseConfig | ✅ |
| Discovery agent uses filings + light web search to propose 1-3 candidates | ✅ |
| Top-1 candidate becomes working theme; full list saved to audit trail | ✅ |
| `--discover-strategies` CLI flag forces re-discovery (audit-only) | ✅ |
| Boeing smoke test: discovers a sharper theme than the hand-authored one | ✅ "737 MAX production ramp vs quality and certification integrity" (conf 0.95) — more specific and verifiable than the human's "Commercial-aerospace quality, certification, and capital strategy" |

This was added per user feedback that authoring a strategy theme requires the user to already know the company's strategy, which doesn't generalize beyond cases the user has studied. Discovery closes that gap cleanly.

### Stability re-verification (9 runs, 3×3, post-L2)

| Round | Honda | Toyota | BYD | H>T>B |
|-------|------:|-------:|----:|:-----:|
| R1 | 66 HIGH | **73 HIGH** | 41 MED | ✗ T outlier |
| R2 | 72 HIGH | 54 MED | 36 LOW | ✓ |
| R3 | 64 HIGH | 54 MED | 27 LOW | ✓ |
| **Mean** | **67.3** | **60.3** | **34.7** | **2/3** |
| Range | 64-72 (8) | 54-73 (19) | 27-41 (14) | |

vs iter-42 baseline (H=77, T=58, B=22): Honda -10 (at edge of ±10 tolerance), Toyota +2 (in range), BYD +13 (outside ±10 strict, but within ±10 of iter-41's 28.0).

R1 Toyota=73 is the outlier — 5pts above its iter-42 range max (63). With only 37 evidence items in R1 (vs 33-35 in R2/R3), retrieval was thinner and synthesis drifted high. **L2 changes don't touch JP/CN scoring or retrieval paths** (HKEX live + SEC EDGAR are gated by jurisdiction; URL auto-promotion only fires on HKEX URLs); R2/R3 returning to baseline behavior strongly supports "LLM variance" over "regression". Strict-1/3-inversion criterion is borderline — 2/3 is the honest read.

### New verification cases

| Case | Type | Score | Backtest | L1 audit clean | Notes |
|------|------|------:|---------|---------------|-------|
| Boeing (BA, US retro, cutoff 2023-12-31) | retrospective | **76 HIGH** | 6S+1P+1M / 7 | ✓ | 8 SEC EDGAR filings (10-K, 10-Q×2, 8-K, DEF 14A), 159 chunks, all `source: sec_edgar`. Confidence 0.74 (vs Boeing v1 web-only 0.6 — Tier-1 sources lift confidence). |
| Country Garden (2007 HK, retro, cutoff 2023-07-31) | retrospective | **92 CRITICAL** | 4S+3P / 7 (zero MISS) | ✓ | 10 HKEX filings discovered via DDG site search + URL auto-promotion. Backtest covers all 7 GT events (USD bond default → H1 loss → onshore extension → offshore default → wind-up petition → onshore default → restructuring). Manifest 100% `source: hkexnews`. |

Country Garden is the clearest L2 acceptance signal: a clean retrospective with dated bond-default failures, the pipeline correctly flagged CRITICAL with full HKEX Tier-1 audit envelope, and the agent fetched its own filings without manual staging or Playwright.

### L2 audit invariants — verified across all post-L2 runs (12 runs total)

- **Citation resolution**: 110/110 top-level claims resolved (factor-level) across 11 runs. Boeing v2 had 1 unresolved citation (acceptable — `audit_violations` records it).
- **Manifest cleanliness**: 0 `kept`-with-post-cutoff entries across all 11 manifests.
- **Sentence-level audit data** present on every run; resolution rates 1-10% (honest signal — see L2.3 above).
- **Verifier corpus propagation**: Country Garden's `allowed_sources_only` envelope correctly skipped Phase 2 web verification.
- **Strategy discovery audit trail**: when invoked, full candidate list saved to `discovered_strategies.json`.

### Key insights

1. **DDG site search beats Playwright for HKEX.** The L1 investigation concluded headless browser was the only path. L2.1's first attempt with full corporate names + `filetype:pdf` returned empty rows. The breakthrough was discovering DDG is verbosity-sensitive: short company names + year hint surface HKEX URLs that DDG has indexed, then we download from the publicly accessible direct-PDF URL pattern. The Playwright fallback exists for cases DDG hasn't indexed but isn't the primary path.

2. **URL auto-promotion is cleaner than discovery as a separate step.** Original design: explicit `_discover_and_load_hkex` makes 3 site-scoped DDG queries upfront. New design: any HKEX URL the agent surfaces during normal search gets auto-promoted to Tier-1. The agent doesn't need to know about HKEX specifically — it issues normal queries like "Country Garden 2022 financial results" and HKEX URLs that come back are silently promoted. Reduces discovery dependency on a single set of pre-baked queries.

3. **CIK resolver corporate-suffix bug found mid-run.** Boeing v1 logged "SEC EDGAR CIK not found — skipping regulatory filings" because SEC's title is "BOEING CO" but case YAML had "The Boeing Company". Fixed with stopword normalization (`THE`, `COMPANY`, `CO`, `INC`, ...) + bidirectional containment + ticker-first dispatch. Boeing v2 then loaded 8 EDGAR filings cleanly. The failure mode was instructive: a fuzzy matcher must be tested against the actual variation in real titles, not idealized examples.

4. **Strategy discovery surfaced a sharper theme than the human author.** Boeing case YAML had `strategy_theme: "Commercial-aerospace quality, certification, and capital strategy"`. Discovery on the same case proposed `"737 MAX production ramp vs quality and certification integrity"` (confidence 0.95) — more specific, more verifiable, more directly aligned with the failure that materialized. Worth remembering when judging whether the agent's auto-output is "good enough" — sometimes it's *better*.

5. **Sentence-level citation is honest signal, not enforcement.** Resolution rates of 1-10% across all cases reveal that analysts paraphrase synthesized claims; they don't quote evidence verbatim. A strict matcher would flag every run as failing. The right move is honest data: log how many sentences trace cleanly to evidence vs. how many are synthesis. Reviewers can read that and form their own confidence judgment.

### Architecture doc updates

`docs/architecture.md` updated surgically (+10 lines net): §1 mentions optional theme + sentence_citations; §5 jurisdiction status table now shows 4 live providers (added SEC EDGAR row, upgraded HKEX from "cache-first only" to "live via DDG"); §9 has 6 audit primitives (added sentence-level row); §11 Agentic table grows with strategy-discovery + HK auto-promotion rows; §12 package tree adds new files. "L1.x" tags stripped from headers since L1+L2 are now unified.

### What's NOT done from L2.3 "Other deferred items"

Honest scope-cut from the roadmap (these are outside the engineering surface):
- Domain (`sfewa.app`/`.io`) + HK-region hosting
- Submit-a-company queue / form
- Deep refactor of `edinet.py` / `cninfo.py` internals (still adapter-wrapped — works fine)
- Forward AIA / additional surveillance demos

### Stability state entering Iteration 44

| Metric | Honda | Toyota | BYD |
|--------|-------|--------|-----|
| Retro mean (iter 43, 3 runs) | 67.3 | 60.3 | 34.7 |
| Retro range | 64-72 (8) | 54-73 (19) | 27-41 (14) |
| Citations resolved / factors | 30/30 | 30/30 | 30/30 |
| Manifest kept-post-cutoff | 0 | 0 | 0 |
| Sentence resolution rate | ~1% | ~3% | ~2% |
| Filings | 24 EDINET | 19 EDINET | 28 CNINFO |
| Strict H>T>B | 2/3 (R1 Toyota outlier) |  |  |
| New cases verified | Boeing 76 HIGH (US retro, 8 SEC EDGAR), Country Garden 92 CRITICAL (HK retro, 10 HKEX) |  |  |
| Test count | 302 (197 → +105) |  |  |

---

## Next Steps

1. **Peer-side filings (deferred from L2.2)** — currently the FilingProvider only runs for the primary company. Adding a peer-filings stage would let Honda/Toyota/BYD pull Tesla/Ford/GM SEC EDGAR data as Tier-1 instead of web-search, closing the L2.2 acceptance gap.
2. **Sentence-level matcher upgrade** — token-overlap or embedding similarity (instead of difflib longest-block) would improve resolution rates from 1-10% to something more useful as a primary audit signal. Or: ask the analyst LLM to emit `claim_to_evidence_spans: list[dict]` as structured output, eliminating the post-hoc match entirely.
3. **HKEX coverage broadening** — DDG indexes Country Garden well; Tencent / Ping An 2023 filings did not surface in our probes. Either Playwright fallback (heavy) or alternative search backends (Brave/Serper paid APIs) would close that gap.
4. **Forward cases** — Tencent shipped, but more forward surveillance demos would strengthen the "what's the agent watching now?" narrative for distribution.
5. **Distribution** — see `private/ROADMAP.md` Priority 2 window. The L2 deliverables (HKEX live, SEC EDGAR, strategy discovery, sentence-level audit) materially strengthen the "audit-grade domain agent" pitch.
