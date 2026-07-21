from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"patch anchor not found: {label}")
    return text.replace(old, new, 1)


release = Path("tkr/release_freeze.py")
text = release.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from typing import Mapping, Sequence\n",
    "from typing import Mapping, Sequence\n\nfrom .gold_benchmark import verify_benchmark_report\n",
    "gold benchmark import",
)
old_constants = '''REQUIRED_PYTHON_MINORS = ("3.10", "3.11", "3.12")
SINGLETON_ROLES = (
    "wheel",
    "release_manifest",
    "release_report",
    "release_verification",
    "reproducible_build_report",
)
'''
new_constants = '''REQUIRED_PYTHON_MINORS = ("3.10", "3.11", "3.12")
RELEASE_MANIFEST_FILE_ROLES = (
    ("normalized-text.txt", "release_source"),
    ("unit-index.csv", "release_units"),
    ("claims.accepted.jsonl", "release_claims"),
    ("knowledge.sqlite3", "release_database"),
    ("knowledge.report.json", "release_index_report"),
    ("gold-release.jsonl", "release_gold"),
    ("release-report.json", "release_report"),
    ("release-verification.json", "release_verification"),
)
SINGLETON_ROLES = (
    "wheel",
    "release_manifest",
    "release_source",
    "release_units",
    "release_claims",
    "release_database",
    "release_index_report",
    "release_gold",
    "release_report",
    "release_verification",
    "reproducible_build_report",
)
'''
text = replace_once(text, old_constants, new_constants, "artifact role constants")
old_group = '''def _group_records(records: Sequence[ArtifactRecord]) -> dict[str, list[ArtifactRecord]]:
    grouped: dict[str, list[ArtifactRecord]] = {}
    for record in records:
        grouped.setdefault(record.role, []).append(record)
    for role in SINGLETON_ROLES:
        count = len(grouped.get(role, []))
        if count != 1:
            raise FreezeError(f"exactly one {role} artifact is required; found {count}")
    package_count = len(grouped.get("package_acceptance", []))
    if package_count < len(REQUIRED_PYTHON_MINORS):
        raise FreezeError(
            f"at least {len(REQUIRED_PYTHON_MINORS)} package_acceptance artifacts are required"
        )
    allowed = set(SINGLETON_ROLES) | {"package_acceptance"}
    unknown = sorted(set(grouped) - allowed)
    if unknown:
        raise FreezeError(f"unsupported artifact roles: {unknown}")
    return grouped
'''
new_group = '''def _group_records(records: Sequence[ArtifactRecord]) -> dict[str, list[ArtifactRecord]]:
    grouped: dict[str, list[ArtifactRecord]] = {}
    for record in records:
        grouped.setdefault(record.role, []).append(record)
    for role in SINGLETON_ROLES:
        count = len(grouped.get(role, []))
        if count != 1:
            raise FreezeError(f"exactly one {role} artifact is required; found {count}")
    package_count = len(grouped.get("package_acceptance", []))
    if package_count < len(REQUIRED_PYTHON_MINORS):
        raise FreezeError(
            f"at least {len(REQUIRED_PYTHON_MINORS)} package_acceptance artifacts are required"
        )
    reproducible_count = len(grouped.get("reproducible_wheel", []))
    if reproducible_count < 2:
        raise FreezeError("at least 2 reproducible_wheel artifacts are required")
    allowed = set(SINGLETON_ROLES) | {"package_acceptance", "reproducible_wheel"}
    unknown = sorted(set(grouped) - allowed)
    if unknown:
        raise FreezeError(f"unsupported artifact roles: {unknown}")
    return grouped
'''
text = replace_once(text, old_group, new_group, "group records")
start = text.index("def _validate_release_evidence(")
end = text.index("\n\ndef _candidate_core(", start)
new_validate = '''def _validate_release_evidence(
    root: Path,
    records: Sequence[ArtifactRecord],
    *,
    release_version: str,
) -> dict[str, object]:
    grouped = _group_records(records)
    release_manifest = _load_json_object(
        _single_path(root, grouped, "release_manifest"), "release manifest"
    )
    release_report_path = _single_path(root, grouped, "release_report")
    release_report = _load_json_object(release_report_path, "release report")
    release_verification = _load_json_object(
        _single_path(root, grouped, "release_verification"), "release verification"
    )
    reproducible = _load_json_object(
        _single_path(root, grouped, "reproducible_build_report"),
        "reproducible build report",
    )

    manifest_files = release_manifest.get("files")
    if not isinstance(manifest_files, dict):
        raise FreezeError("release manifest files must be an object")
    expected_manifest_files = {name for name, _ in RELEASE_MANIFEST_FILE_ROLES}
    if set(manifest_files) != expected_manifest_files:
        missing = sorted(expected_manifest_files - set(manifest_files))
        unknown = sorted(set(manifest_files) - expected_manifest_files)
        raise FreezeError(
            f"release manifest files mismatch; missing={missing}, unknown={unknown}"
        )
    for file_name, role in RELEASE_MANIFEST_FILE_ROLES:
        declared = manifest_files[file_name]
        if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
            raise FreezeError(f"release manifest hash is invalid: {file_name}")
        if grouped[role][0].sha256 != declared:
            raise FreezeError(f"release manifest hash mismatch: {file_name}")

    governance = release_manifest.get("governance")
    if not isinstance(governance, dict):
        raise FreezeError("release manifest governance must be an object")
    _bool_is(governance, "may_freeze", False, "release manifest governance")
    if not isinstance(release_manifest.get("case_count"), int) or release_manifest["case_count"] < 100:
        raise FreezeError("release manifest must contain at least 100 Gold cases")

    _bool_is(release_report, "passed", True, "release report")
    _bool_is(release_report, "may_certify_release", True, "release report")
    _bool_is(release_report, "may_freeze", False, "release report")
    if release_report.get("blockers") != []:
        raise FreezeError("release report blockers must be empty")
    report_id = _nonempty_string(release_report.get("report_id"), "release report.report_id")

    benchmark_verification = verify_benchmark_report(
        _single_path(root, grouped, "release_database"),
        _single_path(root, grouped, "release_gold"),
        release_report_path,
        index_report_path=_single_path(root, grouped, "release_index_report"),
        expected_profile="release",
    )
    if not benchmark_verification.accepted:
        raise FreezeError(
            "release benchmark recomputation failed: "
            + ",".join(benchmark_verification.reason_codes)
        )
    recomputed_verification = benchmark_verification.to_dict()
    if release_verification != recomputed_verification:
        raise FreezeError("release verification does not match independent recomputation")
    if release_verification.get("expected_report_id") != report_id:
        raise FreezeError("release verification expected_report_id mismatch")
    if release_verification.get("supplied_report_id") != report_id:
        raise FreezeError("release verification supplied_report_id mismatch")

    package_versions: set[str] = set()
    package_python_minors: set[str] = set()
    package_wheel_hashes: set[str] = set()
    package_wheel_names: set[str] = set()
    for record in grouped["package_acceptance"]:
        payload = _load_json_object(
            _resolve_under_root(root, record.path), f"package acceptance {record.path}"
        )
        _bool_is(payload, "accepted", True, "package acceptance")
        if payload.get("failures") != []:
            raise FreezeError(f"package acceptance failures must be empty: {record.path}")
        package_versions.add(_nonempty_string(payload.get("version"), "package version"))
        package_python_minors.add(_python_minor(payload.get("python")))
        wheel_hash = _nonempty_string(payload.get("wheel_sha256"), "package wheel_sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", wheel_hash):
            raise FreezeError("package wheel_sha256 must be lowercase SHA-256")
        package_wheel_hashes.add(wheel_hash)
        package_wheel_names.add(_nonempty_string(payload.get("wheel_name"), "package wheel_name"))

    if package_versions != {release_version}:
        raise FreezeError(
            f"package acceptance versions do not match release version: {sorted(package_versions)}"
        )
    missing_minors = sorted(set(REQUIRED_PYTHON_MINORS) - package_python_minors)
    if missing_minors:
        raise FreezeError(f"missing package acceptance Python versions: {missing_minors}")
    if len(package_wheel_hashes) != 1:
        raise FreezeError("package acceptance reports disagree on wheel SHA-256")
    if len(package_wheel_names) != 1:
        raise FreezeError("package acceptance reports disagree on wheel filename")
    wheel_sha256 = next(iter(package_wheel_hashes))
    wheel_record = grouped["wheel"][0]
    if wheel_record.sha256 != wheel_sha256:
        raise FreezeError("declared wheel bytes do not match package acceptance SHA-256")

    if reproducible.get("schema_version") != REPRODUCIBLE_BUILD_SCHEMA_VERSION:
        raise FreezeError("unsupported reproducible build report schema")
    _bool_is(reproducible, "accepted", True, "reproducible build report")
    reproducible_records = grouped["reproducible_wheel"]
    actual_build_hashes = [record.sha256 for record in reproducible_records]
    build_count = reproducible.get("build_count")
    if (
        not isinstance(build_count, int)
        or isinstance(build_count, bool)
        or build_count != len(reproducible_records)
    ):
        raise FreezeError("reproducible build count does not match bound artifacts")
    if reproducible.get("wheel_sha256") != wheel_sha256:
        raise FreezeError("reproducible build wheel SHA-256 mismatch")
    build_hashes = reproducible.get("build_sha256")
    if build_hashes != actual_build_hashes:
        raise FreezeError("reproducible build hashes do not match bound artifacts")
    if any(item != wheel_sha256 for item in actual_build_hashes):
        raise FreezeError("bound reproducible wheels are not byte-identical")

    return {
        "release_report_id": report_id,
        "gold_case_count": release_manifest["case_count"],
        "benchmark_recomputed": True,
        "benchmark_reason_codes": list(benchmark_verification.reason_codes),
        "package_python_minors": sorted(package_python_minors),
        "wheel_name": next(iter(package_wheel_names)),
        "wheel_sha256": wheel_sha256,
        "reproducible_build_count": build_count,
        "reproducible_wheel_artifact_count": len(reproducible_records),
        "technical_gate_passed": True,
    }
'''
text = text[:start] + new_validate + text[end:]
release.write_text(text, encoding="utf-8")

