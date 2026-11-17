"""Text report for CLI."""

from __future__ import annotations

from .filters import CANONICAL, kit_for
from .ingest import FocusSample, IngestStats
from .model import (
    SetupSolve,
    build_edges,
    per_session_report,
    summarize_edge_agreements,
)


def _filter_order_key(name: str) -> tuple[int, str]:
    if name in CANONICAL:
        return (CANONICAL.index(name), name)
    return (100, name)


def format_report(
    samples: list[FocusSample],
    stats: IngestStats,
    solve: SetupSolve,
    *,
    agree_tol: float,
    accept_error: float,
    af_step: float,
    outlier_sigma: float = 3.0,
) -> str:
    lines: list[str] = []
    lines.append("=== Filter Focus Offsets ===")
    lines.append(
        f"Ingest: {stats.files_seen} files | {stats.lights} Lights | "
        f"{stats.with_focus} with FOCUSPOS | "
        f"{stats.skipped_no_focus} missing FOCUSPOS | "
        f"{stats.skipped_not_light} non-Light | "
        f"{stats.skipped_read_error} read errors"
    )
    if stats.unknown_filters:
        lines.append(f"Unknown filters kept as-is: {', '.join(sorted(stats.unknown_filters))}")
    lines.append(f"Setup: {solve.setup.label()}")
    if solve.configuration:
        focus_txt = (
            f"{solve.configuration_focus:.0f}"
            if solve.configuration_focus is not None
            else "?"
        )
        lines.append(f"Configuration: {solve.configuration} (abs focus ~{focus_txt})")
    lines.append(
        f"Gates: agree-tol=±{agree_tol:.0f} | accept-error=±{accept_error:.0f} | "
        f"af-step={af_step:.0f} | outlier-σ={outlier_sigma:g}"
    )
    if solve.outlier_notes:
        lines.append(f"Outliers dropped: {len(solve.outlier_notes)}")
        for note in solve.outlier_notes[:12]:
            lines.append(f"  - {note}")
        if len(solve.outlier_notes) > 12:
            lines.append(f"  - … {len(solve.outlier_notes) - 12} more")
    lines.append("")

    # Focus samples summary
    lines.append("--- Focus Samples (unique FOCUSPOS; frame count is not confidence) ---")
    by_session: dict[str, list[FocusSample]] = {}
    for sample in samples:
        by_session.setdefault(sample.session_id, []).append(sample)
    for session_id in sorted(by_session):
        lines.append(f"Session: {session_id}")
        for sample in sorted(
            by_session[session_id],
            key=lambda s: (_filter_order_key(s.filter_name), s.focuspos),
        ):
            kit = kit_for(sample.filter_name) or "?"
            lines.append(
                f"  {sample.filter_name:4}  FOCUSPOS={sample.focuspos:5d}  "
                f"frames={sample.frame_count:3d}  kit={kit}"
            )
    lines.append("")

    # Per-session offsets
    lines.append("--- Per-Session offsets (primary) ---")
    for session_id, gauge, positions, offsets in per_session_report(
        samples, outlier_sigma=outlier_sigma
    ):
        pos_txt = ", ".join(
            f"{k}={v:.0f}" for k, v in sorted(positions.items(), key=lambda kv: _filter_order_key(kv[0]))
        )
        off_txt = ", ".join(
            f"{k}={v:+.0f}" for k, v in sorted(offsets.items(), key=lambda kv: _filter_order_key(kv[0]))
        )
        lines.append(f"Session: {session_id}")
        lines.append(f"  positions: {pos_txt}")
        lines.append(f"  vs {gauge}: {off_txt}")
    lines.append("")

    # Edges + confidence
    lines.append("--- Offset Edges across Sessions ---")
    edges = build_edges(samples)
    agreements = summarize_edge_agreements(edges, agree_tol=agree_tol)
    if not agreements:
        lines.append("  (none)")
    for ag in agreements:
        flag = "CONFIDENT" if ag.confident else "weak"
        vals = ", ".join(f"{v:+.1f}" for v in ag.values)
        lines.append(
            f"  {ag.filter_a}-{ag.filter_b}: median={ag.median:+.1f}  "
            f"spread={ag.spread:.1f}  n={ag.n_sessions}  [{flag}]  values=[{vals}]"
        )
    lines.append("")

    # Connected components (bridges)
    lines.append("--- Filter graph components ---")
    for i, comp in enumerate(solve.components, start=1):
        bridged = "L-bridged" if "L" in comp.filters else "not bridged to L"
        rms = f"{comp.residual_rms:.2f}" if comp.residual_rms is not None else "n/a"
        off = ", ".join(
            f"{k}={v:+.1f}"
            for k, v in sorted(comp.offsets.items(), key=lambda kv: _filter_order_key(kv[0]))
        )
        lines.append(
            f"  #{i} [{bridged}] gauge={comp.gauge}  rms={rms}  "
            f"filters={','.join(sorted(comp.filters, key=_filter_order_key))}"
        )
        lines.append(f"      offsets vs {comp.gauge}: {off}")
    lines.append("")

    # Setup offset set (L-relative only for L-bridged filters)
    lines.append("--- Setup Offset Set (L=0; L-bridged filters only) ---")
    lines.append(f"Gauge: {solve.gauge}")
    if solve.residual_rms is not None:
        lines.append(f"Fit residual RMS: {solve.residual_rms:.2f} steps")
    if solve.offsets:
        for name in CANONICAL:
            if name not in solve.offsets:
                continue
            value = solve.offsets[name]
            marker = ""
            if abs(value) <= accept_error:
                marker = "  (~parfocal / within accept band)"
            lines.append(f"  {name:4}  {value:+7.1f}{marker}")
        extras = [n for n in solve.offsets if n not in CANONICAL]
        for name in sorted(extras):
            lines.append(f"  {name:4}  {solve.offsets[name]:+7.1f}")
    else:
        lines.append("  (empty)")
    if solve.publishable:
        lines.append("PUBLISH: yes — confidence/residual gates passed")
    else:
        lines.append("PUBLISH: no — do not enter as a single ASIAIR offset table yet")
    if solve.publish_reasons:
        lines.append("Notes:")
        for reason in solve.publish_reasons:
            lines.append(f"  - {reason}")
    lines.append("")

    lines.append("--- Proposed ASIAIR filter offsets (steps vs L) ---")
    for name in CANONICAL:
        if name in solve.offsets:
            lines.append(f"  {name:4}  {solve.offsets[name]:+.0f}")
        else:
            lines.append(f"  {name:4}  —")
    return "\n".join(lines) + "\n"
