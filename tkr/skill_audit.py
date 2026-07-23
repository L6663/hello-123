"""Stage 8 product-layout audit and runtime environment doctor."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import sys
import sysconfig
import tempfile
from typing import Iterable

from .engineering import (
    ENGINEERING_VERSION,
    available_profile_paths,
    load_engineering_profile,
    profile_sha256,
)

SKILL_AUDIT_SCHEMA_VERSION = "tkr-skill-audit-v1"
SKILL_DOCTOR_SCHEMA_VERSION = "tkr-skill-doctor-v1"
SKILL_AUDIT_VERSION = "6.0.0-stage8"
_MAX_TEXT_BYTES = 4 * 1024 * 1024
_MAX_SCAN_FILES = 20_000

_REQUIRED_FILES = (
    "SKILL.md",
    "README.md",
    "PROJECT_STATUS.yaml",
    "pyproject.toml",
    "profiles/balanced.json",
    "profiles/strict.json",
    "profiles/high-recall.json",
    "examples/minimal-corpus.txt",
    "examples/questions.jsonl",
    "docs/INSTALL.md",
    "docs/SECURITY.md",
    "docs/MIGRATION_STAGE5.md",
    "docs/STAGE1_EVIDENCE_ENGINE.md",
    "docs/STAGE2_CHAPTER_STRUCTURE_ENGINE.md",
    "docs/STAGE3_EVENT_CAUSALITY_ENGINE.md",
    "docs/STAGE4_FOCUSED_CHARACTER_ENGINE.md",
    "docs/STAGE5_LAYERED_REASONING_ENGINE.md",
    "docs/STAGE6_NOTION_KNOWLEDGE_SYSTEM.md",
    "docs/STAGE7_LITERARY_REGRESSION_BENCHMARK.md",
    "docs/STAGE8_FINAL_PRODUCTIZATION_ACCEPTANCE.md",
    "schemas/literary-benchmark-case.schema.json",
    "schemas/literary-benchmark-observation.schema.json",
    "schemas/literary-benchmark-report.schema.json",
    "schemas/literary-benchmark-verification.schema.json",
    "schemas/private-blind-attestation.schema.json",
    "schemas/package-acceptance-v2.schema.json",
    "schemas/engineering-validation.schema.json",
    "schemas/reproducible-build-v2.schema.json",
    "schemas/final-acceptance-candidate.schema.json",
    "schemas/final-acceptance-approval.schema.json",
    "schemas/final-acceptance-seal.schema.json",
    "schemas/final-acceptance-verification.schema.json",
)
_REQUIRED_DIRECTORIES = ("tkr", "schemas", "profiles", "examples", "docs")
_REQUIRED_SKILL_MARKERS = (
    "## Purpose",
    "## Inputs",
    "## Workflow",
    "## Safety boundaries",
    "## Standard artifacts",
    "## Commands",
    "## Acceptance boundary",
)
_REQUIRED_SCRIPTS = (
    "tkr-project",
    "tkr-skill",
    "tkr-literary",
    "tkr-evidence",
    "tkr-chapter",
    "tkr-event",
    "tkr-character",
    "tkr-reason",
    "tkr-notion",
    "tkr-literary-benchmark",
    "tkr-final-acceptance",
)
_REQUIRED_PACKAGE_MARKERS = (
    "SKILL.md",
    "profiles/balanced.json",
    "examples/minimal-corpus.txt",
    "schemas/final-acceptance-candidate.schema.json",
    "docs/STAGE8_FINAL_PRODUCTIZATION_ACCEPTANCE.md",
)


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    severity: str
    path: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillAuditReport:
    schema_version: str
    audit_version: str
    root: str
    status: str
    checked_file_count: int
    schema_count: int
    profile_count: int
    finding_count: int
    findings: tuple[AuditFinding, ...]
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    release_candidate: bool = False
    may_freeze: bool = False

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        payload["findings"] = [item.to_dict() for item in self.findings]
        return payload


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillDoctorReport:
    schema_version: str
    audit_version: str
    status: str
    python_version: str
    sqlite_version: str
    check_count: int
    checks: tuple[DoctorCheck, ...]
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    release_candidate: bool = False
    may_freeze: bool = False

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        payload["checks"] = [item.to_dict() for item in self.checks]
        return payload


def _installed_root() -> Path:
    return Path(sysconfig.get_paths()["data"]) / "share" / "text-knowledge-reader"


def resolve_skill_root(root: str | Path | None = None) -> Path:
    if root is not None:
        selected = Path(root)
    else:
        source = Path(__file__).resolve().parents[1]
        selected = source if (source / "SKILL.md").is_file() else _installed_root()
    if selected.is_symlink() or not selected.is_dir():
        raise ValueError(f"Skill root is not a safe directory: {selected}")
    return selected.resolve()


def _safe_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("not a safe regular file")
    size = path.stat().st_size
    if size <= 0 or size > _MAX_TEXT_BYTES:
        raise ValueError("file is empty or exceeds the audit size limit")
    return path.read_text(encoding="utf-8", errors="strict")


def _iter_files(root: Path) -> Iterable[Path]:
    count = 0
    for path in sorted(root.rglob("*")):
        count += 1
        if count > _MAX_SCAN_FILES:
            raise ValueError("Skill layout exceeds the audit file-count limit")
        yield path


def audit_skill_layout(root: str | Path | None = None) -> SkillAuditReport:
    selected = resolve_skill_root(root)
    findings: list[AuditFinding] = []
    checked = schema_count = profile_count = 0

    def add(code: str, severity: str, relative: str, message: str) -> None:
        findings.append(AuditFinding(code, severity, relative, message))

    for directory in _REQUIRED_DIRECTORIES:
        path = selected / directory
        if path.is_symlink() or not path.is_dir():
            add(
                "REQUIRED_DIRECTORY_MISSING",
                "blocker",
                directory,
                "required directory is missing or unsafe",
            )
    for relative in _REQUIRED_FILES:
        path = selected / relative
        if path.is_symlink() or not path.is_file():
            add(
                "REQUIRED_FILE_MISSING",
                "blocker",
                relative,
                "required file is missing or unsafe",
            )
            continue
        checked += 1
        try:
            _safe_text(path)
        except (OSError, UnicodeError, ValueError) as exc:
            add("REQUIRED_FILE_INVALID", "blocker", relative, str(exc))

    try:
        for path in _iter_files(selected):
            if path.is_symlink():
                add(
                    "SYMLINK_IN_SKILL_LAYOUT",
                    "blocker",
                    path.relative_to(selected).as_posix(),
                    "Skill packages must not contain symbolic links",
                )
    except ValueError as exc:
        add("SKILL_LAYOUT_SCAN_LIMIT", "blocker", ".", str(exc))

    skill_path = selected / "SKILL.md"
    if skill_path.is_file() and not skill_path.is_symlink():
        try:
            skill_text = _safe_text(skill_path)
            for marker in _REQUIRED_SKILL_MARKERS:
                if marker not in skill_text:
                    add(
                        "SKILL_CONTRACT_SECTION_MISSING",
                        "blocker",
                        "SKILL.md",
                        marker,
                    )
            for marker in ("6.0.0rc1", "Stage 8", "tkr-final-acceptance"):
                if marker not in skill_text:
                    add(
                        "SKILL_PRODUCT_MARKER_MISSING",
                        "blocker",
                        "SKILL.md",
                        marker,
                    )
        except (OSError, UnicodeError, ValueError):
            pass

    readme_path = selected / "README.md"
    if readme_path.is_file() and not readme_path.is_symlink():
        try:
            readme = _safe_text(readme_path)
            for marker in (
                "6.0.0rc1",
                "Stage 8",
                "private blind",
                "explicit approval",
            ):
                if marker not in readme:
                    add(
                        "README_PRODUCT_MARKER_MISSING",
                        "blocker",
                        "README.md",
                        marker,
                    )
        except (OSError, UnicodeError, ValueError):
            pass

    status_path = selected / "PROJECT_STATUS.yaml"
    if status_path.is_file() and not status_path.is_symlink():
        try:
            status_text = _safe_text(status_path)
            for marker in (
                "Stage 8 Final Productization and Acceptance",
                "project_acceptance_performed: false",
                "may_release: false",
                "may_freeze: false",
            ):
                if marker not in status_text:
                    add(
                        "PROJECT_STATUS_MARKER_MISSING",
                        "blocker",
                        "PROJECT_STATUS.yaml",
                        marker,
                    )
        except (OSError, UnicodeError, ValueError):
            pass

    pyproject = selected / "pyproject.toml"
    if pyproject.is_file() and not pyproject.is_symlink():
        try:
            project_text = _safe_text(pyproject)
            if 'version = "6.0.0rc1"' not in project_text:
                add(
                    "PACKAGE_VERSION_MISMATCH",
                    "blocker",
                    "pyproject.toml",
                    "expected version 6.0.0rc1",
                )
            for script in _REQUIRED_SCRIPTS:
                if f"{script} =" not in project_text:
                    add(
                        "CONSOLE_SCRIPT_MISSING",
                        "blocker",
                        "pyproject.toml",
                        script,
                    )
            for required in _REQUIRED_PACKAGE_MARKERS:
                if required not in project_text:
                    add(
                        "PACKAGE_DATA_DECLARATION_MISSING",
                        "blocker",
                        "pyproject.toml",
                        required,
                    )
        except (OSError, UnicodeError, ValueError):
            pass

    schema_root = selected / "schemas"
    if schema_root.is_dir() and not schema_root.is_symlink():
        for path in sorted(schema_root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                add(
                    "SCHEMA_FILE_UNSAFE",
                    "blocker",
                    path.relative_to(selected).as_posix(),
                    "unsafe schema file",
                )
                continue
            checked += 1
            try:
                payload = json.loads(_safe_text(path))
                if not isinstance(payload, dict) or payload.get("$schema") is None:
                    raise ValueError("schema must be a JSON object with $schema")
                schema_count += 1
            except (
                OSError,
                UnicodeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                add(
                    "SCHEMA_INVALID",
                    "blocker",
                    path.relative_to(selected).as_posix(),
                    str(exc),
                )
    if schema_count < 75:
        add(
            "SCHEMA_SET_INCOMPLETE",
            "blocker",
            "schemas",
            f"only {schema_count} schemas were valid; Stage 8 requires at least 75",
        )

    profile_root = selected / "profiles"
    if profile_root.is_dir() and not profile_root.is_symlink():
        names: set[str] = set()
        for path in sorted(profile_root.glob("*.json")):
            checked += 1
            try:
                profile = load_engineering_profile(path)
                if profile.name in names:
                    raise ValueError("duplicate profile name")
                names.add(profile.name)
                profile_sha256(profile)
                profile_count += 1
            except (
                OSError,
                UnicodeError,
                TypeError,
                ValueError,
            ) as exc:
                add(
                    "PROFILE_INVALID",
                    "blocker",
                    path.relative_to(selected).as_posix(),
                    str(exc),
                )
        for name in {"balanced", "strict", "high-recall"} - names:
            add("BUILTIN_PROFILE_MISSING", "blocker", "profiles", name)

    questions = selected / "examples" / "questions.jsonl"
    if questions.is_file() and not questions.is_symlink():
        try:
            for number, line in enumerate(
                _safe_text(questions).splitlines(), start=1
            ):
                if not line.strip():
                    raise ValueError(f"blank JSONL record at line {number}")
                payload = json.loads(line)
                if (
                    not isinstance(payload, dict)
                    or not isinstance(payload.get("question"), str)
                ):
                    raise ValueError(
                        f"invalid question record at line {number}"
                    )
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            add(
                "EXAMPLE_QUESTIONS_INVALID",
                "blocker",
                "examples/questions.jsonl",
                str(exc),
            )

    unique = tuple(findings)
    status = (
        "passed"
        if not any(item.severity in {"blocker", "high"} for item in unique)
        else "failed"
    )
    return SkillAuditReport(
        SKILL_AUDIT_SCHEMA_VERSION,
        SKILL_AUDIT_VERSION,
        str(selected),
        status,
        checked,
        schema_count,
        profile_count,
        len(unique),
        unique,
    )


def _fts5_available() -> bool:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        connection.close()


def doctor_environment(
    root: str | Path | None = None,
) -> SkillDoctorReport:
    checks: list[DoctorCheck] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append(
            DoctorCheck(name, "passed" if passed else "failed", detail)
        )

    check(
        "python_version",
        sys.version_info >= (3, 10),
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
    check(
        "engineering_runtime",
        bool(ENGINEERING_VERSION),
        str(ENGINEERING_VERSION),
    )
    check(
        "sqlite_available",
        bool(sqlite3.sqlite_version),
        sqlite3.sqlite_version,
    )
    fts5 = _fts5_available()
    check(
        "sqlite_fts5",
        fts5,
        "available" if fts5 else "unavailable",
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix="tkr-doctor-"
        ) as directory:
            probe = Path(directory) / "probe"
            probe.write_text("ok", encoding="utf-8")
            writable = probe.read_text(encoding="utf-8") == "ok"
        check(
            "temporary_storage",
            writable,
            "atomic temporary storage is writable",
        )
    except OSError as exc:
        check("temporary_storage", False, str(exc))

    paths = available_profile_paths()
    check(
        "builtin_profiles",
        {"balanced", "strict", "high-recall"}.issubset(paths),
        ",".join(sorted(paths)) or "none",
    )
    try:
        audit = audit_skill_layout(root)
        check(
            "skill_layout",
            audit.passed,
            f"{audit.checked_file_count} files; "
            f"{audit.schema_count} schemas; "
            f"{audit.finding_count} findings",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        check("skill_layout", False, str(exc))

    status = (
        "passed"
        if all(item.status == "passed" for item in checks)
        else "failed"
    )
    return SkillDoctorReport(
        SKILL_DOCTOR_SCHEMA_VERSION,
        SKILL_AUDIT_VERSION,
        status,
        sys.version.split()[0],
        sqlite3.sqlite_version,
        len(checks),
        tuple(checks),
    )


def profile_catalog() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, path in sorted(available_profile_paths().items()):
        profile = load_engineering_profile(path)
        rows.append(
            {
                "name": name,
                "description": profile.description,
                "index_mode": profile.index_mode,
                "cache_enabled": profile.cache_enabled,
                "profile_sha256": profile_sha256(profile),
                "path": str(path),
            }
        )
    return rows


__all__ = [
    "SKILL_AUDIT_SCHEMA_VERSION",
    "SKILL_AUDIT_VERSION",
    "SKILL_DOCTOR_SCHEMA_VERSION",
    "AuditFinding",
    "DoctorCheck",
    "SkillAuditReport",
    "SkillDoctorReport",
    "audit_skill_layout",
    "doctor_environment",
    "profile_catalog",
    "resolve_skill_root",
]
