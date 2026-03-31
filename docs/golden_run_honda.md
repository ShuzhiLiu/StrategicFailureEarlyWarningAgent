# Golden Run: Honda EV Strategy Case

Idealized end-to-end walkthrough assuming perfect model and code execution.
Use this as a reference to validate pipeline behavior against expected output.

**Case**: Honda EV electrification strategy
**Cutoff**: 2025-05-19 (day before business briefing)
**Ground truth**: May 2025 target revision + March 2026 writedown

---

## Step 0: init_case

Loads `configs/cases/honda_ev_pre_reset.yaml`, initializes PipelineState.

```
State:
  case_id: "honda_ev_pre_reset_2025"
  company: "Honda Motor Co., Ltd."
  strategy_theme: "EV electrification strategy"
  cutoff_date: "2025-05-19"
  regions: ["north_america", "china", "global"]
  peers: ["Toyota", "BYD", "Tesla", "Hyundai", "VW", "GM", "Ford"]
  iteration_count: 0
  adversarial_pass_count: 0
  current_stage: "init"
```

**Routing**: Fixed edge → `retrieval`

---

## Step 1: retrieval

Retrieval agent uses DuckDuckGo to search for public information. LLM autonomously generates search queries from case context.

### Generated search queries (LLM decides):

```
"Honda EV electrification strategy"
"Honda EV strategy target revision"
"Honda electric vehicle investment plan"
"Honda north_america EV market"
"Honda china EV market"
"Honda 0 Series EV launch timeline"
"Honda LG battery plant Ohio"
"BYD vs Honda EV sales China"
"IEA global EV outlook 2024 2025"
"GM Ford EV strategy pullback 2024"
```

### Search results (~40 raw, ~25 after dedup):

| # | title | published | status |
|---|---|---|---|
| 1 | "Honda targets 30% EV ratio by 2030, invests 10T yen" | 2024-04-16 | accepted |
| 2 | "Honda 0 Series concepts at CES 2025" | 2025-01-07 | accepted |
| 3 | "Sony Honda AFEELA begins pre-orders" | 2025-01-08 | accepted |
| 4 | "Honda China sales fall 30% as BYD dominates" | 2025-03-12 | accepted |
| 5 | "IEA: Global EV sales hit 20M in 2024" | 2025-02-15 | accepted |
| 6 | "Honda revises 2030 EV target to 20%" | 2025-05-20 | **REJECTED: after cutoff** |
| 7 | "GM scales back EV production plans" | 2024-10-08 | accepted |
| 8 | "Honda-LG Ohio battery plant delayed" | 2025-04-22 | accepted |
| 9 | "BYD enters Japan, Southeast Asia markets" | 2025-02-28 | accepted |
| 10 | "Ford cuts F-150 Lightning production" | 2024-08-15 | accepted |

`check_temporal_validity` tool hard-checks each result → 3 post-cutoff documents rejected with reasons logged.

```
State:
  retrieved_docs: [22 documents]
  current_stage: "retrieval"
```

**Routing**: Fixed edge → `evidence_extraction`

---

## Step 2: evidence_extraction

LLM extracts structured claims from each document, outputs `EvidenceItem` list.

### Extracted evidence (~35 items), key examples:

```yaml
- evidence_id: "E001"
  claim_text: "Honda targets 30% EV sales ratio by 2030 and 100% by 2040"
  claim_type: "target_statement"
  entity: "Honda"
  metric_name: "EV sales ratio"
  metric_value: "30%"
  region: "global"
  published_at: "2024-04-16"
  source_type: "company_presentation"
  stance: "neutral"
  relevance_score: 0.95

- evidence_id: "E002"
  claim_text: "Honda plans 10 trillion yen investment in EV and software through 2030"
  claim_type: "investment_commitment"
  entity: "Honda"
  metric_name: "EV/software investment"
  metric_value: "10000000000000"
  unit: "JPY"
  published_at: "2024-04-16"
  stance: "contradicts_risk"
  relevance_score: 0.90

- evidence_id: "E007"
  claim_text: "Honda China sales declined 30.7% YoY in Q1 2025 amid BYD dominance"
  claim_type: "financial_metric"
  entity: "Honda"
  metric_name: "China sales growth"
  metric_value: "-30.7%"
  region: "china"
  published_at: "2025-03-12"
  stance: "supports_risk"
  relevance_score: 0.92

- evidence_id: "E012"
  claim_text: "BYD sold 4.2M NEVs in 2024, becoming world's largest EV maker"
  claim_type: "competitive_positioning"
  entity: "BYD"
  published_at: "2025-01-15"
  stance: "supports_risk"
  relevance_score: 0.85

- evidence_id: "E018"
  claim_text: "GM delays Buick and Chevrolet EV launches, cuts Ultium production"
  claim_type: "strategic_revision"
  entity: "GM"
  published_at: "2024-10-08"
  stance: "supports_risk"
  relevance_score: 0.70

- evidence_id: "E023"
  claim_text: "Honda-LG Ohio battery JV plant construction delayed by 6 months"
  claim_type: "execution"
  entity: "Honda"
  region: "north_america"
  published_at: "2025-04-22"
  stance: "supports_risk"
  relevance_score: 0.88

- evidence_id: "E028"
  claim_text: "Honda 0 Series first model launch pushed to 2026, no firm NA date"
  claim_type: "product_launch_plan"
  entity: "Honda"
  published_at: "2025-03-05"
  stance: "supports_risk"
  relevance_score: 0.91

- evidence_id: "E031"
  claim_text: "China NEV penetration exceeds 50% in March 2025"
  claim_type: "market_outlook"
  region: "china"
  published_at: "2025-04-10"
  stance: "supports_risk"
  relevance_score: 0.87
```

