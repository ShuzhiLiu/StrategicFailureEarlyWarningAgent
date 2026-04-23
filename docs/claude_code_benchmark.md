# Claude Code Benchmark Prompt — Strategic Risk Forward Prediction

**Purpose**: Run the same forward-prediction task SFEWA runs, but inside Claude Code, so we can compare a purpose-built research agent (SFEWA, ~1000-LOC liteagent + 8-node pipeline) against a general-purpose agent harness with skills, persistent memory, multi-level context compression, hook-enforced policies, specialised sub-agents, and battle-tested web search.

**SFEWA forward prediction baseline** (cutoff 2026-04-19, 9 runs, mean score):

| Company | Score | Level |
|---|---:|:---:|
| Honda Motor Co., Ltd. | 98.0 | CRITICAL |
| Toyota Motor Corporation | 68.3 | MEDIUM–HIGH |
| BYD Company Limited | 57.3 | MEDIUM |

Score bands: 0–39 LOW · 40–59 MEDIUM · 60–79 HIGH · 80–100 CRITICAL.

---

## How to run this benchmark

1. Open a fresh Claude Code session in an empty working directory (no SFEWA code, no CLAUDE.md — a neutral environment).
2. Paste the prompt below as the first user message.
3. Let Claude Code run to completion — it should take 15–60 minutes depending on how deeply it researches.
4. Save the final assistant output to `benchmark_claudecode_run1.md`.
5. Repeat 2–3 times (different sessions) to compare variance against SFEWA's 9-run stability test.

**Do not provide the SFEWA baseline scores or case configs to Claude Code.** The comparison is only valid if Claude Code has to derive its own scoring rubric interpretation from the prompt alone.

---

## The prompt (copy everything below verbatim)

