from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys

# The candidate verifier must come from the reviewed checkout, not the wheel.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_TEXT = str(REPOSITORY_ROOT)
if not sys.path or sys.path[0] != REPOSITORY_TEXT:
    sys.path.insert(0, REPOSITORY_TEXT)

import tkr.release_freeze as release_freeze_module  # noqa: E402
import tkr.source_provenance as source_provenance_module  # noqa: E402
from tkr.release_freeze import prepare_freeze_candidate, verify_freeze_candidate  # noqa: E402
from tkr.source_provenance import build_source_provenance  # noqa: E402


RELEASE_FILE_ROLES = {
    "normalized-text.txt": "release_source",
    "unit-index.csv": "release_units",
    "claims.accepted.jsonl": "release_claims",
    "knowledge.sqlite3": "release_database",
    "knowledge.report.json": "release_index_report",
    "gold-release.jsonl": "release_gold",
    "release-report.json": "release_report",
    "release-verification.json": "release_verification",
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON object: {path}: {exc}") from exc
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
            raise SystemExit(
                "output root must not contain a reproducible wheel input"
            )


def _copy_verified_release_files(
    benchmark_root: Path,
    output: Path,
) -> tuple[Path, dict[str, Path]]:
    manifest_source = benchmark_root / "release-manifest.json"
    manifest = load(manifest_source)
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, dict):
        raise SystemExit("release manifest files must be an object")
    if set(manifest_files) != set(RELEASE_FILE_ROLES):
        raise SystemExit(
            "release manifest file set does not match the freeze contract"
        )

    copied: dict[str, Path] = {}
    for name in RELEASE_FILE_ROLES:
        source = benchmark_root / name
        if not source.is_file():
            raise SystemExit(f"release benchmark file is missing: {source}")
        expected = manifest_files[name]
        if not isinstance(expected, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected
        ):
            raise SystemExit(f"invalid release manifest hash for {name}")
        if digest(source) != expected:
            raise SystemExit(f"release manifest hash mismatch for {name}")
        target = output / name
        shutil.copy2(source, target)
        copied[name] = target

    manifest_target = output / "release-manifest.json"
    shutil.copy2(manifest_source, manifest_target)
    return manifest_target, copied