```
State:
  evidence: [35 items]  (operator.add appends)
  current_stage: "evidence_extraction"
  iteration_count: 1
```

**Routing**: `should_continue_extraction()` → `iteration_count=1 < 3` and evidence count sufficient → no loop → fan-out to three analysts

---

## Step 3: Three Analysts in Parallel (Fan-out via `Send`)

### 3a. Industry Analyst

**Input**: Evidence filtered to `source_type in [industry_report, government_policy]` + market evidence

**Output risk_factors**:

```yaml
- factor_id: "RF001"
  dimension: "market_timing"
  title: "China EV market tipping point already passed"
  description: >
    China NEV penetration exceeded 50% in early 2025. Honda's 30% global EV
    target by 2030 assumes gradual transition, but China — Honda's second
    largest market — has already tipped. Honda is planning for a market
    that no longer exists.
  severity: "critical"
  confidence: 0.88
  supporting_evidence: ["E007", "E031", "E012"]
  contradicting_evidence: []
  causal_chain:
    - "China NEV penetration >50%"
    - "Consumer preference shift irreversible at this penetration"
    - "Honda China sales declining 30% YoY"
    - "Honda's 2030 timeline too slow for China market"
  unresolved_gaps:
    - "Honda may have unreported China-specific EV acceleration plans"

- factor_id: "RF002"
  dimension: "policy_dependency"
  title: "US IRA subsidy assumptions fragile"
  description: >
    Honda's NA EV investment plan (Ohio battery plant, 0 Series launch)
    heavily depends on IRA subsidies. Political uncertainty around 2025
    creates risk that subsidy landscape shifts before Honda's products
    reach market.
  severity: "medium"
  confidence: 0.65
  supporting_evidence: ["E023", "E033"]
  contradicting_evidence: ["E034"]
  causal_chain:
    - "Honda NA EV plan built around IRA battery manufacturing credits"
    - "2025 political transition creates policy uncertainty"
    - "Honda plant delayed → may miss subsidy qualification windows"
  unresolved_gaps:
    - "Actual IRA policy changes not yet announced before cutoff"
```

### 3b. Company Strategy Analyst

**Input**: Evidence filtered to `source_type in [company_filing, company_presentation]`

**Output risk_factors**:

