"""Build and verify immutable Stage 3 Event Causality projects."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Iterable, Mapping, Sequence

from .chapter_project import verify_chapter_project
from .event_engine import (
    EVENT_ENGINE_VERSION,
    CausalEvent,
    EventCausalEdge,
    EventComponent,
    EventEngineError,
    EventFinding,
    EventGraph,
    build_event_graph,
    component_from_dict,
    edge_from_dict,
    event_from_dict,
)
from .hashing import sha256_file
from .literary_engine import verify_literary_engine

EVENT_PROJECT_REPORT_SCHEMA_VERSION = "tkr-event-project-report-v1"
EVENT_PROJECT_MANIFEST_SCHEMA_VERSION = "tkr-event-project-manifest-v1"
EVENT_PROJECT_VERIFICATION_SCHEMA_VERSION = "tkr-event-project-verification-v1"
EVENT_SQLITE_SCHEMA_VERSION = "tkr-event-sqlite-v1"
EVENT_ANNOTATION_SCHEMA_VERSION = "tkr-event-annotation-v1"

_DATA_FILES = (
    "events.jsonl",
    "event-components.jsonl",
    "event-causal-edges.jsonl",
    "event-findings.jsonl",
)
_ALLOWED_FILES = set(_DATA_FILES) | {
    "event.sqlite",
    "event-project-report.json",
    "artifact-manifest.json",
}


class EventProjectError(ValueError):
    """Raised when an Event Project cannot be built or verified safely."""


@dataclass(frozen=True, slots=True)
class EventProjectVerification:
    schema_version: str
    status: str
    valid: bool
    graph_valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    chapter_project_logical_sha256: str
    literary_project_ids: tuple[str, ...]
    annotation_sha256: str
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_PROJECT_VERIFICATION_SCHEMA_VERSION:
            raise EventProjectError("event verification schema mismatch")
        if self.valid != (not self.reason_codes):
            raise EventProjectError("event verification validity mismatch")
        if any((
            self.project_acceptance_performed,
            self.may_accept_project,
            self.may_release,
            self.may_freeze,
        )):
            raise EventProjectError("event verification cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        payload["literary_project_ids"] = list(self.literary_project_ids)
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


def _safe_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise EventProjectError(f"{label} must be a safe directory")


def _load_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise EventProjectError(f"{label} is not a safe regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EventProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise EventProjectError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise EventProjectError(f"{label} is not a safe regular file")
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise EventProjectError(f"blank {label} record at line {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EventProjectError(
                    f"invalid {label} JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise EventProjectError(
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


def _file_map(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = manifest.get("files")
    if not isinstance(raw, list):
        raise EventProjectError("event manifest files must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for row in raw:
        if not isinstance(row, dict):
            raise EventProjectError("event manifest file entry must be an object")
        path = _safe_relative(row.get("path"))
        if path is None or path in result:
            raise EventProjectError("event manifest contains invalid or duplicate path")
        result[path] = row
    return result


def _annotation_records(path: Path) -> tuple[list[CausalEvent], list[EventComponent], list[EventCausalEdge], str]:
    if path.is_symlink() or not path.is_file():
        raise EventProjectError("event annotation must be a safe regular file")
    annotation_sha = sha256_file(path)
    events: list[CausalEvent] = []
    components: list[EventComponent] = []
    edges: list[EventCausalEdge] = []
    for row in _load_jsonl(path, "event annotation"):
        if row.get("schema_version") != EVENT_ANNOTATION_SCHEMA_VERSION:
            raise EventProjectError("event annotation envelope schema mismatch")
        record_type = row.get("record_type")
        record = row.get("record")
        if not isinstance(record_type, str) or not isinstance(record, dict):
            raise EventProjectError("event annotation requires record_type and record")
        try:
            if record_type == "event":
                events.append(event_from_dict(record))
            elif record_type == "component":
                components.append(component_from_dict(record))
            elif record_type == "edge":
                edges.append(edge_from_dict(record))
            else:
                raise EventProjectError(f"unsupported event annotation record type: {record_type}")
        except EventEngineError as exc:
            raise EventProjectError(str(exc)) from exc
    return events, components, edges, annotation_sha


def _chapter_context(
    chapter_project: Path,
    source_projects: Sequence[Path],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    verification = verify_chapter_project(source_projects, chapter_project)
    if not verification.valid:
        raise EventProjectError(
            "chapter project failed verification: " + ",".join(verification.reason_codes)
        )
    report = _load_object(chapter_project / "chapter-project-report.json", "chapter project report")
    chapters = {
        str(row["chapter_id"]): row
        for row in _load_jsonl(chapter_project / "chapters.jsonl", "chapter records")
        if isinstance(row.get("chapter_id"), str)
    }
    if not chapters:
        raise EventProjectError("chapter project contains no chapters")
    return chapters, report


def _literary_context(
    literary_projects: Sequence[Path],
) -> tuple[set[str], set[str], tuple[str, ...], tuple[str, ...]]:
    if not literary_projects:
        raise EventProjectError("at least one literary project is required")
    assertion_ids: set[str] = set()
    evidence_ids: set[str] = set()
    project_ids: list[str] = []
    logical_hashes: list[str] = []
    for index, project in enumerate(literary_projects):
        _safe_directory(project, f"literary project {index}")
        verification = verify_literary_engine(project)
        if not verification.valid:
            raise EventProjectError(
                "literary project failed verification: " + ",".join(verification.reason_codes)
            )
        report = _load_object(project / "literary-report.json", "literary report")
        project_id = report.get("project_id")
        logical_sha = report.get("logical_sha256")
        if not isinstance(project_id, str) or not project_id:
            raise EventProjectError("literary report omits project_id")
        if not isinstance(logical_sha, str) or len(logical_sha) != 64:
            raise EventProjectError("literary report omits logical_sha256")
        project_ids.append(project_id)
        logical_hashes.append(logical_sha)
        assertion_ids.update(
            str(row["assertion_id"])
            for row in _load_jsonl(project / "assertions.jsonl", "literary assertions")
            if isinstance(row.get("assertion_id"), str)
        )
        evidence_ids.update(
            str(row["anchor_id"])
            for row in _load_jsonl(project / "evidence-anchors.jsonl", "literary evidence")
            if isinstance(row.get("anchor_id"), str)
        )
    if len(project_ids) != len(set(project_ids)):
        raise EventProjectError("literary project IDs must be unique")
    return assertion_ids, evidence_ids, tuple(project_ids), tuple(logical_hashes)


def _bind_event_positions(
    events: Sequence[CausalEvent], chapters: Mapping[str, Mapping[str, object]]
) -> None:
    for event in events:
        start = chapters.get(event.start_chapter_id)
        end = chapters.get(event.end_chapter_id)
        if start is None or end is None:
            raise EventProjectError(f"event references unknown Chapter Project chapter: {event.event_id}")
        start_position = start.get("global_physical_order")
        end_position = end.get("global_physical_order")
        if start_position != event.start_position or end_position != event.end_position:
            raise EventProjectError(f"event position differs from Chapter Project: {event.event_id}")
        if event.review_status in {"active", "contested"}:
            if start.get("contamination_status") != "clean" or end.get("contamination_status") != "clean":
                raise EventProjectError(f"active event cannot bind contaminated chapter: {event.event_id}")


def _payloads(graph: EventGraph) -> dict[str, bytes]:
    return {
        "events.jsonl": _jsonl_bytes(graph.events),
        "event-components.jsonl": _jsonl_bytes(graph.components),
        "event-causal-edges.jsonl": _jsonl_bytes(graph.edges),
        "event-findings.jsonl": _jsonl_bytes(graph.findings),
    }


def _logical_hash(
    payloads: Mapping[str, bytes],
    chapter_logical_sha: str,
    literary_hashes: Sequence[str],
    annotation_sha: str,
) -> str:
    digest = sha256()
    digest.update(EVENT_ENGINE_VERSION.encode("utf-8"))
    digest.update(chapter_logical_sha.encode("utf-8"))
    digest.update(annotation_sha.encode("utf-8"))
    for value in literary_hashes:
        digest.update(b"\0literary\0")
        digest.update(value.encode("utf-8"))
    for name in sorted(payloads):
        digest.update(b"\0file\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payloads[name])
    return digest.hexdigest()


def _create_database(path: Path, graph: EventGraph, metadata: Mapping[str, str]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA page_size=4096")
        connection.executescript(
            """
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE events(
                event_id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                significance TEXT NOT NULL,
                start_chapter_id TEXT NOT NULL,
                end_chapter_id TEXT NOT NULL,
                start_position INTEGER NOT NULL,
                end_position INTEGER NOT NULL,
                review_status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX event_time ON events(start_position,end_position);
            CREATE TABLE event_participants(
                event_id TEXT NOT NULL REFERENCES events(event_id),
                entity_id TEXT NOT NULL,
                PRIMARY KEY(event_id,entity_id)
            );
            CREATE TABLE event_places(
                event_id TEXT NOT NULL REFERENCES events(event_id),
                entity_id TEXT NOT NULL,
                PRIMARY KEY(event_id,entity_id)
            );
            CREATE TABLE event_evidence(
                event_id TEXT NOT NULL REFERENCES events(event_id),
                anchor_id TEXT NOT NULL,
                PRIMARY KEY(event_id,anchor_id)
            );
            CREATE TABLE components(
                component_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL REFERENCES events(event_id),
                component_type TEXT NOT NULL,
                tier TEXT NOT NULL,
                statement TEXT NOT NULL,
                confidence REAL NOT NULL,
                attribution TEXT NOT NULL,
                status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX component_event_type ON components(event_id,component_type,tier);
            CREATE TABLE component_assertions(
                component_id TEXT NOT NULL REFERENCES components(component_id),
                assertion_id TEXT NOT NULL,
                PRIMARY KEY(component_id,assertion_id)
            );
            CREATE TABLE component_evidence(
                component_id TEXT NOT NULL REFERENCES components(component_id),
                anchor_id TEXT NOT NULL,
                PRIMARY KEY(component_id,anchor_id)
            );
            CREATE TABLE component_supports(
                component_id TEXT NOT NULL REFERENCES components(component_id),
                supporting_component_id TEXT NOT NULL REFERENCES components(component_id),
                PRIMARY KEY(component_id,supporting_component_id)
            );
            CREATE TABLE edges(
                edge_id TEXT PRIMARY KEY,
                source_event_id TEXT NOT NULL REFERENCES events(event_id),
                relation_type TEXT NOT NULL,
                target_event_id TEXT NOT NULL REFERENCES events(event_id),
                tier TEXT NOT NULL,
                source_position INTEGER NOT NULL,
                target_position INTEGER NOT NULL,
                temporal_direction TEXT NOT NULL,
                confidence REAL NOT NULL,
                attribution TEXT NOT NULL,
                status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX edge_source ON edges(source_event_id,relation_type,target_event_id);
            CREATE INDEX edge_target ON edges(target_event_id,relation_type,source_event_id);
            CREATE TABLE edge_assertions(
                edge_id TEXT NOT NULL REFERENCES edges(edge_id),
                assertion_id TEXT NOT NULL,
                PRIMARY KEY(edge_id,assertion_id)
            );
            CREATE TABLE edge_evidence(
                edge_id TEXT NOT NULL REFERENCES edges(edge_id),
                anchor_id TEXT NOT NULL,
                PRIMARY KEY(edge_id,anchor_id)
            );
            CREATE TABLE edge_supports(
                edge_id TEXT NOT NULL REFERENCES edges(edge_id),
                component_id TEXT NOT NULL REFERENCES components(component_id),
                PRIMARY KEY(edge_id,component_id)
            );
            CREATE TABLE findings(
                finding_id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                signals_json TEXT NOT NULL,
                recommended_action TEXT NOT NULL
            );
            CREATE TABLE finding_events(
                finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                event_id TEXT NOT NULL,
                PRIMARY KEY(finding_id,event_id)
            );
            CREATE TABLE finding_edges(
                finding_id TEXT NOT NULL REFERENCES findings(finding_id),
                edge_id TEXT NOT NULL,
                PRIMARY KEY(finding_id,edge_id)
            );
            """
        )
        connection.executemany("INSERT INTO metadata VALUES(?,?)", sorted(metadata.items()))
        for item in graph.events:
            connection.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    item.event_id,
                    item.canonical_name,
                    item.event_type,
                    item.significance,
                    item.start_chapter_id,
                    item.end_chapter_id,
                    item.start_position,
                    item.end_position,
                    item.review_status,
                    _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany(
                "INSERT INTO event_participants VALUES(?,?)",
                [(item.event_id, value) for value in item.participant_entity_ids],
            )
            connection.executemany(
                "INSERT INTO event_places VALUES(?,?)",
                [(item.event_id, value) for value in item.place_entity_ids],
            )
            connection.executemany(
                "INSERT INTO event_evidence VALUES(?,?)",
                [(item.event_id, value) for value in item.evidence_anchor_ids],
            )
        for item in graph.components:
            connection.execute(
                "INSERT INTO components VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    item.component_id,
                    item.event_id,
                    item.component_type,
                    item.tier,
                    item.statement,
                    item.confidence,
                    item.attribution,
                    item.status,
                    _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany(
                "INSERT INTO component_assertions VALUES(?,?)",
                [(item.component_id, value) for value in item.assertion_ids],
            )
            connection.executemany(
                "INSERT INTO component_evidence VALUES(?,?)",
                [(item.component_id, value) for value in item.evidence_anchor_ids],
            )
        for item in graph.components:
            connection.executemany(
                "INSERT INTO component_supports VALUES(?,?)",
                [(item.component_id, value) for value in item.supporting_component_ids],
            )
        for item in graph.edges:
            connection.execute(
                "INSERT INTO edges VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.edge_id,
                    item.source_event_id,
                    item.relation_type,
                    item.target_event_id,
                    item.tier,
                    item.source_position,
                    item.target_position,
                    item.temporal_direction,
                    item.confidence,
                    item.attribution,
                    item.status,
                    _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany(
                "INSERT INTO edge_assertions VALUES(?,?)",
                [(item.edge_id, value) for value in item.assertion_ids],
            )
            connection.executemany(
                "INSERT INTO edge_evidence VALUES(?,?)",
                [(item.edge_id, value) for value in item.evidence_anchor_ids],
            )
            connection.executemany(
                "INSERT INTO edge_supports VALUES(?,?)",
                [(item.edge_id, value) for value in item.supporting_component_ids],
            )
        for item in graph.findings:
            connection.execute(
                "INSERT INTO findings VALUES(?,?,?,?,?)",
                (
                    item.finding_id,
                    item.rule_id,
                    item.severity,
                    _canonical_json(list(item.signals)),
                    item.recommended_action,
                ),
            )
            connection.executemany(
                "INSERT INTO finding_events VALUES(?,?)",
                [(item.finding_id, value) for value in item.event_ids],
            )
            connection.executemany(
                "INSERT INTO finding_edges VALUES(?,?)",
                [(item.finding_id, value) for value in item.edge_ids],
            )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise EventProjectError("event SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise EventProjectError("event SQLite foreign key check failed")
    finally:
        connection.close()


def _install(temporary: Path, output: Path, replace_existing: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace_existing:
        raise EventProjectError(f"output directory already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise EventProjectError("existing output directory is unsafe")
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


def _build_graph(
    chapter_project: Path,
    source_projects: Sequence[Path],
    literary_projects: Sequence[Path],
    annotation_path: Path,
) -> tuple[EventGraph, dict[str, object], tuple[str, ...], tuple[str, ...], str]:
    chapters, chapter_report = _chapter_context(chapter_project, source_projects)
    assertion_ids, evidence_ids, literary_ids, literary_hashes = _literary_context(literary_projects)
    events, components, edges, annotation_sha = _annotation_records(annotation_path)
    _bind_event_positions(events, chapters)
    graph = build_event_graph(
        events,
        components,
        edges,
        known_assertion_ids=assertion_ids,
        known_evidence_anchor_ids=evidence_ids,
    )
    if graph.report.unsupported_reference_count or graph.report.temporal_violation_count:
        raise EventProjectError("event graph contains unsafe support or temporal bindings")
    return graph, chapter_report, literary_ids, literary_hashes, annotation_sha


def build_event_project(
    chapter_project: str | Path,
    source_projects: Sequence[str | Path],
    literary_projects: Sequence[str | Path],
    annotation_path: str | Path,
    output_directory: str | Path,
    *,
    replace_existing: bool = False,
) -> dict[str, object]:
    chapter_root = Path(chapter_project)
    source_roots = [Path(value) for value in source_projects]
    literary_roots = [Path(value) for value in literary_projects]
    graph, chapter_report, literary_ids, literary_hashes, annotation_sha = _build_graph(
        chapter_root, source_roots, literary_roots, Path(annotation_path)
    )
    chapter_logical = chapter_report.get("logical_sha256")
    if not isinstance(chapter_logical, str) or len(chapter_logical) != 64:
        raise EventProjectError("chapter project report omits logical_sha256")
    output = Path(output_directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        payloads = _payloads(graph)
        logical_sha = _logical_hash(payloads, chapter_logical, literary_hashes, annotation_sha)
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        metadata = {
            "event_engine_version": EVENT_ENGINE_VERSION,
            "event_sqlite_schema_version": EVENT_SQLITE_SCHEMA_VERSION,
            "logical_sha256": logical_sha,
            "chapter_project_logical_sha256": chapter_logical,
            "literary_project_ids_json": _canonical_json(list(literary_ids)),
            "annotation_sha256": annotation_sha,
            "graph_valid": str(int(graph.report.graph_valid)),
        }
        database = temporary / "event.sqlite"
        _create_database(database, graph, metadata)
        database_sha = sha256_file(database)
        report: dict[str, object] = {
            "schema_version": EVENT_PROJECT_REPORT_SCHEMA_VERSION,
            "status": "completed" if graph.report.graph_valid else "review_required",
            "event_engine_version": EVENT_ENGINE_VERSION,
            "event_sqlite_schema_version": EVENT_SQLITE_SCHEMA_VERSION,
            "chapter_project_logical_sha256": chapter_logical,
            "literary_project_ids": list(literary_ids),
            "literary_project_logical_sha256": list(literary_hashes),
            "annotation_sha256": annotation_sha,
            **graph.report.to_dict(),
            "logical_sha256": logical_sha,
            "database_sha256": database_sha,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        report["schema_version"] = EVENT_PROJECT_REPORT_SCHEMA_VERSION
        report["status"] = "completed" if graph.report.graph_valid else "review_required"
        _write_atomic(temporary / "event-project-report.json", _json_bytes(report))
        files = [
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(temporary.iterdir())
            if path.is_file()
        ]
        manifest = {
            "schema_version": EVENT_PROJECT_MANIFEST_SCHEMA_VERSION,
            "event_engine_version": EVENT_ENGINE_VERSION,
            "chapter_project_logical_sha256": chapter_logical,
            "literary_project_ids": list(literary_ids),
            "annotation_sha256": annotation_sha,
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


def verify_event_project(
    chapter_project: str | Path,
    source_projects: Sequence[str | Path],
    literary_projects: Sequence[str | Path],
    annotation_path: str | Path,
    event_project: str | Path,
) -> EventProjectVerification:
    root = Path(event_project)
    reasons: list[str] = []
    checked = 0
    graph_valid = False
    chapter_logical = ""
    literary_ids: tuple[str, ...] = ()
    annotation_sha = ""
    logical_sha = ""
    database_sha = ""
    try:
        _safe_directory(root, "event project")
        report = _load_object(root / "event-project-report.json", "event project report")
        manifest = _load_object(root / "artifact-manifest.json", "event manifest")
        graph_valid = report.get("graph_valid") is True
        chapter_logical = str(report.get("chapter_project_logical_sha256", ""))
        literary_raw = report.get("literary_project_ids", [])
        if isinstance(literary_raw, list) and all(isinstance(value, str) for value in literary_raw):
            literary_ids = tuple(literary_raw)
        else:
            reasons.append("EVENT_LITERARY_PROJECT_IDS_INVALID")
        annotation_sha = str(report.get("annotation_sha256", ""))
        logical_sha = str(report.get("logical_sha256", ""))
        database_sha = str(report.get("database_sha256", ""))
        if report.get("schema_version") != EVENT_PROJECT_REPORT_SCHEMA_VERSION:
            reasons.append("EVENT_REPORT_SCHEMA_MISMATCH")
        if manifest.get("schema_version") != EVENT_PROJECT_MANIFEST_SCHEMA_VERSION:
            reasons.append("EVENT_MANIFEST_SCHEMA_MISMATCH")
        if report.get("event_engine_version") != EVENT_ENGINE_VERSION:
            reasons.append("EVENT_ENGINE_VERSION_MISMATCH")
        if manifest.get("logical_sha256") != logical_sha:
            reasons.append("EVENT_MANIFEST_LOGICAL_HASH_MISMATCH")
        if manifest.get("annotation_sha256") != annotation_sha:
            reasons.append("EVENT_MANIFEST_ANNOTATION_HASH_MISMATCH")
        files = _file_map(manifest)
        if set(files) != _ALLOWED_FILES - {"artifact-manifest.json"}:
            reasons.append("EVENT_MANIFEST_FILE_SET_MISMATCH")
        actual_names = {
            path.name for path in root.iterdir() if path.is_file() and not path.is_symlink()
        }
        if actual_names != _ALLOWED_FILES:
            reasons.append("EVENT_DIRECTORY_FILE_SET_MISMATCH")
        for name, row in files.items():
            path = root / name
            if path.is_symlink() or not path.is_file():
                reasons.append(f"EVENT_FILE_UNSAFE:{name}")
                continue
            checked += 1
            if row.get("size_bytes") != path.stat().st_size:
                reasons.append(f"EVENT_FILE_SIZE_MISMATCH:{name}")
            if row.get("sha256") != sha256_file(path):
                reasons.append(f"EVENT_FILE_HASH_MISMATCH:{name}")
        graph, chapter_report, expected_literary_ids, literary_hashes, expected_annotation_sha = _build_graph(
            Path(chapter_project),
            [Path(value) for value in source_projects],
            [Path(value) for value in literary_projects],
            Path(annotation_path),
        )
        expected_chapter_logical = str(chapter_report.get("logical_sha256", ""))
        expected_payloads = _payloads(graph)
        expected_logical = _logical_hash(
            expected_payloads,
            expected_chapter_logical,
            literary_hashes,
            expected_annotation_sha,
        )
        if expected_chapter_logical != chapter_logical:
            reasons.append("EVENT_CHAPTER_PROJECT_BINDING_MISMATCH")
        if expected_literary_ids != literary_ids:
            reasons.append("EVENT_LITERARY_PROJECT_BINDING_MISMATCH")
        if expected_annotation_sha != annotation_sha:
            reasons.append("EVENT_ANNOTATION_HASH_MISMATCH")
        if expected_logical != logical_sha:
            reasons.append("EVENT_REBUILT_LOGICAL_HASH_MISMATCH")
        for name, data in expected_payloads.items():
            path = root / name
            if path.is_file() and path.read_bytes() != data:
                reasons.append(f"EVENT_REBUILT_ARTIFACT_MISMATCH:{name}")
        if graph.report.graph_valid != graph_valid:
            reasons.append("EVENT_GRAPH_VALIDITY_MISMATCH")
        database = root / "event.sqlite"
        actual_database_sha = sha256_file(database) if database.is_file() else ""
        if actual_database_sha != database_sha or manifest.get("database_sha256") != database_sha:
            reasons.append("EVENT_DATABASE_HASH_MISMATCH")
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                reasons.append("EVENT_SQLITE_INTEGRITY_FAILED")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                reasons.append("EVENT_SQLITE_FOREIGN_KEY_FAILED")
            metadata = dict(connection.execute("SELECT key,value FROM metadata"))
            if metadata.get("event_engine_version") != EVENT_ENGINE_VERSION:
                reasons.append("EVENT_SQLITE_ENGINE_VERSION_MISMATCH")
            if metadata.get("logical_sha256") != logical_sha:
                reasons.append("EVENT_SQLITE_LOGICAL_HASH_MISMATCH")
            specs = (
                ("events", "event_id", [item.event_id for item in graph.events]),
                ("components", "component_id", [item.component_id for item in graph.components]),
                ("edges", "edge_id", [item.edge_id for item in graph.edges]),
                ("findings", "finding_id", [item.finding_id for item in graph.findings]),
            )
            for table, column, expected_ids in specs:
                actual_ids = [
                    str(row[0]) for row in connection.execute(
                        f"SELECT {column} FROM {table} ORDER BY {column}"
                    )
                ]
                if actual_ids != sorted(expected_ids):
                    reasons.append(f"EVENT_SQLITE_IDENTIFIER_MISMATCH:{table}")
        finally:
            connection.close()
    except Exception as exc:
        reasons.extend(("EVENT_VERIFICATION_EXCEPTION", type(exc).__name__))
    unique_reasons = tuple(dict.fromkeys(reasons))
    return EventProjectVerification(
        EVENT_PROJECT_VERIFICATION_SCHEMA_VERSION,
        "verified" if not unique_reasons else "rejected",
        not unique_reasons,
        graph_valid,
        unique_reasons,
        checked,
        chapter_logical,
        literary_ids,
        annotation_sha,
        logical_sha,
        database_sha,
    )


__all__ = [
    "EVENT_ANNOTATION_SCHEMA_VERSION",
    "EVENT_PROJECT_MANIFEST_SCHEMA_VERSION",
    "EVENT_PROJECT_REPORT_SCHEMA_VERSION",
    "EVENT_PROJECT_VERIFICATION_SCHEMA_VERSION",
    "EVENT_SQLITE_SCHEMA_VERSION",
    "EventProjectError",
    "EventProjectVerification",
    "build_event_project",
    "verify_event_project",
]
