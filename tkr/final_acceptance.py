"""Stage 8 final productization and explicit product-acceptance sealing.

The module assembles a hash-bound technical acceptance candidate from an
independently verified Stage 7 release benchmark, a private-blind protocol
attestation, package/runtime checks, reproducible wheels, source provenance,
and product documentation. A technical candidate never grants acceptance or
release authority. Only a separate, explicit approval record can create an
acceptance seal, and even that seal does not authorize publication or freeze.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from .literary_benchmark import (
    LiteraryBenchmarkError,
    load_cases,
    read_report,
    verify_benchmark_report,
)
from .source_provenance import SourceProvenanceError, verify_source_provenance


FINAL_ACCEPTANCE_VERSION = "6.0.0-stage8-rc1"
CANDIDATE_SCHEMA_VERSION = "tkr-final-acceptance-candidate-v1"
APPROVAL_SCHEMA_VERSION = "tkr-final-acceptance-approval-v1"
SEAL_SCHEMA_VERSION = "tkr-final-acceptance-seal-v1"
VERIFICATION_SCHEMA_VERSION = "tkr-final-acceptance-verification-v1"
BLIND_ATTESTATION_SCHEMA_VERSION = "tkr-private-blind-attestation-v1"
PACKAGE_ACCEPTANCE_SCHEMA_VERSION = "tkr-package-acceptance-v2"
ENGINEERING_VALIDATION_SCHEMA_VERSION = "tkr-engineering-validation-v1"
REPRODUCIBLE_BUILD_SCHEMA_VERSION = "tkr-reproducible-build-v2"

REQUIRED_PYTHON_MINORS = ("3.10", "3.11", "3.12")
REQUIRED_CONSOLE_SCRIPTS = frozenset({
    "tkr-skill",
    "tkr-project",
    "tkr-literary",
    "tkr-evidence",
    "tkr-chapter",
    "tkr-event",
    "tkr-character",
    "tkr-reason",
    "tkr-notion",
    "tkr-literary-benchmark",
    "tkr-final-acceptance",
})
SINGLETON_ROLES = (
    "wheel",
    "skill_audit",
    "skill_doctor",
    "literary_cases",
    "literary_observations",
    "literary_report",
    "literary_verification",
    "blind_attestation",
    "engineering_validation",
    "reproducible_build_report",
    "source_bundle",
    "source_provenance",
    "project_status",
    "skill_contract",
    "readme",
)
MULTI_ROLES = frozenset({"package_acceptance", "reproducible_wheel"})
APPROVAL_STATEMENT_PREFIX = "I explicitly approve final product acceptance for "
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^6\.\d+\.\d+(?:rc\d+)?$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class FinalAcceptanceError(ValueError):
    """Raised when final product evidence is unsafe or inconsistent."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _safe_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FinalAcceptanceError(f"{label} must be a safe regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FinalAcceptanceError(f"cannot read {label}: {path}: {exc}") from exc


