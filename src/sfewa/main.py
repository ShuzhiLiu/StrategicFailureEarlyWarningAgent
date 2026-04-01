"""CLI entry point for the Strategic Failure Early Warning Agent."""

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
from sfewa.graph.pipeline import compile_pipeline
from sfewa.schemas.config import CaseConfig
from sfewa.tools.artifacts import save_run_artifacts

app = typer.Typer(help="Strategic Failure Early Warning Agent")
console = Console()


def _make_case_id(company: str, cutoff: str) -> str:
    """Generate a case_id from company name and cutoff date."""
    slug = re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")
    # Keep it short
    slug = "_".join(slug.split("_")[:3])
    return f"{slug}_{cutoff.replace('-', '')}"


@app.command()
def run(
    case: Optional[Path] = typer.Option(
        None,
        "--case",
        "-c",
        help="Path to case config YAML file",
    ),
    company: Optional[str] = typer.Option(
        None,
        "--company",
        help="Company name (e.g., 'Honda Motor Co., Ltd.')",
    ),
    theme: Optional[str] = typer.Option(
        None,
        "--theme",
        help="Strategy theme (e.g., 'EV electrification strategy')",
    ),
    cutoff: Optional[str] = typer.Option(
        None,
        "--cutoff",
        help="Analysis cutoff date in ISO format (e.g., '2025-05-19')",
    ),
) -> None:
    """Run the full analysis pipeline.

    Two modes:

      1. YAML config:  --case configs/cases/honda_ev_pre_reset.yaml

      2. Minimal input: --company "Honda" --theme "EV strategy" --cutoff 2025-05-19
    """
    if case:
        # ── Mode 1: Load from YAML ──
        console.print(Panel(f"Loading case: {case}", title="SFEWA", style="blue"))
        with open(case) as f:
            raw_config = yaml.safe_load(f)

        # Normalize peers: accept both structured and simple string formats
        raw_peers = raw_config.get("peers", [])
        if raw_peers and isinstance(raw_peers[0], dict):
            raw_config["peers"] = [
                p.get("company", p) if isinstance(p, dict) else str(p)
                for p in raw_peers
            ]

        config = CaseConfig(**raw_config)
    elif company and theme and cutoff:
        # ── Mode 2: Minimal input — LLM generates the rest ──
        console.print(Panel(
            f"Analyzing: {company}",
            title="SFEWA (minimal input)", style="blue",
        ))
        config = CaseConfig(
            company=company,
            strategy_theme=theme,
            cutoff_date=cutoff,
        )
    else:
        console.print(
            "[red]Error:[/red] Provide either --case YAML "
            "or --company + --theme + --cutoff",
        )
        raise typer.Exit(1)

    # Auto-generate case_id if not set
    if not config.case_id:
        config.case_id = _make_case_id(config.company, config.cutoff_date)

    console.print(f"  Company:  [bold]{config.company}[/bold]")
    console.print(f"  Strategy: {config.strategy_theme}")
    console.print(f"  Cutoff:   [red]{config.cutoff_date}[/red]")
    if config.regions:
        console.print(f"  Regions:  {', '.join(config.regions)}")
    else:
        console.print("  Regions:  [dim](LLM will generate)[/dim]")
    if config.peers:
        console.print(f"  Peers:    {len(config.peers)}")
    else:
        console.print("  Peers:    [dim](LLM will generate)[/dim]")
    if config.ground_truth_events:
        console.print(f"  Backtest: {len(config.ground_truth_events)} ground truth events")
    else:
        console.print("  Backtest: [dim](skipped — no ground truth)[/dim]")

    # Build and run pipeline
    graph = compile_pipeline()

    initial_state: dict = {
        "case_id": config.case_id,
        "company": config.company,
        "strategy_theme": config.strategy_theme,
        "cutoff_date": config.cutoff_date,
        "regions": config.regions,
        "peers": config.peers,
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
