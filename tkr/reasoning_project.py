"""Build and verify immutable Stage 5 Layered Reasoning projects."""
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
from .character_project import verify_character_project
from .evidence_project import verify_evidence_project
from .event_project import verify_event_project
from .hashing import sha256_file
from .literary_engine import verify_literary_engine
from .reasoning_engine import (
    REASONING_ENGINE_VERSION,
    ReasoningEdge,
    ReasoningEngineError,
    ReasoningGraph,
    ReasoningNode,
    build_reasoning_graph,
)

REASONING_ANNOTATION_SCHEMA_VERSION = "tkr-reasoning-annotation-v1"
REASONING_PROJECT_SCHEMA_VERSION = "tkr-reasoning-project-v1"
REASONING_PROJECT_REPORT_SCHEMA_VERSION = "tkr-reasoning-project-report-v1"
REASONING_PROJECT_MANIFEST_SCHEMA_VERSION = "tkr-reasoning-project-manifest-v1"
REASONING_PROJECT_VERIFICATION_SCHEMA_VERSION = "tkr-reasoning-project-verification-v1"
REASONING_SQLITE_SCHEMA_VERSION = "tkr-reasoning-sqlite-v1"

_DATA_FILES = (
    "reasoning-nodes.jsonl",
    "reasoning-edges.jsonl",
    "reasoning-findings.jsonl",
)
_ALLOWED_FILES = set(_DATA_FILES) | {
    "reasoning.sqlite",
    "reasoning-project-report.json",
    "artifact-manifest.json",
}
T = TypeVar("T")
EvidenceBinding = tuple[Path, Path, Path]


class ReasoningProjectError(ValueError):
    """Raised when a Reasoning Project cannot be built or verified safely."""


@dataclass(frozen=True, slots=True)
class ReasoningProjectBuildResult:
    schema_version: str
    status: str
    reasoning_engine_version: str
    output_directory: str
    node_count: int
    edge_count: int
    finding_count: int
    blocking_finding_count: int
    layer_counts: dict[str, int]
    graph_valid: bool
    chapter_project_logical_sha256: str
    literary_project_ids: tuple[str, ...]
    evidence_project_logical_sha256s: tuple[str, ...]
    event_project_logical_sha256: str
    character_project_logical_sha256: str
    annotation_sha256: str
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != REASONING_PROJECT_REPORT_SCHEMA_VERSION:
            raise ReasoningProjectError("reasoning project report schema mismatch")
        if self.status not in {"completed", "review_required"}:
            raise ReasoningProjectError("reasoning project status is invalid")
        if self.graph_valid != (self.status == "completed"):
            raise ReasoningProjectError("reasoning project status and graph validity disagree")
        for name in ("node_count", "edge_count", "finding_count", "blocking_finding_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReasoningProjectError(f"{name} must be a non-negative integer")
        if any((
            self.project_acceptance_performed,
            self.may_accept_project,
            self.may_release,
            self.may_freeze,
        )):
            raise ReasoningProjectError("reasoning project cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["literary_project_ids"] = list(self.literary_project_ids)
        payload["evidence_project_logical_sha256s"] = list(
            self.evidence_project_logical_sha256s
        )
        return payload


@dataclass(frozen=True, slots=True)
class ReasoningProjectVerification:
    schema_version: str
    status: str
    valid: bool
    graph_valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != REASONING_PROJECT_VERIFICATION_SCHEMA_VERSION:
            raise ReasoningProjectError("reasoning verification schema mismatch")
        if self.valid != (not self.reason_codes):
            raise ReasoningProjectError("reasoning verification validity mismatch")
        if any((
            self.project_acceptance_performed,
            self.may_accept_project,
            self.may_release,
            self.may_freeze,
        )):
            raise ReasoningProjectError("reasoning verification cannot grant authority")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True, slots=True)
class _UpstreamContext:
    chapter_logical: str
    literary_project_ids: tuple[str, ...]
    literary_logicals: tuple[str, ...]
    evidence_logicals: tuple[str, ...]
    event_logical: str
    character_logical: str
    known_record_ids: frozenset[str]
    known_evidence_ids: frozenset[str]
    evidence_by_record: Mapping[str, frozenset[str]]
    evidence_rows: Mapping[str, Mapping[str, object]]
    upstream_rows: Mapping[str, Mapping[str, object]]


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
        raise ReasoningProjectError(f"{label} must be a safe directory")


def _safe_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ReasoningProjectError(f"{label} must be a safe regular file")


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        return None
    return value


def _load_object(path: Path, label: str) -> dict[str, object]:
    _safe_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReasoningProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReasoningProjectError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, object]]:
    _safe_file(path, label)
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ReasoningProjectError(f"blank {label} record at line {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReasoningProjectError(
                    f"invalid {label} JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise ReasoningProjectError(
                    f"{label} record at line {line_number} must be an object"
                )
            rows.append(value)
    return rows