```yaml
- factor_id: "RF003"
  dimension: "capital_allocation"
  title: "10T yen investment commitment disproportionate to EV revenue base"
  description: >
    Honda committed 10T yen to EV/software through 2030, but EV revenue
    as of early 2025 is negligible. This represents ~40% of Honda's market
    cap being bet on unproven EV execution while ICE/HEV cash flows fund
    the transition.
  severity: "high"
  confidence: 0.82
  supporting_evidence: ["E002", "E001", "E028"]
  contradicting_evidence: ["E002"]
  causal_chain:
    - "10T yen committed to EV/software"
    - "No EV volume revenue before 2026"
    - "If EV demand doesn't materialize as planned → stranded investment"
    - "HEV margin pressure from Chinese competitors accelerates cash drain"

- factor_id: "RF004"
  dimension: "narrative_consistency"
  title: "Messaging gap between ambition and execution timeline"
  description: >
    Honda announced aggressive 2030/2040 targets in April 2024, but by
    early 2025 the 0 Series launch is delayed, the Ohio plant is behind
    schedule, and no concrete NA EV model lineup has been confirmed.
    The gap between announcement rhetoric and execution milestones
    is widening.
  severity: "high"
  confidence: 0.85
  supporting_evidence: ["E001", "E028", "E023"]
  contradicting_evidence: ["E003"]
  causal_chain:
    - "April 2024: 30% EV by 2030, 10T yen investment"
    - "Jan 2025: 0 Series concepts shown but no production date"
    - "Mar 2025: First model launch pushed to 2026"
    - "Apr 2025: Ohio plant delayed 6 months"
    - "Narrative → execution gap pattern = classic pre-revision signal"

- factor_id: "RF005"
  dimension: "execution"
  title: "Honda-LG JV and Sony Honda Mobility add execution complexity"
  description: >
    Honda's EV strategy depends on multiple JV partnerships (LG for batteries,
    Sony for AFEELA). JV structures add coordination overhead, split decision
    authority, and historically show slower execution than vertically
    integrated competitors like BYD and Tesla.
  severity: "medium"
  confidence: 0.72
  supporting_evidence: ["E003", "E023"]
  contradicting_evidence: []
```

### 3c. Peer Benchmark Analyst

**Input**: Evidence filtered to peer-related + competitive evidence

**Output risk_factors**:

```yaml
- factor_id: "RF006"
  dimension: "competitive_pressure"
  title: "BYD cost and scale advantage creates insurmountable gap in China"
  description: >
    BYD sold 4.2M NEVs in 2024 vs Honda's ~50K EVs globally. BYD's
    vertical integration (batteries, chips, software) gives 15-20%
    cost advantage. Honda cannot compete on price in China, its
    second largest market.
  severity: "critical"
  confidence: 0.90
  supporting_evidence: ["E012", "E007", "E031"]
  contradicting_evidence: []
  causal_chain:
    - "BYD: 4.2M units, vertically integrated, cost leader"
    - "Honda: ~50K EVs, dependent on JV for batteries"
    - "15-20% cost gap → Honda EVs uncompetitive in China"
    - "China >50% NEV → Honda loses its ICE customer base"
    - "No credible path to close gap before 2030"

- factor_id: "RF007"
  dimension: "regional_mismatch"
  title: "Honda's EV investment concentrated in NA while growth is in China/SEA"
  description: >
    Ohio battery plant and 0 Series designed for NA market. But fastest
    EV adoption is in China (>50% NEV) and expanding to SEA. Honda's
    geographic allocation of EV investment mismatches where the market
    is moving fastest.
  severity: "high"
  confidence: 0.78
  supporting_evidence: ["E023", "E031", "E009"]
  contradicting_evidence: []
```

```
State (three analysts write in parallel, operator.add merges):
  risk_factors: [RF001, RF002, RF003, RF004, RF005, RF006, RF007]
  current_stage: "analysis"
```

**Routing**: All three analysts complete → fixed edge → `adversarial_review`

---

## Step 4: adversarial_review (Thinking Mode)

Adversarial reviewer uses thinking mode (`<think>...</think>` CoT) to challenge each risk factor.

### LLM internal reasoning (thinking mode `<think>` block):

```
<think>
Let me examine each risk factor for potential biases:

RF001 (market_timing/China): Strong evidence. But is this Honda-specific
or industry-wide? Toyota also struggling in China. The factor correctly
identifies Honda-specific impact (30% sales decline), so it's not purely
industry-level. Challenge: weak.

RF003 (capital_allocation): The 10T yen sounds alarming, but need to check —
is this unusual relative to Honda's revenue base? Honda's annual revenue is
~20T yen, so 10T over 6 years is ~8% of annual revenue per year. That's
aggressive but not unprecedented for a major pivot. However, the factor's
real point is about ROI risk with no EV revenue yet — that's valid.
Challenge: moderate.

RF004 (narrative_consistency): This is the strongest factor. The timeline
from announcement (Apr 2024) to delays (early 2025) is only 9 months.
But — could the delays be normal for a new platform? The 0 Series was always
planned for 2026 launch. The Ohio plant delay is more concerning. Let me
check if there's counter-evidence...E003 (CES concepts) shows progress.
Challenge: moderate — the delays may be within normal range for a new
EV platform.

RF006 (competitive_pressure/BYD): Very strong evidence, hard to challenge.
The volume and cost gap is factual. Only challenge: Honda may not be
competing directly with BYD (different segments). But in China, BYD spans
all segments now. Challenge: weak.

RF002 (policy_dependency): This is the weakest factor. Policy uncertainty
is generic, not Honda-specific. No concrete evidence of IRA changes before
cutoff. Challenge: strong — this is speculative.
</think>
```

