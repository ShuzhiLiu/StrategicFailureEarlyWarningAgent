"""Pipeline runtime reporter — structured console output for debugging and demos.

Each agent node calls reporter functions at key moments:
  1. enter_node()  — node started, input summary
  2. log_action()  — key action taken (search, filter, extract, etc.)
  3. exit_node()   — output summary + routing decision

Uses Rich for formatted terminal output. All output goes through a single
Console instance for consistent rendering.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

# ── Singleton console ──
_console = Console()

# Node order for display (step numbering)
NODE_ORDER = [
    "init_case",
    "retrieval",
    "evidence_extraction",
    "quality_gate",
    "industry_analyst",
    "company_analyst",
    "peer_analyst",
    "adversarial_review",
    "risk_synthesis",
    "backtest",
]

# Severity → color mapping
_SEVERITY_COLORS = {
    "critical": "red bold",
    "high": "red",
    "medium": "yellow",
    "low": "green",
}


def _step_label(node_name: str) -> str:
    """Return '[3/9] evidence_extraction' style label."""
    try:
        idx = NODE_ORDER.index(node_name) + 1
    except ValueError:
        idx = "?"
    return f"[{idx}/{len(NODE_ORDER)}] {node_name}"


def enter_node(node_name: str, summary: dict[str, Any] | None = None) -> None:
    """Print when a node starts executing.

    Args:
        node_name: The pipeline node name.
        summary: Optional dict of key input metrics, e.g.
                 {"documents": 22, "cutoff_date": "2025-05-19"}
    """
    label = _step_label(node_name)
    _console.print()
    _console.rule(f"[bold cyan]{label}[/bold cyan]", style="cyan")

    if summary:
        for key, value in summary.items():
            _console.print(f"  {key}: {value}")


def log_action(action: str, details: dict[str, Any] | None = None) -> None:
    """Print a key action taken within a node.

    Args:
        action: Short description of the action, e.g. "Temporal filter"
        details: Optional key-value pairs, e.g.
                 {"accepted": 22, "rejected": 3}
    """
    _console.print(f"  [bold]{action}[/bold]")
    if details:
        for key, value in details.items():
            _console.print(f"    {key}: {value}")


def log_item(label: str, style: str = "") -> None:
    """Print a single indented line item.

    Args:
        label: The text to display.
        style: Optional Rich style string.
    """
    if style:
        _console.print(f"    [{style}]{label}[/{style}]")
    else:
        _console.print(f"    {label}")


def log_rejection(title: str, reason: str) -> None:
    """Print a rejected item (e.g., temporal filter rejection)."""
    _console.print(f"    [red]x[/red] {title} — {reason}")


def log_acceptance(title: str, detail: str = "") -> None:
    """Print an accepted item."""
    suffix = f" — {detail}" if detail else ""
    _console.print(f"    [green]v[/green] {title}{suffix}")


def log_risk_factor(
    factor_id: str,
    dimension: str,
    severity: str,
    confidence: float,
    title: str,
) -> None:
    """Print a risk factor summary line."""
    color = _SEVERITY_COLORS.get(severity, "white")
    _console.print(
        f"    {factor_id} {dimension:<22} [{color}]{severity.upper():<8}[/{color}] "
        f"conf={confidence:.2f}  {title}"
    )


def log_challenge(
    challenge_id: str,
    target_factor: str,
    severity: str,
    summary: str,
) -> None:
    """Print an adversarial challenge summary line."""
    color = _SEVERITY_COLORS.get(severity, "white")
    _console.print(
        f"    {challenge_id} -> {target_factor}  [{color}]{severity.upper():<8}[/{color}] "
        f"{summary}"
    )


def log_backtest_match(
    event_id: str,
    match_quality: str,
    matched_factors: list[str],
    description: str,
) -> None:
    """Print a backtest match result."""
    quality_colors = {
        "strong": "green bold",
        "partial": "yellow",
        "weak": "red",
        "miss": "red bold",
    }
    color = quality_colors.get(match_quality, "white")
    factors_str = ", ".join(matched_factors) if matched_factors else "none"
    _console.print(
        f"    {event_id}  [{color}]{match_quality.upper():<7}[/{color}] "
        f"matched=[{factors_str}]"
    )
    _console.print(f"           {description[:80]}")


def exit_node(
    node_name: str,
    output_summary: dict[str, Any] | None = None,
    next_node: str | None = None,
    reason: str | None = None,
) -> None:
    """Print when a node finishes executing.

    Args:
        node_name: The pipeline node name.
        output_summary: Key output metrics.
        next_node: Where the pipeline routes next.
        reason: Why this routing decision was made.
    """
    if output_summary:
        _console.print(f"  [dim]Output:[/dim]")
        for key, value in output_summary.items():
            _console.print(f"    {key}: {value}")

    if next_node:
        route_text = f"  -> Next: [bold]{next_node}[/bold]"
        if reason:
            route_text += f" ({reason})"
        _console.print(route_text)


def print_risk_summary_table(risk_factors: list[dict], challenges: list[dict]) -> None:
    """Print a Rich table summarizing risk factors and adversarial outcomes."""
    challenged_factors = {
        c["target_factor_id"]: c["severity"]
        for c in challenges
    }

    table = Table(title="Risk Factor Summary", show_lines=True)
    table.add_column("ID", style="bold", width=6)
    table.add_column("Dimension", width=24)
    table.add_column("Severity", width=10)
    table.add_column("Conf", width=6)
    table.add_column("Challenge", width=10)
    table.add_column("Title", width=40)

    for rf in risk_factors:
        fid = rf.get("factor_id", "?")
        severity = rf.get("severity", "?")
        color = _SEVERITY_COLORS.get(severity, "white")
        challenge = challenged_factors.get(fid, "—")

        table.add_row(
            fid,
            rf.get("dimension", "?"),
            Text(severity.upper(), style=color),
            f"{rf.get('confidence', 0):.2f}",
            challenge.upper() if challenge != "—" else "—",
            rf.get("title", "?"),
        )

    _console.print()
    _console.print(table)


def print_final_result(
    risk_level: str | None,
    confidence: float | None,
    evidence_count: int,
    factor_count: int,
    challenge_count: int,
    backtest_summary: str | None,
) -> None:
    """Print the final pipeline result summary."""
    _console.print()
    _console.rule("[bold green]Pipeline Complete[/bold green]", style="green")

    if risk_level:
        color = _SEVERITY_COLORS.get(risk_level, "white")
        _console.print(f"  Risk Level:  [{color}]{risk_level.upper()}[/{color}]")
    if confidence is not None:
        _console.print(f"  Confidence:  {confidence:.2f}")

    _console.print(f"  Evidence:    {evidence_count} items")
    _console.print(f"  Risk factors: {factor_count}")
    _console.print(f"  Challenges:  {challenge_count}")

    if backtest_summary:
        _console.print()
        _console.print(f"  [dim]{backtest_summary[:200]}[/dim]")
