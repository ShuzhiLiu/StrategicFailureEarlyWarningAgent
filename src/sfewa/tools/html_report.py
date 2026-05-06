"""Static HTML report generator (L1.7 — hosted demo first-screen MVP).

Reads the artifacts under outputs/{run_id}/ and produces a single
self-contained `report.html` with three pillars visible above the fold:

    1. Evidence trace   — every top-level claim links to its citations
    2. Provenance       — model + commit + cutoff + manifest counts
    3. Controls applied — temporal gate / verifier / adversarial / self-consistency

For forward cases, "Forward surveillance case. Not a retrospective
validation." appears above the fold per the roadmap acceptance criterion.

Single file, embedded CSS, no external dependencies. Can be opened
locally, served by any static host, or pasted into a hosted demo.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _e(s: Any) -> str:
    """HTML-escape a value, gracefully handling None/non-string."""
    if s is None:
        return ""
    return html.escape(str(s))


# ── CSS (embedded; one of the design goals is single-file) ──

_CSS = """
:root {
  --c-bg: #0f1116;
  --c-fg: #e8eaf0;
  --c-muted: #8d94a3;
  --c-accent: #3b82f6;
  --c-warn: #f59e0b;
  --c-danger: #ef4444;
  --c-success: #10b981;
  --c-card: #181b23;
  --c-border: #262b35;
  --c-low: #10b981;
  --c-medium: #f59e0b;
  --c-high: #ef4444;
  --c-critical: #b91c1c;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 15px/1.55 -apple-system, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
  background: var(--c-bg);
  color: var(--c-fg);
}
a { color: var(--c-accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px; }
.forward-banner {
  background: var(--c-warn);
  color: #1a1300;
  padding: 12px 16px;
  font-weight: 600;
  text-align: center;
  border-radius: 6px;
  margin-bottom: 18px;
}
header.case {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--c-border);
  padding-bottom: 14px;
  margin-bottom: 22px;
}
header h1 { margin: 0 0 4px; font-size: 26px; }
header .subtitle { color: var(--c-muted); margin: 0; font-size: 14px; }
.verdict {
  display: flex; align-items: baseline; gap: 14px;
}
.verdict .score {
  font-size: 42px; font-weight: 700; letter-spacing: -1px;
}
.verdict .level {
  font-size: 13px; font-weight: 600; padding: 4px 10px; border-radius: 4px;
  text-transform: uppercase;
}
.level.low      { background: rgba(16,185,129,0.15); color: var(--c-low); }
.level.medium   { background: rgba(245,158,11,0.15); color: var(--c-medium); }
.level.high     { background: rgba(239,68,68,0.15);  color: var(--c-high); }
.level.critical { background: rgba(185,28,28,0.20);  color: var(--c-critical); }
.confidence { color: var(--c-muted); font-size: 13px; }

.pillars {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 22px;
}
.pillar {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 16px;
}
.pillar h2 {
  margin: 0 0 10px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--c-muted);
}
.pillar .stat {
  font-size: 20px; font-weight: 600; margin-right: 6px;
}
.pillar ul { margin: 0; padding: 0 0 0 16px; }
.pillar li { margin-bottom: 4px; }
.kept-vs-rejected {
  display: flex; gap: 8px; align-items: center;
}
.kept-vs-rejected .kept { color: var(--c-success); font-weight: 600; }
.kept-vs-rejected .rejected { color: var(--c-warn); font-weight: 600; }
.kept-vs-rejected .sep { color: var(--c-muted); }
.pill {
  display: inline-block; padding: 2px 8px;
  font-size: 11px; border-radius: 999px;
  border: 1px solid var(--c-border);
  color: var(--c-muted);
  margin-right: 4px;
}
.pill.ok { color: var(--c-success); border-color: rgba(16,185,129,0.4); }