def _tuple_fields(data: dict[str, object], fields: Sequence[str], label: str) -> dict[str, object]:
    result = dict(data)
    for field in fields:
        value = result.get(field, [])
        if not isinstance(value, list):
            raise ReasoningProjectError(f"{label}.{field} must be a JSON array")
        result[field] = tuple(value)
    return result


def _construct(cls: type[T], row: Mapping[str, object], fields: Sequence[str], label: str) -> T:
    try:
        return cls(**_tuple_fields(dict(row), fields, label))
    except (TypeError, ReasoningEngineError) as exc:
        raise ReasoningProjectError(f"invalid {label}: {exc}") from exc


def _annotation_records(path: Path) -> tuple[list[ReasoningNode], list[ReasoningEdge], str]:
    _safe_file(path, "reasoning annotation")
    digest = sha256_file(path)
    nodes: list[ReasoningNode] = []
    edges: list[ReasoningEdge] = []
    for envelope in _load_jsonl(path, "reasoning annotation"):
        if envelope.get("schema_version") != REASONING_ANNOTATION_SCHEMA_VERSION:
            raise ReasoningProjectError("reasoning annotation envelope schema mismatch")
        record_type = envelope.get("record_type")
        record = envelope.get("record")
        if not isinstance(record_type, str) or not isinstance(record, dict):
            raise ReasoningProjectError("reasoning annotation requires record_type and record")
        if record_type == "node":
            nodes.append(_construct(
                ReasoningNode,
                record,
                (
                    "intent_tags", "chapter_ids", "entity_ids", "event_ids",
                    "upstream_record_ids", "support_node_ids", "evidence_anchor_ids",
                    "independence_groups", "limitations", "alternatives",
                ),
                "reasoning node",
            ))
        elif record_type == "edge":
            edges.append(_construct(
                ReasoningEdge,
                record,
                ("limitations",),
                "reasoning edge",
            ))
        else:
            raise ReasoningProjectError(f"unsupported reasoning annotation type: {record_type}")
    if not nodes:
        raise ReasoningProjectError("reasoning annotation must contain at least one node")
    return nodes, edges, digest


def _record_id(row: Mapping[str, object], candidates: Sequence[str]) -> str | None:
    for key in candidates:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _evidence_ids(row: Mapping[str, object]) -> frozenset[str]:
    values = row.get("evidence_anchor_ids", [])
    if not isinstance(values, list):
        return frozenset()
    return frozenset(value for value in values if isinstance(value, str) and value)


def _add_records(
    rows: Iterable[Mapping[str, object]],
    candidates: Sequence[str],
    upstream_rows: dict[str, Mapping[str, object]],
    evidence_by_record: dict[str, frozenset[str]],
) -> None:
    for row in rows:
        identifier = _record_id(row, candidates)
        if identifier is None:
            continue
        if identifier in upstream_rows:
            raise ReasoningProjectError(f"duplicate upstream record ID: {identifier}")
        upstream_rows[identifier] = dict(row)
        evidence_by_record[identifier] = _evidence_ids(row)