> You are running a strategic risk assessment on three public automakers. Your goal is to produce, for each company, a forward-looking risk score (0–100) for its EV (electric vehicle) electrification strategy, along with an auditable reasoning trail.
>
> This is a **benchmark evaluation** of how well a general-purpose agent harness can perform strategic research. Use your full capabilities — sub-agents (Explore, Plan, Verification), persistent memory, TaskCreate for structured tracking, WebSearch and WebFetch, parallel tool execution, and any skills you have available. You are free to design the workflow however you judge best. The only hard constraints are listed below.
>
> ## Hard constraints
>
> 1. **Temporal cutoff — today, 2026-04-19.** You may use any public information published on or before this date. Treat this as a forward prediction: events after today are unknowable. Verify publication dates when the information materially affects scoring.
>
> 2. **Evidence-driven only.** Every claim that affects a score must be traceable to a specific, citable source — an article, regulatory filing, earnings release, or analyst report — with publisher, URL, and publication date. Do not score based on your own prior knowledge; score based on what the public record shows.
>
> 3. **Adversarial self-check.** Before finalising any score, structurally challenge your own conclusions. The cleanest way is to spawn a separate sub-agent (or equivalent mechanism) whose only job is to find counter-evidence — articles, metrics, analyst views that contradict your risk narrative. If contradicting evidence is strong, reflect that in a lower score. If weak or absent, defend the original score explicitly.
>
> 4. **Same rubric across companies.** Apply identical scoring methodology to all three. Do not tune per-company.
>
> ## Scoring rubric
>
> Produce an integer 0–100 per company where higher = more strategic risk:
>
> | Band | Meaning |
> |---|---|
> | 80–100 CRITICAL | Strategic failure visible in current evidence — material writedowns, cancelled programmes, missed targets, structural business threat |
> | 60–79 HIGH | Clear structural headwinds not yet resolved — capital strain, competitive gap widening, unmitigated policy exposure |
> | 40–59 MEDIUM | Mixed signals — some risks present but counterbalanced by executed mitigations or strong revenue base |
> | 0–39 LOW | Evidence shows strategy is executing — growing revenue, technology leadership, or dominant market position |
>
> Also provide:
>
> - `level`: one of CRITICAL / HIGH / MEDIUM / LOW derived from the score
> - `confidence`: float 0.0–1.0. Lower when evidence is thin, mixed, or contradictory. Lower when your adversarial check found meaningful counter-evidence you chose to discount.
> - `risk_factors`: 5–10 structured factors per company, each with: dimension name, severity (low/medium/high/critical), 1–2 sentence description, and 2–5 evidence citations (url + date + one-line quote or figure)
> - `memo`: 200–400 word narrative explaining the overall score
> - `counter_evidence_summary`: 3–5 bullet points describing the strongest evidence *against* your conclusion
>
> ## Suggested workflow (not prescriptive)
>
> You are encouraged to leverage features a minimal agent framework wouldn't have:
>
> - **Plan first.** Enter Plan Mode, outline your research approach, and only then start executing. Show your plan.
> - **Parallel research sub-agents.** Three companies is a natural fan-out — consider spawning one Explore sub-agent per company so research runs in parallel. Each sub-agent returns structured findings.
> - **Memory for calibration.** As you gather evidence, persist notes to memory (sources you've verified, dimensions that matter for this sector, counter-evidence patterns). If you run this benchmark multiple times, memory should make subsequent runs faster and more consistent.
> - **TaskCreate for discipline.** Track your progress explicitly: research phase, adversarial phase, scoring phase, memo writing. Mark tasks in_progress and completed as you go.
> - **WebSearch + WebFetch aggressively.** Don't settle for one round of search per company. Search for: official strategy announcements, financial results, competitor comparisons, policy/regulatory changes, technology benchmarks, and actively search for contrarian takes.
> - **Structured output throughout.** When a sub-agent returns findings, require JSON-shaped output so you can merge across companies cleanly.
> - **Verify before citing.** When a source matters to the score, WebFetch the URL and confirm the date + content. Treat undated or post-cutoff sources as inadmissible.
>
> ## Dimensions to consider (derive more as needed)
>
> At minimum assess: capital allocation efficiency, market timing, product portfolio competitiveness, technology capability (proprietary tech, vertical integration, supply chain), competitive pressure, regional/geographic exposure, policy and tariff exposure, execution track record. You are free to generate additional dimensions specific to the company.
>
> Apply a **depth gate**: for each dimension, decide whether it threatens the company's *primary* strategy or is only a *secondary* trade-off. Primary-strategy risks that are structurally reinforcing and whose core assumption is already failing should score HIGH or CRITICAL. Secondary trade-offs or risks where balancing forces (hybrid revenue, cost advantage, etc.) clearly dominate should score MEDIUM or LOW. The severity should emerge from how deep the evidence forces you to go, not from a pre-assigned label.
>
> ## The three companies
>
> 1. **Honda Motor Co., Ltd.** — Japanese automaker, historically hybrid-strong, committed large capital to EV electrification (2024 announcement: 30% EV/FCEV by 2030, 10 trillion yen investment).
> 2. **Toyota Motor Corporation** — Japanese automaker, "multi-pathway" strategy emphasising hybrids, solid-state battery programme, slower BEV rollout than peers.
> 3. **BYD Company Limited** — Chinese EV and battery maker, world's largest NEV producer, vertically integrated (battery, motor, semiconductor), Blade Battery (LFP) technology, international expansion into Europe / SE Asia / Brazil.
>
> These brief descriptions are only pointers — do not trust them as facts. Verify everything from current public sources.
>
> ## Required final output (verbatim structure)
>
> Produce a single Markdown document with the following sections:
>
> ```
> # Forward Prediction — EV Strategy Risk Assessment
>
> **Cutoff**: 2026-04-19
> **Evaluator**: Claude Code (version / model, if known)
> **Total research tool calls**: <count>
> **Total sub-agents spawned**: <count>
> **Total session duration**: <minutes>
>
> ## Summary table
>
> | Company | Score | Level | Confidence |
> |---|---:|:---:|---:|
> | Honda Motor Co., Ltd.   | ... | ... | ... |
> | Toyota Motor Corporation | ... | ... | ... |
> | BYD Company Limited      | ... | ... | ... |
>
> ## Honda Motor Co., Ltd.
> ### Risk factors
> <table of factor / dimension / severity / description / citations>
> ### Memo
> <200-400 words>
> ### Counter-evidence summary
> <3-5 bullets>
>
> ## Toyota Motor Corporation
> [same sub-structure]
>
> ## BYD Company Limited
> [same sub-structure]
>
> ## Methodology notes
> - How many rounds of web search per company?
> - How did you implement the adversarial self-check?
> - Did you use sub-agents / memory / skills / TaskCreate? Which, and where?
> - What was the most difficult judgement call?
> - Where do you think your score is most likely wrong, and why?
>
> ## Reproducibility
> - List of URLs actually fetched (not just searched)
> - Any sources you tried to fetch but couldn't access
> ```
>
> ## What success looks like
>
> A hiring manager or senior engineer should be able to read your output and:
>
> - Understand each score without following a single citation
> - Reproduce the research approach from your methodology notes
> - Disagree with a specific factor by pointing to its citation
> - See evidence you actively looked for contradicting data
>
> Begin by entering Plan Mode and showing your plan. Then execute.

---

## What to capture for the comparison

After running this 2–3 times, compare against SFEWA's forward results on these axes:

| Axis | SFEWA forward (9 runs) | Claude Code benchmark (3 runs) |
|---|---|---|
| **Honda score** | mean 98.0, range 96–100 (CRITICAL all runs) | mean 79.0, range 75–84 (2 HIGH + 1 CRITICAL) |
| **Toyota score** | mean 68.3, range 58–84 (HIGH–CRITICAL) | mean 41.3, range 32–50 (MEDIUM in 2, LOW in 1) |
| **BYD score** | mean 57.3, range 53–64 (MEDIUM) | mean 42.3, range 38–45 (MEDIUM in 2, LOW in 1) |
| **Ordering H>T>B** | 2/3 strict, 3/3 by mean | **1/3 strict** — CC flips to H>B>T in R2 and R3 (mean T<B by 1 pt) |
| **Honda direction** | flagged as top risk | ✓ flagged as top risk |
| **Magnitude delta** | baseline | SFEWA +19 on Honda, +27 on Toyota, +15 on BYD |
| **Evidence volume** | 63–155 items per run | ~30–60 URLs per run; CC citations are higher-quality (filings, earnings releases) |
| **Run duration** | 35–75 min per company | 15–60 min for all three (with sub-agent parallelism) |
| **Auditable citations** | every factor has evidence_id list | every factor has URL + date + one-line figure/quote |
| **Adversarial discipline** | 3-phase CoVe + verification search + refinement, 0–10 STRONG challenges | R2: dedicated adversarial sub-agent wave; R1/R3: less structured |
| **Cross-run stability** | Honda ±4, Toyota ±26, BYD ±11 | Honda ±9, Toyota ±18, BYD ±7 — CC tighter on Toyota and BYD |
| **Memory / institutional knowledge** | none (single-session) | R2 seeded from `sector_auto_ev_risk.md` written during R1 |
| **What the harness gave it** | Tool-loop + parallel fan-out + structured output only | Plan Mode, sub-agents, memory, TaskCreate, Skills, context compression |

### Fair-comparison notes

- Claude Code has access to its proprietary web search tools and may reach higher-quality sources than DuckDuckGo. This is a **feature of the comparison**, not a flaw — it tests whether a richer tool environment compensates for less domain-tuned reasoning design.
- SFEWA is specifically tuned on Qwen3.5-27B and has 39 iterations of depth-routing and adversarial calibration behind it. Claude Code has no tuning for this specific task.
- Neither system has ground truth for this forward window — agreement between SFEWA and Claude Code (or a notable disagreement) is informative on its own.

### What to look for

- **Does Claude Code reach similar scoring magnitudes?** If Claude Code puts Honda at 60 while SFEWA puts it at 98, that's a sharp disagreement worth investigating — is it because Claude Code discounted the March 2026 writedown, or because our depth-routing over-weights it?
- **Does Claude Code find evidence SFEWA missed?** Its web search is almost certainly stronger. Which factors does it surface that our agentic retrieval doesn't?
- **Does Claude Code's adversarial check fire?** Our 3-phase adversarial is a core component. Does Claude Code's Verification sub-agent produce comparable counter-evidence, or does it rubber-stamp?
- **Does it use memory between runs?** If memory actually makes run 2 and 3 more consistent, that's evidence that institutional knowledge would help SFEWA too.

A full comparison should feed into a follow-up document (`docs/claude_code_vs_sfewa_comparison.md`) with concrete side-by-side scoring, citation overlap, and methodology differences.

---

## Key findings from the 3 runs

**Summary scores:**

| Run | Honda | Toyota | BYD | Ordering | Method note |
|---:|---:|---:|---:|:---:|---|
| 1 | 78 HIGH (0.75) | 50 MEDIUM (0.70) | 44 MEDIUM (0.65) | H>T>B ✓ | standard research |
| 2 | 75 HIGH (0.78) | 32 LOW (0.72)    | 38 LOW (0.70)    | H>B>T  | 6 sub-agents (3 primary + 3 adversarial), ~120 tool calls, memory-seeded from R1 |
| 3 | 84 CRITICAL (0.85) | 42 MEDIUM (0.75) | 45 MEDIUM (0.65) | H>B>T  | most evidence-rich reasoning, strongest Honda case |
| **mean** | **79.0** | **41.3** | **42.3** | — | — |

**Where the two systems agree**

- **Honda is the top risk.** Both systems flag Honda's post-March-2026 cancellations, ¥10T→¥7T capex retraction, and Sony-Honda Afeela dissolution as structural strategy failure. This convergence — under different retrieval, different reasoning, different base models — is the strongest external validation SFEWA has received.
- **Toyota and BYD sit below Honda.** Absolute magnitudes differ but both systems reject a CRITICAL reading for either.

**Where they diverge**

- **Magnitude.** SFEWA scores 15–27 points more severe across all three. SFEWA's Iceberg depth gate + 3-phase adversarial tend to score "primary-strategy-failure" aggressively once evidence supports it. Claude Code more readily credits balancing forces (Honda's motorcycle cash, Toyota's hybrid margin, BYD's overseas growth) as mitigations. Neither system has ground truth for this forward window — the correct calibration is an open question.
- **Toyota vs BYD ordering.** SFEWA puts Toyota > BYD (68.3 vs 57.3). Claude Code puts BYD > Toyota (42.3 vs 41.3) in 2 of 3 runs. Claude Code reads Toyota's multi-pathway strategy as *being vindicated* by the BEV demand plateau (R2: "multi-pathway is being vindicated as global BEV demand plateaus"). SFEWA's adversarial reviewer weights SSB-timeline slippage and China BEV losses more heavily. Worth a direct audit.

