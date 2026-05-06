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

## Iterations 33–41: Summary

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

**Key architectural decisions (cumulative through iter 41):**
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

## Next Steps

1. **L2.1 — HKEX live discovery**: Playwright-based headless browser to drive the JSF UI; produces real Tier-1 evidence for HK cases. Acceptance: Ping An or HSBC re-run within ±10 of cache-only baseline.
2. **L2.2 — SEC EDGAR provider**: `data.sec.gov` JSON API; 4-6 hours estimated; rounds out FilingProvider story to four jurisdictions. Honda/BYD/Toyota peers (Tesla, Ford, GM, VW) get Tier-1 citations instead of web search.
3. **L2.3 — sentence-level claim citation**: tighten the L1.4-C invariant from "top-level claim → ≥1 resolvable evidence id" to "every sentence in a claim → `(doc_id, global_char_start, global_char_end)`". Builds on the `EvidenceChunk` offsets already produced by L1.1.
4. **Distribution push**: blog post + Show HN + LinkedIn + 知乎 — see `private/ROADMAP.md` Priority 2 window (2026-05-19 → 2026-05-26).