### Output adversarial_challenges:

```yaml
- challenge_id: "AC001"
  target_factor_id: "RF002"
  challenge_text: >
    Policy dependency risk is speculative. No concrete IRA policy changes
    occurred before cutoff. This factor applies equally to all NA EV makers
    (GM, Ford, Hyundai), not Honda-specific. Risk of selection bias:
    choosing a generic industry risk to inflate Honda's risk profile.
  counter_evidence: ["E034"]
  severity: "strong"
  resolution: null

- challenge_id: "AC002"
  target_factor_id: "RF003"
  challenge_text: >
    10T yen over 6 years is ~8% of Honda's annual revenue — aggressive but
    not unprecedented for auto industry pivots. VW committed similar
    proportions. The capital allocation risk may be overstated without
    comparing to industry norms.
  counter_evidence: []
  severity: "moderate"
  resolution: null

- challenge_id: "AC003"
  target_factor_id: "RF004"
  challenge_text: >
    0 Series was always announced for 2026 launch. The "delay" framing
    may reflect analyst expectation bias rather than actual slippage.
    However, the Ohio plant delay is a genuine execution miss.
  counter_evidence: ["E003"]
  severity: "moderate"
  resolution: null

- challenge_id: "AC004"
  target_factor_id: "RF005"
  challenge_text: >
    JV complexity is a generic risk. Many successful EV programs use JVs
    (e.g., Toyota-Panasonic). Without evidence of specific Honda JV
    dysfunction, this factor is speculative.
  counter_evidence: []
  severity: "moderate"
  resolution: null
```

**Routing**: `after_adversarial_review()`:
```
strong challenges: 1 (AC001)
total risk_factors: 7
ratio: 1/7 = 14.3% < 50% threshold
→ No loop back → proceed to risk_synthesis
adversarial_pass_count: 1
```

---

## Step 5: risk_synthesis (Thinking Mode)

Synthesis agent combines all risk factors + adversarial challenges into final assessment.

### Weighted scoring (based on `configs/ontology_v1.yaml` dimension weights):

```
Dimension                Weight  Severity    Score  Notes
──────────────────────── ─────── ─────────── ────── ──────────────────────────
market_timing (RF001)     0.15   critical    0.95   Not effectively challenged
regional_mismatch (RF007) 0.10   high        0.80   Not challenged
product_portfolio         0.10   —           —      No factor (gap)
technology_capability     0.10   —           —      No factor (gap)
capital_allocation (RF003)0.15   high→medium 0.65   Downgraded by AC002
execution (RF005)         0.10   medium→low  0.45   Downgraded by AC004
narrative_consistency     0.10   high        0.80   AC003 partial, Ohio confirmed
policy_dependency (RF002) 0.05   medium→low  0.30   Downgraded by AC001 (strong)
competitive_pressure      0.15   critical    0.92   Nearly unchallengeable

Weighted overall = sum(weight * score) = 0.72
```

### Output:

```
overall_risk_level: "high"
overall_confidence: 0.72
```

### Risk memo (abbreviated):

```markdown
# Strategic Risk Assessment: Honda EV Electrification Strategy
## Cutoff: 2025-05-19 | Risk: HIGH | Confidence: 0.72

## Executive Summary
Based on 35 pieces of pre-cutoff evidence, Honda's EV electrification
strategy faces HIGH risk of significant revision. Two critical factors
dominate: (1) China's EV market has already tipped past 50% NEV
penetration while Honda China sales are collapsing (-30.7% YoY), and
(2) BYD's cost/scale advantage creates an effectively insurmountable
competitive gap in Honda's second largest market.

## Risk Factor Summary
| Dimension | Severity | Confidence | Key Evidence |
|---|---|---|---|
| Market Timing (China) | CRITICAL | 0.88 | E007, E031, E012 |
| Competitive Pressure | CRITICAL | 0.90 | E012, E007 |
| Capital Allocation | MEDIUM | 0.65 | E002, E028 (challenged) |
| Narrative Consistency | HIGH | 0.85 | E001, E028, E023 |
| Regional Mismatch | HIGH | 0.78 | E023, E031, E009 |
| Execution | LOW | 0.45 | E003, E023 (challenged) |
| Policy Dependency | LOW | 0.30 | Downgraded: speculative |

## Causal Narrative
1. Commitment at wrong granularity: Honda treats EV transition as global
   and gradual (30% by 2030), but transition is regional and non-linear
2. Geographic misallocation: Investment concentrated in NA while
   competitive battlefield is in China and expanding to SEA
3. Speed mismatch: BYD iterates in 12-18 months; Honda 0 Series on 3+ year cycle
4. Predicted outcome: Honda forced to revise EV targets downward, reduce
   investment, pivot to HEV bridge — likely within 6-12 months of cutoff

## Adversarial Resolutions
- RF002 (Policy) DOWNGRADED: speculative, not Honda-specific
- RF003 (Capital) DOWNGRADED: investment ratio not unprecedented
- RF004 (Narrative) MAINTAINED: Ohio delay confirms execution gap
- RF005 (Execution) DOWNGRADED: JV risk generic without specific evidence

## Evidence Gaps
1. No access to Honda internal board discussions
2. Product portfolio and technology dimensions have no risk factors
3. LLM world knowledge contamination risk
```

