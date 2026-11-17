"""CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .html_report import format_html_report, write_html_report
from .ingest import group_by_setup, ingest_lights
from .model import (
    DEFAULT_CONFIG_GAP,
    DEFAULT_OUTLIER_SIGMA,
    solve_setup_offsets,
    split_samples_by_configuration,
)
from .report import format_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filter-focus-offsets",
        description=(
            "Estimate filter focus offsets from ASIAIR Light FITS frames. "
            "Groups by Session (folder), builds Focus Samples without frame-count "
            "weighting, and optionally publishes a Setup Offset Set with L=0."
        ),
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="One or more directories (or files) to scan for FITS",
    )
    parser.add_argument(
        "--af-step",
        type=float,
        default=30.0,
        help="ASIAIR AF coarse step (default: 30)",
    )
    parser.add_argument(
        "--agree-tol",
        type=float,
        default=10.0,
        help="Max spread for cross-Session edge confidence (default: 10)",
    )
    parser.add_argument(
        "--accept-error",
        type=float,
        default=15.0,
        help="Max offset error / parfocal band (default: 15, ~½ AF step)",
    )
    parser.add_argument(
        "--outlier-sigma",
        type=float,
        default=DEFAULT_OUTLIER_SIGMA,
        help=(
            "Reject FOCUSPOS outside ±Nσ using MAD (median absolute deviation; "
            "robust to outlier masking). Applies within Session×Filter and across "
            f"Sessions inside a Configuration. Default: {DEFAULT_OUTLIER_SIGMA:g}. "
            "Use 0 to disable."
        ),
    )
    parser.add_argument(
        "--config-gap",
        type=float,
        default=DEFAULT_CONFIG_GAP,
        help=(
            "Absolute FOCUSPOS gap between Sessions that starts a new optical "
            f"Configuration (CAA/backfocus). Default: {DEFAULT_CONFIG_GAP:g}. "
            "Use 0 to keep one Configuration per Setup."
        ),
    )
    parser.add_argument(
        "--allow-no-l",
        action="store_true",
        help="Allow publishing a Setup Offset Set without L (gauge = first filter)",
    )
    parser.add_argument(
        "--html",
        type=Path,
        metavar="PATH",
        help="Write a self-contained HTML report to PATH",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Skip printing the text report (useful with --html)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    samples, stats = ingest_lights(args.roots)
    if not samples:
        print("No Focus Samples found (need Light + FILTER + FOCUSPOS).", file=sys.stderr)
        print(
            f"Saw {stats.files_seen} files, {stats.lights} Lights, "
            f"{stats.skipped_no_focus} missing FOCUSPOS.",
            file=sys.stderr,
        )
        return 1

    grouped = group_by_setup(samples)
    exit_code = 0
    setup_results: list = []

    for setup, setup_samples in sorted(grouped.items(), key=lambda kv: kv[0].label()):
        if args.config_gap > 0:
            configs = split_samples_by_configuration(
                setup_samples, min_gap=args.config_gap
            )
        else:
            configs = [("FOCUS~all", 0.0, setup_samples)]

        for config_label, config_focus, config_samples in configs:
            solve = solve_setup_offsets(
                config_samples,
                agree_tol=args.agree_tol,
                accept_error=args.accept_error,
                require_l=not args.allow_no_l,
                outlier_sigma=args.outlier_sigma,
                configuration=config_label,
                configuration_focus=config_focus,
            )
            setup_results.append((config_samples, solve))
            if not args.quiet:
                text = format_report(
                    config_samples,
                    stats,
                    solve,
                    agree_tol=args.agree_tol,
                    accept_error=args.accept_error,
                    af_step=args.af_step,
                    outlier_sigma=args.outlier_sigma,
                )
                print(text)
            if not solve.publishable:
                exit_code = 2

    if args.html:
        html = format_html_report(
            setup_results,
            stats,
            agree_tol=args.agree_tol,
            accept_error=args.accept_error,
            af_step=args.af_step,
            outlier_sigma=args.outlier_sigma,
            roots=list(args.roots),
        )
        out = write_html_report(args.html, html)
        print(f"HTML report: {out}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
