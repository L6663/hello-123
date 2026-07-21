"""Phase 8 release-manifest, reproducible-build, and explicit freeze sealing.

The technical candidate gate never grants freeze authority by itself. A separate,
explicit operator approval is required to create a seal, and the seal records that
its approval identity is asserted rather than cryptographically authenticated.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

FREEZE_CANDIDATE_SCHEMA_VERSION = "tkr-freeze-candidate-v1"
FREEZE_SEAL_SCHEMA_VERSION = "tkr-freeze-seal-v1"
FREEZE_APPROVAL_SCHEMA_VERSION = "tkr-freeze-approval-v1"
REPRODUCIBLE_BUILD_SCHEMA_VERSION = "tkr-reproducible-build-v1"
REQUIRED_PYTHON_MINORS = ("3.10", "3.11", "3.12")
SINGLETON_ROLES = (
    "wheel",
    "release_manifest",
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
        digest = _nonempty_string(payload["sha256"], "artifact.sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise FreezeError("artifact.sha256 must be lowercase SHA-256")
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


def _records_from_specs(root: Path, artifact_specs: Sequence[tuple[str, str | Path]]) -> tuple[ArtifactRecord, ...]:
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
    allowed = set(SINGLETON_ROLES) | {"package_acceptance"}
    unknown = sorted(set(grouped) - allowed)
    if unknown:
        raise FreezeError(f"unsupported artifact roles: {unknown}")
    return grouped


def _single_path(root: Path, grouped: Mapping[str, Sequence[ArtifactRecord]], role: str) -> Path:
    return _resolve_under_root(root, grouped[role][0].path)


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
    release_report = _load_json_object(
        _single_path(root, grouped, "release_report"), "release report"
    )
    release_verification = _load_json_object(
        _single_path(root, grouped, "release_verification"), "release verification"
    )
    reproducible = _load_json_object(
        _single_path(root, grouped, "reproducible_build_report"),
        "reproducible build report",
    )

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

    _bool_is(release_verification, "accepted", True, "release verification")
    if release_verification.get("status") != "accepted":
        raise FreezeError("release verification status must be accepted")
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
    build_count = reproducible.get("build_count")
    if not isinstance(build_count, int) or isinstance(build_count, bool) or build_count < 2:
        raise FreezeError("reproducible build report requires at least two builds")
    if reproducible.get("wheel_sha256") != wheel_sha256:
        raise FreezeError("reproducible build wheel SHA-256 mismatch")
    build_hashes = reproducible.get("build_sha256")
    if not isinstance(build_hashes, list) or len(build_hashes) < 2:
        raise FreezeError("reproducible build report build_sha256 must list at least two builds")
    if any(item != wheel_sha256 for item in build_hashes):
        raise FreezeError("reproducible builds are not byte-identical")

    return {
        "release_report_id": report_id,
        "gold_case_count": release_manifest["case_count"],
        "package_python_minors": sorted(package_python_minors),
        "wheel_name": next(iter(package_wheel_names)),
        "wheel_sha256": wheel_sha256,
        "reproducible_build_count": build_count,
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
        raise FreezeError("source_commit must be a lowercase 40-character Git SHA")
    if not isinstance(source_date_epoch, int) or isinstance(source_date_epoch, bool) or source_date_epoch < 0:
        raise FreezeError("source_date_epoch must be a non-negative integer")

    records = _records_from_specs(root_path, artifact_specs)
    evidence = _validate_release_evidence(root_path, records, release_version=version)
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
    output = Path(output_path) if output_path is not None else root_path / "freeze-candidate.json"
    _write_json(output, payload)
    return payload


def verify_freeze_candidate(
    candidate_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Recompute all artifact hashes and technical release gates."""

    path = Path(candidate_path).resolve()
    payload = _load_json_object(path, "freeze candidate")
    expected_keys = {
        "schema_version", "release_version", "source_commit", "source_date_epoch",
        "artifacts", "evidence", "technical_gate_passed", "requires_explicit_approval",
        "may_freeze", "status", "candidate_id",
    }
    _require_exact_keys(payload, expected_keys, "freeze candidate")
    if payload["schema_version"] != FREEZE_CANDIDATE_SCHEMA_VERSION:
        raise FreezeError("unsupported freeze candidate schema")
    _bool_is(payload, "technical_gate_passed", True, "freeze candidate")
    _bool_is(payload, "requires_explicit_approval", True, "freeze candidate")
    _bool_is(payload, "may_freeze", False, "freeze candidate")
    if payload["status"] != "candidate":
        raise FreezeError("freeze candidate status must be candidate")

    release_version = _nonempty_string(payload["release_version"], "release_version")
    source_commit = _nonempty_string(payload["source_commit"], "source_commit")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise FreezeError("source_commit must be a lowercase 40-character Git SHA")
    source_date_epoch = payload["source_date_epoch"]
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise FreezeError("source_date_epoch must be a non-negative integer")

    root_path = Path(root).resolve() if root is not None else path.parent.resolve()
    raw_records = payload["artifacts"]
    if not isinstance(raw_records, list) or not raw_records:
        raise FreezeError("freeze candidate artifacts must be a non-empty list")
    records = tuple(ArtifactRecord.from_dict(item) for item in raw_records if isinstance(item, dict))
    if len(records) != len(raw_records):
        raise FreezeError("every freeze candidate artifact must be an object")
    if tuple(sorted(records, key=lambda item: (item.role, item.path))) != records:
        raise FreezeError("freeze candidate artifacts must be canonically sorted")
    for record in records:
        artifact = _resolve_under_root(root_path, record.path)
        if not artifact.is_file():
            raise FreezeError(f"missing freeze artifact: {record.path}")
        if artifact.stat().st_size != record.size_bytes:
            raise FreezeError(f"freeze artifact size mismatch: {record.path}")
        if _sha256_path(artifact) != record.sha256:
            raise FreezeError(f"freeze artifact SHA-256 mismatch: {record.path}")

    evidence = _validate_release_evidence(root_path, records, release_version=release_version)
    if payload["evidence"] != evidence:
        raise FreezeError("freeze candidate evidence summary mismatch")
    core = dict(payload)
    supplied_id = _nonempty_string(core.pop("candidate_id"), "candidate_id")
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
            "RELEASE_GATE_RECOMPUTED",
            "EXPLICIT_APPROVAL_STILL_REQUIRED",
        ],
        "may_freeze": False,
    }


