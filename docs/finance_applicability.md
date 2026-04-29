# Finance Applicability

SFEWA is a public-data strategic risk analysis agent. It is **not** a bank production system, credit decision engine, trading system, AML system, fraud detector, or investment recommendation engine.

Its relevance to regulated finance is at the **agent harness architecture** level: how to structure a long-running AI workflow so that evidence, decisions, uncertainty, and review steps remain visible.

## Short Version

SFEWA demonstrates a reusable pattern for regulated financial AI workflows:

```text
case intake
  -> time-bounded evidence retrieval
  -> source-attributed evidence extraction
  -> evidence sufficiency gate
  -> multi-perspective analyst fan-out
  -> adversarial verification
  -> confidence-bounded synthesis
  -> file-based audit artifacts
```

The current case study uses public-company strategic risk. The same harness pattern can support financial workflows where the output should assist an analyst rather than automate a final decision.

## Financial Workflows This Maps To

| Workflow                          | How SFEWA maps                                                                                                                                              |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Counterparty due diligence        | Gather public disclosures and news before a cutoff date, extract traceable evidence, surface strategic / operational risks, produce analyst-reviewable memo |
| Credit-watchlist research support | Monitor public-company risk signals, separate supporting and contradicting evidence, show confidence and evidence gaps                                      |
| Insurance underwriting research   | Summarize company / industry risk signals from public sources, keep citations and uncertainty visible                                                       |
| Financial research copilot        | Build evidence-backed risk memos with adversarial challenge before synthesis                                                                                |
| AI governance evaluation          | Demonstrate tool orchestration, traceability, routing gates, evaluator-agent review, and audit artifacts                                                    |

## Existing Controls in SFEWA

| Control                   | Current implementation                                                       | Why it matters in finance                           |
| ------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------- |
| Temporal integrity        | Evidence is filtered against a configured cutoff date                        | Avoids hindsight leakage in point-in-time review    |
| Source attribution        | Evidence items include source references and exact quotes                    | Supports analyst review and auditability            |
| Evidence sufficiency gate | The pipeline loops when evidence coverage is insufficient                    | Prevents premature conclusions from thin evidence   |
| Multi-agent separation    | Industry, company, and peer analysts run as separate roles                   | Reduces single-perspective reasoning bias           |
| Adversarial review        | A separate evaluator challenges each risk factor against evidence            | Creates independent challenge before final memo     |
| Confidence and gaps       | Final synthesis includes confidence and evidence limitations                 | Makes uncertainty explicit instead of hiding it     |
| File artifacts            | Runs save evidence, risk factors, challenges, summary, memo, and LLM history | Creates a reviewable audit package                  |
| Plain-Python harness      | Pipeline control flow is readable in ordinary Python                         | Makes governance hooks easier to inspect and extend |

## Boundaries

SFEWA should be presented as a **decision-support research harness**, not an autonomous financial decision system.

Current boundaries:

- Uses public information only
- Does not process customer PII
- Does not connect to bank, insurer, broker, payment, or trading systems
- Does not make or approve credit decisions
- Does not generate investment recommendations
- Does not execute trades or transactions
- Does not perform real-time AML or fraud operations
- Does not claim regulatory compliance by itself

The intended user is a human analyst, reviewer, or AI platform team evaluating how an auditable agent workflow could be structured.

## Example Finance Translation

The existing Honda EV strategy case can be described in finance terms as:

> A public-data counterparty / issuer risk research workflow that asks whether pre-cutoff evidence was sufficient to flag strategic execution risk before later negative events became obvious.

This does not require changing the core system. It changes how the architecture is explained:

| SFEWA term             | Finance-facing interpretation                   |
| ---------------------- | ----------------------------------------------- |
| Company strategy theme | Counterparty / issuer risk topic                |
| Temporal cutoff        | Point-in-time review date                       |
| Evidence extraction    | Source-backed research extraction               |
| Quality gate           | Evidence sufficiency control                    |
| Analyst fan-out        | Specialist review lenses                        |
| Adversarial reviewer   | Independent challenge / model-risk style review |
| Risk memo              | Analyst decision-support memo                   |
| Run artifacts          | Audit and reproducibility package               |

## Why This Is Useful for Regulated Agentic AI

Many financial AI use cases fail not because the model cannot produce text, but because the workflow lacks control:

- no clear evidence boundary
- no source traceability
- no point-in-time constraint
- no independent review step
- no visible confidence and gaps
- no durable audit artifacts
- no obvious place to add human approval

SFEWA is designed around those control points. The current implementation is a public-data prototype, but the harness pattern is directly relevant to regulated AI systems where agents must be inspectable, bounded, and reviewable.

## Practical Roadmap

Short-term, before job applications:

1. Keep the current SFEWA benchmark and case study.
2. Use this note to explain finance relevance.
3. Link this page from the README.
4. In resumes and interviews, describe SFEWA as an auditable agent harness for strategic risk analysis with regulated finance applicability.

Later, only if needed for interviews or portfolio depth:

1. Add a policy gate that blocks unsupported conclusions.
2. Add a human handoff artifact for high-impact outputs.
3. Add an audit graph that links claims, evidence, prompts, and reviewer challenges.
4. Add a public-data counterparty due diligence demo.
5. Add benchmark-style evaluation only after the product story is already clear.

## Resume-Safe Description

> Built SFEWA, a time-bounded multi-agent risk analysis harness with autonomous retrieval, source-attributed evidence extraction, temporal cutoff enforcement, evidence sufficiency gating, adversarial verification, confidence-bounded synthesis, and JSON/JSONL audit artifacts; documented applicability to regulated finance workflows such as counterparty due diligence and credit-watchlist research support.