def _sha256_path(path: Path, label: str = "artifact") -> str:
    return _sha256_bytes(_safe_file(path, label))


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    raw = _safe_file(path, label)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FinalAcceptanceError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FinalAcceptanceError(f"{label} must be a JSON object: {path}")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise FinalAcceptanceError(
            f"{label} keys mismatch; missing={missing}; extra={extra}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinalAcceptanceError(f"{label} must be non-empty text")
    return value.strip()


def _sha256(value: object, label: str) -> str:
    text = _text(value, label)
    if not _HEX64.fullmatch(text):
        raise FinalAcceptanceError(f"{label} must be lowercase SHA-256")
    return text


def _commit(value: object, label: str = "source_commit") -> str:
    text = _text(value, label)
    if not _HEX40.fullmatch(text):
        raise FinalAcceptanceError(f"{label} must be a lowercase 40-character Git SHA")
    return text


def _version(value: object) -> str:
    text = _text(value, "release_version")
    if not _VERSION.fullmatch(text):
        raise FinalAcceptanceError(
            "release_version must be a v6 release-candidate or final version, "
            "for example 6.0.0rc1 or 6.0.0"
        )
    return text


def _bool_is(
    payload: Mapping[str, object],
    key: str,
    expected: bool,
    label: str,
) -> None:
    if payload.get(key) is not expected:
        raise FinalAcceptanceError(f"{label}.{key} must be {expected}")


def _python_minor(value: object) -> str:
    text = _text(value, "package_acceptance.python")
    match = re.match(r"^(\d+\.\d+)", text)
    if not match:
        raise FinalAcceptanceError(f"cannot determine Python minor from {text!r}")
    return match.group(1)


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    role: str
    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ArtifactRecord":
        _require_exact_keys(
            payload, {"role", "path", "sha256", "size_bytes"}, "artifact"
        )
        role = _text(payload.get("role"), "artifact.role")
        path = _text(payload.get("path"), "artifact.path")
        digest = _sha256(payload.get("sha256"), "artifact.sha256")
        size = payload.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise FinalAcceptanceError(
                "artifact.size_bytes must be a non-negative integer"
            )
        return cls(role=role, path=path, sha256=digest, size_bytes=size)


def _resolve_under_root(root: Path, stored_path: str) -> Path:
    relative = Path(stored_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise FinalAcceptanceError(f"artifact path is unsafe: {stored_path}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FinalAcceptanceError(f"artifact escapes root: {stored_path}") from exc
    return candidate


def _records_from_specs(
    root: Path,
    artifact_specs: Sequence[tuple[str, str | Path]],
) -> tuple[ArtifactRecord, ...]:
    records: list[ArtifactRecord] = []
    seen_paths: set[str] = set()
    for raw_role, raw_path in artifact_specs:
        role = _text(raw_role, "artifact role")
        if role not in set(SINGLETON_ROLES) | MULTI_ROLES:
            raise FinalAcceptanceError(f"unsupported artifact role: {role}")
        path = Path(raw_path)
        if path.is_symlink() or not path.is_file():
            raise FinalAcceptanceError(f"artifact is not a safe regular file: {path}")
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise FinalAcceptanceError(f"artifact is outside acceptance root: {path}") from exc
        if relative in seen_paths:
            raise FinalAcceptanceError(
                f"artifact path is declared more than once: {relative}"
            )
        seen_paths.add(relative)
        records.append(
            ArtifactRecord(
                role=role,
                path=relative,
                sha256=_sha256_path(resolved),
                size_bytes=resolved.stat().st_size,
            )
        )
    if not records:
        raise FinalAcceptanceError("at least one artifact is required")
    return tuple(sorted(records, key=lambda item: (item.role, item.path)))


def _group_records(
    records: Sequence[ArtifactRecord],
) -> dict[str, list[ArtifactRecord]]:
    grouped: dict[str, list[ArtifactRecord]] = {}
    for record in records:
        grouped.setdefault(record.role, []).append(record)
    for role in SINGLETON_ROLES:
        count = len(grouped.get(role, []))
        if count != 1:
            raise FinalAcceptanceError(
                f"exactly one {role} artifact is required; found {count}"
            )
    package_count = len(grouped.get("package_acceptance", []))
    if package_count != len(REQUIRED_PYTHON_MINORS):
        raise FinalAcceptanceError(
            "exactly three package_acceptance artifacts are required "
            "for Python 3.10, 3.11, and 3.12"
        )
    if len(grouped.get("reproducible_wheel", [])) < 2:
        raise FinalAcceptanceError(
            "at least two reproducible_wheel artifacts are required"
        )
    unknown = sorted(set(grouped) - set(SINGLETON_ROLES) - MULTI_ROLES)
    if unknown:
        raise FinalAcceptanceError(f"unsupported artifact roles: {unknown}")
    return grouped


def _single_path(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
    role: str,
) -> Path:
    return _resolve_under_root(root, grouped[role][0].path)


def _validate_skill_reports(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
) -> dict[str, object]:
    audit = _load_json_object(
        _single_path(root, grouped, "skill_audit"), "Skill audit report"
    )
    doctor = _load_json_object(
        _single_path(root, grouped, "skill_doctor"), "Skill doctor report"
    )
    for label, payload in (("Skill audit report", audit), ("Skill doctor report", doctor)):
        _bool_is(payload, "passed", True, label)
        _bool_is(payload, "project_acceptance_performed", False, label)
        _bool_is(payload, "may_accept_project", False, label)
        _bool_is(payload, "release_candidate", False, label)
        _bool_is(payload, "may_freeze", False, label)
        if payload.get("audit_version") != "6.0.0-stage8":
            raise FinalAcceptanceError(
                f"{label}.audit_version must be 6.0.0-stage8"
            )
    if audit.get("findings") != [] or audit.get("finding_count") != 0:
        raise FinalAcceptanceError("Skill audit must contain zero findings")
    checks = doctor.get("checks")
    if not isinstance(checks, list) or not checks:
        raise FinalAcceptanceError("Skill doctor checks must be a non-empty array")
    if any(
        not isinstance(item, dict) or item.get("status") != "passed"
        for item in checks
    ):
        raise FinalAcceptanceError("every Skill doctor check must pass")
    return {
        "skill_audit_passed": True,
        "skill_doctor_passed": True,
        "skill_audit_version": "6.0.0-stage8",
    }


def _validate_benchmark(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
) -> tuple[dict[str, object], tuple[str, ...]]:
    cases_path = _single_path(root, grouped, "literary_cases")
    observations_path = _single_path(root, grouped, "literary_observations")
    report_path = _single_path(root, grouped, "literary_report")
    supplied_verification_path = _single_path(
        root, grouped, "literary_verification"
    )
    try:
        cases, _, _ = load_cases(cases_path)
        report = read_report(report_path)
        verification = verify_benchmark_report(
            cases_path, observations_path, report
        )
    except LiteraryBenchmarkError as exc:
        raise FinalAcceptanceError(
            f"Stage 7 literary benchmark verification failed: {exc}"
        ) from exc
    if not verification.valid:
        raise FinalAcceptanceError(
            "Stage 7 literary benchmark recomputation failed: "
            + ",".join(verification.reason_codes)
        )
    supplied_verification = _load_json_object(
        supplied_verification_path, "literary benchmark verification"
    )
    if supplied_verification != verification.to_dict():
        raise FinalAcceptanceError(
            "literary benchmark verification does not match recomputation"
        )
    if report.get("policy_profile") != "release":
        raise FinalAcceptanceError("literary benchmark must use the release profile")
    _bool_is(report, "passed", True, "literary benchmark report")
    if report.get("blockers") != []:
        raise FinalAcceptanceError("literary benchmark blockers must be empty")
    case_count = report.get("case_count")
    if (
        not isinstance(case_count, int)
        or isinstance(case_count, bool)
        or case_count < 120
        or case_count != len(cases)
    ):
        raise FinalAcceptanceError(
            "literary benchmark must contain at least 120 bound cases"
        )
    for key in (
        "project_acceptance_performed",
        "may_accept_project",
        "may_release",
        "may_freeze",
    ):
        _bool_is(report, key, False, "literary benchmark report")
    corpus_sha256s = tuple(sorted({
        digest
        for case in cases
        for digest in case.source_sha256s
    }))
    if not corpus_sha256s:
        raise FinalAcceptanceError(
            "literary benchmark Gold cases must bind source SHA-256 identities"
        )
    report_id = _text(report.get("report_id"), "literary benchmark report_id")
    return {
        "literary_report_id": report_id,
        "literary_case_count": case_count,
        "literary_benchmark_recomputed": True,
        "literary_benchmark_verification_id": verification.expected_report_id,
    }, corpus_sha256s


def _validate_blind_attestation(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
    corpus_sha256s: Sequence[str],
) -> dict[str, object]:
    path = _single_path(root, grouped, "blind_attestation")
    payload = _load_json_object(path, "private blind attestation")
    expected_keys = {
        "schema_version",
        "protocol_id",
        "corpus_sha256s",
        "cases_file_sha256",
        "observations_file_sha256",
        "report_file_sha256",
        "gold_locked_before_run",
        "gold_hidden_from_answer_system",
        "observations_generated_without_gold_access",
        "corpus_not_used_for_v6_development",
        "evaluator_id",
        "gold_custodian_id",
        "reviewer_ids",
        "status",
        "statement",
        "attested_at_utc",
        "project_acceptance_performed",
        "may_release",
        "may_freeze",
    }
    _require_exact_keys(payload, expected_keys, "private blind attestation")
    if payload.get("schema_version") != BLIND_ATTESTATION_SCHEMA_VERSION:
        raise FinalAcceptanceError("unsupported private blind attestation schema")
    _text(payload.get("protocol_id"), "private blind attestation.protocol_id")
    supplied_corpus = payload.get("corpus_sha256s")
    if not isinstance(supplied_corpus, list) or not supplied_corpus:
        raise FinalAcceptanceError(
            "private blind attestation.corpus_sha256s must be non-empty"
        )
    normalized = tuple(sorted({
        _sha256(item, "private blind attestation.corpus_sha256s")
        for item in supplied_corpus
    }))
    if len(normalized) != len(supplied_corpus):
        raise FinalAcceptanceError(
            "private blind attestation corpus hashes must be unique"
        )
    if normalized != tuple(sorted(corpus_sha256s)):
        raise FinalAcceptanceError(
            "private blind attestation corpus hashes do not match Gold cases"
        )
    hash_bindings = {
        "cases_file_sha256": grouped["literary_cases"][0].sha256,
        "observations_file_sha256": grouped["literary_observations"][0].sha256,
        "report_file_sha256": grouped["literary_report"][0].sha256,
    }
    for key, expected in hash_bindings.items():
        if _sha256(payload.get(key), f"private blind attestation.{key}") != expected:
            raise FinalAcceptanceError(
                f"private blind attestation {key} mismatch"
            )
    for key in (
        "gold_locked_before_run",
        "gold_hidden_from_answer_system",
        "observations_generated_without_gold_access",
        "corpus_not_used_for_v6_development",
    ):
        _bool_is(payload, key, True, "private blind attestation")
    evaluator = _text(
        payload.get("evaluator_id"), "private blind attestation.evaluator_id"
    )
    custodian = _text(
        payload.get("gold_custodian_id"),
        "private blind attestation.gold_custodian_id",
    )
    reviewers = payload.get("reviewer_ids")
    if not isinstance(reviewers, list) or len(reviewers) < 2:
        raise FinalAcceptanceError(
            "private blind attestation requires at least two reviewers"
        )
    reviewer_ids = tuple(
        _text(item, "private blind attestation.reviewer_ids")
        for item in reviewers
    )
    if len(reviewer_ids) != len(set(reviewer_ids)):
        raise FinalAcceptanceError(
            "private blind attestation reviewer IDs must be unique"
        )
    actors = (evaluator, custodian, *reviewer_ids)
    if len(set(actors)) != len(actors):
        raise FinalAcceptanceError(
            "evaluator, Gold custodian, and reviewers must be independent"
        )
    if payload.get("status") != "approved":
        raise FinalAcceptanceError(
            "private blind attestation.status must be approved"
        )
    _text(payload.get("statement"), "private blind attestation.statement")
    attested_at = _text(
        payload.get("attested_at_utc"),
        "private blind attestation.attested_at_utc",
    )
    if not _UTC.fullmatch(attested_at):
        raise FinalAcceptanceError(
            "private blind attestation.attested_at_utc must be UTC ISO-8601"
        )
    _bool_is(
        payload,
        "project_acceptance_performed",
        False,
        "private blind attestation",
    )
    _bool_is(payload, "may_release", False, "private blind attestation")
    _bool_is(payload, "may_freeze", False, "private blind attestation")
    return {
        "private_blind_protocol_attested": True,
        "private_blind_protocol_id": payload["protocol_id"],
        "private_blind_reviewer_count": len(reviewer_ids),
        "private_corpus_sha256s": list(normalized),
    }


def _validate_package_matrix(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
    *,
    release_version: str,
) -> dict[str, object]:
    versions: set[str] = set()
    minors: list[str] = []
    wheel_hashes: set[str] = set()
    wheel_names: set[str] = set()
    for record in grouped["package_acceptance"]:
        payload = _load_json_object(
            _resolve_under_root(root, record.path),
            f"package acceptance {record.path}",
        )
        expected_keys = {
            "schema_version",
            "accepted",
            "failures",
            "python",
            "version",
            "wheel_name",
            "wheel_sha256",
            "installed_cli",
            "skill_audit_passed",
            "skill_doctor_passed",
        }
        _require_exact_keys(payload, expected_keys, "package acceptance")
        if payload.get("schema_version") != PACKAGE_ACCEPTANCE_SCHEMA_VERSION:
            raise FinalAcceptanceError("unsupported package acceptance schema")
        _bool_is(payload, "accepted", True, "package acceptance")
        if payload.get("failures") != []:
            raise FinalAcceptanceError(
                f"package acceptance failures must be empty: {record.path}"
            )
        versions.add(_text(payload.get("version"), "package acceptance.version"))
        minors.append(_python_minor(payload.get("python")))
        wheel_hashes.add(
            _sha256(
                payload.get("wheel_sha256"),
                "package acceptance.wheel_sha256",
            )
        )
        wheel_names.add(
            _text(payload.get("wheel_name"), "package acceptance.wheel_name")
        )
        installed = payload.get("installed_cli")
        if not isinstance(installed, list):
            raise FinalAcceptanceError(
                "package acceptance.installed_cli must be an array"
            )
        installed_set = {
            _text(item, "package acceptance.installed_cli")
            for item in installed
        }
        missing_cli = sorted(REQUIRED_CONSOLE_SCRIPTS - installed_set)
        if missing_cli:
            raise FinalAcceptanceError(
                f"package acceptance is missing console scripts: {missing_cli}"
            )
        _bool_is(
            payload, "skill_audit_passed", True, "package acceptance"
        )
        _bool_is(
            payload, "skill_doctor_passed", True, "package acceptance"
        )
    if versions != {release_version}:
        raise FinalAcceptanceError(
            f"package acceptance versions do not match {release_version}: "
            f"{sorted(versions)}"
        )
    if sorted(minors) != sorted(REQUIRED_PYTHON_MINORS):
        raise FinalAcceptanceError(
            f"package acceptance Python matrix mismatch: {sorted(minors)}"
        )
    if len(wheel_hashes) != 1 or len(wheel_names) != 1:
        raise FinalAcceptanceError(
            "package acceptance reports disagree on wheel identity"
        )
    wheel_hash = next(iter(wheel_hashes))
    wheel_name = next(iter(wheel_names))
    wheel_record = grouped["wheel"][0]
    if wheel_record.sha256 != wheel_hash:
        raise FinalAcceptanceError(
            "bound wheel bytes do not match package acceptance"
        )
    if Path(wheel_record.path).name != wheel_name:
        raise FinalAcceptanceError(
            "bound wheel filename does not match package acceptance"
        )
    return {
        "package_python_minors": sorted(minors),
        "wheel_name": wheel_name,
        "wheel_sha256": wheel_hash,
        "required_console_script_count": len(REQUIRED_CONSOLE_SCRIPTS),
    }


def _validate_reproducible_build(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
    *,
    release_version: str,
    source_date_epoch: int,
    wheel_name: str,
    wheel_sha256: str,
) -> dict[str, object]:
    payload = _load_json_object(
        _single_path(root, grouped, "reproducible_build_report"),
        "reproducible build report",
    )
    expected_keys = {
        "schema_version",
        "accepted",
        "version",
        "source_date_epoch",
        "build_count",
        "wheel_name",
        "wheel_sha256",
        "build_sha256",
    }
    _require_exact_keys(payload, expected_keys, "reproducible build report")
    if payload.get("schema_version") != REPRODUCIBLE_BUILD_SCHEMA_VERSION:
        raise FinalAcceptanceError("unsupported reproducible build report schema")
    _bool_is(payload, "accepted", True, "reproducible build report")
    if payload.get("version") != release_version:
        raise FinalAcceptanceError(
            "reproducible build version does not match acceptance version"
        )
    if payload.get("source_date_epoch") != source_date_epoch:
        raise FinalAcceptanceError(
            "reproducible build SOURCE_DATE_EPOCH mismatch"
        )
    records = grouped["reproducible_wheel"]
    build_count = payload.get("build_count")
    if (
        not isinstance(build_count, int)
        or isinstance(build_count, bool)
        or build_count != len(records)
        or build_count < 2
    ):
        raise FinalAcceptanceError(
            "reproducible build count does not match bound wheels"
        )
    if payload.get("wheel_name") != wheel_name:
        raise FinalAcceptanceError("reproducible build wheel name mismatch")
    if payload.get("wheel_sha256") != wheel_sha256:
        raise FinalAcceptanceError("reproducible build wheel SHA-256 mismatch")
    actual_hashes = [record.sha256 for record in records]
    if payload.get("build_sha256") != actual_hashes:
        raise FinalAcceptanceError(
            "reproducible build hashes do not match bound wheels"
        )
    if any(value != wheel_sha256 for value in actual_hashes):
        raise FinalAcceptanceError(
            "reproducible wheel artifacts are not byte-identical"
        )
    return {
        "reproducible_build_count": build_count,
        "reproducible_wheels_verified": True,
    }


def _validate_engineering_validation(
    root: Path,
    grouped: Mapping[str, Sequence[ArtifactRecord]],
    *,
    source_commit: str,
) -> dict[str, object]:
    payload = _load_json_object(
        _single_path(root, grouped, "engineering_validation"),
        "engineering validation",
    )
    expected_keys = {
        "schema_version",
        "source_commit",
        "workflow_run_id",
        "conclusion",
        "focused_test_count",
        "full_repository_regression",
        "schema_contracts",
        "cli_contracts",
        "package_matrix",
        "wheel_reproducible",
        "project_acceptance_performed",
        "may_release",
        "may_freeze",
    }
    _require_exact_keys(payload, expected_keys, "engineering validation")
    if payload.get("schema_version") != ENGINEERING_VALIDATION_SCHEMA_VERSION:
        raise FinalAcceptanceError("unsupported engineering validation schema")
    if _commit(payload.get("source_commit"), "engineering source_commit") != source_commit:
        raise FinalAcceptanceError(
            "engineering validation source_commit mismatch"
        )
    run_id = payload.get("workflow_run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise FinalAcceptanceError(
            "engineering validation.workflow_run_id must be positive"
        )
    if payload.get("conclusion") != "success":
        raise FinalAcceptanceError(
            "engineering validation conclusion must be success"
        )
    focused = payload.get("focused_test_count")
    if not isinstance(focused, int) or isinstance(focused, bool) or focused < 1:
        raise FinalAcceptanceError(
            "engineering validation focused_test_count must be positive"
        )
    for key in (
        "full_repository_regression",
        "schema_contracts",
        "cli_contracts",
        "wheel_reproducible",
    ):
        _bool_is(payload, key, True, "engineering validation")
    matrix = payload.get("package_matrix")
    if not isinstance(matrix, list) or sorted(matrix) != sorted(REQUIRED_PYTHON_MINORS):
        raise FinalAcceptanceError(
            "engineering validation package_matrix mismatch"
        )
    _bool_is(
        payload,
        "project_acceptance_performed",
        False,
        "engineering validation",
    )
    _bool_is(payload, "may_release", False, "engineering validation")
    _bool_is(payload, "may_freeze", False, "engineering validation")
    return {
        "engineering_workflow_run_id": run_id,
        "engineering_focused_test_count": focused,
        "full_repository_regression_passed": True,
        "schema_and_cli_contracts_passed": True,
    }


def _validate_all(
    root: Path,
    records: Sequence[ArtifactRecord],
    *,
    release_version: str,
    source_commit: str,
    source_date_epoch: int,
) -> dict[str, object]:
    grouped = _group_records(records)
    evidence: dict[str, object] = {}
    evidence.update(_validate_skill_reports(root, grouped))
    benchmark, corpus_sha256s = _validate_benchmark(root, grouped)
    evidence.update(benchmark)
    evidence.update(
        _validate_blind_attestation(
            root, grouped, corpus_sha256s
        )
    )
    package = _validate_package_matrix(
        root, grouped, release_version=release_version
    )
    evidence.update(package)
    evidence.update(
        _validate_reproducible_build(
            root,
            grouped,
            release_version=release_version,
            source_date_epoch=source_date_epoch,
            wheel_name=str(package["wheel_name"]),
            wheel_sha256=str(package["wheel_sha256"]),
        )
    )
    evidence.update(
        _validate_engineering_validation(
            root, grouped, source_commit=source_commit
        )
    )
    try:
        source = verify_source_provenance(
            _single_path(root, grouped, "source_bundle"),
            _single_path(root, grouped, "source_provenance"),
            _single_path(root, grouped, "wheel"),
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
            release_version=release_version,
        )
    except SourceProvenanceError as exc:
        raise FinalAcceptanceError(
            f"source provenance verification failed: {exc}"
        ) from exc
    evidence.update({
        "source_commit_bound": source["source_commit"],
        "source_date_epoch_bound": source["source_date_epoch"],
        "source_bundle_sha256": source["source_bundle_sha256"],
        "source_runtime_file_count": source["runtime_file_count"],
        "source_runtime_files_sha256": source["runtime_files_sha256"],
        "source_provenance_verified": source["source_provenance_verified"],
        "product_documentation_bound": True,
        "technical_gate_passed": True,
    })
    return evidence


def _candidate_core(
    *,
    release_version: str,
    source_commit: str,
    source_date_epoch: int,
    records: Sequence[ArtifactRecord],
    evidence: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "acceptance_version": FINAL_ACCEPTANCE_VERSION,
        "release_version": release_version,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "artifacts": [record.to_dict() for record in records],
        "evidence": dict(evidence),
        "technical_gate_passed": True,
        "requires_explicit_approval": True,
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "release_candidate": False,
        "may_release": False,
        "may_freeze": False,
        "status": "candidate",
    }


def prepare_final_acceptance_candidate(
    root: str | Path,
    artifact_specs: Sequence[tuple[str, str | Path]],
    *,
    release_version: str,
    source_commit: str,
    source_date_epoch: int,
    output_path: str | Path | None = None,
) -> dict[str, object]:
    """Build a technical candidate that cannot approve or release itself."""
    root_path = Path(root).resolve()
    if root_path.is_symlink() or not root_path.is_dir():
        raise FinalAcceptanceError(
            f"acceptance root is not a safe directory: {root_path}"
        )
    version = _version(release_version)
    commit = _commit(source_commit)
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise FinalAcceptanceError(
            "source_date_epoch must be a non-negative integer"
        )
    records = _records_from_specs(root_path, artifact_specs)
    evidence = _validate_all(
        root_path,
        records,
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
    )
    core = _candidate_core(
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
        records=records,
        evidence=evidence,
    )
    candidate_id = "final_acceptance_candidate_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    payload = {**core, "candidate_id": candidate_id}
    output = (
        Path(output_path)
        if output_path is not None
        else root_path / "final-acceptance-candidate.json"
    )
    _write_json(output, payload)
    return payload


def _candidate_records(
    payload: Mapping[str, object],
) -> tuple[ArtifactRecord, ...]:
    raw = payload.get("artifacts")
    if not isinstance(raw, list) or not raw:
        raise FinalAcceptanceError(
            "final acceptance candidate artifacts must be non-empty"
        )
    records = tuple(
        ArtifactRecord.from_dict(item)
        for item in raw
        if isinstance(item, dict)
    )
    if len(records) != len(raw):
        raise FinalAcceptanceError(
            "every final acceptance artifact must be an object"
        )
    if tuple(sorted(records, key=lambda item: (item.role, item.path))) != records:
        raise FinalAcceptanceError(
            "final acceptance artifacts must be canonically sorted"
        )
    return records


def verify_final_acceptance_candidate(
    candidate_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Recompute every technical gate while preserving false authority flags."""
    path = Path(candidate_path).resolve()
    payload = _load_json_object(path, "final acceptance candidate")
    expected_keys = {
        "schema_version",
        "acceptance_version",
        "release_version",
        "source_commit",
        "source_date_epoch",
        "artifacts",
        "evidence",
        "technical_gate_passed",
        "requires_explicit_approval",
        "project_acceptance_performed",
        "may_accept_project",
        "release_candidate",
        "may_release",
        "may_freeze",
        "status",
        "candidate_id",
    }
    _require_exact_keys(payload, expected_keys, "final acceptance candidate")
    if payload.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise FinalAcceptanceError("unsupported final acceptance candidate schema")
    if payload.get("acceptance_version") != FINAL_ACCEPTANCE_VERSION:
        raise FinalAcceptanceError("final acceptance runtime version mismatch")
    version = _version(payload.get("release_version"))
    commit = _commit(payload.get("source_commit"))
    source_date_epoch = payload.get("source_date_epoch")
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise FinalAcceptanceError("invalid candidate source_date_epoch")
    _bool_is(payload, "technical_gate_passed", True, "candidate")
    _bool_is(payload, "requires_explicit_approval", True, "candidate")
    _bool_is(payload, "project_acceptance_performed", False, "candidate")
    _bool_is(payload, "may_accept_project", False, "candidate")
    _bool_is(payload, "release_candidate", False, "candidate")
    _bool_is(payload, "may_release", False, "candidate")
    _bool_is(payload, "may_freeze", False, "candidate")
    if payload.get("status") != "candidate":
        raise FinalAcceptanceError("candidate.status must be candidate")
    root_path = (
        Path(root).resolve() if root is not None else path.parent.resolve()
    )
    if root_path.is_symlink() or not root_path.is_dir():
        raise FinalAcceptanceError("candidate root is unsafe")
    records = _candidate_records(payload)
    for record in records:
        artifact = _resolve_under_root(root_path, record.path)
        if artifact.is_symlink() or not artifact.is_file():
            raise FinalAcceptanceError(
                f"missing or unsafe acceptance artifact: {record.path}"
            )
        if artifact.stat().st_size != record.size_bytes:
            raise FinalAcceptanceError(
                f"acceptance artifact size mismatch: {record.path}"
            )
        if _sha256_path(artifact) != record.sha256:
            raise FinalAcceptanceError(
                f"acceptance artifact SHA-256 mismatch: {record.path}"
            )
    evidence = _validate_all(
        root_path,
        records,
        release_version=version,
        source_commit=commit,
        source_date_epoch=source_date_epoch,
    )
    if payload.get("evidence") != evidence:
        raise FinalAcceptanceError(
            "final acceptance candidate evidence summary mismatch"
        )
    core = dict(payload)
    supplied_id = _text(core.pop("candidate_id"), "candidate_id")
    expected_id = "final_acceptance_candidate_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    if supplied_id != expected_id:
        raise FinalAcceptanceError("final acceptance candidate ID mismatch")
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "status": "verified",
        "valid": True,
        "candidate_id": supplied_id,
        "seal_id": "",
        "reason_codes": [
            "ALL_ARTIFACT_HASHES_RECOMPUTED",
            "LITERARY_RELEASE_BENCHMARK_RECOMPUTED",
            "PRIVATE_BLIND_PROTOCOL_ATTESTATION_BOUND",
            "PACKAGE_MATRIX_RECOMPUTED",
            "REPRODUCIBLE_WHEELS_REHASHED",
            "SOURCE_PROVENANCE_RECOMPUTED",
            "EXPLICIT_APPROVAL_STILL_REQUIRED",
        ],
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "release_candidate": False,
        "may_release": False,
        "may_freeze": False,
    }


def _load_approval(path: Path) -> dict[str, object]:
    payload = _load_json_object(path, "final acceptance approval")
    expected_keys = {
        "schema_version",
        "candidate_id",
        "release_version",
        "source_commit",
        "approver",
        "decision",
        "statement",
        "approved_at_utc",
    }
    _require_exact_keys(payload, expected_keys, "final acceptance approval")
    if payload.get("schema_version") != APPROVAL_SCHEMA_VERSION:
        raise FinalAcceptanceError("unsupported final acceptance approval schema")
    candidate_id = _text(payload.get("candidate_id"), "approval.candidate_id")
    _version(payload.get("release_version"))
    _commit(payload.get("source_commit"), "approval.source_commit")
    _text(payload.get("approver"), "approval.approver")
    if payload.get("decision") != "approve_final_product_acceptance":
        raise FinalAcceptanceError(
            "approval.decision must be approve_final_product_acceptance"
        )
    expected_statement = APPROVAL_STATEMENT_PREFIX + candidate_id + "."
    if payload.get("statement") != expected_statement:
        raise FinalAcceptanceError(
            "approval.statement must explicitly name the candidate ID"
        )
    approved_at = _text(payload.get("approved_at_utc"), "approval.approved_at_utc")
    if not _UTC.fullmatch(approved_at):
        raise FinalAcceptanceError(
            "approval.approved_at_utc must be UTC ISO-8601"
        )
    return payload


def seal_final_acceptance(
    candidate_path: str | Path,
    approval_path: str | Path,
    output_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Seal project acceptance after a separate explicit approval record exists."""
    candidate = Path(candidate_path).resolve()
    approval = Path(approval_path).resolve()
    verification = verify_final_acceptance_candidate(candidate, root=root)
    candidate_payload = _load_json_object(candidate, "final acceptance candidate")
    approval_payload = _load_approval(approval)
    for key in ("candidate_id", "release_version", "source_commit"):
        if approval_payload.get(key) != candidate_payload.get(key):
            raise FinalAcceptanceError(
                f"approval {key} does not match candidate"
            )
    core = {
        "schema_version": SEAL_SCHEMA_VERSION,
        "candidate_id": candidate_payload["candidate_id"],
        "release_version": candidate_payload["release_version"],
        "source_commit": candidate_payload["source_commit"],
        "candidate_sha256": _sha256_path(candidate, "candidate"),
        "approval_sha256": _sha256_path(approval, "approval"),
        "approver": approval_payload["approver"],
        "approved_at_utc": approval_payload["approved_at_utc"],
        "verification_reason_codes": verification["reason_codes"],
        "project_acceptance_performed": True,
        "may_accept_project": True,
        "release_candidate": True,
        "may_release": False,
        "may_freeze": False,
        "status": "accepted",
    }
    seal_id = "final_acceptance_seal_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    payload = {**core, "seal_id": seal_id}
    _write_json(Path(output_path), payload)
    return payload


def verify_final_acceptance_seal(
    seal_path: str | Path,
    candidate_path: str | Path,
    approval_path: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, object]:
    """Recompute the technical candidate and explicit approval seal."""
    seal = Path(seal_path).resolve()
    candidate = Path(candidate_path).resolve()
    approval = Path(approval_path).resolve()
    verification = verify_final_acceptance_candidate(candidate, root=root)
    candidate_payload = _load_json_object(candidate, "final acceptance candidate")
    approval_payload = _load_approval(approval)
    payload = _load_json_object(seal, "final acceptance seal")
    for key in ("candidate_id", "release_version", "source_commit"):
        if approval_payload.get(key) != candidate_payload.get(key):
            raise FinalAcceptanceError(
                f"approval {key} does not match candidate"
            )
    expected_keys = {
        "schema_version",
        "candidate_id",
        "release_version",
        "source_commit",
        "candidate_sha256",
        "approval_sha256",
        "approver",
        "approved_at_utc",
        "verification_reason_codes",
        "project_acceptance_performed",
        "may_accept_project",
        "release_candidate",
        "may_release",
        "may_freeze",
        "status",
        "seal_id",
    }
    _require_exact_keys(payload, expected_keys, "final acceptance seal")
    if payload.get("schema_version") != SEAL_SCHEMA_VERSION:
        raise FinalAcceptanceError("unsupported final acceptance seal schema")
    if payload.get("candidate_id") != candidate_payload.get("candidate_id"):
        raise FinalAcceptanceError("seal candidate_id mismatch")
    for key in ("release_version", "source_commit", "approver", "approved_at_utc"):
        expected = (
            candidate_payload[key]
            if key in {"release_version", "source_commit"}
            else approval_payload[key]
        )
        if payload.get(key) != expected:
            raise FinalAcceptanceError(f"seal {key} mismatch")
    if payload.get("candidate_sha256") != _sha256_path(candidate, "candidate"):
        raise FinalAcceptanceError("seal candidate SHA-256 mismatch")
    if payload.get("approval_sha256") != _sha256_path(approval, "approval"):
        raise FinalAcceptanceError("seal approval SHA-256 mismatch")
    if payload.get("verification_reason_codes") != verification["reason_codes"]:
        raise FinalAcceptanceError("seal verification reason codes mismatch")
    _bool_is(payload, "project_acceptance_performed", True, "seal")
    _bool_is(payload, "may_accept_project", True, "seal")
    _bool_is(payload, "release_candidate", True, "seal")
    _bool_is(payload, "may_release", False, "seal")
    _bool_is(payload, "may_freeze", False, "seal")
    if payload.get("status") != "accepted":
        raise FinalAcceptanceError("seal.status must be accepted")
    core = dict(payload)
    supplied_id = _text(core.pop("seal_id"), "seal_id")
    expected_id = "final_acceptance_seal_" + _sha256_bytes(
        _canonical_json(core).encode("utf-8")
    )[:24]
    if supplied_id != expected_id:
        raise FinalAcceptanceError("final acceptance seal ID mismatch")
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "status": "verified",
        "valid": True,
        "candidate_id": candidate_payload["candidate_id"],
        "seal_id": supplied_id,
        "reason_codes": [
            "TECHNICAL_CANDIDATE_RECOMPUTED",
            "EXPLICIT_APPROVAL_RECOMPUTED",
            "FINAL_ACCEPTANCE_SEAL_RECOMPUTED",
            "RELEASE_APPROVAL_STILL_REQUIRED",
        ],
        "project_acceptance_performed": True,
        "may_accept_project": True,
        "release_candidate": True,
        "may_release": False,
        "may_freeze": False,
    }


__all__ = [
    "APPROVAL_SCHEMA_VERSION",
    "APPROVAL_STATEMENT_PREFIX",
    "ArtifactRecord",
    "BLIND_ATTESTATION_SCHEMA_VERSION",
    "CANDIDATE_SCHEMA_VERSION",
    "ENGINEERING_VALIDATION_SCHEMA_VERSION",
    "FINAL_ACCEPTANCE_VERSION",
    "FinalAcceptanceError",
    "PACKAGE_ACCEPTANCE_SCHEMA_VERSION",
    "REPRODUCIBLE_BUILD_SCHEMA_VERSION",
    "REQUIRED_CONSOLE_SCRIPTS",
    "REQUIRED_PYTHON_MINORS",
    "SEAL_SCHEMA_VERSION",
    "VERIFICATION_SCHEMA_VERSION",
    "prepare_final_acceptance_candidate",
    "seal_final_acceptance",
    "verify_final_acceptance_candidate",
    "verify_final_acceptance_seal",
]