def main() -> int:
    expected_release = (REPOSITORY_ROOT / "tkr" / "release_freeze.py").resolve()
    expected_source = (REPOSITORY_ROOT / "tkr" / "source_provenance.py").resolve()
    if Path(release_freeze_module.__file__).resolve() != expected_release:
        raise SystemExit("release verifier was not loaded from the reviewed checkout")
    if Path(source_provenance_module.__file__).resolve() != expected_source:
        raise SystemExit("source verifier was not loaded from the reviewed checkout")

    parser = argparse.ArgumentParser(
        description="Assemble a Phase 8 technical freeze candidate."
    )
    parser.add_argument("--matrix-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument(
        "--reproducible-wheel",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    args = parser.parse_args()

    if len(args.reproducible_wheel) < 2:
        raise SystemExit("at least two reproducible wheels are required")

    matrix_root = args.matrix_root.resolve()
    if not matrix_root.is_dir():
        raise SystemExit(f"matrix root is not a directory: {matrix_root}")

    reproducible_inputs = [
        item.resolve() for item in args.reproducible_wheel
    ]
    if any(not item.is_file() for item in reproducible_inputs):
        raise SystemExit("every reproducible wheel input must be a file")

    output = args.output_root.resolve()
    ensure_disjoint_output(matrix_root, output, reproducible_inputs)
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
            raise SystemExit(
                f"duplicate package acceptance for Python {minor}"
            )
        reports[minor] = path
        accepted_wheel_hashes.add(str(payload.get("wheel_sha256")))
        accepted_wheel_names.add(str(payload.get("wheel_name")))

    required = {"3.10", "3.11", "3.12"}
    if set(reports) != required:
        raise SystemExit(
            f"package acceptance matrix mismatch: {sorted(reports)}"
        )
    if len(accepted_wheel_hashes) != 1 or len(accepted_wheel_names) != 1:
        raise SystemExit(
            "package acceptance reports disagree on wheel identity"
        )

    expected_wheel_sha = next(iter(accepted_wheel_hashes))
    wheel_name = next(iter(accepted_wheel_names))
    if not re.fullmatch(r"[0-9a-f]{64}", expected_wheel_sha):
        raise SystemExit("package acceptance wheel SHA-256 is invalid")

    source_wheels = list(matrix_root.rglob(wheel_name))
    if not source_wheels:
        raise SystemExit(f"accepted wheel not found: {wheel_name}")
    if any(digest(path) != expected_wheel_sha for path in source_wheels):
        raise SystemExit(
            "a matrix wheel does not match package acceptance SHA-256"
        )

    wheel = output / wheel_name
    shutil.copy2(source_wheels[0], wheel)

    source_bundle = output / "source.bundle"
    source_provenance = output / "source-provenance.json"
    build_source_provenance(
        args.source_root,
        source_bundle,
        source_provenance,
        source_commit=args.source_commit,
        source_date_epoch=args.source_date_epoch,
        wheel_path=wheel,
    )

    benchmark_manifests = list(
        matrix_root.rglob("benchmark/release-manifest.json")
    )
    if not benchmark_manifests:
        raise SystemExit("release benchmark evidence not found")
    if len(benchmark_manifests) != 3:
        raise SystemExit(
            "expected one benchmark evidence directory per Python minor"
        )

    benchmark_hashes = {
        digest(path.parent / "release-manifest.json")
        for path in benchmark_manifests
    }
    if len(benchmark_hashes) != 1:
        raise SystemExit(
            "release benchmark manifests disagree across Python versions"
        )

    manifest_target, release_targets = _copy_verified_release_files(
        benchmark_manifests[0].parent,
        output,
    )

    package_targets: list[Path] = []
    for minor in sorted(reports):
        target = output / f"package-acceptance-python-{minor}.json"
        shutil.copy2(reports[minor], target)
        package_targets.append(target)

    reproducible_dir = output / "reproducible-wheels"
    reproducible_dir.mkdir()
    reproducible_targets: list[Path] = []
    for index, source in enumerate(reproducible_inputs, 1):
        target = reproducible_dir / f"build-{index:02d}.whl"
        shutil.copy2(source, target)
        reproducible_targets.append(target)

    build_hashes = [digest(item) for item in reproducible_targets]
    reproducible = {
        "schema_version": "tkr-reproducible-build-v1",
        "accepted": (
            len(set(build_hashes)) == 1
            and build_hashes[0] == expected_wheel_sha
        ),
        "build_count": len(build_hashes),
        "wheel_sha256": expected_wheel_sha,
        "build_sha256": build_hashes,
    }
    if reproducible["accepted"] is not True:
        raise SystemExit(
            f"reproducible wheel mismatch: {build_hashes} "
            f"!= {expected_wheel_sha}"
        )
    reproducible_path = output / "reproducible-build-report.json"
    reproducible_path.write_text(
        json.dumps(reproducible, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    specs: list[tuple[str, Path]] = [
        ("wheel", wheel),
        ("release_manifest", manifest_target),
        *(
            (role, release_targets[name])
            for name, role in RELEASE_FILE_ROLES.items()
        ),
        ("reproducible_build_report", reproducible_path),
        ("source_bundle", source_bundle),
        ("source_provenance", source_provenance),
    ]
    specs.extend(
        ("package_acceptance", path) for path in package_targets
    )
    specs.extend(
        ("reproducible_wheel", path)
        for path in reproducible_targets
    )

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

    if (
        candidate.get("may_freeze") is not False
        or verification.get("may_freeze") is not False
    ):
        raise SystemExit(
            "technical candidate must not self-grant freeze authority"
        )

    print(
        json.dumps(
            {"candidate": candidate, "verification": verification},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
