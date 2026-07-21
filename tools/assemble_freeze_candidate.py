from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from tkr.release_freeze import prepare_freeze_candidate, verify_freeze_candidate


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON object required: {path}")
    return payload


def python_minor(value: object) -> str:
    match = re.match(r"^(\d+\.\d+)", str(value))
    if not match:
        raise SystemExit(f"cannot parse Python version: {value!r}")
    return match.group(1)


def ensure_disjoint_output(
    matrix_root: Path,
    output_root: Path,
    reproducible_wheels: list[Path],
) -> None:
    """Reject output paths that could delete or overwrite release evidence."""

    matrix = matrix_root.resolve()
    output = output_root.resolve()
    if output == matrix or output in matrix.parents or matrix in output.parents:
        raise SystemExit(
            "output root must be a dedicated directory disjoint from matrix input"
        )
    for wheel in reproducible_wheels:
        resolved = wheel.resolve()
        if output == resolved or output in resolved.parents:
            raise SystemExit("output root must not contain a reproducible wheel input")


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble a Phase 8 technical freeze candidate.")
    parser.add_argument("--matrix-root", type=Path, required=True)
    parser.add_argument("--reproducible-wheel", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    args = parser.parse_args()

    if len(args.reproducible_wheel) < 2:
        raise SystemExit("at least two reproducible wheels are required")
    matrix_root = args.matrix_root.resolve()
    reproducible_wheels = [item.resolve() for item in args.reproducible_wheel]
    output = args.output_root.resolve()
    ensure_disjoint_output(matrix_root, output, reproducible_wheels)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    reports: dict[str, Path] = {}
    accepted_wheel_hashes: set[str] = set()
    accepted_wheel_names: set[str] = set()
    for path in matrix_root.rglob("package-acceptance.json"):
        payload = load(path)
        if payload.get("accepted") is not True:
            raise SystemExit(f"package acceptance is not accepted: {path}")
        minor = python_minor(payload.get("python"))
        if minor in reports:
            raise SystemExit(f"duplicate package acceptance for Python {minor}")
        reports[minor] = path
        accepted_wheel_hashes.add(str(payload.get("wheel_sha256")))
        accepted_wheel_names.add(str(payload.get("wheel_name")))
    required = {"3.10", "3.11", "3.12"}
    if set(reports) != required:
        raise SystemExit(f"package acceptance matrix mismatch: {sorted(reports)}")
    if len(accepted_wheel_hashes) != 1 or len(accepted_wheel_names) != 1:
        raise SystemExit("package acceptance reports disagree on wheel identity")
    expected_wheel_sha = next(iter(accepted_wheel_hashes))
    wheel_name = next(iter(accepted_wheel_names))

    source_wheels = list(matrix_root.rglob(wheel_name))
    if not source_wheels:
        raise SystemExit(f"accepted wheel not found: {wheel_name}")
    if any(digest(path) != expected_wheel_sha for path in source_wheels):
        raise SystemExit("a matrix wheel does not match its package acceptance SHA-256")
    wheel = output / wheel_name
    shutil.copy2(source_wheels[0], wheel)

    benchmark_roots = list(matrix_root.rglob("benchmark/release-manifest.json"))
    if not benchmark_roots:
        raise SystemExit("release benchmark evidence not found")
    benchmark = benchmark_roots[0].parent
    copied: dict[str, Path] = {}
    for name in ("release-manifest.json", "release-report.json", "release-verification.json"):
        target = output / name
        shutil.copy2(benchmark / name, target)
        copied[name] = target

    package_targets: list[Path] = []
    for minor in sorted(reports):
        target = output / f"package-acceptance-python-{minor}.json"
        shutil.copy2(reports[minor], target)
        package_targets.append(target)

    build_hashes = [digest(item) for item in reproducible_wheels]
    reproducible = {
        "schema_version": "tkr-reproducible-build-v1",
        "accepted": len(set(build_hashes)) == 1 and build_hashes[0] == expected_wheel_sha,
        "build_count": len(build_hashes),
        "wheel_sha256": expected_wheel_sha,
        "build_sha256": build_hashes,
    }
    if reproducible["accepted"] is not True:
        raise SystemExit(f"reproducible wheel mismatch: {build_hashes} != {expected_wheel_sha}")
    reproducible_path = output / "reproducible-build-report.json"
    reproducible_path.write_text(
        json.dumps(reproducible, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    specs: list[tuple[str, Path]] = [
        ("wheel", wheel),
        ("release_manifest", copied["release-manifest.json"]),
        ("release_report", copied["release-report.json"]),
        ("release_verification", copied["release-verification.json"]),
        ("reproducible_build_report", reproducible_path),
    ]
    specs.extend(("package_acceptance", path) for path in package_targets)
    candidate_path = output / "freeze-candidate.json"
    candidate = prepare_freeze_candidate(
        output,
        specs,
        release_version=args.release_version,
        source_commit=args.source_commit,
        source_date_epoch=args.source_date_epoch,
        output_path=candidate_path,
    )
    verification = verify_freeze_candidate(candidate_path, root=output)
    (output / "freeze-candidate-verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if candidate.get("may_freeze") is not False or verification.get("may_freeze") is not False:
        raise SystemExit("technical candidate must not self-grant freeze authority")
    print(json.dumps({"candidate": candidate, "verification": verification}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