def _upstream_context(
    chapter_project: Path,
    source_projects: Sequence[Path],
    literary_projects: Sequence[Path],
    evidence_bindings: Sequence[EvidenceBinding],
    event_project: Path,
    event_annotations: Path,
    character_project: Path,
    character_annotations: Path,
) -> _UpstreamContext:
    if not source_projects or not literary_projects or not evidence_bindings:
        raise ReasoningProjectError(
            "Reasoning Project requires source, literary, and Evidence project inputs"
        )
    chapter_verification = verify_chapter_project(source_projects, chapter_project)
    if not chapter_verification.valid:
        raise ReasoningProjectError(
            "chapter project failed verification: " + ",".join(chapter_verification.reason_codes)
        )
    chapter_report = _load_object(chapter_project / "chapter-project-report.json", "chapter report")
    chapter_logical = chapter_report.get("logical_sha256")
    if not isinstance(chapter_logical, str) or len(chapter_logical) != 64:
        raise ReasoningProjectError("chapter report omits logical_sha256")

    upstream_rows: dict[str, Mapping[str, object]] = {}
    evidence_by_record: dict[str, frozenset[str]] = {}
    evidence_rows: dict[str, Mapping[str, object]] = {}
    literary_ids: list[str] = []
    literary_logicals: list[str] = []
    for index, project in enumerate(literary_projects):
        _safe_directory(project, f"literary project {index}")
        verification = verify_literary_engine(project)
        if not verification.valid:
            raise ReasoningProjectError(
                "literary project failed verification: " + ",".join(verification.reason_codes)
            )
        report = _load_object(project / "literary-report.json", "literary report")
        project_id = report.get("project_id")
        logical = report.get("logical_sha256")
        if not isinstance(project_id, str) or not project_id:
            raise ReasoningProjectError("literary report omits project_id")
        if not isinstance(logical, str) or len(logical) != 64:
            raise ReasoningProjectError("literary report omits logical_sha256")
        literary_ids.append(project_id)
        literary_logicals.append(logical)
        assertion_rows = _load_jsonl(project / "assertions.jsonl", "literary assertions")
        _add_records(assertion_rows, ("assertion_id",), upstream_rows, evidence_by_record)
        for row in _load_jsonl(project / "evidence-anchors.jsonl", "literary evidence"):
            anchor_id = row.get("anchor_id")
            if isinstance(anchor_id, str) and anchor_id:
                previous = evidence_rows.get(anchor_id)
                if previous is not None and previous != row:
                    raise ReasoningProjectError(f"conflicting evidence anchor ID: {anchor_id}")
                evidence_rows[anchor_id] = dict(row)
    if len(literary_ids) != len(set(literary_ids)):
        raise ReasoningProjectError("literary project IDs must be unique")

    evidence_logicals: list[str] = []
    for index, (source, literary, evidence_project) in enumerate(evidence_bindings):
        _safe_directory(evidence_project, f"Evidence project {index}")
        verification = verify_evidence_project(source, literary, evidence_project)
        if not verification.valid:
            raise ReasoningProjectError(
                "Evidence project failed verification: " + ",".join(verification.reason_codes)
            )
        report = _load_object(
            evidence_project / "evidence-project-report.json", "Evidence project report"
        )
        logical = report.get("logical_sha256")
        if not isinstance(logical, str) or len(logical) != 64:
            raise ReasoningProjectError("Evidence project report omits logical_sha256")
        evidence_logicals.append(logical)
        for row in _load_jsonl(
            evidence_project / "claim-evidence-anchors.jsonl", "Claim Evidence anchors"
        ):
            anchor_id = row.get("anchor_id")
            if isinstance(anchor_id, str) and anchor_id:
                previous = evidence_rows.get(anchor_id)
                if previous is not None and previous != row:
                    raise ReasoningProjectError(f"conflicting Evidence anchor ID: {anchor_id}")
                evidence_rows[anchor_id] = dict(row)

    event_verification = verify_event_project(
        chapter_project,
        source_projects,
        literary_projects,
        event_annotations,
        event_project,
    )
    if not event_verification.valid:
        raise ReasoningProjectError(
            "Event Project failed verification: " + ",".join(event_verification.reason_codes)
        )
    event_report = _load_object(event_project / "event-project-report.json", "event report")
    event_logical = event_report.get("logical_sha256")
    if not isinstance(event_logical, str) or len(event_logical) != 64:
        raise ReasoningProjectError("event report omits logical_sha256")
    if not bool(event_report.get("graph_valid")):
        raise ReasoningProjectError("review-required Event Project cannot support reasoning")
    _add_records(
        _load_jsonl(event_project / "events.jsonl", "events"),
        ("event_id",), upstream_rows, evidence_by_record,
    )
    _add_records(
        _load_jsonl(event_project / "event-components.jsonl", "event components"),
        ("component_id",), upstream_rows, evidence_by_record,
    )
    _add_records(
        _load_jsonl(event_project / "event-causal-edges.jsonl", "event edges"),
        ("edge_id",), upstream_rows, evidence_by_record,
    )

    character_verification = verify_character_project(
        chapter_project,
        source_projects,
        literary_projects,
        event_project,
        event_annotations,
        character_annotations,
        character_project,
    )
    if not character_verification.valid:
        raise ReasoningProjectError(
            "Character Project failed verification: "
            + ",".join(character_verification.reason_codes)
        )
    character_report = _load_object(
        character_project / "character-project-report.json", "character report"
    )
    character_logical = character_report.get("logical_sha256")
    if not isinstance(character_logical, str) or len(character_logical) != 64:
        raise ReasoningProjectError("character report omits logical_sha256")
    if not bool(character_report.get("graph_valid")):
        raise ReasoningProjectError("review-required Character Project cannot support reasoning")
    for filename, candidates in (
        ("characters.jsonl", ("character_id",)),
        ("character-attributes.jsonl", ("attribute_id",)),
        ("character-states.jsonl", ("state_id",)),
        ("character-relationships.jsonl", ("relationship_id",)),
        ("character-event-links.jsonl", ("link_id",)),
    ):
        _add_records(
            _load_jsonl(character_project / filename, filename),
            candidates,
            upstream_rows,
            evidence_by_record,
        )

    return _UpstreamContext(
        chapter_logical,
        tuple(literary_ids),
        tuple(literary_logicals),
        tuple(evidence_logicals),
        event_logical,
        character_logical,
        frozenset(upstream_rows),
        frozenset(evidence_rows),
        dict(evidence_by_record),
        dict(evidence_rows),
        dict(upstream_rows),
    )


