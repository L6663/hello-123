"""CLI for Phase 9.4 review candidates and deterministic artifact publication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .anomaly_artifacts import publish_anomaly_artifacts
from .anomaly_detection import (
    AnomalyInspectionError,
    AnomalyPolicy,
    MarkerGroup,
    inspect_source_anomalies,
)


def _marker_group(value: str) -> MarkerGroup:
    name, separator, payload = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(
            "marker groups must use NAME=MARKER1|MARKER2 syntax"
        )
    markers = tuple(marker for marker in payload.split("|") if marker)
    try:
        return MarkerGroup(name=name, markers=markers)
    except AnomalyInspectionError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tkr-anomaly-scan",
        description=(
            "Emit source-bound anomaly and contamination review candidates; "
            "this command does not perform project acceptance."
        ),
    )
    parser.add_argument("source", type=Path)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--output", type=Path, help="write one complete JSON report")
    output.add_argument("--outdir", type=Path, help="write the standard artifact set")
    parser.add_argument(
        "--marker-group",
        action="append",
        default=[],
        type=_marker_group,
        metavar="NAME=MARKER1|MARKER2",
    )
    parser.add_argument("--max-findings", type=int, default=10_000)
    parser.add_argument("--max-line-characters", type=int, default=20_000)
    parser.add_argument("--duplicate-min-characters", type=int, default=80)
    parser.add_argument("--duplicate-min-line-distance", type=int, default=20)
    parser.add_argument("--window-characters", type=int, default=800)
    parser.add_argument("--window-stride", type=int, default=800)
    parser.add_argument("--window-min-characters", type=int, default=240)
    parser.add_argument("--same-language-min-signals", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policy = AnomalyPolicy(
            max_findings=args.max_findings,
            max_line_characters=args.max_line_characters,
            duplicate_min_characters=args.duplicate_min_characters,
            duplicate_min_line_distance=args.duplicate_min_line_distance,
            window_characters=args.window_characters,
            window_stride=args.window_stride,
            window_min_characters=args.window_min_characters,
            same_language_min_signals=args.same_language_min_signals,
        )
        report = inspect_source_anomalies(
            args.source,
            policy=policy,
            marker_groups=args.marker_group,
        )
        if args.outdir is not None:
            manifest = publish_anomaly_artifacts(report, args.outdir)
            print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            return 0
        payload = json.dumps(
            report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        if args.output is None:
            print(payload, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_name(f".{args.output.name}.tmp")
            temporary.write_text(payload, encoding="utf-8", newline="\n")
            temporary.replace(args.output)
    except (OSError, TypeError, ValueError) as exc:
        raise SystemExit(f"anomaly scan failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
