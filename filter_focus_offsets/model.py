"""Session edges, confidence, and Setup Offset Set solve."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from itertools import combinations
from statistics import mean, median
from typing import Iterable

import numpy as np

from .filters import CANONICAL, LRGB_KIT, NB_KIT
from .ingest import FocusSample, SetupKey

DEFAULT_OUTLIER_SIGMA = 3.0
DEFAULT_CONFIG_GAP = 2500.0  # absolute FOCUSPOS gap → new optical Configuration


@dataclass(frozen=True)
class OffsetEdge:
    session_id: str
    filter_a: str
    filter_b: str
    delta: float  # pos(a) - pos(b)
    pos_a: float
    pos_b: float


@dataclass
class EdgeAgreement:
    filter_a: str
    filter_b: str
    values: list[float]
    median: float
    spread: float
    n_sessions: int
    confident: bool


@dataclass
class ComponentSolve:
    filters: list[str]
    gauge: str
    offsets: dict[str, float]
    residual_rms: float | None


@dataclass
class SetupSolve:
    setup: SetupKey
    offsets: dict[str, float]
    gauge: str
    per_session_zero: dict[str, float]
    residual_rms: float | None
    publishable: bool
    publish_reasons: list[str] = field(default_factory=list)
    edge_agreements: list[EdgeAgreement] = field(default_factory=list)
    components: list[ComponentSolve] = field(default_factory=list)
    bridged_to_l: set[str] = field(default_factory=set)
    outlier_notes: list[str] = field(default_factory=list)
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA
    configuration: str = ""
    configuration_focus: float | None = None


# Consistent with a normal distribution: σ ≈ 1.4826 × MAD
_MAD_TO_SIGMA = 1.4826


def robust_clip(values: list[float], sigma: float) -> tuple[list[float], list[float]]:
    """
    Keep values within median ± sigma × (1.4826×MAD).

    MAD resists outlier-inflated σ (classic 3σ masking). Needs ≥3 points.
    If MAD is 0 (majority identical), drop points that differ from the median.
    """
    if sigma <= 0 or len(values) < 3:
        return list(values), []

    med = median(values)
    abs_dev = [abs(v - med) for v in values]
    mad = median(abs_dev)

    kept: list[float] = []
    rejected: list[float] = []
    if mad == 0:
        for value in values:
            if value == med:
                kept.append(value)
            else:
                rejected.append(value)
    else:
        limit = sigma * _MAD_TO_SIGMA * mad
        for value in values:
            if abs(value - med) <= limit:
                kept.append(value)
            else:
                rejected.append(value)

    if not kept:
        return list(values), []
    return kept, rejected


def session_filter_positions(
    samples: Iterable[FocusSample],
    *,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """
    session -> filter -> mean FOCUSPOS after robust outlier rejection.

    1) Within Session×Filter: MAD-clip distinct FOCUSPOS (n≥3)
    2) Across Sessions per filter: MAD-clip session means (n≥3)
    """
    by_session: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for sample in samples:
        by_session[sample.session_id][sample.filter_name].append(float(sample.focuspos))

    notes: list[str] = []
    within: dict[str, dict[str, float]] = {}
    for session_id, filters in by_session.items():
        within[session_id] = {}
        for name, positions in filters.items():
            kept, rejected = robust_clip(positions, outlier_sigma)
            if rejected:
                notes.append(
                    f"{session_id} / {name}: dropped within-session "
                    f"{', '.join(f'{v:.0f}' for v in rejected)} "
                    f"(>{outlier_sigma:g}σ MAD)"
                )
            within[session_id][name] = float(mean(kept))

    # Across-session clip per filter
    per_filter: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for session_id, fmap in within.items():
        for name, pos in fmap.items():
            per_filter[name].append((session_id, pos))

    out: dict[str, dict[str, float]] = defaultdict(dict)
    for name, pairs in per_filter.items():
        values = [pos for _, pos in pairs]
        _kept, rejected_vals = robust_clip(values, outlier_sigma)
        if not rejected_vals:
            for session_id, pos in pairs:
                out[session_id][name] = pos
            continue

        med = median(values)
        mad = median([abs(v - med) for v in values])
        for session_id, pos in pairs:
            if mad == 0:
                drop = pos != med
            else:
                drop = abs(pos - med) > outlier_sigma * _MAD_TO_SIGMA * mad
            if drop:
                notes.append(
                    f"{session_id} / {name}: dropped session mean "
                    f"{pos:.0f} (>{outlier_sigma:g}σ MAD across Sessions)"
                )
            else:
                out[session_id][name] = pos

    # Drop empty sessions
    out = {sid: fmap for sid, fmap in out.items() if fmap}
    return dict(out), notes


def session_abs_focus(positions: dict[str, dict[str, float]]) -> dict[str, float]:
    """Representative absolute FOCUSPOS per Session (mean across filters)."""
    return {
        session_id: float(mean(fmap.values()))
        for session_id, fmap in positions.items()
        if fmap
    }


def split_samples_by_configuration(
    samples: list[FocusSample],
    *,
    min_gap: float = DEFAULT_CONFIG_GAP,
) -> list[tuple[str, float, list[FocusSample]]]:
    """
    Split one Setup's samples into optical Configurations.

    A large gap in absolute FOCUSPOS across Sessions (e.g. CAA / backfocus change)
    starts a new Configuration. Returns (label, center_focus, samples).
    """
    if not samples:
        return []

    # No across-session clip here — regimes must remain visible for splitting
    raw_positions, _ = session_filter_positions(samples, outlier_sigma=0.0)
    abs_focus = session_abs_focus(raw_positions)
    if not abs_focus:
        return [("FOCUS~?", 0.0, samples)]

    ordered = sorted(abs_focus.items(), key=lambda kv: kv[1])
    clusters: list[list[tuple[str, float]]] = [[ordered[0]]]
    for session_id, value in ordered[1:]:
        prev = clusters[-1][-1][1]
        if value - prev >= min_gap:
            clusters.append([(session_id, value)])
        else:
            clusters[-1].append((session_id, value))

    results: list[tuple[str, float, list[FocusSample]]] = []
    for cluster in clusters:
        session_ids = {sid for sid, _ in cluster}
        center = float(mean(v for _, v in cluster))
        label = f"FOCUS~{center:.0f}"
        subset = [s for s in samples if s.session_id in session_ids]
        if subset:
            results.append((label, center, subset))
    results.sort(key=lambda row: row[1])
    return results


def build_edges(
    samples: list[FocusSample],
    *,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
) -> list[OffsetEdge]:
    positions, _ = session_filter_positions(samples, outlier_sigma=outlier_sigma)
    edges: list[OffsetEdge] = []
    for session_id, filters in positions.items():
        names = sorted(filters.keys(), key=_filter_sort_key)
        for a, b in combinations(names, 2):
            pos_a = filters[a]
            pos_b = filters[b]
            edges.append(
                OffsetEdge(
                    session_id=session_id,
                    filter_a=a,
                    filter_b=b,
                    delta=pos_a - pos_b,
                    pos_a=pos_a,
                    pos_b=pos_b,
                )
            )
    return edges


def summarize_edge_agreements(
    edges: list[OffsetEdge],
    agree_tol: float,
) -> list[EdgeAgreement]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for edge in edges:
        pair = tuple(sorted([edge.filter_a, edge.filter_b], key=_filter_sort_key))
        if (edge.filter_a, edge.filter_b) == pair:
            grouped[pair].append(edge.delta)
        else:
            grouped[pair].append(-edge.delta)

    agreements: list[EdgeAgreement] = []
    for (a, b), values in sorted(
        grouped.items(),
        key=lambda kv: (_filter_sort_key(kv[0][0]), _filter_sort_key(kv[0][1])),
    ):
        med = float(median(values))
        spread = float(max(values) - min(values)) if len(values) > 1 else 0.0
        confident = len(values) >= 2 and spread <= agree_tol
        agreements.append(
            EdgeAgreement(
                filter_a=a,
                filter_b=b,
                values=list(values),
                median=med,
                spread=spread,
                n_sessions=len(values),
                confident=confident,
            )
        )
    return agreements


def _filter_sort_key(name: str) -> tuple[int, str]:
    if name in CANONICAL:
        return (CANONICAL.index(name), name)
    return (100, name)


def _pick_gauge(filters: list[str], prefer: str = "L") -> str:
    if prefer in filters:
        return prefer
    # RGB-only: prefer B as a stable ladder anchor when no L
    for candidate in ("B", "G", "R", "OIII", "Ha", "SII"):
        if candidate in filters:
            return candidate
    return sorted(filters, key=_filter_sort_key)[0]


def filter_components(positions: dict[str, dict[str, float]]) -> list[list[str]]:
    """Connected components: filters linked by co-occurrence in any Session."""
    graph: dict[str, set[str]] = defaultdict(set)
    all_filters: set[str] = set()
    for fmap in positions.values():
        names = list(fmap.keys())
        all_filters.update(names)
        for a, b in combinations(names, 2):
            graph[a].add(b)
            graph[b].add(a)
        for name in names:
            graph.setdefault(name, set())

    seen: set[str] = set()
    components: list[list[str]] = []
    for start in sorted(all_filters, key=_filter_sort_key):
        if start in seen:
            continue
        queue = deque([start])
        comp: list[str] = []
        seen.add(start)
        while queue:
            node = queue.popleft()
            comp.append(node)
            for nbr in sorted(graph[node], key=_filter_sort_key):
                if nbr not in seen:
                    seen.add(nbr)
                    queue.append(nbr)
        components.append(sorted(comp, key=_filter_sort_key))
    return components


def _solve_component(
    positions: dict[str, dict[str, float]],
    filters: list[str],
    gauge: str,
) -> tuple[dict[str, float], dict[str, float], float | None]:
    """Least squares: pos[s,f] ≈ zero[s] + offset[f], offset[gauge]=0."""
    filter_set = set(filters)
    sessions = sorted(
        sid for sid, fmap in positions.items() if set(fmap) & filter_set
    )
    session_index = {s: i for i, s in enumerate(sessions)}
    free_filters = [f for f in filters if f != gauge]
    free_index = {f: i for i, f in enumerate(free_filters)}
    n_s = len(sessions)
    n_off = len(free_filters)

    rows = []
    obs = []
    for session_id in sessions:
        fmap = positions[session_id]
        for fname, pos in fmap.items():
            if fname not in filter_set:
                continue
            row = np.zeros(n_s + n_off)
            row[session_index[session_id]] = 1.0
            if fname != gauge:
                row[n_s + free_index[fname]] = 1.0
            rows.append(row)
            obs.append(pos)

    offsets = {f: 0.0 for f in filters}
    zeros: dict[str, float] = {}
    residual_rms: float | None = None
    if not rows:
        return offsets, zeros, residual_rms

    a = np.vstack(rows)
    b = np.asarray(obs, dtype=float)
    sol, _, _, _ = np.linalg.lstsq(a, b, rcond=None)
    for session_id, i in session_index.items():
        zeros[session_id] = float(sol[i])
    offsets[gauge] = 0.0
    for fname, i in free_index.items():
        offsets[fname] = float(sol[n_s + i])
    fitted = a @ sol
    residual_rms = float(np.sqrt(np.mean((fitted - b) ** 2)))
    return offsets, zeros, residual_rms


def solve_setup_offsets(
    samples: list[FocusSample],
    *,
    agree_tol: float,
    accept_error: float,
    require_l: bool = True,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
    configuration: str = "",
    configuration_focus: float | None = None,
) -> SetupSolve:
    if not samples:
        setup = SetupKey("?", "?", 0)
        return SetupSolve(
            setup=setup,
            offsets={},
            gauge="L",
            per_session_zero={},
            residual_rms=None,
            publishable=False,
            publish_reasons=["no Focus Samples"],
            outlier_sigma=outlier_sigma,
            configuration=configuration,
            configuration_focus=configuration_focus,
        )

    setup = samples[0].setup
    edges = build_edges(samples, outlier_sigma=outlier_sigma)
    agreements = summarize_edge_agreements(edges, agree_tol=agree_tol)
    positions, outlier_notes = session_filter_positions(
        samples, outlier_sigma=outlier_sigma
    )
    components = filter_components(positions)

    reasons: list[str] = []
    component_solves: list[ComponentSolve] = []
    all_offsets: dict[str, float] = {}
    all_zeros: dict[str, float] = {}
    residual_parts: list[float] = []
    bridged_to_l: set[str] = set()

    l_component = next((c for c in components if "L" in c), None)
    if l_component:
        bridged_to_l.update(l_component)

    for comp in components:
        gauge = _pick_gauge(comp, prefer="L")
        offsets, zeros, rms = _solve_component(positions, comp, gauge)
        component_solves.append(
            ComponentSolve(filters=comp, gauge=gauge, offsets=offsets, residual_rms=rms)
        )
        # Only merge into L-gauge published vector filters that share L's component
        if l_component is not None and set(comp) <= set(l_component):
            all_offsets.update(offsets)
            all_zeros.update(zeros)
            if rms is not None:
                residual_parts.append(rms)
        elif l_component is None:
            all_offsets.update(offsets)
            all_zeros.update(zeros)
            if rms is not None:
                residual_parts.append(rms)

    # Annotate disconnected kits
    for comp in components:
        if l_component and "L" not in comp:
            reasons.append(
                f"filters {','.join(comp)} not bridged to L "
                f"(no same-Session co-occurrence) — omitted from L-relative Set"
            )

    gauge = "L" if l_component else (
        component_solves[0].gauge if component_solves else "L"
    )
    residual_rms = float(np.mean(residual_parts)) if residual_parts else None

    publishable = True
    if require_l and not l_component:
        publishable = False
        reasons.append("no L in graph — refuse L-gauge Setup Offset Set")

    if residual_rms is not None and residual_rms > accept_error:
        publishable = False
        reasons.append(
            f"residual RMS {residual_rms:.1f} > accept-error {accept_error:.0f}"
        )

    for fname, value in all_offsets.items():
        if fname == gauge:
            continue
        if abs(value) <= accept_error:
            continue
        related = [
            ag
            for ag in agreements
            if fname in (ag.filter_a, ag.filter_b) and ag.confident
        ]
        if not related:
            publishable = False
            reasons.append(
                f"{fname} offset {value:+.1f} exceeds ±{accept_error:.0f} "
                "without cross-Session confidence"
            )

    for kit_name, kit in (("LRGB", LRGB_KIT), ("NB", NB_KIT)):
        present = [f for f in all_offsets if f in kit]
        if len(present) < 2:
            continue
        vals = [all_offsets[f] for f in present]
        span = max(vals) - min(vals)
        if span > accept_error:
            publishable = False
            reasons.append(
                f"{kit_name} kit span {span:.1f} steps "
                f"(parfocal prior expects ≤ {accept_error:.0f})"
            )
        # Also check NB components not in all_offsets
    for comp in component_solves:
        if "L" in comp.filters:
            continue
        kit_filters = [f for f in comp.filters if f in NB_KIT]
        if len(kit_filters) < 2:
            continue
        vals = [comp.offsets[f] for f in kit_filters]
        span = max(vals) - min(vals)
        if span > accept_error:
            reasons.append(
                f"NB component span {span:.1f} vs {comp.gauge} "
                f"(informational; not in L-relative Set)"
            )

    # Show NB component offsets in report via components; keep all_offsets L-bridged only
    if require_l and l_component is None:
        publishable = False

    # If we have L but LRGB offsets disagree strongly across sessions, still may publish
    # with reasons — residual gate handles fit quality.

    if not all_offsets and l_component is None:
        publishable = False

    return SetupSolve(
        setup=setup,
        offsets=all_offsets,
        gauge=gauge,
        per_session_zero=all_zeros,
        residual_rms=residual_rms,
        publishable=publishable,
        publish_reasons=reasons,
        edge_agreements=agreements,
        components=component_solves,
        bridged_to_l=bridged_to_l,
        outlier_notes=outlier_notes,
        outlier_sigma=outlier_sigma,
        configuration=configuration,
        configuration_focus=configuration_focus,
    )


def per_session_report(
    samples: list[FocusSample],
    gauge_preference: str = "L",
    *,
    outlier_sigma: float = DEFAULT_OUTLIER_SIGMA,
) -> list[tuple[str, str, dict[str, float], dict[str, float]]]:
    """Return list of (session_id, gauge, positions, offsets_vs_gauge)."""
    positions, _ = session_filter_positions(samples, outlier_sigma=outlier_sigma)
    rows = []
    for session_id, fmap in sorted(positions.items()):
        gauge = _pick_gauge(list(fmap.keys()), prefer=gauge_preference)
        gpos = fmap[gauge]
        offsets = {name: pos - gpos for name, pos in fmap.items()}
        rows.append((session_id, gauge, dict(fmap), offsets))
    return rows