assemble = Path("tools/assemble_freeze_candidate.py")
assemble.write_text('''from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from tkr.release_freeze import prepare_freeze_candidate, verify_freeze_candidate


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
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON object required: {path}")
    return payload


def python_minor(value: object) -> str:
    match = re.match(r"^(\\d+\\.\\d+)", str(value))
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
    if any(not item.is_file() for item in reproducible_wheels):
        raise SystemExit("every reproducible wheel input must be a file")
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

    source_wheels = sorted(matrix_root.rglob(wheel_name))
    if not source_wheels:
        raise SystemExit(f"accepted wheel not found: {wheel_name}")
    if any(digest(path) != expected_wheel_sha for path in source_wheels):
        raise SystemExit("a matrix wheel does not match its package acceptance SHA-256")
    wheel = output / wheel_name
    shutil.copy2(source_wheels[0], wheel)

    manifest_paths = sorted(matrix_root.rglob("benchmark/release-manifest.json"))
    if not manifest_paths:
        raise SystemExit("release benchmark evidence not found")
    benchmark_bundles: list[tuple[Path, dict[str, str]]] = []
    for manifest_path in manifest_paths:
        benchmark_root = manifest_path.parent
        manifest = load(manifest_path)
        declared = manifest.get("files")
        if not isinstance(declared, dict) or set(declared) != set(RELEASE_FILE_ROLES):
            raise SystemExit(f"release manifest file set mismatch: {manifest_path}")
        actual: dict[str, str] = {}
        for name in RELEASE_FILE_ROLES:
            artifact = benchmark_root / name
            if not artifact.is_file():
                raise SystemExit(f"release benchmark artifact missing: {artifact}")
            actual[name] = digest(artifact)
        if actual != declared:
            raise SystemExit(f"release manifest hashes do not match files: {manifest_path}")
        benchmark_bundles.append((benchmark_root, actual))
    if len({json.dumps(item[1], sort_keys=True) for item in benchmark_bundles}) != 1:
        raise SystemExit("release benchmark artifacts differ across Python acceptance jobs")
    benchmark = benchmark_bundles[0][0]
    release_manifest = output / "release-manifest.json"
    shutil.copy2(benchmark / "release-manifest.json", release_manifest)
    copied: dict[str, Path] = {}
    for name in RELEASE_FILE_ROLES:
        target = output / name
        shutil.copy2(benchmark / name, target)
        copied[name] = target

    package_targets: list[Path] = []
    for minor in sorted(reports):
        target = output / f"package-acceptance-python-{minor}.json"
        shutil.copy2(reports[minor], target)
        package_targets.append(target)

    reproducible_targets: list[Path] = []
    for index, source in enumerate(reproducible_wheels, 1):
        target = output / f"reproducible-build-{index:02d}-{wheel_name}"
        shutil.copy2(source, target)
        reproducible_targets.append(target)
    build_hashes = [digest(item) for item in reproducible_targets]
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
        json.dumps(reproducible, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )

    specs: list[tuple[str, Path]] = [
        ("wheel", wheel),
        ("release_manifest", release_manifest),
        ("reproducible_build_report", reproducible_path),
    ]
    specs.extend((role, copied[name]) for name, role in RELEASE_FILE_ROLES.items())
    specs.extend(("reproducible_wheel", path) for path in reproducible_targets)
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
        json.dumps(verification, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    if candidate.get("may_freeze") is not False or verification.get("may_freeze") is not False:
        raise SystemExit("technical candidate must not self-grant freeze authority")
    print(json.dumps({"candidate": candidate, "verification": verification}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''', encoding="utf-8")

