# Documentation

Suggested reading order by audience and time budget.

## 5-minute skim

Start with the project [README](../README.md) — thesis, results, architecture diagram, demo links, quickstart.

## 15-minute thesis read

1. **[harness_engineering.md](harness_engineering.md)** — The thesis document. What an agent harness is, what this project's harness implements, what it deliberately omits and why. Start here if you care about the framing.
2. **[architecture.md](architecture.md)** — Pipeline, node contracts, Iceberg Model, 3-phase adversarial, state management, temporal integrity gates.
3. **[cross_company_results.md](cross_company_results.md)** — Honda / Toyota / BYD risk profiles, evidence stance distributions, backtest details per run.
4. **[claude_code_benchmark.md](claude_code_benchmark.md)** — Independent validation against a general-purpose agent harness; side-by-side methodology.

## 45-minute full read

5. **[liteagent_architecture.md](liteagent_architecture.md)** — The underlying ~1,000-line harness toolkit: module map, patterns encoded, comparison vs LangChain/LangGraph.
6. **[iteration_log.md](iteration_log.md)** — All 40 iterations of development: what was tried, what failed, what was learned, pre/post stability numbers. This is the engineering audit trail.

## Supplementary essays (optional)

See [essays/](essays/) for longer-form background notes:
- `framework_anti_patterns.md` — Why we did not use LangChain/LangGraph.
- `agentic_architecture_research.md` — Survey of production agent systems that informed the harness design.
- `design_report_lite_agent_framework.md` — Historical design doc documenting the monolith → liteagent split.
