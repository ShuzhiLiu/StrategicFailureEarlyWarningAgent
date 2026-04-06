"""CLI entry point for the Strategic Failure Early Warning Agent.

Primary interface:
    python -m sfewa.main "Honda Motor Co., Ltd." "EV electrification strategy" 2025-05-19

The agent handles everything else — regions, peers, search queries,
evidence gathering, analysis, and evaluation.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

from sfewa import reporting
from sfewa.graph.pipeline import run_pipeline, run_pipeline_v2
from sfewa.schemas.config import CaseConfig
from sfewa.tools.artifacts import save_run_artifacts
from sfewa.tools.chat_log import clear_log

app = typer.Typer(
    help="Strategic Failure Early Warning Agent — "
    "analyze strategic risk for any public company.",
    add_completion=False,
)
console = Console()


def _make_case_id(company: str, cutoff: str) -> str:
    """Generate a case_id from company name and cutoff date."""
    slug = re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")
    slug = "_".join(slug.split("_")[:3])
    return f"{slug}_{cutoff.replace('-', '')}"


@app.command()
def run(
    company: str = typer.Argument(
        None,
        help="Company name (e.g., 'Honda Motor Co., Ltd.')",
    ),
    strategy_theme: str = typer.Argument(
        None,
        help="Strategy theme to analyze (e.g., 'EV electrification strategy')",
    ),
    cutoff_date: str = typer.Argument(
        None,
        help="Analysis cutoff date, ISO format (e.g., '2025-05-19')",
    ),
    case: Optional[Path] = typer.Option(
        None,
        "--case",
        "-c",
        help="YAML case config file (alternative to positional args)",
    ),
    ground_truth: Optional[Path] = typer.Option(
        None,
        "--ground-truth",
        "-g",
        help="Optional YAML file with ground truth events for backtesting",
    ),
    agentic: bool = typer.Option(
        False,
        "--agentic",
        "-a",
        help="Use agentic retrieval (tool-loop agent for evidence gathering)",
    ),
) -> None:
    """Analyze strategic risk for a company.

    Examples:

        python -m sfewa.main "Honda Motor Co., Ltd." "EV electrification strategy" 2025-05-19

        python -m sfewa.main --case configs/cases/honda_ev_pre_reset.yaml

        python -m sfewa.main "BYD Company Limited" "EV electrification strategy" 2025-05-19
    """
    # Load from YAML config if --case provided
    if case:
        with open(case) as f:
            cfg = yaml.safe_load(f)
        company = cfg["company"]
        strategy_theme = cfg["strategy_theme"]
        cutoff_date = cfg["cutoff_date"]
        regions = cfg.get("regions", [])
        peers = cfg.get("peers", [])
        # Normalize peer dicts to strings
        peers = [
            p.get("company", str(p)) if isinstance(p, dict) else str(p)
            for p in peers
        ]
        gt_events = cfg.get("ground_truth_events", [])
    elif not company or not strategy_theme or not cutoff_date:
        console.print("[red]Error: Provide company, strategy_theme, cutoff_date "
                      "or use --case config.yaml[/red]")
        raise typer.Exit(1)
    else:
        regions = []
        peers = []
        gt_events = []

    # Load ground truth from separate file if provided
    if ground_truth:
        with open(ground_truth) as f:
            gt_raw = yaml.safe_load(f)
        gt_list = gt_raw if isinstance(gt_raw, list) else gt_raw.get("ground_truth_events", [])
        gt_events = gt_list

    console.print(Panel(
        f"[bold]{company}[/bold]\n"
        f"{strategy_theme} | cutoff: [red]{cutoff_date}[/red]",
        title="SFEWA", style="blue",
    ))

    if gt_events:
        console.print(f"  Backtest: {len(gt_events)} ground truth events loaded")
    else:
        console.print("  Backtest: [dim](no ground truth — skipped)[/dim]")

    # Build and run pipeline
    case_id = _make_case_id(company, cutoff_date)

    initial_state: dict = {
        "case_id": case_id,
        "company": company,
        "strategy_theme": strategy_theme,
        "cutoff_date": cutoff_date,
        "regions": regions,
        "peers": peers,
        "ground_truth_events": gt_events,
    }

    clear_log()  # Reset chat log before each run
    t0 = time.time()
    pipeline_fn = run_pipeline_v2 if agentic else run_pipeline
    if agentic:
        console.print("  Pipeline: [bold cyan]v2 (agentic retrieval)[/bold cyan]")
    result = pipeline_fn(initial_state)
    elapsed = time.time() - t0

    # ── Final summary ──
    reporting.print_risk_summary_table(
        result.get("risk_factors", []),
        result.get("adversarial_challenges", []),
    )

    reporting.print_final_result(
        risk_level=result.get("overall_risk_level"),
        confidence=result.get("overall_confidence"),
        evidence_count=len(result.get("evidence", [])),
        factor_count=len(result.get("risk_factors", [])),
        challenge_count=len(result.get("adversarial_challenges", [])),
        backtest_summary=result.get("backtest_summary"),
        risk_score=result.get("risk_score"),
    )

    if result.get("risk_memo"):
        console.print()
        console.print(Panel(result["risk_memo"], title="Risk Memo"))

    # ── Save artifacts ──
    run_dir = save_run_artifacts(result)
    console.print()
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    console.print(f"  Artifacts saved to: [bold]{run_dir}[/bold]")
    console.print(f"  Total pipeline time: [bold]{minutes}m {seconds}s[/bold]")


if __name__ == "__main__":
    app()
