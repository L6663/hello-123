"""Phase 8 release evidence binding and explicit freeze sealing.

A technical candidate recomputes every bound artifact and the Phase 7 Release Gold
report, but always remains ``may_freeze=false``. Freeze authority exists only in a
separate seal that binds an explicit operator approval record.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from .gold_benchmark import verify_benchmark_report

FREEZE_CANDIDATE_SCHEMA_VERSION = "tkr-freeze-candidate-v1"
FREEZE_SEAL_SCHEMA_VERSION = "tkr-freeze-seal-v1"
FREEZE_APPROVAL_SCHEMA_VERSION = "tkr-freeze-approval-v1"
REPRODUCIBLE_BUILD_SCHEMA_VERSION = "tkr-reproducible-build-v1"
REQUIRED_PYTHON_MINORS = ("3.10", "3.11", "3.12")

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


class FreezeError(ValueError):
    """Raised when release evidence or a freeze artifact is invalid."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FreezeError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FreezeError(f"{label} must be a JSON object: {path}")
    return payload


def _require_exact_keys(payload: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise FreezeError(f"{label} keys mismatch; missing={missing}, unknown={unknown}")


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FreezeError(f"{label} must be a non-empty string")
    return value.strip()


def _lower_sha256(value: object, label: str) -> str:
    text = _nonempty_string(value, label)
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise FreezeError(f"{label} must be lowercase SHA-256")
    return text


def _python_minor(value: object) -> str:
    text = _nonempty_string(value, "package acceptance python")
    match = re.match(r"^(\d+\.\d+)", text)
    if not match:
        raise FreezeError(f"cannot determine Python minor from {text!r}")
    return match.group(1)


def _bool_is(payload: Mapping[str, object], key: str, expected: bool, label: str) -> None:
    if payload.get(key) is not expected:
        raise FreezeError(f"{label}.{key} must be {expected}")


@dataclass(frozen=True)
class ArtifactRecord:
    role: str
    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ArtifactRecord":
        _require_exact_keys(payload, {"role", "path", "sha256", "size_bytes"}, "artifact")
        role = _nonempty_string(payload["role"], "artifact.role")
        path = _nonempty_string(payload["path"], "artifact.path")
        digest = _lower_sha256(payload["sha256"], "artifact.sha256")
        size = payload["size_bytes"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise FreezeError("artifact.size_bytes must be a non-negative integer")
        return cls(role=role, path=path, sha256=digest, size_bytes=size)


def _resolve_under_root(root: Path, stored_path: str) -> Path:
    candidate = (root / stored_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FreezeError(f"artifact escapes root: {stored_path}") from exc
    return candidate


def _records_from_specs(
    root: Path,
    artifact_specs: Sequence[tuple[str, str | Path]],
) -> tuple[ArtifactRecord, ...]:
    records: list[ArtifactRecord] = []
    seen_paths: set[str] = set()
    for raw_role, raw_path in artifact_specs:
        role = _nonempty_string(raw_role, "artifact role")
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise FreezeError(f"artifact is not a file: {path}")
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise FreezeError(f"artifact is outside release root: {path}") from exc
        if relative in seen_paths:
            raise FreezeError(f"artifact path is declared more than once: {relative}")
        seen_paths.add(relative)
        records.append(
            ArtifactRecord(
                role=role,
                path=relative,
                sha256=_sha256_path(path),
                size_bytes=path.stat().st_size,
            )
        )
    if not records:
        raise FreezeError("at least one artifact is required")
    return tuple(sorted(records, key=lambda item: (item.role, item.path)))


def _group_records(records: Sequence[ArtifactRecord]) -> dict[str, list[ArtifactRecord]]:
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


def _single_path(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
    role: str,
) -> Path:
    return _resolve_under_root(root, grouped[role][0].path)


def _validate_manifest_bindings(
    release_manifest: Mapping[str, object],
    grouped: Mapping[str, Sequence[ArtifactRecord]],
) -> None:
    manifest_files = release_manifest.get("files")
    if not isinstance(manifest_files, dict):
        raise FreezeError("release manifest files must be an object")

    expected_names = {name for name, _ in RELEASE_MANIFEST_FILE_ROLES}
    actual_names = set(manifest_files)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unknown = sorted(actual_names - expected_names)
        raise FreezeError(
            f"release manifest files mismatch; missing={missing}, unknown={unknown}"
        )

    for file_name, role in RELEASE_MANIFEST_FILE_ROLES:
        declared = _lower_sha256(
            manifest_files[file_name],
            f"release manifest files[{file_name!r}]",
        )
        if grouped[role][0].sha256 != declared:
            raise FreezeError(f"release manifest hash mismatch: {file_name}")


def _validate_release_evidence(
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
        _single_path(root, grouped, "release_verification"),
        "release verification",
    )
    reproducible = _load_json_object(
        _single_path(root, grouped, "reproducible_build_report"),
        "reproducible build report",
    )

    _validate_manifest_bindings(release_manifest, grouped)

    governance = release_manifest.get("governance")
    if not isinstance(governance, dict):
        raise FreezeError("release manifest governance must be an object")
    _bool_is(governance, "may_freeze", False, "release manifest governance")

    case_count = release_manifest.get("case_count")
    if not isinstance(case_count, int) or isinstance(case_count, bool) or case_count < 100:
        raise FreezeError("release manifest must contain at least 100 Gold cases")

    _bool_is(release_report, "passed", True, "release report")
    _bool_is(release_report, "may_certify_release", True, "release report")
    _bool_is(release_report, "may_freeze", False, "release report")
    if release_report.get("policy_profile") != "release":
        raise FreezeError("release report policy_profile must be release")
    if release_report.get("blockers") != []:
        raise FreezeError("release report blockers must be empty")
    if release_report.get("case_count") != case_count:
        raise FreezeError("release report case_count does not match manifest")
    report_id = _nonempty_string(
        release_report.get("report_id"), "release report.report_id"
    )
    if release_manifest.get("report_id") != report_id:
        raise FreezeError("release manifest report_id does not match release report")

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
        raise FreezeError(
            "release verification does not match independent recomputation"
        )
    if release_verification.get("expected_report_id") != report_id:
        raise FreezeError("release verification expected_report_id mismatch")
    if release_verification.get("supplied_report_id") != report_id:
        raise FreezeError("release verification supplied_report_id mismatch")

    package_versions: set[str] = set()
    package_python_minors: list[str] = []
    package_wheel_hashes: set[str] = set()
    package_wheel_names: set[str] = set()
    for record in grouped["package_acceptance"]:
        payload = _load_json_object(
            _resolve_under_root(root, record.path),
            f"package acceptance {record.path}",
        )
        _bool_is(payload, "accepted", True, "package acceptance")
        if payload.get("failures") != []:
            raise FreezeError(
                f"package acceptance failures must be empty: {record.path}"
            )
        package_versions.add(
            _nonempty_string(payload.get("version"), "package version")
        )
        package_python_minors.append(_python_minor(payload.get("python")))
        package_wheel_hashes.add(
            _lower_sha256(payload.get("wheel_sha256"), "package wheel_sha256")
        )
        package_wheel_names.add(
            _nonempty_string(payload.get("wheel_name"), "package wheel_name")
        )

    if package_versions != {release_version}:
        raise FreezeError(
            "package acceptance versions do not match release version: "
            f"{sorted(package_versions)}"
        )
    if sorted(package_python_minors) != sorted(REQUIRED_PYTHON_MINORS):
        raise FreezeError(
            "package acceptance Python matrix mismatch: "
            f"{sorted(package_python_minors)}"
        )
    if len(package_wheel_hashes) != 1:
        raise FreezeError("package acceptance reports disagree on wheel SHA-256")
    if len(package_wheel_names) != 1:
        raise FreezeError("package acceptance reports disagree on wheel filename")

    wheel_sha256 = next(iter(package_wheel_hashes))
    wheel_name = next(iter(package_wheel_names))
    wheel_record = grouped["wheel"][0]
    if wheel_record.sha256 != wheel_sha256:
        raise FreezeError(
            "declared wheel bytes do not match package acceptance SHA-256"
        )
    if Path(wheel_record.path).name != wheel_name:
        raise FreezeError(
            "declared wheel filename does not match package acceptance"
        )

    if reproducible.get("schema_version") != REPRODUCIBLE_BUILD_SCHEMA_VERSION:
        raise FreezeError("unsupported reproducible build report schema")
    _bool_is(reproducible, "accepted", True, "reproducible build report")

    reproducible_records = grouped["reproducible_wheel"]
    if any(Path(record.path).suffix != ".whl" for record in reproducible_records):
        raise FreezeError("every reproducible_wheel artifact must be a wheel file")
    actual_build_hashes = [record.sha256 for record in reproducible_records]

    build_count = reproducible.get("build_count")
    if (
        not isinstance(build_count, int)
        or isinstance(build_count, bool)
        or build_count != len(reproducible_records)
    ):
        raise FreezeError(
            "reproducible build count does not match bound artifacts"
        )
    if reproducible.get("wheel_sha256") != wheel_sha256:
        raise FreezeError("reproducible build wheel SHA-256 mismatch")
    if reproducible.get("build_sha256") != actual_build_hashes:
        raise FreezeError(
            "reproducible build hashes do not match bound artifacts"
        )
    if any(item != wheel_sha256 for item in actual_build_hashes):
        raise FreezeError("bound reproducible wheels are not byte-identical")

    return {
        "release_report_id": report_id,
        "gold_case_count": case_count,
        "benchmark_recomputed": True,
        "benchmark_reason_codes": list(benchmark_verification.reason_codes),
        "package_python_minors": sorted(package_python_minors),
        "wheel_name": wheel_name,
        "wheel_sha256": wheel_sha256,
        "reproducible_build_count": build_count,
        "reproducible_wheel_artifact_count": len(reproducible_records),
        "technical_gate_passed": True,
    }


def _candidate_core(
    *,
    release_version: str,
    source_commit: str,
    source_date_epoch: int,
    records: Sequence[ArtifactRecord],
    evidence: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": FREEZE_CANDIDATE_SCHEMA_VERSION,
        "release_version": release_version,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "artifacts": [record.to_dict() for record in records],
        "evidence": dict(evidence),
        "technical_gate_passed": True,
        "requires_explicit_approval": True,
        "may_freeze": False,
        "status": "candidate",
    }


def prepare_freeze_candidate(
    root: str | Path,
    artifact_specs: Sequence[tuple[str, str | Path]],
    *,
    release_version: str,
    source_commit: str,
    source_date_epoch: int,
    output_path: str | Path | None = None,
) -> dict[str, object]:
    """Build a hash-bound technical candidate that cannot freeze by itself."""

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FreezeError(f"release root is not a directory: {root_path}")
    version = _nonempty_string(release_version, "release_version")
    commit = _nonempty_string(source_commit, "source_commit")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise FreezeError(
            "source_commit must be a lowercase 40-character Git SHA"
        )
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise FreezeError("source_date_epoch must be a non-negative integer")

    records = _records_from_specs(root_path, artifact_specs)
    evidence = _validate_release_evidence(
        root_path, records, release_version=version
    )
    core = _candidate_core(
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
        records=records,
        evidence=evidence,
    )
    candidate_id = "freeze_candidate_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    payload = dict(core)
    payload["candidate_id"] = candidate_id
    output = (
        Path(output_path)
        if output_path is not None
        else root_path / "freeze-candidate.json"
    )
    _write_json(output, payload)
    return payload


def verify_freeze_candidate(
    candidate_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Recompute artifact hashes, Release Gold, and reproducible builds."""

    path = Path(candidate_path).resolve()
    payload = _load_json_object(path, "freeze candidate")
    expected_keys = {
        "schema_version",
        "release_version",
        "source_commit",
        "source_date_epoch",
        "artifacts",
        "evidence",
        "technical_gate_passed",
        "requires_explicit_approval",
        "may_freeze",
        "status",
        "candidate_id",
    }
    _require_exact_keys(payload, expected_keys, "freeze candidate")
    if payload["schema_version"] != FREEZE_CANDIDATE_SCHEMA_VERSION:
        raise FreezeError("unsupported freeze candidate schema")
    _bool_is(payload, "technical_gate_passed", True, "freeze candidate")
    _bool_is(payload, "requires_explicit_approval", True, "freeze candidate")
    _bool_is(payload, "may_freeze", False, "freeze candidate")
    if payload["status"] != "candidate":
        raise FreezeError("freeze candidate status must be candidate")

    release_version = _nonempty_string(
        payload["release_version"], "release_version"
    )
    source_commit = _nonempty_string(
        payload["source_commit"], "source_commit"
    )
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise FreezeError(
            "source_commit must be a lowercase 40-character Git SHA"
        )
    source_date_epoch = payload["source_date_epoch"]
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise FreezeError("source_date_epoch must be a non-negative integer")

    root_path = (
        Path(root).resolve() if root is not None else path.parent.resolve()
    )
    raw_records = payload["artifacts"]
    if not isinstance(raw_records, list) or not raw_records:
        raise FreezeError(
            "freeze candidate artifacts must be a non-empty list"
        )
    records = tuple(
        ArtifactRecord.from_dict(item)
        for item in raw_records
        if isinstance(item, dict)
    )
    if len(records) != len(raw_records):
        raise FreezeError(
            "every freeze candidate artifact must be an object"
        )
    if tuple(
        sorted(records, key=lambda item: (item.role, item.path))
    ) != records:
        raise FreezeError(
            "freeze candidate artifacts must be canonically sorted"
        )

    for record in records:
        artifact = _resolve_under_root(root_path, record.path)
        if not artifact.is_file():
            raise FreezeError(f"missing freeze artifact: {record.path}")
        if artifact.stat().st_size != record.size_bytes:
            raise FreezeError(
                f"freeze artifact size mismatch: {record.path}"
            )
        if _sha256_path(artifact) != record.sha256:
            raise FreezeError(
                f"freeze artifact SHA-256 mismatch: {record.path}"
            )

    evidence = _validate_release_evidence(
        root_path, records, release_version=release_version
    )
    if payload["evidence"] != evidence:
        raise FreezeError("freeze candidate evidence summary mismatch")

    core = dict(payload)
    supplied_id = _nonempty_string(
        core.pop("candidate_id"), "candidate_id"
    )
    expected_id = "freeze_candidate_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    if supplied_id != expected_id:
        raise FreezeError("freeze candidate ID mismatch")

    return {
        "status": "accepted",
        "accepted": True,
        "candidate_id": supplied_id,
        "reason_codes": [
            "ARTIFACT_HASHES_RECOMPUTED",
            "RELEASE_BENCHMARK_RECOMPUTED",
            "REPRODUCIBLE_WHEELS_REHASHED",
            "EXPLICIT_APPROVAL_STILL_REQUIRED",
        ],
        "may_freeze": False,
    }


def _load_approval(path: Path) -> dict[str, object]:
    payload = _load_json_object(path, "freeze approval")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "candidate_id",
            "release_version",
            "source_commit",
            "approver",
            "decision",
            "statement",
            "approved_at",
        },
        "freeze approval",
    )
    if payload["schema_version"] != FREEZE_APPROVAL_SCHEMA_VERSION:
        raise FreezeError("unsupported freeze approval schema")
    if payload["decision"] != "approve":
        raise FreezeError("freeze approval decision must be approve")
    for key in (
        "candidate_id",
        "release_version",
        "source_commit",
        "approver",
        "statement",
        "approved_at",
    ):
        _nonempty_string(payload[key], f"freeze approval.{key}")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload["source_commit"])):
        raise FreezeError(
            "freeze approval.source_commit must be a lowercase "
            "40-character Git SHA"
        )
    return payload


def seal_freeze_candidate(
    candidate_path: str | Path,
    approval_path: str | Path,
    output_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Create a seal only after a separate explicit approval exists."""

    candidate = Path(candidate_path).resolve()
    approval = Path(approval_path).resolve()
    verification = verify_freeze_candidate(candidate, root=root)
    candidate_payload = _load_json_object(candidate, "freeze candidate")
    approval_payload = _load_approval(approval)
    for field in ("candidate_id", "release_version", "source_commit"):
        if approval_payload[field] != candidate_payload[field]:
            raise FreezeError(
                f"freeze approval {field} does not match candidate"
            )

    core = {
        "schema_version": FREEZE_SEAL_SCHEMA_VERSION,
        "candidate_id": candidate_payload["candidate_id"],
        "candidate_sha256": _sha256_path(candidate),
        "approval_sha256": _sha256_path(approval),
        "release_version": candidate_payload["release_version"],
        "source_commit": candidate_payload["source_commit"],
        "approver": approval_payload["approver"],
        "approved_at": approval_payload["approved_at"],
        "technical_gate_passed": verification["accepted"],
        "approval_asserted": True,
        "approval_authentication":
            "operator_asserted_not_cryptographically_verified",
        "may_freeze": True,
        "status": "sealed",
    }
    freeze_id = "freeze_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    payload = dict(core)
    payload["freeze_id"] = freeze_id
    _write_json(Path(output_path), payload)
    return payload


def verify_freeze_seal(
    seal_path: str | Path,
    candidate_path: str | Path,
    approval_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Verify a seal, its candidate, approval, and all bound artifacts."""

    seal = Path(seal_path).resolve()
    candidate = Path(candidate_path).resolve()
    approval = Path(approval_path).resolve()
    payload = _load_json_object(seal, "freeze seal")
    expected_keys = {
        "schema_version",
        "candidate_id",
        "candidate_sha256",
        "approval_sha256",
        "release_version",
        "source_commit",
        "approver",
        "approved_at",
        "technical_gate_passed",
        "approval_asserted",
        "approval_authentication",
        "may_freeze",
        "status",
        "freeze_id",
    }
    _require_exact_keys(payload, expected_keys, "freeze seal")
    if payload["schema_version"] != FREEZE_SEAL_SCHEMA_VERSION:
        raise FreezeError("unsupported freeze seal schema")
    _bool_is(payload, "technical_gate_passed", True, "freeze seal")
    _bool_is(payload, "approval_asserted", True, "freeze seal")
    _bool_is(payload, "may_freeze", True, "freeze seal")
    if payload["status"] != "sealed":
        raise FreezeError("freeze seal status must be sealed")
    if (
        payload["approval_authentication"]
        != "operator_asserted_not_cryptographically_verified"
    ):
        raise FreezeError("unsupported approval authentication mode")

    verify_freeze_candidate(candidate, root=root)
    candidate_payload = _load_json_object(candidate, "freeze candidate")
    approval_payload = _load_approval(approval)

    if payload["candidate_sha256"] != _sha256_path(candidate):
        raise FreezeError("freeze seal candidate SHA-256 mismatch")
    if payload["approval_sha256"] != _sha256_path(approval):
        raise FreezeError("freeze seal approval SHA-256 mismatch")

    for field in ("candidate_id", "release_version", "source_commit"):
        if approval_payload[field] != candidate_payload[field]:
            raise FreezeError(
                f"freeze approval {field} does not match candidate"
            )

    expected_values = {
        "candidate_id": candidate_payload["candidate_id"],
        "release_version": candidate_payload["release_version"],
        "source_commit": candidate_payload["source_commit"],
        "approver": approval_payload["approver"],
        "approved_at": approval_payload["approved_at"],
    }
    for field, expected in expected_values.items():
        if payload[field] != expected:
            raise FreezeError(f"freeze seal {field} mismatch")

    core = dict(payload)
    supplied_id = _nonempty_string(core.pop("freeze_id"), "freeze_id")
    expected_id = "freeze_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    if supplied_id != expected_id:
        raise FreezeError("freeze seal ID mismatch")

    return {
        "status": "accepted",
        "accepted": True,
        "freeze_id": supplied_id,
        "reason_codes": [
            "FREEZE_CANDIDATE_RECOMPUTED",
            "EXPLICIT_APPROVAL_BOUND",
            "FREEZE_SEAL_RECOMPUTED",
        ],
        "may_freeze": True,
        "approval_authentication": payload["approval_authentication"],
    }