tests = Path("tests/test_release_freeze.py")
tests.write_text('''from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tkr.gold_benchmark import BenchmarkVerification
from tkr.release_freeze import (
    FREEZE_APPROVAL_SCHEMA_VERSION,
    FreezeError,
    prepare_freeze_candidate,
    seal_freeze_candidate,
    verify_freeze_candidate,
    verify_freeze_seal,
)


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


class ReleaseFreezeTests(unittest.TestCase):
    SOURCE_COMMIT = "a" * 40
    VERSION = "5.8.0a1"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wheel = self.root / "text_knowledge_reader_core-5.8.0a1-py3-none-any.whl"
        self.wheel.write_bytes(b"canonical-wheel-bytes")
        self.wheel_sha = sha256(self.wheel.read_bytes()).hexdigest()

        self.benchmark_verification = BenchmarkVerification(
            "accepted",
            True,
            ("BENCHMARK_RECOMPUTED_EXACTLY", "IMMUTABLE_POLICY_CONFIRMED"),
            "bench_release_001",
            "bench_release_001",
        )
        self.verify_patch = patch(
            "tkr.release_freeze.verify_benchmark_report",
            return_value=self.benchmark_verification,
        )
        self.verify_mock = self.verify_patch.start()

        self.benchmark_files: dict[str, Path] = {}
        for name, data in {
            "normalized-text.txt": b"fixture source\\n",
            "unit-index.csv": b"source_id,unit_id,start,end\\n",
            "claims.accepted.jsonl": b"{}\\n",
            "knowledge.sqlite3": b"sqlite fixture bytes",
            "knowledge.report.json": b"{}\\n",
            "gold-release.jsonl": b"{}\\n",
        }.items():
            path = self.root / name
            path.write_bytes(data)
            self.benchmark_files[name] = path

        self.release_report = self._write_json(
            "release-report.json",
            {
                "passed": True,
                "may_certify_release": True,
                "may_freeze": False,
                "blockers": [],
                "report_id": "bench_release_001",
            },
        )
        self.benchmark_files["release-report.json"] = self.release_report
        self.release_verification = self._write_json(
            "release-verification.json",
            self.benchmark_verification.to_dict(),
        )
        self.benchmark_files["release-verification.json"] = self.release_verification
        self.release_manifest = self._write_json(
            "release-manifest.json",
            {
                "case_count": 108,
                "governance": {"may_freeze": False},
                "files": {
                    name: sha256(path.read_bytes()).hexdigest()
                    for name, path in self.benchmark_files.items()
                },
            },
        )

        self.reproducible_wheels = []
        for index in (1, 2):
            path = self.root / f"reproducible-build-{index:02d}.whl"
            path.write_bytes(self.wheel.read_bytes())
            self.reproducible_wheels.append(path)
        self.reproducible = self._write_json(
            "reproducible-build.json",
            {
                "schema_version": "tkr-reproducible-build-v1",
                "accepted": True,
                "build_count": 2,
                "wheel_sha256": self.wheel_sha,
                "build_sha256": [
                    sha256(path.read_bytes()).hexdigest()
                    for path in self.reproducible_wheels
                ],
            },
        )
        self.package_reports = []
        for minor in ("3.10", "3.11", "3.12"):
            self.package_reports.append(
                self._write_json(
                    f"package-{minor}.json",
                    {
                        "accepted": True,
                        "failures": [],
                        "python": f"{minor}.9 (main, test)",
                        "version": self.VERSION,
                        "wheel_sha256": self.wheel_sha,
                        "wheel_name": self.wheel.name,
                    },
                )
            )

    def tearDown(self) -> None:
        self.verify_patch.stop()
        self.temporary.cleanup()

    def _write_json(self, name: str, payload: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload, sort_keys=True) + "\\n", encoding="utf-8")
        return path

    def _refresh_manifest(self) -> None:
        payload = json.loads(self.release_manifest.read_text(encoding="utf-8"))
        payload["files"] = {
            name: sha256(path.read_bytes()).hexdigest()
            for name, path in self.benchmark_files.items()
        }
        self.release_manifest.write_text(json.dumps(payload, sort_keys=True) + "\\n", encoding="utf-8")

    def _specs(self) -> list[tuple[str, Path]]:
        specs: list[tuple[str, Path]] = [
            ("wheel", self.wheel),
            ("release_manifest", self.release_manifest),
            ("reproducible_build_report", self.reproducible),
        ]
        specs.extend((role, self.benchmark_files[name]) for name, role in RELEASE_FILE_ROLES.items())
        specs.extend(("reproducible_wheel", path) for path in self.reproducible_wheels)
        specs.extend(("package_acceptance", path) for path in self.package_reports)
        return specs

    def _prepare(self) -> Path:
        path = self.root / "freeze-candidate.json"
        payload = prepare_freeze_candidate(
            self.root,
            self._specs(),
            release_version=self.VERSION,
            source_commit=self.SOURCE_COMMIT,
            source_date_epoch=1700000000,
            output_path=path,
        )
        self.assertFalse(payload["may_freeze"])
        self.assertTrue(payload["requires_explicit_approval"])
        return path

    def test_prepare_and_verify_candidate(self) -> None:
        candidate = self._prepare()
        result = verify_freeze_candidate(candidate, root=self.root)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["may_freeze"])
        self.assertIn("EXPLICIT_APPROVAL_STILL_REQUIRED", result["reason_codes"])
        self.assertGreaterEqual(self.verify_mock.call_count, 2)

    def test_rejected_benchmark_recomputation_blocks_candidate(self) -> None:
        self.verify_mock.return_value = BenchmarkVerification(
            "rejected",
            False,
            ("BENCHMARK_REPORT_RECOMPUTATION_MISMATCH",),
            "bench_release_001",
            "bench_release_001",
        )
        with self.assertRaisesRegex(FreezeError, "benchmark recomputation failed"):
            prepare_freeze_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_saved_verification_must_match_recomputation(self) -> None:
        payload = json.loads(self.release_verification.read_text(encoding="utf-8"))
        payload["reason_codes"] = ["FORGED"]
        self.release_verification.write_text(json.dumps(payload), encoding="utf-8")
        self._refresh_manifest()
        with self.assertRaisesRegex(FreezeError, "does not match independent recomputation"):
            prepare_freeze_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_tampered_artifact_is_rejected(self) -> None:
        candidate = self._prepare()
        self.wheel.write_bytes(b"tampered")
        with self.assertRaisesRegex(FreezeError, "mismatch"):
            verify_freeze_candidate(candidate, root=self.root)

    def test_missing_required_python_acceptance_is_rejected(self) -> None:
        specs = self._specs()
        specs.remove(("package_acceptance", self.package_reports[-1]))
        with self.assertRaisesRegex(FreezeError, "at least 3 package_acceptance"):
            prepare_freeze_candidate(
                self.root,
                specs,
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_missing_second_reproducible_wheel_is_rejected(self) -> None:
        specs = self._specs()
        specs.remove(("reproducible_wheel", self.reproducible_wheels[-1]))
        with self.assertRaisesRegex(FreezeError, "at least 2 reproducible_wheel"):
            prepare_freeze_candidate(
                self.root,
                specs,
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_reported_reproducible_hashes_must_match_bound_wheels(self) -> None:
        self.reproducible_wheels[-1].write_bytes(b"different-build")
        with self.assertRaisesRegex(FreezeError, "hashes do not match bound artifacts"):
            prepare_freeze_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_mismatched_package_wheel_hash_is_rejected(self) -> None:
        payload = json.loads(self.package_reports[0].read_text(encoding="utf-8"))
        payload["wheel_sha256"] = "0" * 64
        self.package_reports[0].write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FreezeError, "disagree on wheel SHA-256"):
            prepare_freeze_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_phase7_cannot_self_grant_freeze(self) -> None:
        payload = json.loads(self.release_report.read_text(encoding="utf-8"))
        payload["may_freeze"] = True
        self.release_report.write_text(json.dumps(payload), encoding="utf-8")
        self._refresh_manifest()
        with self.assertRaisesRegex(FreezeError, "may_freeze must be False"):
            prepare_freeze_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_explicit_approval_creates_and_verifies_seal(self) -> None:
        candidate = self._prepare()
        candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
        approval = self._write_json(
            "approval.json",
            {
                "schema_version": FREEZE_APPROVAL_SCHEMA_VERSION,
                "candidate_id": candidate_payload["candidate_id"],
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "approver": "release-owner",
                "decision": "approve",
                "statement": "I approve this exact technical candidate for freezing.",
                "approved_at": "2026-07-21T05:00:00Z",
            },
        )
        seal = self.root / "freeze-seal.json"
        payload = seal_freeze_candidate(candidate, approval, seal, root=self.root)
        self.assertTrue(payload["may_freeze"])
        self.assertEqual(
            payload["approval_authentication"],
            "operator_asserted_not_cryptographically_verified",
        )
        verification = verify_freeze_seal(seal, candidate, approval, root=self.root)
        self.assertTrue(verification["accepted"])
        self.assertTrue(verification["may_freeze"])

    def test_approval_for_another_candidate_is_rejected(self) -> None:
        candidate = self._prepare()
        approval = self._write_json(
            "approval.json",
            {
                "schema_version": FREEZE_APPROVAL_SCHEMA_VERSION,
                "candidate_id": "freeze_candidate_wrong",
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "approver": "release-owner",
                "decision": "approve",
                "statement": "approve",
                "approved_at": "2026-07-21T05:00:00Z",
            },
        )
        with self.assertRaisesRegex(FreezeError, "candidate_id does not match"):
            seal_freeze_candidate(
                candidate,
                approval,
                self.root / "freeze-seal.json",
                root=self.root,
            )

    def test_unknown_approval_fields_are_rejected(self) -> None:
        candidate = self._prepare()
        candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
        approval = self._write_json(
            "approval.json",
            {
                "schema_version": FREEZE_APPROVAL_SCHEMA_VERSION,
                "candidate_id": candidate_payload["candidate_id"],
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "approver": "release-owner",
                "decision": "approve",
                "statement": "approve",
                "approved_at": "2026-07-21T05:00:00Z",
                "may_freeze": True,
            },
        )
        with self.assertRaisesRegex(FreezeError, "keys mismatch"):
            seal_freeze_candidate(
                candidate,
                approval,
                self.root / "freeze-seal.json",
                root=self.root,
            )

    def _rewrite_candidate_id(self, payload: dict[str, object]) -> None:
        core = dict(payload)
        core.pop("candidate_id", None)
        canonical = json.dumps(
            core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload["candidate_id"] = "freeze_candidate_" + sha256(
            canonical.encode("utf-8")
        ).hexdigest()[:24]

    def test_verify_rejects_malformed_source_commit_even_with_recomputed_id(self) -> None:
        candidate = self._prepare()
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        payload["source_commit"] = "not-a-git-sha"
        self._rewrite_candidate_id(payload)
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FreezeError, "lowercase 40-character Git SHA"):
            verify_freeze_candidate(candidate, root=self.root)

    def test_verify_rejects_negative_source_epoch_even_with_recomputed_id(self) -> None:
        candidate = self._prepare()
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        payload["source_date_epoch"] = -1
        self._rewrite_candidate_id(payload)
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FreezeError, "non-negative integer"):
            verify_freeze_candidate(candidate, root=self.root)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

for path_name in ("README.md", "docs/phase8-security-notes.md"):
    path = Path(path_name)
    body = path.read_text(encoding="utf-8")
    marker = "Phase 8 final evidence binding"
    if marker not in body:
        body += '''

## Phase 8 final evidence binding

The technical freeze candidate now binds every file committed by the Release Gold manifest, independently reruns the release-profile benchmark against the bound SQLite database, Gold JSONL, index report, and benchmark report, and requires the saved verification JSON to equal the recomputed result. Two separately produced wheel files are copied into the candidate as distinct `reproducible_wheel` artifacts; their bytes are hashed again during both candidate preparation and independent verification. Repeated digest strings in an unbound report are not accepted as reproducibility evidence.
'''
        path.write_text(body, encoding="utf-8")

Path(".github/scripts/apply_phase8_binding_fixes.py").unlink()
Path(".github/workflows/phase8-binding-fixes.yml").unlink()