**What the harness gave Claude Code that liteagent doesn't**

- **Persistent memory across runs.** R2 was explicitly seeded by a memory file written during R1 (`sector_auto_ev_risk.md`). This made R2 faster and arguably more disciplined — it also suggests memory would help SFEWA's calibration stability on repeated analyses.
- **Sub-agent fan-out as first-class.** R2 spawned 6 Explore sub-agents in two parallel waves (3 primary research + 3 adversarial). SFEWA fans out 3 analysts, but they share one context; Claude Code's sub-agents have independent message histories and tool pools, which is closer to the paper-original adversarial pattern.
- **Higher-quality evidence.** Claude Code's citations consistently reach primary sources (HKEX-filed BYD results, S&P rating action, specific filing IDs). DuckDuckGo + EDINET/CNINFO retrieval in SFEWA reaches comparable primary sources but with more noise and more effort.

**What Claude Code didn't do that SFEWA did**

- **Systematic severity calibration from depth.** SFEWA's Iceberg depth gate forces the LLM to decide whether a risk is primary or secondary, and severity emerges from layer depth. Claude Code applies a looser "depth gate" per the prompt but doesn't anchor severity in structural depth — result: severity drifts toward MEDIUM even on clearly structural risks.
- **Programmatic consistency flags.** No citation cross-validation, no stance-mismatch detection, no phantom-citation checking. All of SFEWA's 7 programmatic flags are absent. The trade-off is that Claude Code's reasoning feels more natural; SFEWA's is more disciplined.
- **Cross-run backtest.** Claude Code runs are single-shot narratives. SFEWA's 9-run stability protocol catches scoring drift that a 3-run sample can miss.