def _load_approval(path: Path) -> dict[str, object]:
    payload = _load_json_object(path, "freeze approval")
    _require_exact_keys(
        payload,
        {
            "schema_version", "candidate_id", "release_version", "source_commit",
            "approver", "decision", "statement", "approved_at",
        },
        "freeze approval",
    )
    if payload["schema_version"] != FREEZE_APPROVAL_SCHEMA_VERSION:
        raise FreezeError("unsupported freeze approval schema")
    if payload["decision"] != "approve":
        raise FreezeError("freeze approval decision must be approve")
    for key in ("candidate_id", "release_version", "source_commit", "approver", "statement", "approved_at"):
        _nonempty_string(payload[key], f"freeze approval.{key}")
    return payload


def seal_freeze_candidate(
    candidate_path: str | Path,
    approval_path: str | Path,
    output_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Create a final seal only after an explicit operator approval record exists."""

    candidate = Path(candidate_path).resolve()
    approval = Path(approval_path).resolve()
    verification = verify_freeze_candidate(candidate, root=root)
    candidate_payload = _load_json_object(candidate, "freeze candidate")
    approval_payload = _load_approval(approval)
    for field in ("candidate_id", "release_version", "source_commit"):
        if approval_payload[field] != candidate_payload[field]:
            raise FreezeError(f"freeze approval {field} does not match candidate")

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
        "approval_authentication": "operator_asserted_not_cryptographically_verified",
        "may_freeze": True,
        "status": "sealed",
    }
    freeze_id = "freeze_" + _sha256_bytes(_canonical_json(core).encode("utf-8"))[:24]
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
    """Verify a seal, its candidate, its approval, and every bound artifact."""

    seal = Path(seal_path).resolve()
    candidate = Path(candidate_path).resolve()
    approval = Path(approval_path).resolve()
    payload = _load_json_object(seal, "freeze seal")
    expected_keys = {
        "schema_version", "candidate_id", "candidate_sha256", "approval_sha256",
        "release_version", "source_commit", "approver", "approved_at",
        "technical_gate_passed", "approval_asserted", "approval_authentication",
        "may_freeze", "status", "freeze_id",
    }
    _require_exact_keys(payload, expected_keys, "freeze seal")
    if payload["schema_version"] != FREEZE_SEAL_SCHEMA_VERSION:
        raise FreezeError("unsupported freeze seal schema")
    _bool_is(payload, "technical_gate_passed", True, "freeze seal")
    _bool_is(payload, "approval_asserted", True, "freeze seal")
    _bool_is(payload, "may_freeze", True, "freeze seal")
    if payload["status"] != "sealed":
        raise FreezeError("freeze seal status must be sealed")
    if payload["approval_authentication"] != "operator_asserted_not_cryptographically_verified":
        raise FreezeError("unsupported approval authentication mode")

    verify_freeze_candidate(candidate, root=root)
    candidate_payload = _load_json_object(candidate, "freeze candidate")
    approval_payload = _load_approval(approval)
    if payload["candidate_sha256"] != _sha256_path(candidate):
        raise FreezeError("freeze seal candidate SHA-256 mismatch")
    if payload["approval_sha256"] != _sha256_path(approval):
        raise FreezeError("freeze seal approval SHA-256 mismatch")
    for field in ("candidate_id", "release_version", "source_commit", "approver", "approved_at"):
        source = candidate_payload if field in candidate_payload else approval_payload
        if field in ("approver", "approved_at"):
            source = approval_payload
        if payload[field] != source[field]:
            raise FreezeError(f"freeze seal {field} mismatch")
    if approval_payload["candidate_id"] != candidate_payload["candidate_id"]:
        raise FreezeError("freeze approval candidate_id mismatch")

    core = dict(payload)
    supplied_id = _nonempty_string(core.pop("freeze_id"), "freeze_id")
    expected_id = "freeze_" + _sha256_bytes(_canonical_json(core).encode("utf-8"))[:24]
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
