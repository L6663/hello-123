"""Stage 5 strict filesystem and manifest boundary for immutable projects."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Mapping

from .engineering import EngineeringBuildResult, EngineeringProfile, build_engineered_project
from .knowledge_models import (
    KNOWLEDGE_SYSTEM_VERSION,
    KNOWLEDGE_VERIFICATION_SCHEMA_VERSION,
    KnowledgeAnswerPacket,
    KnowledgeAnswerVerification,
    KnowledgeProjectError,
    KnowledgeProjectVerification,
)
from .knowledge_project import verify_knowledge_project as verify_stage4_project
from .knowledge_query import answer_knowledge_project, verify_knowledge_answer

SECURITY_BOUNDARY_VERSION = "tkr-project-security-v1"
_MAX_CONTROL_BYTES = 16 * 1024 * 1024
_MAX_PROJECT_FILES = 100_000
_EXPECTED_IMMUTABLE_ROOTS = {
    "source",
    "stage1-anomaly",
    "stage2-structure",
    "stage3-semantics",
    "bridge",
    "index",
}
_ALLOWED_ROOT_FILES = {"project-report.json", "project-manifest.json"}


def _read_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise KnowledgeProjectError(f"{label} is not a safe regular file")
    if path.stat().st_size > _MAX_CONTROL_BYTES:
        raise KnowledgeProjectError(f"{label} exceeds the control-file size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KnowledgeProjectError(f"{label} must be a JSON object")
    return payload


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or value != pure.as_posix():
        return None
    if value == "project-manifest.json":
        return None
    if not pure.parts:
        return None
    if pure.parts[0] not in _EXPECTED_IMMUTABLE_ROOTS and value != "project-report.json":
        return None
    return value


def _walk_project(root: Path) -> tuple[set[str], list[str]]:
    files: set[str] = set()
    reasons: list[str] = []
    count = 0
    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        safe_directories: list[str] = []
        for name in sorted(directory_names):
            path = base / name
            count += 1
            if count > _MAX_PROJECT_FILES:
                reasons.append("PROJECT_FILE_COUNT_LIMIT_EXCEEDED")
                return files, reasons
            if path.is_symlink():
                reasons.append("SYMLINK_IN_PROJECT")
                continue
            if not path.is_dir():
                reasons.append("NON_DIRECTORY_PROJECT_ENTRY")
                continue
            safe_directories.append(name)
        directory_names[:] = safe_directories
        for name in sorted(file_names):
            path = base / name
            count += 1
            if count > _MAX_PROJECT_FILES:
                reasons.append("PROJECT_FILE_COUNT_LIMIT_EXCEEDED")
                return files, reasons
            if path.is_symlink():
                reasons.append("SYMLINK_IN_PROJECT")
                continue
            if not path.is_file():
                reasons.append("NON_REGULAR_PROJECT_FILE")
                continue
            files.add(path.relative_to(root).as_posix())
    return files, reasons


def verify_secure_knowledge_project(project_directory: str | Path) -> KnowledgeProjectVerification:
    """Verify Stage 4 hashes plus exact, non-symlink filesystem membership."""
    root = Path(project_directory)
    reasons: list[str] = []
    base = verify_stage4_project(root)
    if not base.valid:
        reasons.extend(base.reason_codes)
    checked = base.checked_file_count
    try:
        if root.is_symlink() or not root.is_dir():
            reasons.append("PROJECT_ROOT_UNSAFE")
            raise KnowledgeProjectError("project root is unsafe")
        actual_files, walk_reasons = _walk_project(root)
        reasons.extend(walk_reasons)
        manifest = _read_object(root / "project-manifest.json", "project manifest")
        report = _read_object(root / "project-report.json", "project report")
        roots = manifest.get("immutable_roots")
        if not isinstance(roots, list) or set(roots) != _EXPECTED_IMMUTABLE_ROOTS or len(roots) != len(_EXPECTED_IMMUTABLE_ROOTS):
            reasons.append("IMMUTABLE_ROOT_SET_MISMATCH")
        entries = manifest.get("files")
        expected_files: set[str] = set()
        if not isinstance(entries, list):
            reasons.append("MANIFEST_FILES_INVALID")
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                reasons.append("MANIFEST_FILE_RECORD_INVALID")
                continue
            relative = _safe_relative(entry.get("path"))
            if relative is None or relative in expected_files:
                reasons.append("MANIFEST_PATH_INVALID_OR_DUPLICATE")
                continue
            expected_files.add(relative)
        required_actual = expected_files | {"project-manifest.json"}
        if actual_files != required_actual:
            if actual_files - required_actual:
                reasons.append("UNEXPECTED_PROJECT_FILE")
            if required_actual - actual_files:
                reasons.append("DECLARED_PROJECT_FILE_MISSING")
        top_entries = {path.name for path in root.iterdir() if not path.is_symlink()}
        allowed_top = _EXPECTED_IMMUTABLE_ROOTS | _ALLOWED_ROOT_FILES
        if top_entries != allowed_top:
            reasons.append("PROJECT_TOP_LEVEL_LAYOUT_MISMATCH")
        for payload in (manifest, report):
            if payload.get("project_acceptance_performed") or payload.get("may_accept_project") or payload.get("may_freeze"):
                reasons.append("ILLEGAL_ACCEPTANCE_OR_FREEZE_AUTHORITY")
        if report.get("release_candidate"):
            reasons.append("ILLEGAL_RELEASE_CANDIDATE_STATE")
        checked = max(checked, len(actual_files))
    except Exception as exc:
        reasons.extend(("SECURE_PROJECT_VERIFICATION_EXCEPTION", type(exc).__name__))
    unique = tuple(dict.fromkeys(reasons))
    valid = not unique
    return KnowledgeProjectVerification(
        KNOWLEDGE_VERIFICATION_SCHEMA_VERSION,
        KNOWLEDGE_SYSTEM_VERSION,
        base.project_id,
        "verified" if valid else "rejected",
        valid,
        checked,
        unique if unique else (
            "PROJECT_HASH_CHAIN_VERIFIED",
            "INDEX_INTEGRITY_VERIFIED",
            "PROJECT_FILESYSTEM_MEMBERSHIP_VERIFIED",
            "NO_PROJECT_SYMLINKS",
        ),
        base.source_id,
        base.raw_source_sha256,
        base.normalized_source_sha256,
        base.index_logical_sha256,
        valid,
        False,
        False,
        False,
    )


def build_secure_engineered_project(
    source: str | Path,
    output_directory: str | Path,
    *,
    profile: EngineeringProfile | str | Path = "balanced",
    state_directory: str | Path | None = None,
    reuse_existing: bool = False,
    replace_existing: bool = False,
    use_cache: bool = True,
    resume: bool = True,
    recover_stale_lock: bool = False,
) -> EngineeringBuildResult:
    """Build through Stage 5 engineering and require the enhanced security boundary."""
    result = build_engineered_project(
        source,
        output_directory,
        profile=profile,
        state_directory=state_directory,
        reuse_existing=reuse_existing,
        replace_existing=replace_existing,
        use_cache=use_cache,
        resume=resume,
        recover_stale_lock=recover_stale_lock,
    )
    verification = verify_secure_knowledge_project(output_directory)
    if not verification.valid:
        output = Path(output_directory)
        if output.is_dir() and not output.is_symlink() and not result.reused_existing_project:
            quarantine = output.with_name(f".{output.name}.security-rejected")
            if quarantine.exists() and quarantine.is_dir() and not quarantine.is_symlink():
                shutil.rmtree(quarantine)
            output.replace(quarantine)
        raise KnowledgeProjectError(
            "engineered project failed Stage 5 security verification: "
            + ",".join(verification.reason_codes)
        )
    return result


def answer_secure_knowledge_project(
    project_directory: str | Path,
    question: str,
    *,
    source_id: str | None = None,
    retrieval_limit: int = 20,
    max_citations: int = 5,
) -> KnowledgeAnswerPacket:
    verification = verify_secure_knowledge_project(project_directory)
    if not verification.valid:
        raise KnowledgeProjectError(
            "knowledge project failed Stage 5 security verification: "
            + ",".join(verification.reason_codes)
        )
    return answer_knowledge_project(
        project_directory,
        question,
        source_id=source_id,
        retrieval_limit=retrieval_limit,
        max_citations=max_citations,
    )


def verify_secure_knowledge_answer(
    project_directory: str | Path,
    packet: Mapping[str, object] | str | Path,
) -> KnowledgeAnswerVerification:
    project = verify_secure_knowledge_project(project_directory)
    if not project.valid:
        return KnowledgeAnswerVerification(
            "tkr-knowledge-answer-verification-v1",
            KNOWLEDGE_SYSTEM_VERSION,
            "rejected",
            False,
            tuple(dict.fromkeys(("PROJECT_SECURITY_REJECTED", *project.reason_codes))),
            "",
            "",
            project.project_id,
            False,
            False,
            False,
            False,
            False,
        )
    return verify_knowledge_answer(project_directory, packet)


__all__ = [
    "SECURITY_BOUNDARY_VERSION",
    "answer_secure_knowledge_project",
    "build_secure_engineered_project",
    "verify_secure_knowledge_answer",
    "verify_secure_knowledge_project",
]