---

## Raw Claude Code outputs

#### First Run

Honda Motor Co., Ltd. — Score 78 / HIGH (confidence 0.75)                                                                                 
                                                                                                                
  Honda's EV strategy is in a visible retreat phase after the March 12, 2026 announcement disclosing up to ¥2.5 trillion in maximum         
  cumulative EV-related losses and cancelling the 0 Series Saloon, 0 Series SUV, and Acura RSX for North America less than two months after 
  their CES production-prototype debut. The FY2026 forecast was simultaneously cut to an operating loss of ¥270–570B (from a ¥1.21T profit  
  in FY2025), driven by US tariffs (~$1.8B hit, 9-month profit –42%), a 31% China sales decline, and the related discontinuation of         
  Sony-Honda's Afeela. The 2030 BEV+FCEV target was already trimmed from 30% to 20% in May 2025, operationalising a structural pivot back
  toward hybrids. Counter-evidence is survival-grade rather than strategy-recovery: the motorcycle division generates ~¥663B at ~18% margin,
   US hybrid sales hit a record 400k+ in 2025, the Sakura solid-state pilot line started in January 2025, and the December 2025 Astemo
  majority acquisition strengthens SDV capabilities. The score sits HIGH rather than CRITICAL because those cushions blunt near-term
  solvency risk, but the EV strategy itself meets the criteria for structural failure.

  Toyota Motor Corporation — Score 50 / MEDIUM (confidence 0.70)

  Toyota's "multi-pathway" strategy is being vindicated in real time by the industry-wide pure-BEV demand plateau, and the depth-gate       
  analysis treats BEV lag as a secondary trade-off rather than a primary-strategy failure. Toyota retained the global #1 sales crown in 2025
   (~11.3M units) with an industry-leading ~13.35% operating margin; hybrids now account for ~44% of FY25 sales and are accelerating.       
  Solid-state moved from prospectus to pilot with Japanese production approval on 2025-10-07 and the Sumitomo Metal Mining cathode
  mass-production agreement, while the $15k bZ3X crossed 80,000 deliveries in its first year in China and the $13.9B North Carolina battery
  plant opened in November 2025. Near-term risks remain material — Q3 FY25 operating profit –27.9% YoY, a $1.3B two-month tariff hit, the
  bZ4X recall and 95% US sales collapse, Lexus LF-ZC/LF-ZL delays, and the Daihatsu certification-fraud aftermath — but credit ratings were
  affirmed stable (S&P A+ Feb 2025, Moody's A1 Jun 2025). Confidence is 0.70 because the widely-reported 1.5M→1.0M BEV target cut could not
  be independently verified against a primary Toyota source.

  BYD Company Limited — Score 44 / MEDIUM (confidence 0.65)                                                                                 
   
  BYD's core strategy — volume leadership, deep vertical integration, overseas expansion, and a technology flywheel — is executing, with    
  2025 unit sales growing 7.73% to 4.60M NEVs and revenue growing 3.46%, plus reinforced tech leadership from the March 2026 Blade Battery
  2.0 / Super e-Platform 1000V (1,500kW peak charging, 1,000 km range) and the free February 2025 rollout of God's Eye DiPilot ADAS. The    
  headline-negative Q1 2026 total sales decline of –30% YoY and full-year 2025 net profit decline of –19% (gross margin compressed from
  19.44% to 17.74%) are a margin-and-geography story rather than a demand collapse: overseas sales surged +145% in 2025 to 1.05M units and
  reached ~40% of monthly mix by March 2026 at 28.1% overseas gross margin vs 17.2% domestic. Real structural headwinds are the EU 27%
  effective tariff (partly offset by a PHEV workaround with EU PHEV registrations +~17,000%), the Hungary plant slip to Q1/Q2 2026, the GMT
  Research supplier-finance critique (¥323B recast net debt vs ¥27.7B reported), and the China policy cliff (EV tax-exemption expiry + new
  5% PHEV purchase tax). NEV market share was 19.1% in February 2026 and 22.8% in March 2026 — leadership is intact, contradicting the
  draft's "share collapse" framing. JPMorgan maintains Outperform with a 6.5M-unit 2026 sales forecast (+20% YoY); confidence is 0.65
  because the financial picture is genuinely bifurcated and the GMT debt critique cannot be fully priced from secondary reporting.

#### Second Run
Honda scores 75 (HIGH, conf 0.78) — its May-2024 ¥10T EV plan has visibly retracted in 22 months (¥7T revised capex, ¥2.5T max-exposure   
  writedown, 0-Series and Afeela cancellations, first ~70-year operating loss, China sales −24% YoY), held out of CRITICAL only by intact   
  parent credit ratings and a working hybrid hedge. Toyota scores 32 (LOW, conf 0.72) — multi-pathway is being vindicated as global BEV
  demand plateaus, the 2026 bZ outsold Ford's entire EV lineup in Q1, bZ3X is the #1 JV BEV in China for seven consecutive months,          
  solid-state cleared Japan regulatory approval, and Toyota raised FY2026 OP guidance to ¥3.4T despite a ¥1.45T tariff hit. BYD scores 38 
  (LOW, conf 0.70) — the headline Q1 2026 −30% YoY is largely a Chinese New Year base-effect artifact (industry only −3.6%; March share     
  recovered to 22.8%), 17.74% gross margin is at-or-above Tesla and well above Li Auto/NIO, and overseas (1.05M in 2025; +40% YoY; 1.5M
  target) is now BYD's sole profitable automotive segment per Citi. The hard external constraint for BYD is geopolitics (Mexico plant
  indefinitely shelved July 2025, US passenger market closed by Trump tariffs, EU price-undertaking caps), and domestic share has been ceded
   to Geely (+81% YoY) and Xiaomi (+201% YoY) — material but not collapse. Method: 6 Explore sub-agents in two parallel waves (3 primary
  research + 3 adversarial), ~120 tool calls, seeded by prior-run memory sector_auto_ev_risk.md, all citations verified ≤ 2026-04-19.

