# Strategic Failure Early Warning Agent

**Time-Bounded Multi-Agent Strategic Risk Analysis for Public Companies**

## Problem

Strategic failures at public companies are often visible in public data before they are officially recognized — but the signals are fragmented across company disclosures, industry shifts, competitor moves, and policy changes. No single document tells the full story.

## Approach

A multi-agent system built with LangGraph that:

1. **Retrieves** relevant public documents with strict temporal cutoff enforcement
2. **Extracts** structured evidence with source attribution and exact quotes
3. **Analyzes** risk across 9 dimensions via specialized analyst agents running in parallel
4. **Challenges** its own conclusions through an adversarial reviewer
5. **Synthesizes** a risk assessment with explicit confidence bounds and evidence gaps
6. **Backtests** against actual post-cutoff outcomes to measure prediction quality

## Case Study: Honda EV Strategy

Honda announced ambitious EV targets in 2024 (30% EV/FCEV by 2030, 10 trillion yen investment). By May 2025, targets were revised down to 20% with 7 trillion yen. By March 2026, Honda cancelled multiple North American EV models and recorded up to 2.5 trillion yen in losses.

**The question this system answers**: Using only information available before May 19, 2025, could the system have flagged Honda's EV strategy as high-risk?

**Result**: YES. The system assessed **HIGH risk (0.80 confidence)** using 37 pre-cutoff evidence items across 9 risk dimensions. Backtest matched all 3 ground truth events (2 STRONG + 1 STRONG), correctly predicting the target revision, NA model cancellations, and Afeela restructuring.

## Architecture

```
Case Config → Orchestrator → Agentic Retrieval (3-pass)
  → Evidence Extraction (batched by source)
  → [Industry Analyst | Company Analyst | Peer Analyst] (parallel fan-out)
  → Adversarial Reviewer (with loop-back if >50% strong challenges)
  → Risk Synthesis & Memo (thinking mode)
  → Backtest Evaluator
```

**Agentic retrieval** runs three autonomous passes:
1. **Seed**: EDINET filings (Honda's official regulatory disclosures) + DuckDuckGo web search
2. **Gap analysis**: LLM identifies which risk dimensions lack evidence, generates targeted follow-up queries
3. **Counternarrative**: LLM reads the company's own claims and generates queries seeking challenging external evidence

Built with **LangGraph 2.x** for orchestration, **Qwen3.5-27B** on local vLLM for reasoning (thinking/non-thinking modes), **Pydantic** for structured outputs.

## What This Is Not

- Not a stock price predictor or trading system
- Not a general-purpose chatbot for company summaries
- Not a full-market scanner
- Not an unconstrained AI opinion generator

This is an **auditable research workflow** where every conclusion traces back to timestamped, source-attributed evidence.

## Quick Start

```bash
# Install dependencies
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your vLLM server URL and model name

# Run the Honda case
PYTHONPATH=src uv run python -m sfewa.main --case configs/cases/honda_ev_pre_reset.yaml

# Run tests
PYTHONPATH=src uv run pytest
```

## Project Structure

```
configs/          Case configs, model configs, risk ontology
data/corpus/      Curated document corpus (pre-downloaded)
src/sfewa/
  agents/         One file per agent node
  graph/          LangGraph pipeline assembly and routing
  schemas/        Pydantic models and state definitions
  tools/          Retrieval, parsing, temporal filtering
  prompts/        Prompt templates (not inline)
  ingestion/      Document processing pipeline
  evaluation/     Backtesting and evidence auditing
tests/            Unit and integration tests
```

## Agentic Capabilities

| Capability | Implementation |
|---|---|
| **LLM orchestration** | LangGraph StateGraph: 9 nodes, conditional routing, fan-out parallelism |
| **Autonomous retrieval** | 3-pass retrieval: LLM decides what to search for, identifies evidence gaps, seeks counterevidence |
| **State management** | Typed `PipelineState` with `Annotated[list, operator.add]` reducers for safe concurrent accumulation |
| **Multi-step reasoning loop** | Adversarial loop-back: if >50% factors have strong challenges, re-analyze (max 2 rounds) |
| **Temporal integrity** | Hard cutoff enforcement at retrieval + extraction; LLM constrained from using post-cutoff world knowledge |

## Key Design Principles

1. **Temporal integrity**: All evidence must predate the cutoff. No hindsight leakage.
2. **Evidence over conclusions**: Every claim traces to a specific source and quote.
3. **Adversarial by design**: The system actively challenges its own risk findings.
4. **Structured first**: Produce structured data, then generate narrative.
5. **Uncertainty expressed**: Risk levels include confidence scores and evidence gaps.

## License

MIT
