"""Build and verify immutable Stage 2 Chapter Structure projects."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Iterable, Mapping, Sequence

from .chapter_engine import (
    CHAPTER_ENGINE_VERSION,
    CanonicalChapter,
    CanonicalOrderRecord,
    ChapterCatalog,
    ChapterCatalogReport,
    ChapterEngineError,
    ChapterFinding,
    ChapterSourceInput,
    SourceBinding,
    build_chapter_catalog,
)
from .chapter_ordering import augment_cross_source_order
from .hashing import sha256_file
from .project_security import verify_secure_knowledge_project

CHAPTER_PROJECT_REPORT_SCHEMA_VERSION = "tkr-chapter-project-report-v1"
CHAPTER_PROJECT_MANIFEST_SCHEMA_VERSION = "tkr-chapter-project-manifest-v1"
CHAPTER_PROJECT_VERIFICATION_SCHEMA_VERSION = "tkr-chapter-project-verification-v1"
CHAPTER_SQLITE_SCHEMA_VERSION = "tkr-chapter-sqlite-v1"

_DATA_FILES = (
    "source-bindings.jsonl",
    "chapters.jsonl",
    "canonical-order.jsonl",
    "chapter-findings.jsonl",
)
_ALLOWED_FILES = set(_DATA_FILES) | {
    "chapter.sqlite",
    "chapter-project-report.json",
    "artifact-manifest.json",
}


class ChapterProjectError(ValueError):
    """Raised when a Stage 2 chapter package is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class ChapterProjectVerification:
    schema_version: str
    status: str
    valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    source_project_ids: tuple[str, ...]
    chapter_count: int
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != CHAPTER_PROJECT_VERIFICATION_SCHEMA_VERSION:
            raise ChapterProjectError("chapter verification schema mismatch")
        if self.valid != (not self.reason_codes):
            raise ChapterProjectError("chapter verification validity mismatch")
        if any((
            self.project_acceptance_performed,
            self.may_accept_project,
            self.may_release,
            self.may_freeze,
        )):
            raise ChapterProjectError("chapter verification cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        payload["source_project_ids"] = list(self.source_project_ids)
        return payload


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _jsonl_bytes(values: Iterable[object]) -> bytes:
    rows: list[str] = []
    for value in values:
        payload = value.to_dict() if hasattr(value, "to_dict") else value
        rows.append(_canonical_json(payload))
    return (("\n".join(rows) + "\n") if rows else "").encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _load_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ChapterProjectError(f"{label} is not a safe regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChapterProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ChapterProjectError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise ChapterProjectError(f"{label} is not a safe regular file")
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ChapterProjectError(f"blank {label} record at line {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ChapterProjectError(
                    f"invalid {label} JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise ChapterProjectError(
                    f"{label} record at line {line_number} must be an object"
                )
            rows.append(value)
    return rows


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        return None
    return value


def _safe_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ChapterProjectError(f"{label} must be a safe directory")


def _source_input(project: Path, input_order: int) -> tuple[ChapterSourceInput, dict[str, object]]:
    verification = verify_secure_knowledge_project(project)
    if not verification.valid:
        raise ChapterProjectError(
            "source project failed verification: " + ",".join(verification.reason_codes)
        )
    report = _load_object(project / "project-report.json", "source project report")
    source_path = project / "source" / "normalized-source.txt"
    if source_path.is_symlink() or not source_path.is_file():
        raise ChapterProjectError("normalized source is not a safe regular file")
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ChapterProjectError(f"normalized source cannot be read strictly: {exc}") from exc
    project_id = report.get("project_id")
    source_id = report.get("source_id")
    source_filename = report.get("source_filename")
    source_sha = report.get("normalized_source_sha256")
    if not all(isinstance(value, str) and value for value in (
        project_id, source_id, source_filename, source_sha
    )):
        raise ChapterProjectError("source report omits required source identity")
    assert isinstance(project_id, str)
    assert isinstance(source_id, str)
    assert isinstance(source_filename, str)
    assert isinstance(source_sha, str)
    if sha256(source_text.encode("utf-8")).hexdigest() != source_sha:
        raise ChapterProjectError("normalized source SHA-256 differs from source report")
    units = _load_jsonl(project / "stage2-structure" / "unit-index.jsonl", "unit index")
    headings = _load_jsonl(
        project / "stage2-structure" / "heading-candidates.jsonl", "heading candidates"
    )
    anomalies = _load_jsonl(
        project / "stage1-anomaly" / "anomaly-candidates.jsonl", "anomaly candidates"
    )
    structure_path = project / "stage2-structure" / "structure-anomalies.jsonl"
    structure_findings = (
        _load_jsonl(structure_path, "structure findings") if structure_path.is_file() else []
    )
    return ChapterSourceInput(
        project_id,
        source_id,
        source_filename,
        source_sha,
        input_order,
        source_text,
        tuple(units),
        tuple(headings),
        tuple(anomalies),
        tuple(structure_findings),
    ), report


def _inputs(projects: Sequence[Path]) -> tuple[list[ChapterSourceInput], list[dict[str, object]]]:
    if not projects:
        raise ChapterProjectError("at least one source project is required")
    resolved = [path.resolve() for path in projects]
    if len(resolved) != len(set(resolved)):
        raise ChapterProjectError("source project paths must be unique")
    inputs: list[ChapterSourceInput] = []
    reports: list[dict[str, object]] = []
    for order, project in enumerate(projects):
        _safe_directory(project, f"source project {order}")
        source, report = _source_input(project, order)
        inputs.append(source)
        reports.append(report)
    return inputs, reports


def _payloads(catalog: ChapterCatalog) -> dict[str, bytes]:
    return {
        "source-bindings.jsonl": _jsonl_bytes(catalog.sources),
        "chapters.jsonl": _jsonl_bytes(catalog.chapters),
        "canonical-order.jsonl": _jsonl_bytes(catalog.canonical_order),
        "chapter-findings.jsonl": _jsonl_bytes(catalog.findings),
    }


def _logical_hash(payloads: Mapping[str, bytes], project_ids: Sequence[str]) -> str:
    digest = sha256()
    digest.update(CHAPTER_ENGINE_VERSION.encode("utf-8"))
    for project_id in project_ids:
        digest.update(b"\0project\0")
        digest.update(project_id.encode("utf-8"))
    for name in sorted(payloads):
        digest.update(b"\0file\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payloads[name])
    return digest.hexdigest()


def _create_database(
    path: Path,
    catalog: ChapterCatalog,
    metadata: Mapping[str, str],
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA page_size=4096")
        connection.executescript(
            """
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE source_bindings(
                source_binding_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                input_order INTEGER NOT NULL UNIQUE,
                chapter_count INTEGER NOT NULL,
                first_known_volume INTEGER,
                first_known_chapter INTEGER,
                last_known_volume INTEGER,
                last_known_chapter INTEGER,
                numbering_coverage REAL NOT NULL
            );
            CREATE TABLE chapters(
                chapter_id TEXT PRIMARY KEY,
                source_binding_id TEXT NOT NULL REFERENCES source_bindings(source_binding_id),
                project_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                source_input_order INTEGER NOT NULL,
                local_physical_order INTEGER NOT NULL,
                global_physical_order INTEGER NOT NULL UNIQUE,
                unit_id TEXT NOT NULL,
                parent_unit_id TEXT,
                heading_id TEXT,
                unit_type TEXT NOT NULL,
                volume_ordinal INTEGER,
                volume_basis TEXT NOT NULL,
                chapter_ordinal INTEGER,
                chapter_basis TEXT NOT NULL,
                original_heading TEXT NOT NULL,
                normalized_heading TEXT NOT NULL,
                title TEXT NOT NULL,
                heading_status TEXT NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                heading_start_char INTEGER,
                heading_end_char INTEGER,
                body_start_char INTEGER NOT NULL,
                body_end_char INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL,
                structure_confidence TEXT NOT NULL,
                review_status TEXT NOT NULL,
                contamination_status TEXT NOT NULL,
                canonical_key TEXT NOT NULL
            );
            CREATE INDEX chapter_address ON chapters(volume_ordinal,chapter_ordinal);
            CREATE INDEX chapter_source_order ON chapters(source_binding_id,local_physical_order);
            CREATE INDEX chapter_key ON chapters(canonical_key);
            CREATE TABLE canonical_order(
                canonical_position INTEGER PRIMARY KEY,
                chapter_id TEXT NOT NULL UNIQUE REFERENCES chapters(chapter_id),
                canonical_key TEXT NOT NULL,
                physical_position INTEGER NOT NULL,
                order_basis TEXT NOT NULL,
                confidence TEXT NOT NULL
            );
            CREATE TABLE findings(
                finding_id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                confidence TEXT NOT NULL,
                recommended_action TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                signals_json TEXT NOT NULL
            );
            CREATE TABLE finding_chapters(
                finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                chapter_id TEXT NOT NULL REFERENCES chapters(chapter_id),
                PRIMARY KEY(finding_id,chapter_id)
            );
            CREATE TABLE finding_sources(
                finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                source_binding_id TEXT NOT NULL REFERENCES source_bindings(source_binding_id),
                PRIMARY KEY(finding_id,source_binding_id)
            );
            """
        )
        connection.executemany(
            "INSERT INTO metadata VALUES(?,?)", sorted(metadata.items())
        )
        for item in catalog.sources:
            connection.execute(
                "INSERT INTO source_bindings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.source_binding_id,
                    item.project_id,
                    item.source_id,
                    item.source_filename,
                    item.source_sha256,
                    item.input_order,
                    item.chapter_count,
                    item.first_known_volume,
                    item.first_known_chapter,
                    item.last_known_volume,
                    item.last_known_chapter,
                    item.numbering_coverage,
                ),
            )
        for item in catalog.chapters:
            connection.execute(
                "INSERT INTO chapters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.chapter_id,
                    item.source_binding_id,
                    item.project_id,
                    item.source_id,
                    item.source_filename,
                    item.source_sha256,
                    item.source_input_order,
                    item.local_physical_order,
                    item.global_physical_order,
                    item.unit_id,
                    item.parent_unit_id,
                    item.heading_id,
                    item.unit_type,
                    item.volume_ordinal,
                    item.volume_basis,
                    item.chapter_ordinal,
                    item.chapter_basis,
                    item.original_heading,
                    item.normalized_heading,
                    item.title,
                    item.heading_status,
                    item.start_char,
                    item.end_char,
                    item.start_line,
                    item.end_line,
                    item.heading_start_char,
                    item.heading_end_char,
                    item.body_start_char,
                    item.body_end_char,
                    item.content_sha256,
                    item.structure_confidence,
                    item.review_status,
                    item.contamination_status,
                    item.canonical_key,
                ),
            )
        for item in catalog.canonical_order:
            connection.execute(
                "INSERT INTO canonical_order VALUES(?,?,?,?,?,?)",
                (
                    item.canonical_position,
                    item.chapter_id,
                    item.canonical_key,
                    item.physical_position,
                    item.order_basis,
                    item.confidence,
                ),
            )
        for item in catalog.findings:
            connection.execute(
                "INSERT INTO findings VALUES(?,?,?,?,?,?,?,?)",
                (
                    item.finding_id,
                    item.rule_id,
                    item.category,
                    item.severity,
                    item.confidence,
                    item.recommended_action,
                    item.canonical_key,
                    _canonical_json(list(item.signals)),
                ),
            )
            for chapter_id in item.chapter_ids:
                connection.execute(
                    "INSERT INTO finding_chapters VALUES(?,?)",
                    (item.finding_id, chapter_id),
                )
            for source_binding_id in item.source_binding_ids:
                connection.execute(
                    "INSERT INTO finding_sources VALUES(?,?)",
                    (item.finding_id, source_binding_id),
                )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ChapterProjectError("chapter SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ChapterProjectError("chapter SQLite foreign key check failed")
    finally:
        connection.close()


def _install(temporary: Path, output: Path, replace_existing: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace_existing:
        raise ChapterProjectError(f"output directory already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise ChapterProjectError("existing output directory is unsafe")
    backup = output.with_name(f".{output.name}.backup")
    if backup.exists():
        shutil.rmtree(backup)
    output.replace(backup)
    try:
        temporary.replace(output)
    except Exception:
        if output.exists():
            shutil.rmtree(output, ignore_errors=True)
        backup.replace(output)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def build_chapter_project(
    source_projects: Sequence[str | Path],
    output_directory: str | Path,
    *,
    replace_existing: bool = False,
) -> dict[str, object]:
    projects = [Path(value) for value in source_projects]
    inputs, source_reports = _inputs(projects)
    try:
        catalog = augment_cross_source_order(build_chapter_catalog(inputs))
    except ChapterEngineError as exc:
        raise ChapterProjectError(str(exc)) from exc
    output = Path(output_directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        payloads = _payloads(catalog)
        project_ids = [item.project_id for item in catalog.sources]
        logical_sha = _logical_hash(payloads, project_ids)
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        metadata = {
            "chapter_engine_version": CHAPTER_ENGINE_VERSION,
            "chapter_sqlite_schema_version": CHAPTER_SQLITE_SCHEMA_VERSION,
            "logical_sha256": logical_sha,
            "source_project_ids_json": _canonical_json(project_ids),
        }
        database = temporary / "chapter.sqlite"
        _create_database(database, catalog, metadata)
        database_sha = sha256_file(database)
        report: dict[str, object] = {
            "schema_version": CHAPTER_PROJECT_REPORT_SCHEMA_VERSION,
            "status": "completed",
            "chapter_engine_version": CHAPTER_ENGINE_VERSION,
            "chapter_sqlite_schema_version": CHAPTER_SQLITE_SCHEMA_VERSION,
            "source_project_ids": project_ids,
            "source_bindings": [
                {
                    "project_id": item.project_id,
                    "source_id": item.source_id,
                    "source_filename": item.source_filename,
                    "source_sha256": item.source_sha256,
                    "input_order": item.input_order,
                }
                for item in catalog.sources
            ],
            **catalog.report.to_dict(),
            "logical_sha256": logical_sha,
            "database_sha256": database_sha,
            "source_project_reports_sha256": [
                sha256(_json_bytes(value)).hexdigest() for value in source_reports
            ],
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        report["schema_version"] = CHAPTER_PROJECT_REPORT_SCHEMA_VERSION
        report["status"] = "completed"
        _write_atomic(temporary / "chapter-project-report.json", _json_bytes(report))
        files = []
        for path in sorted(temporary.iterdir()):
            if path.is_file():
                files.append({
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
        manifest = {
            "schema_version": CHAPTER_PROJECT_MANIFEST_SCHEMA_VERSION,
            "chapter_engine_version": CHAPTER_ENGINE_VERSION,
            "source_project_ids": project_ids,
            "logical_sha256": logical_sha,
            "database_sha256": database_sha,
            "files": files,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "artifact-manifest.json", _json_bytes(manifest))
        _install(temporary, output, replace_existing)
        return report
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _file_map(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = manifest.get("files")
    if not isinstance(raw, list):
        raise ChapterProjectError("chapter manifest files must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for row in raw:
        if not isinstance(row, dict):
            raise ChapterProjectError("chapter manifest file entry must be an object")
        path = _safe_relative(row.get("path"))
        if path is None or path in result:
            raise ChapterProjectError("chapter manifest contains invalid or duplicate path")
        result[path] = row
    return result


def verify_chapter_project(
    source_projects: Sequence[str | Path],
    chapter_project: str | Path,
) -> ChapterProjectVerification:
    root = Path(chapter_project)
    reasons: list[str] = []
    checked = 0
    project_ids: tuple[str, ...] = ()
    logical_sha = ""
    database_sha = ""
    chapter_count = 0
    try:
        _safe_directory(root, "chapter project")
        report = _load_object(root / "chapter-project-report.json", "chapter project report")
        manifest = _load_object(root / "artifact-manifest.json", "chapter manifest")
        project_ids_raw = report.get("source_project_ids", [])
        if not isinstance(project_ids_raw, list) or not all(
            isinstance(value, str) and value for value in project_ids_raw
        ):
            reasons.append("CHAPTER_SOURCE_PROJECT_IDS_INVALID")
        else:
            project_ids = tuple(project_ids_raw)
        logical_sha = str(report.get("logical_sha256", ""))
        database_sha = str(report.get("database_sha256", ""))
        chapter_count_value = report.get("chapter_count")
        if isinstance(chapter_count_value, int) and not isinstance(chapter_count_value, bool):
            chapter_count = chapter_count_value
        else:
            reasons.append("CHAPTER_REPORT_COUNT_INVALID")
        if report.get("schema_version") != CHAPTER_PROJECT_REPORT_SCHEMA_VERSION:
            reasons.append("CHAPTER_REPORT_SCHEMA_MISMATCH")
        if manifest.get("schema_version") != CHAPTER_PROJECT_MANIFEST_SCHEMA_VERSION:
            reasons.append("CHAPTER_MANIFEST_SCHEMA_MISMATCH")
        if report.get("chapter_engine_version") != CHAPTER_ENGINE_VERSION:
            reasons.append("CHAPTER_ENGINE_VERSION_MISMATCH")
        if manifest.get("chapter_engine_version") != CHAPTER_ENGINE_VERSION:
            reasons.append("CHAPTER_MANIFEST_ENGINE_VERSION_MISMATCH")
        if manifest.get("source_project_ids") != list(project_ids):
            reasons.append("CHAPTER_MANIFEST_SOURCE_BINDING_MISMATCH")
        if manifest.get("logical_sha256") != logical_sha:
            reasons.append("CHAPTER_MANIFEST_LOGICAL_HASH_MISMATCH")
        files = _file_map(manifest)
        listed = set(files)
        expected_listed = _ALLOWED_FILES - {"artifact-manifest.json"}
        if listed != expected_listed:
            reasons.append("CHAPTER_MANIFEST_FILE_SET_MISMATCH")
        actual_names = {
            path.name for path in root.iterdir()
            if path.is_file() and not path.is_symlink()
        }
        if actual_names != _ALLOWED_FILES:
            reasons.append("CHAPTER_DIRECTORY_FILE_SET_MISMATCH")
        for name, row in files.items():
            path = root / name
            if path.is_symlink() or not path.is_file():
                reasons.append(f"CHAPTER_FILE_UNSAFE:{name}")
                continue
            checked += 1
            size = row.get("size_bytes")
            digest = row.get("sha256")
            if size != path.stat().st_size:
                reasons.append(f"CHAPTER_FILE_SIZE_MISMATCH:{name}")
            if digest != sha256_file(path):
                reasons.append(f"CHAPTER_FILE_HASH_MISMATCH:{name}")
        inputs, _ = _inputs([Path(value) for value in source_projects])
        if tuple(item.project_id for item in inputs) != project_ids:
            reasons.append("CHAPTER_SOURCE_PROJECT_ORDER_MISMATCH")
        catalog = augment_cross_source_order(build_chapter_catalog(inputs))
        expected_payloads = _payloads(catalog)
        expected_logical = _logical_hash(expected_payloads, project_ids)
        if expected_logical != logical_sha:
            reasons.append("CHAPTER_REBUILT_LOGICAL_HASH_MISMATCH")
        for name, data in expected_payloads.items():
            path = root / name
            if path.is_file() and path.read_bytes() != data:
                reasons.append(f"CHAPTER_REBUILT_ARTIFACT_MISMATCH:{name}")
        if catalog.report.chapter_count != chapter_count:
            reasons.append("CHAPTER_REPORT_CHAPTER_COUNT_MISMATCH")
        database = root / "chapter.sqlite"
        actual_database_sha = sha256_file(database) if database.is_file() else ""
        if actual_database_sha != database_sha or manifest.get("database_sha256") != database_sha:
            reasons.append("CHAPTER_DATABASE_HASH_MISMATCH")
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                reasons.append("CHAPTER_SQLITE_INTEGRITY_FAILED")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                reasons.append("CHAPTER_SQLITE_FOREIGN_KEY_FAILED")
            metadata = dict(connection.execute("SELECT key,value FROM metadata"))
            if metadata.get("chapter_engine_version") != CHAPTER_ENGINE_VERSION:
                reasons.append("CHAPTER_SQLITE_ENGINE_VERSION_MISMATCH")
            if metadata.get("logical_sha256") != logical_sha:
                reasons.append("CHAPTER_SQLITE_LOGICAL_HASH_MISMATCH")
            table_specs = (
                ("source_bindings", "source_binding_id", [item.source_binding_id for item in catalog.sources]),
                ("chapters", "chapter_id", [item.chapter_id for item in catalog.chapters]),
                ("findings", "finding_id", [item.finding_id for item in catalog.findings]),
            )
            for table, column, expected_ids in table_specs:
                actual_ids = [
                    str(row[0]) for row in connection.execute(
                        f"SELECT {column} FROM {table} ORDER BY {column}"
                    )
                ]
                if actual_ids != sorted(expected_ids):
                    reasons.append(f"CHAPTER_SQLITE_IDENTIFIER_MISMATCH:{table}")
            order_rows = connection.execute(
                "SELECT canonical_position,chapter_id FROM canonical_order ORDER BY canonical_position"
            ).fetchall()
            expected_order = [
                (item.canonical_position, item.chapter_id) for item in catalog.canonical_order
            ]
            if order_rows != expected_order:
                reasons.append("CHAPTER_SQLITE_CANONICAL_ORDER_MISMATCH")
        finally:
            connection.close()
    except Exception as exc:
        reasons.extend(("CHAPTER_VERIFICATION_EXCEPTION", type(exc).__name__))
    unique_reasons = tuple(dict.fromkeys(reasons))
    return ChapterProjectVerification(
        CHAPTER_PROJECT_VERIFICATION_SCHEMA_VERSION,
        "verified" if not unique_reasons else "rejected",
        not unique_reasons,
        unique_reasons,
        checked,
        project_ids,
        chapter_count,
        logical_sha,
        database_sha,
    )


__all__ = [
    "CHAPTER_PROJECT_MANIFEST_SCHEMA_VERSION",
    "CHAPTER_PROJECT_REPORT_SCHEMA_VERSION",
    "CHAPTER_PROJECT_VERIFICATION_SCHEMA_VERSION",
    "CHAPTER_SQLITE_SCHEMA_VERSION",
    "ChapterProjectError",
    "ChapterProjectVerification",
    "build_chapter_project",
    "verify_chapter_project",
]