#### Third Run
Honda Motor Co., Ltd. — 84 (CRITICAL, 0.85)                                                                                               
                                                                                                                                            
  Honda's primary EV strategy has concretely failed: the ¥10-trillion electrification plan (May 2024) was cut to ¥7 trillion (May 2025) and 
  then effectively gutted when the flagship North-American 0 Series (SUV, Saloon, Acura RSX) was cancelled on 12 March 2026 at a            
  maximum-potential loss of ¥2.5 trillion. Sony-Honda Afeela was scrapped the same month, the GM low-cost EV JV collapsed in 2023, and the  
  Nissan/Mitsubishi merger fallback died six weeks after signing (Feb 2025). FY2026 guidance shifted from ¥550bn profit to ¥270–570bn
  operating loss — the first annual loss since 1957 — and S&P downgraded Honda to BBB+ on 19 March 2026. China is compounding the problem:
  GAC Honda Feb 2026 sales fell 69% YoY and at least one JV plant will close in June 2026. The score is moderated below 90 by a durable
  motorcycle cash engine (¥663bn OP, 18.3% margin) and a credible hybrid pivot, but the primary strategy itself has reset — this is
  structural, not cyclical.

  Toyota Motor Corporation — 42 (MEDIUM, 0.75)

  Toyota's stated multi-pathway strategy is being actively vindicated: FY2025 operating profit hit a record ¥4.8 trillion, 2025 global      
  deliveries reached a record 11.3M, US hybrid share is ~47%, and Toyota was the only Japanese OEM to grow in China in 2025 (+0.23% to
  1.78M). The largest hit is the ¥1.4-trillion US tariff drag that pushed North America to an operating loss and forced FY2026 guidance from
   ¥3.8T down to ¥3.2T before recovering to ¥3.4T — a primary earnings risk but a secondary strategic one, since the plan was never "win US
  BEVs." BEV weakness is real (2026 target cut 50% to 800k, bZ4X sales collapsed, Lexus UX 300e withdrawn), but the load-bearing forward
  concern is solid-state slippage: the timeline has drifted 2020 → 2023 → 2026 → 2027-28, and Chery announced a solid-state EV for 2026. The
   CEO transition to CFO Kenta Kon (Apr 2026) signals a margin-discipline pivot that may slow BEV investment further, and Erste Group
  downgraded to Hold on 2 April 2026. S&P A+ stable was affirmed and Europe BEV sales grew +79% YoY in Q1 2026, keeping the score firmly in
  MEDIUM-LOW territory.

  BYD Company Limited — 45 (MEDIUM, 0.65)                                                                                                   
   
  BYD's FY2025 HKEX-filed results (27 Mar 2026) confirmed real pressure: net profit fell 19% to CNY 32.62bn, gross margin compressed 170 bps
   to 17.74%, and operating cash flow dropped 55.7% — though the OCF decline is investment-cycle-driven (Brazil plant, Hungary trial, 4,239
  Megawatt charging stations) rather than operational distress. The widely reported "Geely overtook BYD" story covered only Jan–Feb 2026 and
   reflected Chinese-New-Year plus EV purchase-tax-exemption expiry; BYD reclaimed #1 NEV share in March at 22.8%, and on 29 March raised
  its 2026 overseas export target from 1.3M to 1.5M after delivering 1.04M (+151% YoY) in 2025. Technology execution is real, not slideware:
   Blade 2.0 is cascading to 10 models, 1.5 MW Flash Charging is deployed at 4,239 live stations, and God's Eye ADAS is free across 21
  models. The balance sheet remains fortress-grade (CNY 154.9B cash, 4.9% debt/liability ratio), so primary-strategy assumptions (vertical
  integration + scale + global ramp) are succeeding, not failing. The score sits in MEDIUM because the earnings miss, EU 27% anti-subsidy
  duties + Hungary probe, Mexico plant cancellation, and unresolved anti-involution enforcement are genuine overhangs that prevent a LOW —
  but none constitute primary-strategy failure.