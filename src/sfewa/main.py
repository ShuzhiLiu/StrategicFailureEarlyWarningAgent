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
from sfewa.schemas.config import load_case_and_truth
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


def build_initial_state_from_case(
    case_path: Path,
    *,
    discover_strategies: bool = False,
) -> dict:
    """Build the pipeline initial_state dict from a case YAML.

    Routes truth content via configs/truth/{case_id}.yaml using the
    load_case_and_truth() loader — the only sanctioned path for ground
    truth to enter the pipeline.

    L2.4: when the case YAML omits `strategy_theme` (or when
    `discover_strategies=True` is passed explicitly), the strategy
    discovery agent runs first and supplies the working theme. The full
    candidate list is added to state["discovered_strategies"] so the
    audit trail records what alternatives existed.

    Used by the CLI and by the runtime sentinel test.
    """
    from sfewa.schemas.config import apply_verifier_corpus_default
    case_cfg, truth_cfg = load_case_and_truth(case_path)
    case_cfg = apply_verifier_corpus_default(case_cfg)
    company = case_cfg.company
    cutoff_date = case_cfg.cutoff_date
    case_id = case_cfg.case_id or _make_case_id(company, cutoff_date)
    peers = [
        p.get("company", str(p)) if isinstance(p, dict) else str(p)
        for p in case_cfg.peers
    ]
    audit_meta = {
        "jurisdiction": case_cfg.jurisdiction,
        "ticker": case_cfg.ticker,
        "allowed_sources": list(case_cfg.allowed_sources),
        "doc_types": list(case_cfg.doc_types),
        "verifier_corpus": case_cfg.verifier_corpus,
    }
    gt_events = (
        [e.model_dump() for e in truth_cfg.ground_truth_events]
        if truth_cfg
        else []
    )

    # ── L2.4: strategy discovery ──
    # Trigger when:
    #   - `case.strategy_theme` is missing/empty, OR
    #   - caller explicitly requested `discover_strategies=True` (CLI flag).
    # Audit-grade: the chosen primary becomes `state["strategy_theme"]`,
    # the full candidate list goes to `state["discovered_strategies"]`.
    strategy_theme = (case_cfg.strategy_theme or "").strip()
    discovery_payload: dict | None = None
    if not strategy_theme or discover_strategies:
        from sfewa.agents.strategy_discovery import discover_strategies as _discover
        discovery_payload = _discover(
            company=company,
            cutoff_date=cutoff_date,
            regions=list(case_cfg.regions),
            audit_meta=audit_meta,
        )
        # If the case YAML had a theme AND the caller forced re-discovery,
        # we keep the human-authored theme as primary (override-friendly)
        # but log the discovered candidates anyway.
        if not strategy_theme:
            strategy_theme = discovery_payload.get("primary") or "primary corporate strategy"

    state = {
        "case_id": case_id,
        "company": company,
        "strategy_theme": strategy_theme,
        "cutoff_date": cutoff_date,
        "regions": list(case_cfg.regions),
        "peers": peers,
        "ground_truth_events": gt_events,
        "case_type": case_cfg.case_type,
        "audit_meta": audit_meta,
    }
    if discovery_payload is not None:
        state["discovered_strategies"] = discovery_payload
    return state


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
    discover_strategies: bool = typer.Option(
        False,
        "--discover-strategies",
        help="Force strategy-discovery agent even when strategy_theme is set "
             "(useful for seeing what alternative themes a company has).",
    ),
) -> None:
    """Analyze strategic risk for a company.

    Examples:

        python -m sfewa.main "Honda Motor Co., Ltd." "EV electrification strategy" 2025-05-19

        python -m sfewa.main --case configs/cases/honda_ev_pre_reset.yaml

        python -m sfewa.main "BYD Company Limited" "EV electrification strategy" 2025-05-19
    """
    # ── Load case (and optional truth) ──
    # Truth content lives in configs/truth/{case_id}.yaml and is loaded ONLY
    # via load_case_and_truth() — agents never read it directly. The loader
    # enforces the case_type ↔ truth-file relationship (see L1.3).
    if case:
        if ground_truth:
            console.print(
                "[red]Error: --ground-truth cannot be combined with --case. "
                "Truth files for --case live under configs/truth/{case_id}.yaml.[/red]"
            )
            raise typer.Exit(1)
        initial_state = build_initial_state_from_case(
            case, discover_strategies=discover_strategies,
        )
        company = initial_state["company"]
        strategy_theme = initial_state["strategy_theme"]
        cutoff_date = initial_state["cutoff_date"]
        gt_events = initial_state["ground_truth_events"]
        case_type = initial_state["case_type"]
        if "discovered_strategies" in initial_state:
            ds = initial_state["discovered_strategies"]
            console.print(f"  Discovery: [cyan]{len(ds.get('candidates', []))} candidate themes[/cyan]")
            for c in ds.get("candidates", []):
                star = "★" if c["name"] == ds.get("primary") else "·"
                console.print(f"    {star} [{c.get('confidence',0):.2f}] {c['name'][:80]}")
            if ds.get("rationale"):
                console.print(f"  Rationale: [dim]{ds['rationale'][:200]}[/dim]")
    elif not company or not strategy_theme or not cutoff_date:
        console.print("[red]Error: Provide company, strategy_theme, cutoff_date "
                      "or use --case config.yaml[/red]")
        raise typer.Exit(1)
    else:
        gt_events = []
        case_type = "retrospective"
        case_id = _make_case_id(company, cutoff_date)
        # Positional-args path: optional sidecar truth file (legacy --ground-truth).
        if ground_truth:
            with open(ground_truth) as f:
                gt_raw = yaml.safe_load(f)
            gt_events = (
                gt_raw if isinstance(gt_raw, list)
                else gt_raw.get("ground_truth_events", [])
            )
        initial_state = {
            "case_id": case_id,
            "company": company,
            "strategy_theme": strategy_theme,
            "cutoff_date": cutoff_date,
            "regions": [],
            "peers": [],
            "ground_truth_events": gt_events,
            "case_type": case_type,
            "audit_meta": {},
        }

    console.print(Panel(
        f"[bold]{company}[/bold]\n"
        f"{strategy_theme} | cutoff: [red]{cutoff_date}[/red] | "
        f"case_type: [cyan]{case_type}[/cyan]",
        title="SFEWA", style="blue",
    ))

    if gt_events:
        console.print(f"  Backtest: {len(gt_events)} ground truth events loaded")
    else:
        console.print("  Backtest: [dim](no ground truth — skipped)[/dim]")

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
    # Resolve the truth path (if any) for provenance hashing — same logic
    # the loader uses, just to compute the hash.
    truth_path = None
    if case:
        case_id_for_truth = result.get("case_id")
        candidate = case.parent.parent / "truth" / f"{case_id_for_truth}.yaml"
        if candidate.exists():
            truth_path = candidate
    run_dir = save_run_artifacts(
        result,
        case_path=case if case else None,
        truth_path=truth_path,
        started_at=t0,
        elapsed_seconds=elapsed,
    )
    console.print()
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    console.print(f"  Artifacts saved to: [bold]{run_dir}[/bold]")
    console.print(f"  Total pipeline time: [bold]{minutes}m {seconds}s[/bold]")


if __name__ == "__main__":
    app()
