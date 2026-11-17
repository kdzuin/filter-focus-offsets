"""Self-contained HTML report."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

from .filters import CANONICAL, kit_for
from .ingest import FocusSample, IngestStats
from .model import (
    DEFAULT_OUTLIER_SIGMA,
    SetupSolve,
    build_edges,
    per_session_report,
    session_filter_positions,
    summarize_edge_agreements,
)

FILTER_COLORS = {
    "L": "#d8dee9",
    "R": "#e06c75",
    "G": "#98c379",
    "B": "#61afef",
    "SII": "#e5c07b",
    "Ha": "#c678dd",
    "OIII": "#56b6c2",
}


def _filter_order_key(name: str) -> tuple[int, str]:
    if name in CANONICAL:
        return (CANONICAL.index(name), name)
    return (100, name)


def _session_sort_key(session_id: str) -> tuple:
    """Prefer DATE-like tokens in the path for chronological x-axis order."""
    dates = re.findall(r"20\d{6}", session_id)
    return (dates[-1] if dates else "99999999", session_id)


def session_mean_positions(
    samples: list[FocusSample],
    *,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
) -> tuple[list[str], dict[str, dict[str, float]], list[str]]:
    """Return (ordered sessions, positions, outlier notes) after σ-clipping."""
    means, notes = session_filter_positions(samples, outlier_sigma=outlier_sigma)
    sessions = sorted(means.keys(), key=_session_sort_key)
    return sessions, means, notes

CSS = """
:root {
  --bg: #0f1218;
  --panel: #171b24;
  --text: #e7ecf3;
  --muted: #9aa3b2;
  --line: #2a3140;
  --ok: #3d9a6a;
  --bad: #c45c5c;
  --warn: #c4a35c;
  --accent: #6b8cae;
  --mono: "SF Mono", "Menlo", "Consolas", monospace;
  --sans: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2rem 1.25rem 4rem;
  font-family: var(--sans);
  background: radial-gradient(1200px 600px at 10% -10%, #1a2230, var(--bg));
  color: var(--text);
  line-height: 1.45;
}
main { max-width: 980px; margin: 0 auto; }
h1 { font-size: 1.75rem; font-weight: 600; margin: 0 0 0.25rem; letter-spacing: -0.02em; }
h2 {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 2rem 0 0.75rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--line);
  color: var(--text);
}
.meta, .muted { color: var(--muted); font-size: 0.92rem; }
.badge {
  display: inline-block;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.badge.ok { background: color-mix(in srgb, var(--ok) 25%, transparent); color: #8fd6b0; }
.badge.bad { background: color-mix(in srgb, var(--bad) 25%, transparent); color: #f0a0a0; }
.badge.weak { background: color-mix(in srgb, var(--warn) 20%, transparent); color: #e6d09a; }
.badge.conf { background: color-mix(in srgb, var(--ok) 25%, transparent); color: #8fd6b0; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0.85rem 1rem;
  margin: 0.75rem 0;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
  font-size: 0.92rem;
}
th, td {
  text-align: left;
  padding: 0.45rem 0.55rem;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
th { color: var(--muted); font-weight: 500; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }
td.num, th.num { text-align: right; font-family: var(--mono); font-size: 0.86rem; }
td.mono { font-family: var(--mono); font-size: 0.86rem; }
tr:last-child td { border-bottom: none; }
ul.notes { margin: 0.5rem 0 0; padding-left: 1.2rem; color: var(--muted); }
ul.notes li { margin: 0.25rem 0; }
.grid { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 0.75rem 0.9rem; }
.stat .label { color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
.stat .value { font-size: 1.25rem; font-weight: 600; margin-top: 0.2rem; font-family: var(--mono); }
.setup-block { margin-top: 2.5rem; scroll-margin-top: 1.25rem; }
.session-title { font-family: var(--mono); font-size: 0.85rem; color: var(--accent); margin: 1rem 0 0.35rem; }
.toc { list-style: none; margin: 1rem 0 0; padding: 0; display: grid; gap: 0.45rem; }
.toc a {
  display: flex; justify-content: space-between; gap: 1rem; align-items: baseline;
  text-decoration: none; color: var(--text);
  padding: 0.55rem 0.75rem; border: 1px solid var(--line); border-radius: 8px;
  background: color-mix(in srgb, var(--panel) 80%, transparent);
}
.toc a:hover { border-color: var(--accent); }
.toc .toc-title { font-size: 0.92rem; }
.toc .toc-meta { color: var(--muted); font-size: 0.8rem; font-family: var(--mono); white-space: nowrap; }
.chart-wrap { overflow-x: auto; }
.chart-legend {
  display: flex; flex-wrap: wrap; gap: 0.55rem 1rem;
  margin: 0.65rem 0 0; padding: 0; list-style: none; font-size: 0.85rem;
}
.chart-legend li { display: flex; align-items: center; gap: 0.4rem; color: var(--muted); }
.chart-legend i {
  width: 12px; height: 12px; border-radius: 3px; display: inline-block;
}
.chart-svg { width: 100%; height: auto; display: block; min-width: 520px; }
.chart-svg .gridline { stroke: var(--line); stroke-width: 1; }
.chart-svg .axis { stroke: var(--line); stroke-width: 1.25; }
.chart-svg .tick { fill: var(--muted); font-size: 11px; font-family: var(--mono); }
.chart-svg .label { fill: var(--muted); font-size: 11px; font-family: var(--sans); }
.chart-svg .point { stroke: var(--bg); stroke-width: 1.5; }
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _fmt_signed(value: float, digits: int = 1) -> str:
    return f"{value:+.{digits}f}"


def format_html_report(
    setups: list[tuple[list[FocusSample], SetupSolve]],
    stats: IngestStats,
    *,
    agree_tol: float,
    accept_error: float,
    af_step: float,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
    roots: list[Path] | None = None,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    root_txt = ", ".join(str(r) for r in roots) if roots else ""

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Filter Focus Offsets</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        "<main>",
        "<h1>Filter Focus Offsets</h1>",
        f'<p class="meta">Generated { _esc(generated) }',
    ]
    if root_txt:
        parts.append(f" · scanned {_esc(root_txt)}")
    parts.append("</p>")

    parts.append('<div class="grid">')
    parts.append(
        f'<div class="stat"><div class="label">Files</div>'
        f'<div class="value">{stats.files_seen}</div></div>'
    )
    parts.append(
        f'<div class="stat"><div class="label">Lights</div>'
        f'<div class="value">{stats.lights}</div></div>'
    )
    parts.append(
        f'<div class="stat"><div class="label">With FOCUSPOS</div>'
        f'<div class="value">{stats.with_focus}</div></div>'
    )
    parts.append(
        f'<div class="stat"><div class="label">Missing FOCUSPOS</div>'
        f'<div class="value">{stats.skipped_no_focus}</div></div>'
    )
    parts.append("</div>")
    parts.append(
        f'<p class="meta">Gates: agree-tol=±{agree_tol:.0f} · '
        f"accept-error=±{accept_error:.0f} · af-step={af_step:.0f} · "
        f"outlier-σ={outlier_sigma:g}</p>"
    )
    if stats.unknown_filters:
        parts.append(
            f'<p class="meta">Unknown filters: '
            f'{_esc(", ".join(sorted(stats.unknown_filters)))}</p>'
        )

    # Top-of-report navigation to every Setup / Configuration section
    parts.append("<h2>Setups</h2>")
    parts.append('<div class="panel"><ul class="toc">')
    for index, (_samples, solve) in enumerate(setups, start=1):
        anchor = _setup_anchor(index)
        label = solve.setup.label()
        if solve.configuration:
            label = f"{label} · {solve.configuration}"
        status = "PUBLISH" if solve.publishable else "DO NOT PUBLISH"
        n_sessions = len({s.session_id for s in _samples})
        parts.append(
            f'<li><a href="#{anchor}">'
            f'<span class="toc-title">{_esc(label)}</span>'
            f'<span class="toc-meta">{_esc(status)} · {n_sessions} sessions</span>'
            f"</a></li>"
        )
    parts.append("</ul></div>")

    for index, (samples, solve) in enumerate(setups, start=1):
        parts.append(
            _render_setup(
                samples,
                solve,
                section_id=_setup_anchor(index),
                agree_tol=agree_tol,
                accept_error=accept_error,
                outlier_sigma=outlier_sigma,
            )
        )

    parts.extend(["</main>", "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def _setup_anchor(index: int) -> str:
    return f"setup-{index}"


def _short_session_label(session_id: str) -> str:
    dates = re.findall(r"20\d{6}", session_id)
    if dates:
        d = dates[-1]
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    # fall back to last path segment, truncated
    name = session_id.rstrip("/").split("/")[-1]
    return name if len(name) <= 22 else name[:19] + "…"


def _render_focuspos_chart(
    samples: list[FocusSample],
    *,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
) -> str:
    sessions, means, _notes = session_mean_positions(
        samples, outlier_sigma=outlier_sigma
    )
    if not sessions:
        return '<div class="panel muted">No Focus Samples to chart.</div>'

    filters_present = sorted(
        {f for fmap in means.values() for f in fmap},
        key=_filter_order_key,
    )
    if not filters_present:
        return '<div class="panel muted">No filter positions to chart.</div>'

    all_vals = [pos for fmap in means.values() for pos in fmap.values()]
    y_min = min(all_vals)
    y_max = max(all_vals)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    pad = max(5.0, (y_max - y_min) * 0.08)
    y_min -= pad
    y_max += pad

    n = len(sessions)
    # Layout
    left, right, top, bottom = 64, 24, 16, 72
    plot_w = max(520, 56 * max(n, 2))
    plot_h = 280
    width = left + plot_w + right
    height = top + plot_h + bottom

    def x_at(i: int) -> float:
        if n == 1:
            return left + plot_w / 2
        return left + (i / (n - 1)) * plot_w

    def y_at(v: float) -> float:
        return top + (1 - (v - y_min) / (y_max - y_min)) * plot_h

    # Y ticks
    span = y_max - y_min
    tick_step = span / 5
    for step_candidate in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if span / step_candidate <= 6:
            tick_step = float(step_candidate)
            break

    first_tick = (int(y_min // tick_step) + 1) * tick_step
    y_ticks = []
    t = first_tick
    while t <= y_max:
        y_ticks.append(t)
        t += tick_step

    svg: list[str] = [
        f'<div class="panel chart-wrap">',
        f'<svg class="chart-svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" aria-label="Focuser position over sessions">',
        # plot background
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" '
        f'fill="#12161e" stroke="var(--line)"/>',
    ]

    for tick in y_ticks:
        y = y_at(tick)
        svg.append(
            f'<line class="gridline" x1="{left}" x2="{left + plot_w}" y1="{y:.1f}" y2="{y:.1f}"/>'
        )
        label = f"{tick:.0f}"
        svg.append(
            f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{_esc(label)}</text>'
        )

    # axes
    svg.append(
        f'<line class="axis" x1="{left}" y1="{top + plot_h}" '
        f'x2="{left + plot_w}" y2="{top + plot_h}"/>'
    )
    svg.append(
        f'<text class="label" x="{left - 48}" y="{top + plot_h / 2}" '
        f'transform="rotate(-90 {left - 48} {top + plot_h / 2})" '
        f'text-anchor="middle">FOCUSPOS</text>'
    )

    # x labels
    for i, session_id in enumerate(sessions):
        x = x_at(i)
        label = _short_session_label(session_id)
        svg.append(
            f'<text class="tick" x="{x:.1f}" y="{top + plot_h + 18}" '
            f'text-anchor="end" transform="rotate(-35 {x:.1f} {top + plot_h + 18})">'
            f"{_esc(label)}</text>"
        )
        svg.append(
            f'<line class="gridline" x1="{x:.1f}" x2="{x:.1f}" '
            f'y1="{top}" y2="{top + plot_h}" opacity="0.35"/>'
        )

    # series — only connect consecutive session indices (no long diagonal spans)
    for fname in filters_present:
        color = FILTER_COLORS.get(fname, "#9aa3b2")
        pts: list[tuple[int, float, float, float, str]] = []
        for i, session_id in enumerate(sessions):
            if fname not in means[session_id]:
                continue
            pts.append(
                (i, x_at(i), y_at(means[session_id][fname]), means[session_id][fname], session_id)
            )
        segment: list[tuple[float, float]] = []
        prev_i: int | None = None
        for i, x, y, _val, _sid in pts:
            if prev_i is not None and i > prev_i + 1:
                if len(segment) >= 2:
                    path = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in segment)
                    svg.append(
                        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.25" '
                        f'stroke-linejoin="round" stroke-linecap="round"/>'
                    )
                segment = []
            segment.append((x, y))
            prev_i = i
        if len(segment) >= 2:
            path = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in segment)
            svg.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.25" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )
        for _i, x, y, val, session_id in pts:
            title = f"{fname} · {_short_session_label(session_id)} · {val:.1f}"
            svg.append(
                f'<circle class="point" cx="{x:.1f}" cy="{y:.1f}" r="4.2" fill="{color}">'
                f"<title>{_esc(title)}</title></circle>"
            )

    svg.append("</svg>")
    svg.append('<ul class="chart-legend">')
    for fname in filters_present:
        color = FILTER_COLORS.get(fname, "#9aa3b2")
        svg.append(
            f'<li><i style="background:{color}"></i>{_esc(fname)}</li>'
        )
    svg.append("</ul></div>")
    return "\n".join(svg)


def _render_setup(
    samples: list[FocusSample],
    solve: SetupSolve,
    *,
    section_id: str,
    agree_tol: float,
    accept_error: float,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
) -> str:
    parts: list[str] = [f'<section class="setup-block" id="{_esc(section_id)}">']
    title = _esc(solve.setup.label())
    if solve.configuration:
        title = f"{title} · {_esc(solve.configuration)}"
    parts.append(f"<h2>Setup · {title}</h2>")

    if solve.publishable:
        badge = '<span class="badge ok">PUBLISH</span>'
    else:
        badge = '<span class="badge bad">DO NOT PUBLISH</span>'
    rms = f"{solve.residual_rms:.2f}" if solve.residual_rms is not None else "n/a"
    parts.append(
        f'<div class="panel">{badge} '
        f'<span class="muted">gauge={_esc(solve.gauge)} · residual RMS={_esc(rms)}</span></div>'
    )
    if solve.outlier_notes:
        parts.append(
            f'<p class="muted">Outliers dropped (MAD >{outlier_sigma:g}σ): '
            f"{len(solve.outlier_notes)}</p>"
        )
        parts.append('<ul class="notes">')
        for note in solve.outlier_notes[:8]:
            parts.append(f"<li>{_esc(note)}</li>")
        if len(solve.outlier_notes) > 8:
            parts.append(f"<li>… {len(solve.outlier_notes) - 8} more</li>")
        parts.append("</ul>")
    if solve.publish_reasons:
        parts.append('<ul class="notes">')
        for reason in solve.publish_reasons:
            parts.append(f"<li>{_esc(reason)}</li>")
        parts.append("</ul>")

    parts.append("<h2>Focuser position over Sessions</h2>")
    parts.append(
        '<p class="muted">Mean FOCUSPOS per Session×Filter after '
        f">{outlier_sigma:g}σ MAD outlier rejection. "
        "Lines break when a filter skips Sessions.</p>"
    )
    parts.append(_render_focuspos_chart(samples, outlier_sigma=outlier_sigma))

    # Proposed ASIAIR table
    parts.append("<h2>Proposed ASIAIR offsets (vs L)</h2>")
    parts.append('<div class="panel"><table><thead><tr>')
    parts.append('<th>Filter</th><th class="num">Offset</th><th>Status</th></tr></thead><tbody>')
    for name in CANONICAL:
        if name in solve.offsets:
            value = solve.offsets[name]
            status = "within accept band" if abs(value) <= accept_error else "outside accept band"
            parts.append(
                f'<tr><td>{_esc(name)}</td><td class="num">{_esc(_fmt_signed(value, 0))}</td>'
                f"<td class=\"muted\">{_esc(status)}</td></tr>"
            )
        else:
            parts.append(
                f'<tr><td>{_esc(name)}</td><td class="num">—</td>'
                f'<td class="muted">not in L-bridged set</td></tr>'
            )
    parts.append("</tbody></table></div>")

    # Components
    parts.append("<h2>Filter graph components</h2>")
    parts.append('<div class="panel"><table><thead><tr>')
    parts.append(
        "<th>#</th><th>Bridge</th><th>Gauge</th><th>Filters</th>"
        '<th class="num">RMS</th><th>Offsets</th></tr></thead><tbody>'
    )
    for i, comp in enumerate(solve.components, start=1):
        bridged = "L-bridged" if "L" in comp.filters else "not bridged to L"
        rms = f"{comp.residual_rms:.2f}" if comp.residual_rms is not None else "n/a"
        off = ", ".join(
            f"{k}={_fmt_signed(v)}"
            for k, v in sorted(comp.offsets.items(), key=lambda kv: _filter_order_key(kv[0]))
        )
        filters_txt = ", ".join(sorted(comp.filters, key=_filter_order_key))
        parts.append(
            f"<tr><td>{i}</td><td>{_esc(bridged)}</td><td>{_esc(comp.gauge)}</td>"
            f"<td>{_esc(filters_txt)}</td>"
            f'<td class="num">{_esc(rms)}</td><td class="mono">{_esc(off)}</td></tr>'
        )
    parts.append("</tbody></table></div>")

    # Edges
    parts.append("<h2>Offset edges across Sessions</h2>")
    edges = build_edges(samples)
    agreements = summarize_edge_agreements(edges, agree_tol=agree_tol)
    parts.append('<div class="panel"><table><thead><tr>')
    parts.append(
        "<th>Edge</th><th class=\"num\">Median</th><th class=\"num\">Spread</th>"
        '<th class="num">n</th><th>Confidence</th><th>Values</th></tr></thead><tbody>'
    )
    if not agreements:
        parts.append('<tr><td colspan="6" class="muted">(none)</td></tr>')
    for ag in agreements:
        flag = (
            '<span class="badge conf">confident</span>'
            if ag.confident
            else '<span class="badge weak">weak</span>'
        )
        vals = ", ".join(_fmt_signed(v) for v in ag.values)
        parts.append(
            f"<tr><td>{_esc(ag.filter_a)}−{_esc(ag.filter_b)}</td>"
            f'<td class="num">{_esc(_fmt_signed(ag.median))}</td>'
            f'<td class="num">{ag.spread:.1f}</td>'
            f'<td class="num">{ag.n_sessions}</td><td>{flag}</td>'
            f'<td class="mono">{_esc(vals)}</td></tr>'
        )
    parts.append("</tbody></table></div>")

    # Per-session
    parts.append("<h2>Per-Session offsets</h2>")
    for session_id, gauge, positions, offsets in per_session_report(
        samples, outlier_sigma=outlier_sigma
    ):
        parts.append(f'<div class="session-title">{_esc(session_id)}</div>')
        parts.append('<div class="panel"><table><thead><tr>')
        parts.append(
            f"<th>Filter</th><th class=\"num\">FOCUSPOS</th>"
            f'<th class="num">vs {_esc(gauge)}</th><th>Kit</th></tr></thead><tbody>'
        )
        for name in sorted(positions.keys(), key=_filter_order_key):
            parts.append(
                f"<tr><td>{_esc(name)}</td>"
                f'<td class="num">{positions[name]:.0f}</td>'
                f'<td class="num">{_esc(_fmt_signed(offsets[name], 0))}</td>'
                f"<td class=\"muted\">{_esc(kit_for(name) or '?')}</td></tr>"
            )
        parts.append("</tbody></table></div>")

    # Focus samples
    parts.append("<h2>Focus Samples</h2>")
    parts.append(
        '<p class="muted">Unique FOCUSPOS per Session×Filter. '
        "Frame count is not confidence.</p>"
    )
    by_session: dict[str, list[FocusSample]] = {}
    for sample in samples:
        by_session.setdefault(sample.session_id, []).append(sample)
    for session_id in sorted(by_session):
        parts.append(f'<div class="session-title">{_esc(session_id)}</div>')
        parts.append('<div class="panel"><table><thead><tr>')
        parts.append(
            "<th>Filter</th><th class=\"num\">FOCUSPOS</th>"
            '<th class="num">Frames</th><th>Kit</th></tr></thead><tbody>'
        )
        for sample in sorted(
            by_session[session_id],
            key=lambda s: (_filter_order_key(s.filter_name), s.focuspos),
        ):
            parts.append(
                f"<tr><td>{_esc(sample.filter_name)}</td>"
                f'<td class="num">{sample.focuspos}</td>'
                f'<td class="num">{sample.frame_count}</td>'
                f"<td class=\"muted\">{_esc(kit_for(sample.filter_name) or '?')}</td></tr>"
            )
        parts.append("</tbody></table></div>")

    parts.append("</section>")
    return "\n".join(parts)


def write_html_report(path: Path, content: str) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