def _anchor_group(row: Mapping[str, object]) -> str:
    source_id = row.get("source_id")
    chapter_id = row.get("chapter_id")
    if not isinstance(source_id, str) or not source_id:
        raise ReasoningProjectError("evidence anchor omits source_id")
    if not isinstance(chapter_id, str) or not chapter_id:
        raise ReasoningProjectError("evidence anchor omits chapter_id")
    return f"{source_id}:{chapter_id}"


def _validate_reasoning_bindings(nodes: Sequence[ReasoningNode], context: _UpstreamContext) -> None:
    by_id = {item.node_id: item for item in nodes}
    if len(by_id) != len(nodes):
        return  # duplicate IDs become graph findings
    for node in nodes:
        if node.layer == "A":
            bound: set[str] = set()
            for record_id in node.upstream_record_ids:
                bound.update(context.evidence_by_record.get(record_id, frozenset()))
            if not set(node.evidence_anchor_ids).issubset(bound):
                raise ReasoningProjectError(
                    f"layer A evidence is not bound to its upstream records: {node.node_id}"
                )
            groups = {
                _anchor_group(context.evidence_rows[anchor_id])
                for anchor_id in node.evidence_anchor_ids
                if anchor_id in context.evidence_rows
            }
            if groups != set(node.independence_groups):
                raise ReasoningProjectError(
                    f"layer A independence group differs from evidence lineage: {node.node_id}"
                )
        elif node.layer == "B" and all(value in by_id for value in node.support_node_ids):
            groups = {
                group
                for support_id in node.support_node_ids
                for group in by_id[support_id].independence_groups
            }
            if groups != set(node.independence_groups):
                raise ReasoningProjectError(
                    f"layer B independence groups differ from A supports: {node.node_id}"
                )


def _validate_support_edges(nodes: Sequence[ReasoningNode], edges: Sequence[ReasoningEdge]) -> None:
    edge_targets: dict[str, set[str]] = {}
    for edge in edges:
        if edge.status != "active" or edge.relation not in {
            "direct_support",
            "independent_support",
            "derived_from",
            "counterfactual_premise",
            "counterfactual_inference",
        }:
            continue
        edge_targets.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
    for node in nodes:
        if node.layer == "A":
            continue
        if edge_targets.get(node.node_id, set()) != set(node.support_node_ids):
            raise ReasoningProjectError(
                f"reasoning support edges differ from declared support nodes: {node.node_id}"
            )


def _payloads(graph: ReasoningGraph) -> dict[str, bytes]:
    return {
        "reasoning-nodes.jsonl": _jsonl_bytes(graph.nodes),
        "reasoning-edges.jsonl": _jsonl_bytes(graph.edges),
        "reasoning-findings.jsonl": _jsonl_bytes(graph.findings),
    }


