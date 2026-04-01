"""CLI entry point for the Strategic Failure Early Warning Agent."""

from __future__ import annotations

import time
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

from sfewa import reporting
from sfewa.graph.pipeline import compile_pipeline
from sfewa.schemas.config import CaseConfig
from sfewa.tools.artifacts import save_run_artifacts

app = typer.Typer(help="Strategic Failure Early Warning Agent")
console = Console()


@app.command()
def run(
    case: Path = typer.Option(
        ...,
        "--case",
        "-c",
        help="Path to case config YAML file",
    ),
) -> None:
    """Run the full analysis pipeline for a given case."""
    # Load case config
    console.print(Panel(f"Loading case: {case}", title="SFEWA", style="blue"))
    with open(case) as f:
        raw_config = yaml.safe_load(f)
    config = CaseConfig(**raw_config)

    console.print(f"  Company:  [bold]{config.company}[/bold]")
    console.print(f"  Strategy: {config.strategy_theme}")
    console.print(f"  Cutoff:   [red]{config.cutoff_date}[/red]")
    console.print(f"  Regions:  {', '.join(config.regions)}")
    console.print(f"  Peers:    {len(config.peers)}")

    # Build and run pipeline
    graph = compile_pipeline()

    initial_state = {
        "case_id": config.case_id,
        "company": config.company,
        "strategy_theme": config.strategy_theme,
        "cutoff_date": config.cutoff_date,
        "regions": config.regions,
        "peers": [p.model_dump() for p in config.peers],
        "search_topics": config.search_topics,
        "ground_truth_events": [e.model_dump() for e in config.ground_truth_events],
    }

    t0 = time.time()
    result = graph.invoke(initial_state)
    elapsed = time.time() - t0

    # ── Final summary via reporter ──
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
    )

    if result.get("risk_memo"):
        console.print()
        console.print(Panel(result["risk_memo"], title="Risk Memo"))

    # ── Save artifacts for audit trail ──
    run_dir = save_run_artifacts(result)
    console.print()
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    console.print(f"  Artifacts saved to: [bold]{run_dir}[/bold]")
    console.print(f"  Total pipeline time: [bold]{minutes}m {seconds}s[/bold]")


if __name__ == "__main__":
    app()
