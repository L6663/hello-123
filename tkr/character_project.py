"""Build and verify immutable Stage 4 Focused Character projects."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Iterable, Mapping, Sequence, TypeVar

from .chapter_project import verify_chapter_project
from .character_engine import (
    CHARACTER_ENGINE_VERSION,
    CharacterAttribute,
    CharacterEngineError,
    CharacterEventLink,
    CharacterFinding,
    CharacterGraph,
    CharacterRelationship,
    CharacterState,
    FocusedCharacter,
    build_character_graph,
)
from .event_project import verify_event_project
from .hashing import sha256_file
from .literary_engine import verify_literary_engine

CHARACTER_ANNOTATION_SCHEMA_VERSION = "tkr-character-annotation-v1"
CHARACTER_PROJECT_REPORT_SCHEMA_VERSION = "tkr-character-project-report-v1"
CHARACTER_PROJECT_MANIFEST_SCHEMA_VERSION = "tkr-character-project-manifest-v1"
CHARACTER_PROJECT_VERIFICATION_SCHEMA_VERSION = "tkr-character-project-verification-v1"
CHARACTER_SQLITE_SCHEMA_VERSION = "tkr-character-sqlite-v1"

_DATA_FILES = (
    "characters.jsonl",
    "character-attributes.jsonl",
    "character-states.jsonl",
    "character-relationships.jsonl",
    "character-event-links.jsonl",
    "character-findings.jsonl",
)
_ALLOWED_FILES = set(_DATA_FILES) | {
    "character.sqlite",
    "character-project-report.json",
    "artifact-manifest.json",
}

T = TypeVar("T")


class CharacterProjectError(ValueError):
    """Raised when a Character Project cannot be built or verified safely."""


@dataclass(frozen=True, slots=True)
class CharacterProjectVerification:
    schema_version: str
    status: str
    valid: bool
    graph_valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    chapter_project_logical_sha256: str
    literary_project_ids: tuple[str, ...]
    event_project_logical_sha256: str
    annotation_sha256: str
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != CHARACTER_PROJECT_VERIFICATION_SCHEMA_VERSION:
            raise CharacterProjectError("character verification schema mismatch")
        if self.valid != (not self.reason_codes):
            raise CharacterProjectError("character verification validity mismatch")
        if any((
            self.project_acceptance_performed,
            self.may_accept_project,
            self.may_release,
            self.may_freeze,
        )):
            raise CharacterProjectError("character verification cannot grant release authority")

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
        raise CharacterProjectError(f"{label} must be a safe directory")


def _load_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise CharacterProjectError(f"{label} is not a safe regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CharacterProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise CharacterProjectError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise CharacterProjectError(f"{label} is not a safe regular file")
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise CharacterProjectError(f"blank {label} record at line {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CharacterProjectError(
                    f"invalid {label} JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise CharacterProjectError(
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
        raise CharacterProjectError("character manifest files must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for row in raw:
        if not isinstance(row, dict):
            raise CharacterProjectError("character manifest file entry must be an object")
        path = _safe_relative(row.get("path"))
        if path is None or path in result:
            raise CharacterProjectError("character manifest contains invalid or duplicate path")
        result[path] = row
    return result


def _tuple_fields(data: dict[str, object], fields: Sequence[str], label: str) -> dict[str, object]:
    result = dict(data)
    for field in fields:
        value = result.get(field, [])
        if not isinstance(value, list):
            raise CharacterProjectError(f"{label}.{field} must be a JSON array")
        result[field] = tuple(value)
    return result


def _construct(cls: type[T], record: Mapping[str, object], fields: Sequence[str], label: str) -> T:
    try:
        return cls(**_tuple_fields(dict(record), fields, label))
    except (TypeError, CharacterEngineError) as exc:
        raise CharacterProjectError(f"invalid {label}: {exc}") from exc


def _annotation_records(
    path: Path,
) -> tuple[
    list[FocusedCharacter],
    list[CharacterAttribute],
    list[CharacterState],
    list[CharacterRelationship],
    list[CharacterEventLink],
    str,
]:
    if path.is_symlink() or not path.is_file():
        raise CharacterProjectError("character annotation must be a safe regular file")
    digest = sha256_file(path)
    characters: list[FocusedCharacter] = []
    attributes: list[CharacterAttribute] = []
    states: list[CharacterState] = []
    relationships: list[CharacterRelationship] = []
    links: list[CharacterEventLink] = []
    for row in _load_jsonl(path, "character annotation"):
        if row.get("schema_version") != CHARACTER_ANNOTATION_SCHEMA_VERSION:
            raise CharacterProjectError("character annotation envelope schema mismatch")
        record_type = row.get("record_type")
        record = row.get("record")
        if not isinstance(record_type, str) or not isinstance(record, dict):
            raise CharacterProjectError("character annotation requires record_type and record")
        if record_type == "character":
            characters.append(_construct(
                FocusedCharacter,
                record,
                ("aliases", "selection_reasons", "evidence_anchor_ids", "limitations"),
                "character",
            ))
        elif record_type == "attribute":
            attributes.append(_construct(
                CharacterAttribute,
                record,
                ("assertion_ids", "evidence_anchor_ids", "supporting_attribute_ids", "limitations"),
                "character attribute",
            ))
        elif record_type == "state":
            states.append(_construct(
                CharacterState,
                record,
                ("assertion_ids", "evidence_anchor_ids", "limitations"),
                "character state",
            ))
        elif record_type == "relationship":
            relationships.append(_construct(
                CharacterRelationship,
                record,
                (
                    "change_event_ids", "assertion_ids", "evidence_anchor_ids",
                    "supporting_relationship_ids", "limitations",
                ),
                "character relationship",
            ))
        elif record_type == "event_link":
            links.append(_construct(
                CharacterEventLink,
                record,
                ("assertion_ids", "evidence_anchor_ids", "limitations"),
                "character event link",
            ))
        else:
            raise CharacterProjectError(f"unsupported character annotation type: {record_type}")
    return characters, attributes, states, relationships, links, digest


def _chapter_context(
    chapter_project: Path,
    source_projects: Sequence[Path],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    verification = verify_chapter_project(source_projects, chapter_project)
    if not verification.valid:
        raise CharacterProjectError(
            "chapter project failed verification: " + ",".join(verification.reason_codes)
        )
    report = _load_object(chapter_project / "chapter-project-report.json", "chapter report")
    chapters = {
        str(row["chapter_id"]): row
        for row in _load_jsonl(chapter_project / "chapters.jsonl", "chapter records")
        if isinstance(row.get("chapter_id"), str)
    }
    return chapters, report


def _literary_context(
    literary_projects: Sequence[Path],
) -> tuple[set[str], set[str], tuple[str, ...], tuple[str, ...]]:
    if not literary_projects:
        raise CharacterProjectError("at least one literary project is required")
    assertion_ids: set[str] = set()
    evidence_ids: set[str] = set()
    project_ids: list[str] = []
    logical_hashes: list[str] = []
    for index, project in enumerate(literary_projects):
        _safe_directory(project, f"literary project {index}")
        verification = verify_literary_engine(project)
        if not verification.valid:
            raise CharacterProjectError(
                "literary project failed verification: " + ",".join(verification.reason_codes)
            )
        report = _load_object(project / "literary-report.json", "literary report")
        project_id = report.get("project_id")
        logical_sha = report.get("logical_sha256")
        if not isinstance(project_id, str) or not project_id:
            raise CharacterProjectError("literary report omits project_id")
        if not isinstance(logical_sha, str) or len(logical_sha) != 64:
            raise CharacterProjectError("literary report omits logical_sha256")
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
        raise CharacterProjectError("literary project IDs must be unique")
    return assertion_ids, evidence_ids, tuple(project_ids), tuple(logical_hashes)


def _event_context(
    chapter_project: Path,
    source_projects: Sequence[Path],
    literary_projects: Sequence[Path],
    event_project: Path,
    event_annotations: Path,
) -> tuple[set[str], dict[str, object]]:
    verification = verify_event_project(
        chapter_project,
        source_projects,
        literary_projects,
        event_annotations,
        event_project,
    )
    if not verification.valid:
        raise CharacterProjectError(
            "event project failed verification: " + ",".join(verification.reason_codes)
        )
    report = _load_object(event_project / "event-project-report.json", "event report")
    event_ids = {
        str(row["event_id"])
        for row in _load_jsonl(event_project / "events.jsonl", "event records")
        if isinstance(row.get("event_id"), str)
    }
    return event_ids, report


def _bind_interval(
    label: str,
    record_id: str,
    start_chapter_id: str,
    end_chapter_id: str,
    start_position: int,
    end_position: int,
    chapters: Mapping[str, Mapping[str, object]],
) -> None:
    start = chapters.get(start_chapter_id)
    end = chapters.get(end_chapter_id)
    if start is None or end is None:
        raise CharacterProjectError(f"{label} references unknown chapter: {record_id}")
    if start.get("global_physical_order") != start_position:
        raise CharacterProjectError(f"{label} start position differs from Chapter Project: {record_id}")
    if end.get("global_physical_order") != end_position:
        raise CharacterProjectError(f"{label} end position differs from Chapter Project: {record_id}")
    if start.get("contamination_status") != "clean" or end.get("contamination_status") != "clean":
        raise CharacterProjectError(f"active {label} cannot bind contaminated chapter: {record_id}")


def _bind_positions(
    characters: Sequence[FocusedCharacter],
    attributes: Sequence[CharacterAttribute],
    states: Sequence[CharacterState],
    relationships: Sequence[CharacterRelationship],
    chapters: Mapping[str, Mapping[str, object]],
) -> None:
    for item in characters:
        if item.review_status in {"active", "contested"}:
            _bind_interval(
                "character", item.character_id, item.first_chapter_id, item.last_chapter_id,
                item.first_position, item.last_position, chapters,
            )
    for label, records in (
        ("attribute", attributes),
        ("state", states),
        ("relationship", relationships),
    ):
        for item in records:
            if item.status in {"active", "contested"}:
                _bind_interval(
                    label,
                    getattr(item, f"{label}_id") if label != "attribute" else item.attribute_id,
                    item.start_chapter_id,
                    item.end_chapter_id,
                    item.start_position,
                    item.end_position,
                    chapters,
                )


def _payloads(graph: CharacterGraph) -> dict[str, bytes]:
    return {
        "characters.jsonl": _jsonl_bytes(graph.characters),
        "character-attributes.jsonl": _jsonl_bytes(graph.attributes),
        "character-states.jsonl": _jsonl_bytes(graph.states),
        "character-relationships.jsonl": _jsonl_bytes(graph.relationships),
        "character-event-links.jsonl": _jsonl_bytes(graph.event_links),
        "character-findings.jsonl": _jsonl_bytes(graph.findings),
    }


def _logical_hash(
    payloads: Mapping[str, bytes],
    chapter_sha: str,
    literary_hashes: Sequence[str],
    event_sha: str,
    annotation_sha: str,
) -> str:
    digest = sha256()
    digest.update(CHARACTER_ENGINE_VERSION.encode("utf-8"))
    digest.update(chapter_sha.encode("utf-8"))
    digest.update(event_sha.encode("utf-8"))
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


def _create_database(path: Path, graph: CharacterGraph, metadata: Mapping[str, str]) -> None:
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
            CREATE TABLE characters(
                character_id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                first_chapter_id TEXT NOT NULL,
                last_chapter_id TEXT NOT NULL,
                first_position INTEGER NOT NULL,
                last_position INTEGER NOT NULL,
                review_status TEXT NOT NULL,
                selection_reasons_json TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE TABLE aliases(
                character_id TEXT NOT NULL REFERENCES characters(character_id),
                alias TEXT NOT NULL,
                PRIMARY KEY(character_id,alias)
            );
            CREATE TABLE character_evidence(
                character_id TEXT NOT NULL REFERENCES characters(character_id),
                anchor_id TEXT NOT NULL,
                PRIMARY KEY(character_id,anchor_id)
            );
            CREATE TABLE attributes(
                attribute_id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL REFERENCES characters(character_id),
                character_scope TEXT NOT NULL,
                attribute_type TEXT NOT NULL,
                tier TEXT NOT NULL,
                value TEXT NOT NULL,
                start_chapter_id TEXT NOT NULL,
                end_chapter_id TEXT NOT NULL,
                start_position INTEGER NOT NULL,
                end_position INTEGER NOT NULL,
                confidence REAL NOT NULL,
                attribution TEXT NOT NULL,
                status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX attribute_character_type ON attributes(character_id,attribute_type,start_position);
            CREATE TABLE attribute_assertions(attribute_id TEXT NOT NULL REFERENCES attributes(attribute_id), assertion_id TEXT NOT NULL, PRIMARY KEY(attribute_id,assertion_id));
            CREATE TABLE attribute_evidence(attribute_id TEXT NOT NULL REFERENCES attributes(attribute_id), anchor_id TEXT NOT NULL, PRIMARY KEY(attribute_id,anchor_id));
            CREATE TABLE attribute_supports(attribute_id TEXT NOT NULL REFERENCES attributes(attribute_id), supporting_attribute_id TEXT NOT NULL REFERENCES attributes(attribute_id), PRIMARY KEY(attribute_id,supporting_attribute_id));
            CREATE TABLE states(
                state_id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL REFERENCES characters(character_id),
                state_type TEXT NOT NULL,
                state_value TEXT NOT NULL,
                start_chapter_id TEXT NOT NULL,
                end_chapter_id TEXT NOT NULL,
                start_position INTEGER NOT NULL,
                end_position INTEGER NOT NULL,
                tier TEXT NOT NULL,
                confidence REAL NOT NULL,
                attribution TEXT NOT NULL,
                status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX state_character_time ON states(character_id,state_type,start_position,end_position);
            CREATE TABLE state_assertions(state_id TEXT NOT NULL REFERENCES states(state_id), assertion_id TEXT NOT NULL, PRIMARY KEY(state_id,assertion_id));
            CREATE TABLE state_evidence(state_id TEXT NOT NULL REFERENCES states(state_id), anchor_id TEXT NOT NULL, PRIMARY KEY(state_id,anchor_id));
            CREATE TABLE relationships(
                relationship_id TEXT PRIMARY KEY,
                subject_character_id TEXT NOT NULL REFERENCES characters(character_id),
                object_character_id TEXT NOT NULL REFERENCES characters(character_id),
                relation_type TEXT NOT NULL,
                tier TEXT NOT NULL,
                start_chapter_id TEXT NOT NULL,
                end_chapter_id TEXT NOT NULL,
                start_position INTEGER NOT NULL,
                end_position INTEGER NOT NULL,
                confidence REAL NOT NULL,
                attribution TEXT NOT NULL,
                status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX relationship_time ON relationships(subject_character_id,object_character_id,start_position,end_position);
            CREATE TABLE relationship_events(relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id), event_id TEXT NOT NULL, PRIMARY KEY(relationship_id,event_id));
            CREATE TABLE relationship_assertions(relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id), assertion_id TEXT NOT NULL, PRIMARY KEY(relationship_id,assertion_id));
            CREATE TABLE relationship_evidence(relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id), anchor_id TEXT NOT NULL, PRIMARY KEY(relationship_id,anchor_id));
            CREATE TABLE relationship_supports(relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id), supporting_relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id), PRIMARY KEY(relationship_id,supporting_relationship_id));
            CREATE TABLE event_links(
                link_id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL REFERENCES characters(character_id),
                event_id TEXT NOT NULL,
                role TEXT NOT NULL,
                tier TEXT NOT NULL,
                confidence REAL NOT NULL,
                attribution TEXT NOT NULL,
                status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX event_link_character ON event_links(character_id,event_id,role);
            CREATE TABLE event_link_assertions(link_id TEXT NOT NULL REFERENCES event_links(link_id), assertion_id TEXT NOT NULL, PRIMARY KEY(link_id,assertion_id));
            CREATE TABLE event_link_evidence(link_id TEXT NOT NULL REFERENCES event_links(link_id), anchor_id TEXT NOT NULL, PRIMARY KEY(link_id,anchor_id));
            CREATE TABLE findings(
                finding_id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                signals_json TEXT NOT NULL,
                recommended_action TEXT NOT NULL
            );
            CREATE TABLE finding_characters(finding_id TEXT NOT NULL REFERENCES findings(finding_id), character_id TEXT NOT NULL, PRIMARY KEY(finding_id,character_id));
            CREATE TABLE finding_records(finding_id TEXT NOT NULL REFERENCES findings(finding_id), record_id TEXT NOT NULL, PRIMARY KEY(finding_id,record_id));
            """
        )
        connection.executemany("INSERT INTO metadata VALUES(?,?)", sorted(metadata.items()))
        for item in graph.characters:
            connection.execute(
                "INSERT INTO characters VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    item.character_id, item.canonical_name, item.scope,
                    item.first_chapter_id, item.last_chapter_id,
                    item.first_position, item.last_position, item.review_status,
                    _canonical_json(list(item.selection_reasons)),
                    _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany(
                "INSERT INTO aliases VALUES(?,?)",
                [(item.character_id, value) for value in item.aliases],
            )
            connection.executemany(
                "INSERT INTO character_evidence VALUES(?,?)",
                [(item.character_id, value) for value in item.evidence_anchor_ids],
            )
        for item in graph.attributes:
            connection.execute(
                "INSERT INTO attributes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.attribute_id, item.character_id, item.character_scope,
                    item.attribute_type, item.tier, item.value,
                    item.start_chapter_id, item.end_chapter_id,
                    item.start_position, item.end_position, item.confidence,
                    item.attribution, item.status, _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany("INSERT INTO attribute_assertions VALUES(?,?)", [(item.attribute_id, value) for value in item.assertion_ids])
            connection.executemany("INSERT INTO attribute_evidence VALUES(?,?)", [(item.attribute_id, value) for value in item.evidence_anchor_ids])
        for item in graph.attributes:
            connection.executemany("INSERT INTO attribute_supports VALUES(?,?)", [(item.attribute_id, value) for value in item.supporting_attribute_ids])
        for item in graph.states:
            connection.execute(
                "INSERT INTO states VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.state_id, item.character_id, item.state_type, item.state_value,
                    item.start_chapter_id, item.end_chapter_id,
                    item.start_position, item.end_position, item.tier, item.confidence,
                    item.attribution, item.status, _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany("INSERT INTO state_assertions VALUES(?,?)", [(item.state_id, value) for value in item.assertion_ids])
            connection.executemany("INSERT INTO state_evidence VALUES(?,?)", [(item.state_id, value) for value in item.evidence_anchor_ids])
        for item in graph.relationships:
            connection.execute(
                "INSERT INTO relationships VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.relationship_id, item.subject_character_id,
                    item.object_character_id, item.relation_type, item.tier,
                    item.start_chapter_id, item.end_chapter_id,
                    item.start_position, item.end_position, item.confidence,
                    item.attribution, item.status, _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany("INSERT INTO relationship_events VALUES(?,?)", [(item.relationship_id, value) for value in item.change_event_ids])
            connection.executemany("INSERT INTO relationship_assertions VALUES(?,?)", [(item.relationship_id, value) for value in item.assertion_ids])
            connection.executemany("INSERT INTO relationship_evidence VALUES(?,?)", [(item.relationship_id, value) for value in item.evidence_anchor_ids])
        for item in graph.relationships:
            connection.executemany("INSERT INTO relationship_supports VALUES(?,?)", [(item.relationship_id, value) for value in item.supporting_relationship_ids])
        for item in graph.event_links:
            connection.execute(
                "INSERT INTO event_links VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    item.link_id, item.character_id, item.event_id, item.role,
                    item.tier, item.confidence, item.attribution, item.status,
                    _canonical_json(list(item.limitations)),
                ),
            )
            connection.executemany("INSERT INTO event_link_assertions VALUES(?,?)", [(item.link_id, value) for value in item.assertion_ids])
            connection.executemany("INSERT INTO event_link_evidence VALUES(?,?)", [(item.link_id, value) for value in item.evidence_anchor_ids])
        for item in graph.findings:
            connection.execute(
                "INSERT INTO findings VALUES(?,?,?,?,?)",
                (
                    item.finding_id, item.rule_id, item.severity,
                    _canonical_json(list(item.signals)), item.recommended_action,
                ),
            )
            connection.executemany("INSERT INTO finding_characters VALUES(?,?)", [(item.finding_id, value) for value in item.character_ids])
            connection.executemany("INSERT INTO finding_records VALUES(?,?)", [(item.finding_id, value) for value in item.record_ids])
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise CharacterProjectError("character SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise CharacterProjectError("character SQLite foreign key check failed")
    finally:
        connection.close()


def _install(temporary: Path, output: Path, replace_existing: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace_existing:
        raise CharacterProjectError(f"output directory already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise CharacterProjectError("existing output directory is unsafe")
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
    event_project: Path,
    event_annotations: Path,
    character_annotations: Path,
) -> tuple[
    CharacterGraph,
    dict[str, object],
    tuple[str, ...],
    tuple[str, ...],
    dict[str, object],
    str,
]:
    chapters, chapter_report = _chapter_context(chapter_project, source_projects)
    assertion_ids, evidence_ids, literary_ids, literary_hashes = _literary_context(literary_projects)
    event_ids, event_report = _event_context(
        chapter_project, source_projects, literary_projects, event_project, event_annotations
    )
    characters, attributes, states, relationships, links, annotation_sha = _annotation_records(
        character_annotations
    )
    _bind_positions(characters, attributes, states, relationships, chapters)
    graph = build_character_graph(
        characters,
        attributes,
        states,
        relationships,
        links,
        known_assertion_ids=assertion_ids,
        known_evidence_anchor_ids=evidence_ids,
        known_event_ids=event_ids,
        event_graph_valid=event_report.get("graph_valid") is True,
    )
    if graph.report.unsupported_reference_count:
        raise CharacterProjectError("character graph contains unsupported references")
    return graph, chapter_report, literary_ids, literary_hashes, event_report, annotation_sha


def build_character_project(
    chapter_project: str | Path,
    source_projects: Sequence[str | Path],
    literary_projects: Sequence[str | Path],
    event_project: str | Path,
    event_annotations: str | Path,
    character_annotations: str | Path,
    output_directory: str | Path,
    *,
    replace_existing: bool = False,
) -> dict[str, object]:
    graph, chapter_report, literary_ids, literary_hashes, event_report, annotation_sha = _build_graph(
        Path(chapter_project),
        [Path(value) for value in source_projects],
        [Path(value) for value in literary_projects],
        Path(event_project),
        Path(event_annotations),
        Path(character_annotations),
    )
    chapter_sha = str(chapter_report.get("logical_sha256", ""))
    event_sha = str(event_report.get("logical_sha256", ""))
    if len(chapter_sha) != 64 or len(event_sha) != 64:
        raise CharacterProjectError("input project logical hashes are invalid")
    output = Path(output_directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        payloads = _payloads(graph)
        logical_sha = _logical_hash(payloads, chapter_sha, literary_hashes, event_sha, annotation_sha)
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        metadata = {
            "character_engine_version": CHARACTER_ENGINE_VERSION,
            "character_sqlite_schema_version": CHARACTER_SQLITE_SCHEMA_VERSION,
            "logical_sha256": logical_sha,
            "chapter_project_logical_sha256": chapter_sha,
            "event_project_logical_sha256": event_sha,
            "literary_project_ids_json": _canonical_json(list(literary_ids)),
            "annotation_sha256": annotation_sha,
            "graph_valid": str(int(graph.report.graph_valid)),
        }
        database = temporary / "character.sqlite"
        _create_database(database, graph, metadata)
        database_sha = sha256_file(database)
        report: dict[str, object] = {
            "schema_version": CHARACTER_PROJECT_REPORT_SCHEMA_VERSION,
            "status": "completed" if graph.report.graph_valid else "review_required",
            "character_engine_version": CHARACTER_ENGINE_VERSION,
            "character_sqlite_schema_version": CHARACTER_SQLITE_SCHEMA_VERSION,
            "chapter_project_logical_sha256": chapter_sha,
            "literary_project_ids": list(literary_ids),
            "literary_project_logical_sha256": list(literary_hashes),
            "event_project_logical_sha256": event_sha,
            "event_graph_valid": event_report.get("graph_valid") is True,
            "annotation_sha256": annotation_sha,
            **graph.report.to_dict(),
            "logical_sha256": logical_sha,
            "database_sha256": database_sha,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        report["schema_version"] = CHARACTER_PROJECT_REPORT_SCHEMA_VERSION
        report["status"] = "completed" if graph.report.graph_valid else "review_required"
        _write_atomic(temporary / "character-project-report.json", _json_bytes(report))
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
            "schema_version": CHARACTER_PROJECT_MANIFEST_SCHEMA_VERSION,
            "character_engine_version": CHARACTER_ENGINE_VERSION,
            "chapter_project_logical_sha256": chapter_sha,
            "event_project_logical_sha256": event_sha,
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


def verify_character_project(
    chapter_project: str | Path,
    source_projects: Sequence[str | Path],
    literary_projects: Sequence[str | Path],
    event_project: str | Path,
    event_annotations: str | Path,
    character_annotations: str | Path,
    character_project: str | Path,
) -> CharacterProjectVerification:
    root = Path(character_project)
    reasons: list[str] = []
    checked = 0
    graph_valid = False
    chapter_sha = ""
    literary_ids: tuple[str, ...] = ()
    event_sha = ""
    annotation_sha = ""
    logical_sha = ""
    database_sha = ""
    try:
        _safe_directory(root, "character project")
        report = _load_object(root / "character-project-report.json", "character report")
        manifest = _load_object(root / "artifact-manifest.json", "character manifest")
        graph_valid = report.get("graph_valid") is True
        chapter_sha = str(report.get("chapter_project_logical_sha256", ""))
        event_sha = str(report.get("event_project_logical_sha256", ""))
        annotation_sha = str(report.get("annotation_sha256", ""))
        logical_sha = str(report.get("logical_sha256", ""))
        database_sha = str(report.get("database_sha256", ""))
        literary_raw = report.get("literary_project_ids", [])
        if isinstance(literary_raw, list) and all(isinstance(value, str) for value in literary_raw):
            literary_ids = tuple(literary_raw)
        else:
            reasons.append("CHARACTER_LITERARY_PROJECT_IDS_INVALID")
        if report.get("schema_version") != CHARACTER_PROJECT_REPORT_SCHEMA_VERSION:
            reasons.append("CHARACTER_REPORT_SCHEMA_MISMATCH")
        if manifest.get("schema_version") != CHARACTER_PROJECT_MANIFEST_SCHEMA_VERSION:
            reasons.append("CHARACTER_MANIFEST_SCHEMA_MISMATCH")
        if report.get("character_engine_version") != CHARACTER_ENGINE_VERSION:
            reasons.append("CHARACTER_ENGINE_VERSION_MISMATCH")
        if manifest.get("logical_sha256") != logical_sha:
            reasons.append("CHARACTER_MANIFEST_LOGICAL_HASH_MISMATCH")
        files = _file_map(manifest)
        if set(files) != _ALLOWED_FILES - {"artifact-manifest.json"}:
            reasons.append("CHARACTER_MANIFEST_FILE_SET_MISMATCH")
        actual_names = {
            path.name for path in root.iterdir() if path.is_file() and not path.is_symlink()
        }
        if actual_names != _ALLOWED_FILES:
            reasons.append("CHARACTER_DIRECTORY_FILE_SET_MISMATCH")
        for name, row in files.items():
            path = root / name
            if path.is_symlink() or not path.is_file():
                reasons.append(f"CHARACTER_FILE_UNSAFE:{name}")
                continue
            checked += 1
            if row.get("size_bytes") != path.stat().st_size:
                reasons.append(f"CHARACTER_FILE_SIZE_MISMATCH:{name}")
            if row.get("sha256") != sha256_file(path):
                reasons.append(f"CHARACTER_FILE_HASH_MISMATCH:{name}")
        graph, chapter_report, expected_literary_ids, literary_hashes, event_report, expected_annotation_sha = _build_graph(
            Path(chapter_project),
            [Path(value) for value in source_projects],
            [Path(value) for value in literary_projects],
            Path(event_project),
            Path(event_annotations),
            Path(character_annotations),
        )
        expected_chapter_sha = str(chapter_report.get("logical_sha256", ""))
        expected_event_sha = str(event_report.get("logical_sha256", ""))
        expected_payloads = _payloads(graph)
        expected_logical = _logical_hash(
            expected_payloads,
            expected_chapter_sha,
            literary_hashes,
            expected_event_sha,
            expected_annotation_sha,
        )
        if expected_chapter_sha != chapter_sha:
            reasons.append("CHARACTER_CHAPTER_PROJECT_BINDING_MISMATCH")
        if expected_event_sha != event_sha:
            reasons.append("CHARACTER_EVENT_PROJECT_BINDING_MISMATCH")
        if expected_literary_ids != literary_ids:
            reasons.append("CHARACTER_LITERARY_PROJECT_BINDING_MISMATCH")
        if expected_annotation_sha != annotation_sha:
            reasons.append("CHARACTER_ANNOTATION_HASH_MISMATCH")
        if expected_logical != logical_sha:
            reasons.append("CHARACTER_REBUILT_LOGICAL_HASH_MISMATCH")
        for name, data in expected_payloads.items():
            path = root / name
            if path.is_file() and path.read_bytes() != data:
                reasons.append(f"CHARACTER_REBUILT_ARTIFACT_MISMATCH:{name}")
        if graph.report.graph_valid != graph_valid:
            reasons.append("CHARACTER_GRAPH_VALIDITY_MISMATCH")
        database = root / "character.sqlite"
        actual_database_sha = sha256_file(database) if database.is_file() else ""
        if actual_database_sha != database_sha or manifest.get("database_sha256") != database_sha:
            reasons.append("CHARACTER_DATABASE_HASH_MISMATCH")
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                reasons.append("CHARACTER_SQLITE_INTEGRITY_FAILED")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                reasons.append("CHARACTER_SQLITE_FOREIGN_KEY_FAILED")
            metadata = dict(connection.execute("SELECT key,value FROM metadata"))
            if metadata.get("character_engine_version") != CHARACTER_ENGINE_VERSION:
                reasons.append("CHARACTER_SQLITE_ENGINE_VERSION_MISMATCH")
            if metadata.get("logical_sha256") != logical_sha:
                reasons.append("CHARACTER_SQLITE_LOGICAL_HASH_MISMATCH")
            specs = (
                ("characters", "character_id", [item.character_id for item in graph.characters]),
                ("attributes", "attribute_id", [item.attribute_id for item in graph.attributes]),
                ("states", "state_id", [item.state_id for item in graph.states]),
                ("relationships", "relationship_id", [item.relationship_id for item in graph.relationships]),
                ("event_links", "link_id", [item.link_id for item in graph.event_links]),
                ("findings", "finding_id", [item.finding_id for item in graph.findings]),
            )
            for table, column, expected_ids in specs:
                actual_ids = [
                    str(row[0]) for row in connection.execute(
                        f"SELECT {column} FROM {table} ORDER BY {column}"
                    )
                ]
                if actual_ids != sorted(expected_ids):
                    reasons.append(f"CHARACTER_SQLITE_IDENTIFIER_MISMATCH:{table}")
        finally:
            connection.close()
    except Exception as exc:
        reasons.extend(("CHARACTER_VERIFICATION_EXCEPTION", type(exc).__name__))
    unique_reasons = tuple(dict.fromkeys(reasons))
    return CharacterProjectVerification(
        CHARACTER_PROJECT_VERIFICATION_SCHEMA_VERSION,
        "verified" if not unique_reasons else "rejected",
        not unique_reasons,
        graph_valid,
        unique_reasons,
        checked,
        chapter_sha,
        literary_ids,
        event_sha,
        annotation_sha,
        logical_sha,
        database_sha,
    )


__all__ = [
    "CHARACTER_ANNOTATION_SCHEMA_VERSION",
    "CHARACTER_PROJECT_MANIFEST_SCHEMA_VERSION",
    "CHARACTER_PROJECT_REPORT_SCHEMA_VERSION",
    "CHARACTER_PROJECT_VERIFICATION_SCHEMA_VERSION",
    "CHARACTER_SQLITE_SCHEMA_VERSION",
    "CharacterProjectError",
    "CharacterProjectVerification",
    "build_character_project",
    "verify_character_project",
]