def _logical_hash(
    payloads: Mapping[str, bytes], context: _UpstreamContext, annotation_sha: str
) -> str:
    digest = sha256()
    digest.update(REASONING_PROJECT_SCHEMA_VERSION.encode("utf-8"))
    for label, value in (
        ("chapter", context.chapter_logical),
        ("event", context.event_logical),
        ("character", context.character_logical),
        ("annotation", annotation_sha),
    ):
        digest.update(b"\0")
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
    for value in context.literary_logicals:
        digest.update(b"\0literary\0")
        digest.update(value.encode("utf-8"))
    for value in context.evidence_logicals:
        digest.update(b"\0evidence\0")
        digest.update(value.encode("utf-8"))
    for name in sorted(payloads):
        digest.update(b"\0file\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payloads[name])
    return digest.hexdigest()


def _create_database(path: Path, graph: ReasoningGraph, metadata: Mapping[str, str]) -> None:
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
            CREATE TABLE nodes(
                node_id TEXT PRIMARY KEY,
                layer TEXT NOT NULL,
                statement TEXT NOT NULL,
                confidence REAL NOT NULL,
                attribution TEXT NOT NULL,
                counterfactual_premise TEXT NOT NULL,
                inference_rule TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE node_intents(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_chapters(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_entities(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_events(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_upstream(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_supports(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL REFERENCES nodes(node_id), PRIMARY KEY(node_id,value));
            CREATE TABLE node_evidence(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_independence(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_limitations(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE node_alternatives(node_id TEXT NOT NULL REFERENCES nodes(node_id), value TEXT NOT NULL, PRIMARY KEY(node_id,value));
            CREATE TABLE edges(
                edge_id TEXT PRIMARY KEY,
                source_node_id TEXT NOT NULL REFERENCES nodes(node_id),
                relation TEXT NOT NULL,
                target_node_id TEXT NOT NULL REFERENCES nodes(node_id),
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                limitations_json TEXT NOT NULL
            );
            CREATE INDEX edge_source_relation ON edges(source_node_id,relation,target_node_id);
            CREATE TABLE findings(
                finding_id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                recommended_action TEXT NOT NULL,
                signals_json TEXT NOT NULL
            );
            CREATE TABLE finding_nodes(finding_id TEXT NOT NULL REFERENCES findings(finding_id), node_id TEXT NOT NULL, PRIMARY KEY(finding_id,node_id));
            CREATE TABLE finding_edges(finding_id TEXT NOT NULL REFERENCES findings(finding_id), edge_id TEXT NOT NULL, PRIMARY KEY(finding_id,edge_id));
            """
        )
        connection.executemany("INSERT INTO metadata VALUES(?,?)", sorted(metadata.items()))
        for item in graph.nodes:
            connection.execute(
                "INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?)",
                (
                    item.node_id, item.layer, item.statement, float(item.confidence),
                    item.attribution, item.counterfactual_premise, item.inference_rule,
                    item.status,
                ),
            )
        table_fields = (
            ("node_intents", "intent_tags"),
            ("node_chapters", "chapter_ids"),
            ("node_entities", "entity_ids"),
            ("node_events", "event_ids"),
            ("node_upstream", "upstream_record_ids"),
            ("node_supports", "support_node_ids"),
            ("node_evidence", "evidence_anchor_ids"),
            ("node_independence", "independence_groups"),
            ("node_limitations", "limitations"),
            ("node_alternatives", "alternatives"),
        )
        for item in graph.nodes:
            for table, field in table_fields:
                connection.executemany(
                    f"INSERT INTO {table} VALUES(?,?)",
                    [(item.node_id, value) for value in getattr(item, field)],
                )
        for item in graph.edges:
            connection.execute(
                "INSERT INTO edges VALUES(?,?,?,?,?,?,?)",
                (
                    item.edge_id, item.source_node_id, item.relation,
                    item.target_node_id, float(item.confidence), item.status,
                    _canonical_json(list(item.limitations)),
                ),
            )
        for item in graph.findings:
            connection.execute(
                "INSERT INTO findings VALUES(?,?,?,?,?)",
                (
                    item.finding_id, item.rule_id, item.severity,
                    item.recommended_action, _canonical_json(list(item.signals)),
                ),
            )
            connection.executemany(
                "INSERT INTO finding_nodes VALUES(?,?)",
                [(item.finding_id, value) for value in item.node_ids],
            )
            connection.executemany(
                "INSERT INTO finding_edges VALUES(?,?)",
                [(item.finding_id, value) for value in item.edge_ids],
            )
        connection.commit()
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ReasoningProjectError("reasoning SQLite foreign-key check failed")
        connection.execute("VACUUM")
    finally:
        connection.close()


def _install(temporary: Path, output: Path, replace_existing: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace_existing:
        raise ReasoningProjectError(f"output directory already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise ReasoningProjectError("existing output is unsafe")
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


def build_reasoning_project(
    chapter_project_directory: str | Path,
    source_project_directories: Sequence[str | Path],
    literary_project_directories: Sequence[str | Path],
    evidence_bindings: Sequence[tuple[str | Path, str | Path, str | Path]],
    event_project_directory: str | Path,
    event_annotations_path: str | Path,
    character_project_directory: str | Path,
    character_annotations_path: str | Path,
    reasoning_annotations_path: str | Path,
    output_directory: str | Path,
    *,
    replace_existing: bool = False,
) -> ReasoningProjectBuildResult:
    chapter_project = Path(chapter_project_directory)
    source_projects = tuple(Path(value) for value in source_project_directories)
    literary_projects = tuple(Path(value) for value in literary_project_directories)
    bindings = tuple((Path(a), Path(b), Path(c)) for a, b, c in evidence_bindings)
    event_project = Path(event_project_directory)
    event_annotations = Path(event_annotations_path)
    character_project = Path(character_project_directory)
    character_annotations = Path(character_annotations_path)
    reasoning_annotations = Path(reasoning_annotations_path)
    output = Path(output_directory)
    for path, label in (
        (chapter_project, "Chapter Project"),
        (event_project, "Event Project"),
        (character_project, "Character Project"),
    ):
        _safe_directory(path, label)
    for path, label in (
        (event_annotations, "event annotations"),
        (character_annotations, "character annotations"),
        (reasoning_annotations, "reasoning annotations"),
    ):
        _safe_file(path, label)
    if output.is_symlink():
        raise ReasoningProjectError("output path must not be a symbolic link")

    context = _upstream_context(
        chapter_project,
        source_projects,
        literary_projects,
        bindings,
        event_project,
        event_annotations,
        character_project,
        character_annotations,
    )
    nodes, edges, annotation_sha = _annotation_records(reasoning_annotations)
    _validate_reasoning_bindings(nodes, context)
    _validate_support_edges(nodes, edges)
    graph = build_reasoning_graph(
        nodes,
        edges,
        known_upstream_record_ids=context.known_record_ids,
        known_evidence_anchor_ids=context.known_evidence_ids,
    )
    payloads = _payloads(graph)
    logical = _logical_hash(payloads, context, annotation_sha)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        metadata = {
            "reasoning_project_schema_version": REASONING_PROJECT_SCHEMA_VERSION,
            "reasoning_sqlite_schema_version": REASONING_SQLITE_SCHEMA_VERSION,
            "reasoning_engine_version": REASONING_ENGINE_VERSION,
            "chapter_project_logical_sha256": context.chapter_logical,
            "event_project_logical_sha256": context.event_logical,
            "character_project_logical_sha256": context.character_logical,
            "annotation_sha256": annotation_sha,
            "logical_sha256": logical,
        }
        database_path = temporary / "reasoning.sqlite"
        _create_database(database_path, graph, metadata)
        database_hash = sha256_file(database_path)
        result = ReasoningProjectBuildResult(
            REASONING_PROJECT_REPORT_SCHEMA_VERSION,
            graph.report.status,
            REASONING_ENGINE_VERSION,
            str(output),
            graph.report.node_count,
            graph.report.edge_count,
            graph.report.finding_count,
            graph.report.blocking_finding_count,
            graph.report.layer_counts,
            graph.report.graph_valid,
            context.chapter_logical,
            context.literary_project_ids,
            context.evidence_logicals,
            context.event_logical,
            context.character_logical,
            annotation_sha,
            logical,
            database_hash,
        )
        report = {
            **result.to_dict(),
            "literary_logical_sha256s": list(context.literary_logicals),
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "reasoning-project-report.json", _json_bytes(report))
        entries = []
        for path in sorted(temporary.iterdir()):
            if path.is_file():
                entries.append({
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
        manifest = {
            "schema_version": REASONING_PROJECT_MANIFEST_SCHEMA_VERSION,
            "reasoning_project_schema_version": REASONING_PROJECT_SCHEMA_VERSION,
            "reasoning_engine_version": REASONING_ENGINE_VERSION,
            "chapter_project_logical_sha256": context.chapter_logical,
            "literary_project_ids": list(context.literary_project_ids),
            "literary_logical_sha256s": list(context.literary_logicals),
            "evidence_project_logical_sha256s": list(context.evidence_logicals),
            "event_project_logical_sha256": context.event_logical,
            "character_project_logical_sha256": context.character_logical,
            "annotation_sha256": annotation_sha,
            "logical_sha256": logical,
            "database_sha256": database_hash,
            "files": entries,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "artifact-manifest.json", _json_bytes(manifest))
        _install(temporary, output, replace_existing)
        return result
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _manifest_file_map(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ReasoningProjectError("reasoning manifest files must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReasoningProjectError("reasoning manifest entry must be an object")
        relative = _safe_relative(entry.get("path"))
        if relative is None or relative in result or relative == "artifact-manifest.json":
            raise ReasoningProjectError("reasoning manifest path is invalid")
        result[relative] = entry
    return result


def verify_reasoning_project(
    chapter_project_directory: str | Path,
    source_project_directories: Sequence[str | Path],
    literary_project_directories: Sequence[str | Path],
    evidence_bindings: Sequence[tuple[str | Path, str | Path, str | Path]],
    event_project_directory: str | Path,
    event_annotations_path: str | Path,
    character_project_directory: str | Path,
    character_annotations_path: str | Path,
    reasoning_annotations_path: str | Path,
    reasoning_project_directory: str | Path,
) -> ReasoningProjectVerification:
    root = Path(reasoning_project_directory)
    reasons: list[str] = []
    checked = 0
    logical = ""
    database_hash = ""
    graph_valid = False
    try:
        _safe_directory(root, "Reasoning Project")
        context = _upstream_context(
            Path(chapter_project_directory),
            tuple(Path(value) for value in source_project_directories),
            tuple(Path(value) for value in literary_project_directories),
            tuple((Path(a), Path(b), Path(c)) for a, b, c in evidence_bindings),
            Path(event_project_directory),
            Path(event_annotations_path),
            Path(character_project_directory),
            Path(character_annotations_path),
        )
        nodes, edges, annotation_sha = _annotation_records(Path(reasoning_annotations_path))
        _validate_reasoning_bindings(nodes, context)
        _validate_support_edges(nodes, edges)
        graph = build_reasoning_graph(
            nodes,
            edges,
            known_upstream_record_ids=context.known_record_ids,
            known_evidence_anchor_ids=context.known_evidence_ids,
        )
        graph_valid = graph.report.graph_valid
        expected_payloads = _payloads(graph)
        expected_logical = _logical_hash(expected_payloads, context, annotation_sha)

        manifest = _load_object(root / "artifact-manifest.json", "reasoning manifest")
        report = _load_object(root / "reasoning-project-report.json", "reasoning report")
        logical = str(manifest.get("logical_sha256", ""))
        database_hash = str(manifest.get("database_sha256", ""))
        if manifest.get("schema_version") != REASONING_PROJECT_MANIFEST_SCHEMA_VERSION:
            reasons.append("REASONING_MANIFEST_SCHEMA_MISMATCH")
        if report.get("schema_version") != REASONING_PROJECT_REPORT_SCHEMA_VERSION:
            reasons.append("REASONING_REPORT_SCHEMA_MISMATCH")
        if manifest.get("reasoning_engine_version") != REASONING_ENGINE_VERSION:
            reasons.append("REASONING_ENGINE_VERSION_MISMATCH")
        if any(
            bool(manifest.get(key)) or bool(report.get(key))
            for key in ("project_acceptance_performed", "may_accept_project", "may_release", "may_freeze")
        ):
            reasons.append("REASONING_AUTHORITY_BOUNDARY_VIOLATION")
        if set(path.name for path in root.iterdir()) != _ALLOWED_FILES:
            reasons.append("REASONING_PROJECT_FILE_SET_MISMATCH")

        file_map = _manifest_file_map(manifest)
        if set(file_map) != (_ALLOWED_FILES - {"artifact-manifest.json"}):
            reasons.append("REASONING_MANIFEST_MEMBERSHIP_MISMATCH")
        for relative, entry in file_map.items():
            path = root / relative
            if path.is_symlink() or not path.is_file():
                reasons.append("REASONING_MANIFEST_FILE_MISSING")
                continue
            checked += 1
            if entry.get("size_bytes") != path.stat().st_size:
                reasons.append("REASONING_FILE_SIZE_MISMATCH")
            if entry.get("sha256") != sha256_file(path):
                reasons.append("REASONING_FILE_HASH_MISMATCH")

        for name, expected in expected_payloads.items():
            path = root / name
            if path.is_file() and path.read_bytes() != expected:
                reasons.append("REASONING_ARTIFACT_CONTENT_MISMATCH")
        if logical != expected_logical or report.get("logical_sha256") != expected_logical:
            reasons.append("REASONING_LOGICAL_HASH_MISMATCH")
        binding_checks = {
            "chapter_project_logical_sha256": context.chapter_logical,
            "literary_project_ids": list(context.literary_project_ids),
            "literary_logical_sha256s": list(context.literary_logicals),
            "evidence_project_logical_sha256s": list(context.evidence_logicals),
            "event_project_logical_sha256": context.event_logical,
            "character_project_logical_sha256": context.character_logical,
            "annotation_sha256": annotation_sha,
        }
        for key, expected in binding_checks.items():
            if manifest.get(key) != expected:
                reasons.append("REASONING_UPSTREAM_BINDING_MISMATCH")
            if key in report and report.get(key) != expected:
                reasons.append("REASONING_REPORT_BINDING_MISMATCH")
        if report.get("graph_valid") != graph.report.graph_valid:
            reasons.append("REASONING_GRAPH_VALIDITY_MISMATCH")
        if report.get("status") != graph.report.status:
            reasons.append("REASONING_GRAPH_STATUS_MISMATCH")
        for key, expected in (
            ("node_count", graph.report.node_count),
            ("edge_count", graph.report.edge_count),
            ("finding_count", graph.report.finding_count),
            ("blocking_finding_count", graph.report.blocking_finding_count),
            ("layer_counts", graph.report.layer_counts),
        ):
            if report.get(key) != expected:
                reasons.append("REASONING_REPORT_COUNT_MISMATCH")

        database_path = root / "reasoning.sqlite"
        if not database_path.is_file() or database_path.is_symlink():
            reasons.append("REASONING_DATABASE_MISSING")
        else:
            actual_database_hash = sha256_file(database_path)
            if actual_database_hash != database_hash or report.get("database_sha256") != database_hash:
                reasons.append("REASONING_DATABASE_HASH_MISMATCH")
            connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    reasons.append("REASONING_DATABASE_INTEGRITY_FAILED")
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    reasons.append("REASONING_DATABASE_FOREIGN_KEY_FAILED")
                metadata = dict(connection.execute("SELECT key,value FROM metadata"))
                if metadata.get("logical_sha256") != expected_logical:
                    reasons.append("REASONING_DATABASE_METADATA_MISMATCH")
                node_ids = [row[0] for row in connection.execute("SELECT node_id FROM nodes ORDER BY layer,node_id")]
                expected_node_ids = [item.node_id for item in graph.nodes]
                if node_ids != expected_node_ids:
                    reasons.append("REASONING_DATABASE_NODE_MISMATCH")
                edge_ids = [row[0] for row in connection.execute("SELECT edge_id FROM edges ORDER BY source_node_id,relation,target_node_id,edge_id")]
                expected_edge_ids = [item.edge_id for item in graph.edges]
                if edge_ids != expected_edge_ids:
                    reasons.append("REASONING_DATABASE_EDGE_MISMATCH")
            finally:
                connection.close()
    except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, ReasoningProjectError, ReasoningEngineError) as exc:
        reasons.append("REASONING_VERIFICATION_EXCEPTION:" + type(exc).__name__)

    unique = tuple(dict.fromkeys(reasons))
    return ReasoningProjectVerification(
        REASONING_PROJECT_VERIFICATION_SCHEMA_VERSION,
        "valid" if not unique else "invalid",
        not unique,
        graph_valid,
        unique,
        checked,
        logical,
        database_hash,
    )


__all__ = [
    "EvidenceBinding",
    "REASONING_ANNOTATION_SCHEMA_VERSION",
    "REASONING_PROJECT_MANIFEST_SCHEMA_VERSION",
    "REASONING_PROJECT_REPORT_SCHEMA_VERSION",
    "REASONING_PROJECT_SCHEMA_VERSION",
    "REASONING_PROJECT_VERIFICATION_SCHEMA_VERSION",
    "REASONING_SQLITE_SCHEMA_VERSION",
    "ReasoningProjectBuildResult",
    "ReasoningProjectError",
    "ReasoningProjectVerification",
    "build_reasoning_project",
    "verify_reasoning_project",
]
