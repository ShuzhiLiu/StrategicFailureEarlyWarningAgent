# Contributing

Thanks for your interest. This project is an open portfolio and research artifact — contributions that extend the scope (new companies, new jurisdictions, new reasoning frameworks) are welcome, but please read the design rules first. Company-specific hacks and prompt-tweaking PRs will be rejected; see **Design rules** below.

## Quick orientation

- **Architecture**: [docs/architecture.md](docs/architecture.md) — system design + Iceberg Model + 3-phase adversarial.
- **Framework**: [docs/liteagent_architecture.md](docs/liteagent_architecture.md) — the ~1,000-line utility layer.
- **What has been tried**: [docs/iteration_log.md](docs/iteration_log.md) — 39 iterations with pre/post stability numbers. Read this before proposing a change — there is a very good chance it has already been attempted or has known consequences.
- **Design rules**: [CLAUDE.md](CLAUDE.md) — the non-negotiables.

## Development setup

```bash
uv sync                      # install deps
cp .env.example .env         # point at your LLM endpoint
PYTHONPATH=src uv run pytest # 71 tests, <1s
PYTHONPATH=src uv run ruff check src/ tests/
```

## Design rules (hard rules — PRs violating these will be closed)

1. **No company-specific logic.** Zero `if company == "honda": ...`. The same pipeline, same prompts, same model must produce different results for different companies through evidence-driven reasoning.
2. **LLM-driven routing, not hardcoded thresholds.** Iteration counters are safety bounds only. `if len(evidence) < 10: loop_back()` is not allowed.
3. **Separated evaluation.** When a new quality problem emerges, prefer adding or strengthening an independent evaluator over asking the generator to self-critique.
4. **Evidence-driven, not knowledge-driven.** Conclusions emerge from retrieved evidence. Never use LLM world knowledge as the basis for a severity assessment.
5. **Temporal integrity is non-negotiable.** Any new retrieval or extraction path must enforce the cutoff at the published-date filter, the extraction filter, and the prompt. Adding a fourth leak is worse than fixing the LLM's output.

## Hierarchy of interventions

When the system produces wrong results, fix the **architecture and agent design** — not the prompt wording. In order of preference:

1. **Structural fix** (best) — Add a new node, change routing logic, restructure information flow.
2. **Reasoning framework** — Give agents better decision frameworks that generalize across companies (e.g., the Iceberg Model).
3. **Prompt tuning** (last resort) — Adjust specific prompt language only when the structural design is correct.

## How to add a new company case

1. Create `configs/cases/{company}_{theme}_{cutoff}.yaml`:
   ```yaml
   case_id: tesla_robotaxi_2024
   company: Tesla, Inc.
   ticker: TSLA
   strategy_theme: Robotaxi commercialization
   description: Brief narrative on why this case is interesting.
   cutoff_date: "2024-08-01"   # pre-announcement date
   regions: []                  # LLM will derive if empty
   peers: []                    # LLM will derive if empty
   ground_truth_events:         # optional, for backtest
     - event_id: GT001
       date: "2024-10-10"
       description: Cybercab reveal at We, Robot event
       event_type: product_launch
   ```
2. Run: `python -m sfewa.main --case configs/cases/<file>.yaml --agentic`.
3. Inspect `outputs/<run_id>/` artifacts (see CLAUDE.md "What to check in raw outputs").
4. For publication-quality results, follow the **stability testing protocol** in CLAUDE.md: 3 rounds × 3 companies sequentially.

## How to propose a design change

1. **Read `docs/iteration_log.md`** to verify your change hasn't already been tried.
2. **Run the baseline stability test** (3 rounds × 3 companies) before any change.
3. **Implement the change.**
4. **Run the post-change stability test.**
5. Open a PR that includes:
   - A 1-paragraph rationale.
   - Pre/post stability tables in the PR description (company × round × score).
   - Confirmation that cross-company ordering (Honda > Toyota > BYD) holds in ≥3/3 rounds.
   - An addition to `docs/iteration_log.md` in the existing format.

Regressions in any company's expected band (see CLAUDE.md "Expected baselines") will block merge.

## Test policy

- Add a test for every programmatic invariant (e.g., factor-ID normalization, depth-severity gate, citation cross-validation).
- Stability is tested end-to-end via the 9-run protocol, not via integration tests. Don't add flaky network-dependent integration tests.
- The full unit-test suite must pass in under 5 seconds.

## Reporting issues

Use GitHub Issues. For bug reports, please attach:
- The `outputs/<run_id>/run_summary.json` from a reproducing run,
- The `outputs/<run_id>/llm_history.jsonl` (or the relevant excerpt),
- Expected vs observed behavior.

For feature requests (new company, new jurisdiction, new LLM backend), please describe what you're trying to achieve before proposing an implementation.

## License

By contributing you agree that your contribution is licensed under the MIT License.
