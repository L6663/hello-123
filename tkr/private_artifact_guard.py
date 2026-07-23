"""Fail-closed guard against committing private acceptance artifacts.

The real Stage 7/Stage 8 blind-evaluation inputs must stay outside the public
repository and outside GitHub Actions.  This module inspects tracked path names
and rejects known private-runtime directories, benchmark artifacts, and the
private literary corpus filenames used by the project.

It intentionally checks path identity rather than file contents.  Content
inspection would risk reading or echoing private material in CI logs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

SCHEMA_VERSION = "tkr-private-artifact-guard-v1"

FORBIDDEN_DIRECTORY_NAMES = frozenset(
    {
        ".tkr-private-acceptance",
        "private-acceptance",
        "private-acceptance-root",
        "private-corpus",
        "private-gold",
        "private-observations",
    }
)

FORBIDDEN_EXACT_BASENAMES = frozenset(
    {
        "private-blind-attestation.json",
        "literary-benchmark-cases.jsonl",
        "literary-benchmark-observations.jsonl",
        "literary-benchmark-report.json",
        "literary-benchmark-verification.json",
    }
)

PRIVATE_CORPUS_PREFIXES = ("步剑庭",)
PRIVATE_CORPUS_SUFFIXES = (".txt", ".zip")


def _normalise(path: str | Path) -> PurePosixPath:
    text = str(path).replace("\\", "/").lstrip("./")
    return PurePosixPath(text)


def classify_path(path: str | Path) -> list[str]:
    """Return deterministic reason codes for a forbidden tracked path."""

    normalised = _normalise(path)
    reasons: list[str] = []

    if any(part in FORBIDDEN_DIRECTORY_NAMES for part in normalised.parts):
        reasons.append("PRIVATE_RUNTIME_DIRECTORY_TRACKED")

    if normalised.name in FORBIDDEN_EXACT_BASENAMES:
        reasons.append("PRIVATE_BENCHMARK_ARTIFACT_TRACKED")

    if normalised.name.startswith(PRIVATE_CORPUS_PREFIXES) and normalised.name.endswith(
        PRIVATE_CORPUS_SUFFIXES
    ):
        reasons.append("PRIVATE_CORPUS_FILE_TRACKED")

    return reasons


def scan_paths(paths: Iterable[str | Path]) -> dict[str, object]:
    """Scan path names without opening files or exposing file contents."""

    findings: list[dict[str, object]] = []
    normalised_paths = sorted({_normalise(path).as_posix() for path in paths})

    for path in normalised_paths:
        reasons = classify_path(path)
        if reasons:
            findings.append({"path": path, "reason_codes": reasons})

    return {
        "schema_version": SCHEMA_VERSION,
        "passed": not findings,
        "tracked_path_count": len(normalised_paths),
        "finding_count": len(findings),
        "findings": findings,
        "content_scanned": False,
        "private_data_echoed": False,
        "project_acceptance_performed": False,
        "release_candidate": False,
        "may_release": False,
        "may_freeze": False,
    }


def git_tracked_paths(root: Path) -> list[str]:
    """Return tracked repository paths using a NUL-delimited Git query."""

    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [
        item.decode("utf-8", errors="strict")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reject tracked private acceptance artifacts without reading contents."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    report = scan_paths(git_tracked_paths(root))
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.output:
        output = args.output
        if not output.is_absolute():
            output = root / output
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