**Routing**: Fixed edge → `backtest`

---

## Step 6: backtest

Backtest agent loads ground truth events (post-cutoff actual outcomes) and matches against predicted risk factors.

### Ground truth events (from case config):

```yaml
GT001: 2025-05-20 — Honda revises 2030 EV ratio from 30% → 20%,
       cuts investment from 10T → 7T yen, emphasizes HEV transition
       (type: target_revision)

GT002: 2026-03-12 — Honda cancels multiple NA EV models, records
       820B-1.12T yen operating expense, up to 2.5T yen total loss
       (type: project_cancellation)
```

### Match results:

```yaml
- event_id: "GT001"
  matched_factors: ["RF001", "RF003", "RF004", "RF006"]
  match_quality: "strong"
  explanation: >
    Predicted: market timing wrong (RF001), capital over-commitment (RF003),
    narrative-execution gap (RF004), competitive pressure (RF006).
    Actual: Honda cut EV ratio 30%→20% (confirms RF001, RF004),
    cut investment 10T→7T yen (confirms RF003), pivoted to HEV
    (confirms competitive pressure forcing retreat, RF006).

- event_id: "GT002"
  matched_factors: ["RF007", "RF003", "RF005"]
  match_quality: "partial"
  explanation: >
    Predicted: regional mismatch with NA focus (RF007), capital risk (RF003),
    JV execution complexity (RF005). Actual: Honda cancelled NA EV models —
    RF007 is strong match. RF003 partially matches via writedown. RF005
    weakly matches. System did NOT predict cancellation as outcome mode.
```

### Backtest scoring:

```
Precision: 5/7 predicted factors matched actual events = 71.4%
  (RF002 policy_dependency and RF005 execution did not directly match)

Recall: 2/2 ground truth events had matching predictions = 100%
  (GT001: strong match, GT002: partial match)

Key miss: Did not predict severity of GT002 (model cancellations + 2.5T yen
total loss). Predicted "target revision" but not "project cancellation and
writedown" as a distinct outcome.
```

**Routing**: Fixed edge → `END`

---

## Pipeline Data Flow Summary

```
init_case ──→ retrieval ──→ evidence_extraction ──→ fan-out ──→ adversarial ──→ synthesis ──→ backtest
   │              │               │                   │            │              │            │
 Load YAML    Search 25 docs  Extract 35 evidence  7 risk factors  4 challenges  Scoring     Match GT
 Init state   Reject 3>cutoff  Structured claims   3 analysts ||   1 strong     HIGH/0.72   P:71% R:100%
                                                               3 moderate
                                                                ↓
                                                          14.3% < 50%
                                                          No loop back
```

## Key Decision Points

| Decision | Condition | This Run |
|---|---|---|
| Extraction loop? | `iteration_count < 3` and evidence insufficient | No (35 items sufficient) |
| Adversarial loop back? | strong challenges > 50% of factors | No (14.3%) |
| Risk level | weighted score > 0.7 = high, > 0.85 = critical | 0.72 → HIGH |
| Which factors downgraded? | Adversarial challenge severity | RF002, RF005 → low |

## Design Validation Takeaways

1. **Temporal filter works** — rejected article containing the ground truth itself (5/20 target revision)
2. **Adversarial review not rubber-stamping** — downgraded 2 weak factors, preserved strong ones
3. **Fan-out genuinely parallel and complementary** — 3 analysts produce non-overlapping risk factors from different angles
4. **Backtest has honest misses** — precision 71% not 100%, system didn't predict cancellation severity