section.memo {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 18px 20px;
  margin-bottom: 22px;
  white-space: pre-wrap;
}
section.memo h2 {
  margin: 0 0 8px;
  font-size: 14px;
  letter-spacing: 0.06em;
  color: var(--c-muted);
  text-transform: uppercase;
}
section h2.section-title {
  font-size: 16px; margin: 28px 0 12px;
  border-top: 1px solid var(--c-border); padding-top: 16px;
}
.factor {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.factor .header {
  display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap;
}
.factor .id {
  font-family: ui-monospace, "SF Mono", monospace;
  font-size: 12px;
  color: var(--c-muted);
}
.factor .dim {
  font-weight: 600; font-size: 14px;
}
.factor .severity {
  font-size: 11px; padding: 2px 8px; border-radius: 4px; text-transform: uppercase;
}
.factor .meta {
  color: var(--c-muted); font-size: 12px;
}
.factor .claim {
  margin: 10px 0 4px; padding-left: 10px; border-left: 3px solid var(--c-border);
  color: #d6dae3;
}
.factor .citations { margin-top: 8px; font-size: 13px; }
.factor .citations a { margin-right: 6px; }
.evidence-card {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
  font-size: 13px;
}
.evidence-card .head {
  display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap;
  margin-bottom: 4px;
}
.evidence-card .id {
  font-family: ui-monospace, "SF Mono", monospace;
  color: var(--c-muted);
}
.evidence-card .stance {
  font-size: 11px; padding: 1px 6px; border-radius: 3px;
}
.stance.supports_risk     { background: rgba(239,68,68,0.15);  color: var(--c-high); }
.stance.contradicts_risk  { background: rgba(16,185,129,0.15); color: var(--c-low); }
.stance.neutral           { background: rgba(141,148,163,0.15); color: var(--c-muted); }
.evidence-card .text { color: #c0c4cd; }
.evidence-card .src { color: var(--c-muted); font-size: 11px; margin-top: 4px; }
.provenance-block {
  font-family: ui-monospace, "SF Mono", monospace;
  font-size: 12px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: 6px;
  padding: 12px 14px;
  white-space: pre-wrap;
  overflow-x: auto;
  color: #c0c4cd;
}
table.manifest {
  width: 100%; border-collapse: collapse; font-size: 13px;
  background: var(--c-card); border: 1px solid var(--c-border);
  border-radius: 6px; overflow: hidden;
}
table.manifest th, table.manifest td {
  padding: 8px 10px; text-align: left; vertical-align: top;
  border-bottom: 1px solid var(--c-border);
}
table.manifest th {
  background: #15181f; font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.06em; color: var(--c-muted);
}
table.manifest td.dec-kept { color: var(--c-success); font-weight: 600; }
table.manifest td.dec-rejected { color: var(--c-warn); font-weight: 600; }
footer {
  color: var(--c-muted); font-size: 12px; text-align: center;
  margin-top: 30px; padding-top: 18px; border-top: 1px solid var(--c-border);
}
"""


# ── Pillar builders ──


def _pillar_evidence_trace(citations: dict, factors: list[dict]) -> str:
    if not citations:
        body = "<p>No citation summary in run.</p>"
    else:
        body = (
            f"<div><span class='stat'>{citations.get('factors_with_resolved_citation', 0)}</span>"
            f"<span style='color:var(--c-muted)'>/{citations.get('total_factors', 0)}</span> factors with resolved citation</div>"
            f"<div style='margin-top:6px;color:var(--c-muted);font-size:13px'>"
            f"{citations.get('total_citations_resolved', 0)} of "
            f"{citations.get('total_citations_made', 0)} citations resolve to "
            f"a source document</div>"
        )
    return f"<div class='pillar evidence'><h2>Evidence trace</h2>{body}</div>"


def _pillar_provenance(prov: dict) -> str:
    model = prov.get("model", {})
    git = prov.get("git", {})
    case_cfg = prov.get("case_config", {})

    bits = []
    if model.get("model_id"):
        bits.append(f"<div>Model: <strong>{_e(model['model_id'])}</strong></div>")
    if git.get("commit"):
        suffix = " (dirty)" if git.get("dirty") else ""
        bits.append(
            f"<div>Commit: <code>{_e(git['commit'])}</code>"
            f"<span style='color:var(--c-muted)'>{_e(suffix)}</span></div>"
        )
    if case_cfg.get("sha256"):
        bits.append(
            f"<div>Case sha: <code>{_e(case_cfg['sha256'][:12])}…</code></div>"
        )
    if prov.get("cutoff_date"):
        bits.append(f"<div>Cutoff: <strong>{_e(prov['cutoff_date'])}</strong></div>")

    body = "".join(bits) or "<p>No provenance recorded.</p>"
    return f"<div class='pillar provenance'><h2>Provenance</h2>{body}</div>"


def _pillar_controls(summary: dict, prov: dict, challenges: list[dict]) -> str:
    """Controls Applied: temporal gate, verifier corpus, adversarial signal."""
    manifest = summary.get("manifest", {}) or {}
    audit_meta = prov.get("audit_meta", {}) or {}

    # Adversarial signal: STRONG count
    strong = sum(1 for c in challenges if (c.get("severity") or "").lower() == "strong")
    moderate = sum(1 for c in challenges if (c.get("severity") or "").lower() == "moderate")

    items = []
    items.append(
        f"<li><strong>Temporal gate:</strong> "
        f"<span class='kept-vs-rejected'>"
        f"<span class='kept'>{manifest.get('kept', 0)} kept</span>"
        f"<span class='sep'>/</span>"
        f"<span class='rejected'>{manifest.get('rejected_post_cutoff', 0)} rejected post-cutoff</span>"
        f"</span></li>"
    )
    verifier = audit_meta.get("verifier_corpus") or "open_web"
    pill_class = "pill ok" if verifier == "allowed_sources_only" else "pill"
    items.append(
        f"<li><strong>Verifier corpus:</strong> "
        f"<span class='{pill_class}'>{_e(verifier)}</span></li>"
    )
    items.append(
        f"<li><strong>Adversarial:</strong> "
        f"{strong} STRONG, {moderate} MODERATE</li>"
    )
    if summary.get("adversarial_pass_count"):
        items.append(
            f"<li><strong>Adversarial passes:</strong> "
            f"{summary['adversarial_pass_count']}</li>"
        )
    return "<div class='pillar controls'><h2>Controls applied</h2><ul>" + "".join(items) + "</ul></div>"


# ── Section builders ──


def _format_factor(f: dict, evidence_index: dict[str, dict]) -> str:
    sev = (f.get("severity") or "low").lower()
    fid = f.get("factor_id") or f.get("dimension") or "?"
    dim = f.get("dimension") or ""
    title = f.get("title") or ""
    claim = f.get("claim") or f.get("description") or ""
    depth = f.get("depth_of_analysis", "?")
    cited = f.get("supporting_evidence") or []
    citation_links = " ".join(
        f"<a href='#ev-{_e(eid)}'>{_e(eid)}</a>"
        for eid in cited if eid in evidence_index
    ) or "<span style='color:var(--c-muted)'>(no resolved citations)</span>"

    return f"""
    <div class='factor' id='factor-{_e(fid)}'>
      <div class='header'>
        <span class='id'>{_e(fid)}</span>
        <span class='dim'>{_e(dim)}</span>
        <span class='severity level {sev}'>{_e(sev)}</span>
        <span class='meta'>depth={_e(depth)}</span>
      </div>
      <div class='claim'>{_e(claim)}</div>
      {f"<div style='font-size:13px;color:var(--c-muted)'>{_e(title)}</div>" if title else ""}
      <div class='citations'>Cites: {citation_links}</div>
    </div>
    """


def _format_evidence_card(e: dict) -> str:
    eid = e.get("evidence_id") or ""
    stance = (e.get("stance") or "neutral").lower()
    text = e.get("claim_text") or e.get("span_text") or ""
    src_title = e.get("source_title") or ""
    src_url = e.get("source_url") or ""
    pub = e.get("published_at") or ""
    src_html = (
        f"<a href='{_e(src_url)}' target='_blank' rel='noopener'>{_e(src_title)}</a>"
        if src_url else _e(src_title)
    )
    return f"""
    <div class='evidence-card' id='ev-{_e(eid)}'>
      <div class='head'>
        <span class='id'>{_e(eid)}</span>
        <span class='stance {stance}'>{_e(stance.replace('_',' '))}</span>
        <span style='color:var(--c-muted);font-size:11px'>{_e(pub)}</span>
      </div>
      <div class='text'>{_e(text)}</div>
      <div class='src'>{src_html}</div>
    </div>
    """


def _format_manifest_table(manifest: list[dict]) -> str:
    if not manifest:
        return "<p style='color:var(--c-muted)'>No manifest entries.</p>"
    rows = []
    for e in manifest[:80]:  # cap rendered table; full data is in source_manifest.json
        dec = e.get("cutoff_decision") or "?"
        cell_class = "dec-kept" if dec == "kept" else "dec-rejected"
        rows.append(
            f"<tr>"
            f"<td>{_e(e.get('source'))}</td>"
            f"<td>{_e(e.get('title') or '')[:80]}</td>"
            f"<td>{_e(e.get('release_time'))}</td>"
            f"<td class='{cell_class}'>{_e(dec)}</td>"
            f"</tr>"
        )
    return (
        "<table class='manifest'><thead>"
        "<tr><th>Source</th><th>Title</th><th>Release</th><th>Decision</th></tr>"
        "</thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


# ── Top-level ──


def render_report(
    *,
    summary: dict,
    factors: list[dict],
    evidence: list[dict],
    challenges: list[dict],
    manifest: list[dict],
    provenance: dict,
    memo: str | None,
) -> str:
    """Render the full HTML document. Pure function — testable without disk I/O."""
    case_type = summary.get("case_type", "retrospective")
    company = summary.get("company") or "(unknown)"
    theme = summary.get("strategy_theme") or ""
    cutoff = summary.get("cutoff_date") or ""
    score = summary.get("risk_score")
    level = (summary.get("overall_risk_level") or "").lower()
    confidence = summary.get("overall_confidence")

    forward_banner = (
        '<div class="forward-banner">Forward surveillance case. '
        'Not a retrospective validation.</div>'
        if case_type == "forward"
        else ""
    )

    evidence_index = {e.get("evidence_id"): e for e in evidence if e.get("evidence_id")}

    pillars = (
        _pillar_evidence_trace(summary.get("citations", {}), factors)
        + _pillar_provenance(provenance)
        + _pillar_controls(summary, provenance, challenges)
    )

    factors_html = "".join(_format_factor(f, evidence_index) for f in factors)
    evidence_html = "".join(_format_evidence_card(e) for e in evidence)

    memo_html = (
        f"<section class='memo'><h2>Risk memo</h2>{_e(memo)}</section>" if memo else ""
    )

    provenance_html = (
        f"<section><h2 class='section-title'>Provenance (full)</h2>"
        f"<div class='provenance-block'>{_e(json.dumps(provenance, indent=2, ensure_ascii=False))}</div>"
        f"</section>"
    )

    manifest_html = (
        f"<section><h2 class='section-title'>Source manifest</h2>"
        f"{_format_manifest_table(manifest)}"
        f"</section>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SFEWA Report — {_e(company)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_CSS}</style>
</head>
<body>
<div class="container">
{forward_banner}
<header class="case">
  <div>
    <h1>{_e(company)}</h1>
    <p class="subtitle">{_e(theme)} · cutoff <strong>{_e(cutoff)}</strong> · {_e(case_type)}</p>
  </div>
  <div class="verdict">
    <span class="score">{_e(score) if score is not None else '—'}</span>
    <span class="level {level}">{_e(level) or '—'}</span>
    <span class="confidence">conf {_e(confidence) if confidence is not None else '—'}</span>
  </div>
</header>

<section class="pillars">
{pillars}
</section>

{memo_html}

<section>
  <h2 class="section-title">Risk factors ({len(factors)})</h2>
  {factors_html}
</section>

<section>
  <h2 class="section-title">Evidence ({len(evidence)})</h2>
  {evidence_html}
</section>

{manifest_html}
{provenance_html}

<footer>
  Generated {_e(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'))}Z
  · SFEWA · {_e(provenance.get('git', {}).get('commit') or '')}
</footer>
</div>
</body>
</html>
"""


def generate_report(run_dir: Path | str) -> Path:
    """Generate report.html from artifacts in `run_dir`. Returns the path written."""
    run = Path(run_dir)
    summary = _safe_load(run / "run_summary.json", {}) or {}
    factors = _safe_load(run / "risk_factors.json", []) or []
    evidence = _safe_load(run / "evidence.json", []) or []
    challenges = _safe_load(run / "challenges.json", []) or []
    manifest = _safe_load(run / "source_manifest.json", []) or []
    provenance = _safe_load(run / "provenance.json", {}) or {}
    memo_path = run / "risk_memo.md"
    memo = memo_path.read_text(encoding="utf-8") if memo_path.exists() else None

    html_text = render_report(
        summary=summary,
        factors=factors,
        evidence=evidence,
        challenges=challenges,
        manifest=manifest,
        provenance=provenance,
        memo=memo,
    )
    out = run / "report.html"
    out.write_text(html_text, encoding="utf-8")
    return out
