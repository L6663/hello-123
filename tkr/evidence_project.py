"""Build and verify an immutable Stage 1 Evidence Engine project.

The Evidence project is a deterministic sidecar over two already verified
inputs:

* a secure Text Knowledge Reader source project;
* its verified literary knowledge sidecar.

It publishes two complementary evidence layers:

* complete trusted-body ``EvidenceUnit`` records for retrieval and coverage;
* exact ``EvidenceAnchor`` records directly referenced by Claims.

The package also contains explicit Claim-Evidence edges, graph validation,
SQLite indexes, reports, and a hash manifest.  It has no project-acceptance,
release, or freeze authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Iterable, Mapping, Sequence

from .evidence_claims import (
    CLAIM_GRAPH_VERSION,
    ClaimEvidenceEdge,
    ClaimGraphReport,
    build_claim_evidence_edges,
    edge_from_dict,
    graph_report_from_dict,
)
from .evidence_engine import (
    EVIDENCE_ENGINE_VERSION,
    EvidenceCoverageReport,
    EvidenceUnit,
    coverage_report_from_dict,
    evidence_unit_from_dict,
    extract_evidence_units,
    verify_evidence_units,
)
from .hashing import sha256_file
from .literary_engine import verify_literary_engine
from .literary_models import (
    ChapterRecord,
    EvidenceAnchor,
    KnowledgeAssertion,
    record_from_dict,
)
from .project_security import verify_secure_knowledge_project

EVIDENCE_PROJECT_SCHEMA_VERSION = "tkr-evidence-project-v1"
EVIDENCE_PROJECT_REPORT_SCHEMA_VERSION = "tkr-evidence-project-report-v1"
EVIDENCE_PROJECT_MANIFEST_SCHEMA_VERSION = "tkr-evidence-project-manifest-v1"
EVIDENCE_PROJECT_VERIFICATION_SCHEMA_VERSION = "tkr-evidence-project-verification-v1"
EVIDENCE_SQLITE_SCHEMA_VERSION = "tkr-evidence-sqlite-v1"

_DATA_FILES = (
    "evidence-units.jsonl",
    "claim-evidence-anchors.jsonl",
    "claim-evidence-edges.jsonl",
)
_REPORT_FILES = (
    "evidence-coverage.json",
    "claim-graph-report.json",
)
_ALLOWED_FILES = set(_DATA_FILES) | set(_REPORT_FILES) | {
    "evidence.sqlite",
    "evidence-project-report.json",
    "artifact-manifest.json",
}


class EvidenceProjectError(ValueError):
    """Raised when an Evidence project is unsafe or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class EvidenceProjectBuildResult:
    schema_version: str
    status: str
    evidence_engine_version: str
    claim_graph_version: str
    source_project_id: str
    literary_project_id: str
    source_id: str
    source_sha256: str
    output_directory: str
    chapter_count: int
    eligible_chapter_count: int
    blocked_chapter_count: int
    evidence_unit_count: int
    claim_evidence_anchor_count: int
    evidence_coverage_rate: float
    evidence_coverage_complete: bool
    assertion_count: int
    claim_edge_count: int
    claim_graph_valid: bool
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_PROJECT_REPORT_SCHEMA_VERSION:
            raise EvidenceProjectError("Evidence project report schema version mismatch")
        if self.status != "completed":
            raise EvidenceProjectError("Evidence project build status must be completed")
        if not self.evidence_coverage_complete or not self.claim_graph_valid:
            raise EvidenceProjectError(
                "completed Evidence project requires valid coverage and Claim graph"
            )
        for name in (
            "chapter_count",
            "eligible_chapter_count",
            "blocked_chapter_count",
            "evidence_unit_count",
            "claim_evidence_anchor_count",
            "assertion_count",
            "claim_edge_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EvidenceProjectError(f"{name} must be a non-negative integer")
        if self.eligible_chapter_count + self.blocked_chapter_count != self.chapter_count:
            raise EvidenceProjectError("eligible and blocked chapter counts are inconsistent")
        if any(
            (
                self.project_acceptance_performed,
                self.may_accept_project,
                self.may_release,
                self.may_freeze,
            )
        ):
            raise EvidenceProjectError("Evidence development project cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceProjectVerification:
    schema_version: str
    status: str
    valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    source_project_id: str
    literary_project_id: str
    source_id: str
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_PROJECT_VERIFICATION_SCHEMA_VERSION:
            raise EvidenceProjectError("Evidence verification schema version mismatch")
        if self.valid != (not self.reason_codes):
            raise EvidenceProjectError("Evidence verification validity does not match reason codes")
        if any(
            (
                self.project_acceptance_performed,
                self.may_accept_project,
                self.may_release,
                self.may_freeze,
            )
        ):
            raise EvidenceProjectError("Evidence verification cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


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
        raise EvidenceProjectError(f"{label} is not a safe regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceProjectError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise EvidenceProjectError(f"{label} is not a safe regular file")
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise EvidenceProjectError(f"blank {label} record at line {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceProjectError(
                    f"invalid {label} JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise EvidenceProjectError(
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
        raise EvidenceProjectError(f"{label} must be a safe directory")


def _input_records(
    source_project: Path,
    literary_project: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    str,
    list[ChapterRecord],
    list[EvidenceAnchor],
    list[KnowledgeAssertion],
]:
    source_verification = verify_secure_knowledge_project(source_project)
    if not source_verification.valid:
        raise EvidenceProjectError(
            "source project failed verification: "
            + ",".join(source_verification.reason_codes)
        )
    literary_verification = verify_literary_engine(literary_project)
    if not literary_verification.valid:
        raise EvidenceProjectError(
            "literary project failed verification: "
            + ",".join(literary_verification.reason_codes)
        )

    source_report = _load_object(
        source_project / "project-report.json", "source project report"
    )
    literary_report = _load_object(
        literary_project / "literary-report.json", "literary report"
    )
    source_path = source_project / "source" / "normalized-source.txt"
    if source_path.is_symlink() or not source_path.is_file():
        raise EvidenceProjectError("normalized source is not a safe regular file")
    try:
        # Preserve stored CRLF/LF bytes after strict UTF-8 decoding.
        # Universal-newline translation would invalidate source hashes and offsets.
        with source_path.open("r", encoding="utf-8", newline="") as handle:
            source_text = handle.read()
    except (OSError, UnicodeError) as exc:
        raise EvidenceProjectError(
            f"normalized source cannot be read strictly: {exc}"
        ) from exc

    source_id = source_report.get("source_id")
    source_sha = source_report.get("normalized_source_sha256")
    if not isinstance(source_id, str) or not isinstance(source_sha, str):
        raise EvidenceProjectError("source report omits source identity")
    if sha256(source_text.encode("utf-8")).hexdigest() != source_sha:
        raise EvidenceProjectError("normalized source hash differs from source report")
    if (
        literary_report.get("source_id") != source_id
        or literary_report.get("source_sha256") != source_sha
    ):
        raise EvidenceProjectError(
            "literary project source binding differs from source project"
        )

    raw_chapters = _load_jsonl(
        literary_project / "chapters.jsonl", "literary chapters"
    )
    raw_anchors = _load_jsonl(
        literary_project / "evidence-anchors.jsonl",
        "literary evidence anchors",
    )
    raw_assertions = _load_jsonl(
        literary_project / "assertions.jsonl", "literary assertions"
    )
    chapters: list[ChapterRecord] = []
    anchors: list[EvidenceAnchor] = []
    assertions: list[KnowledgeAssertion] = []
    for row in raw_chapters:
        item = record_from_dict("chapter", row)
        if not isinstance(item, ChapterRecord):
            raise EvidenceProjectError("chapter artifact contains wrong record type")
        chapters.append(item)
    for row in raw_anchors:
        item = record_from_dict("evidence", row)
        if not isinstance(item, EvidenceAnchor):
            raise EvidenceProjectError("evidence artifact contains wrong record type")
        if source_text[item.evidence_start : item.evidence_end] != item.evidence_text:
            raise EvidenceProjectError("literary Evidence differs from bound source span")
        anchors.append(item)
    for row in raw_assertions:
        item = record_from_dict("assertion", row)
        if not isinstance(item, KnowledgeAssertion):
            raise EvidenceProjectError("assertion artifact contains wrong record type")
        assertions.append(item)
    return source_report, literary_report, source_text, chapters, anchors, assertions


def _create_database(
    path: Path,
    units: Sequence[EvidenceUnit],
    anchors: Sequence[EvidenceAnchor],
    coverage: EvidenceCoverageReport,
    edges: Sequence[ClaimEvidenceEdge],
    graph: ClaimGraphReport,
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
            CREATE TABLE evidence_units(
                evidence_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                volume_ordinal INTEGER,
                chapter_ordinal INTEGER,
                original_heading TEXT NOT NULL,
                normalized_heading TEXT NOT NULL,
                paragraph_ordinal INTEGER NOT NULL,
                sequence_in_chapter INTEGER NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                text TEXT NOT NULL,
                text_sha256 TEXT NOT NULL,
                unit_content_sha256 TEXT NOT NULL,
                source_status TEXT NOT NULL,
                boundary_kind TEXT NOT NULL,
                content_character_count INTEGER NOT NULL,
                review_status TEXT NOT NULL
            );
            CREATE INDEX evidence_chapter_span
                ON evidence_units(chapter_id,start_char,end_char);
            CREATE TABLE claim_evidence_anchors(
                anchor_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                unit_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                volume_ordinal INTEGER,
                chapter_ordinal INTEGER,
                original_heading TEXT NOT NULL,
                normalized_heading TEXT NOT NULL,
                evidence_start INTEGER NOT NULL,
                evidence_end INTEGER NOT NULL,
                evidence_text TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL,
                unit_content_sha256 TEXT NOT NULL,
                evidence_role TEXT NOT NULL,
                source_status TEXT NOT NULL
            );
            CREATE INDEX claim_anchor_chapter_span
                ON claim_evidence_anchors(chapter_id,evidence_start,evidence_end);
            CREATE TABLE claim_evidence_edges(
                edge_id TEXT PRIMARY KEY,
                assertion_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL REFERENCES claim_evidence_anchors(anchor_id),
                relation TEXT NOT NULL,
                evidence_source_status TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                confidence REAL NOT NULL,
                review_status TEXT NOT NULL
            );
            CREATE INDEX claim_edge_claim
                ON claim_evidence_edges(assertion_id,relation,ordinal);
            CREATE INDEX claim_edge_evidence
                ON claim_evidence_edges(evidence_id,relation);
            CREATE TABLE coverage_spans(
                chapter_id TEXT NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY(chapter_id,start_char,end_char,reason)
            );
            CREATE TABLE claim_graph_findings(
                code TEXT NOT NULL,
                assertion_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                message TEXT NOT NULL
            );
            """
        )
        for key, value in sorted(metadata.items()):
            connection.execute("INSERT INTO metadata VALUES(?,?)", (key, value))
        for item in units:
            connection.execute(
                "INSERT INTO evidence_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.evidence_id,
                    item.source_id,
                    item.source_sha256,
                    item.unit_id,
                    item.chapter_id,
                    item.volume_ordinal,
                    item.chapter_ordinal,
                    item.original_heading,
                    item.normalized_heading,
                    item.paragraph_ordinal,
                    item.sequence_in_chapter,
                    item.start_char,
                    item.end_char,
                    item.text,
                    item.text_sha256,
                    item.unit_content_sha256,
                    item.source_status,
                    item.boundary_kind,
                    item.content_character_count,
                    item.review_status,
                ),
            )
        for item in anchors:
            connection.execute(
                "INSERT INTO claim_evidence_anchors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.anchor_id,
                    item.source_id,
                    item.source_sha256,
                    item.unit_id,
                    item.chapter_id,
                    item.volume_ordinal,
                    item.chapter_ordinal,
                    item.original_heading,
                    item.normalized_heading,
                    item.evidence_start,
                    item.evidence_end,
                    item.evidence_text,
                    item.evidence_sha256,
                    item.unit_content_sha256,
                    item.evidence_role,
                    item.source_status,
                ),
            )
        for item in edges:
            connection.execute(
                "INSERT INTO claim_evidence_edges VALUES(?,?,?,?,?,?,?,?)",
                (
                    item.edge_id,
                    item.assertion_id,
                    item.evidence_id,
                    item.relation,
                    item.evidence_source_status,
                    item.ordinal,
                    float(item.confidence),
                    item.review_status,
                ),
            )
        for span in (
            *coverage.uncovered_spans,
            *coverage.overlap_spans,
            *coverage.blocked_spans,
        ):
            connection.execute(
                "INSERT INTO coverage_spans VALUES(?,?,?,?)",
                (span.chapter_id, span.start_char, span.end_char, span.reason),
            )
        for finding in graph.findings:
            connection.execute(
                "INSERT INTO claim_graph_findings VALUES(?,?,?,?)",
                (
                    finding.code,
                    finding.assertion_id,
                    finding.evidence_id,
                    finding.message,
                ),
            )
        connection.commit()
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            raise EvidenceProjectError("Evidence SQLite foreign-key check failed")
        connection.execute("VACUUM")
    finally:
        connection.close()


def _logical_hash(
    payloads: Mapping[str, bytes],
    source_project_id: str,
    literary_project_id: str,
    literary_logical_sha256: str,
) -> str:
    digest = sha256()
    digest.update(EVIDENCE_PROJECT_SCHEMA_VERSION.encode("utf-8"))
    digest.update(b"\0")
    digest.update(source_project_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(literary_project_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(literary_logical_sha256.encode("utf-8"))
    for name in sorted(payloads):
        digest.update(b"\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payloads[name])
    return digest.hexdigest()


def _install(temporary: Path, output: Path, replace_existing: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace_existing:
        raise EvidenceProjectError(f"output directory already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise EvidenceProjectError("existing output is unsafe")
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


def build_evidence_project(
    source_project_directory: str | Path,
    literary_project_directory: str | Path,
    output_directory: str | Path,
    *,
    target_chars: int = 900,
    max_chars: int = 1500,
    replace_existing: bool = False,
) -> EvidenceProjectBuildResult:
    """Build one immutable Evidence Engine project from verified inputs."""

    source_project = Path(source_project_directory)
    literary_project = Path(literary_project_directory)
    output = Path(output_directory)
    _safe_directory(source_project, "source project")
    _safe_directory(literary_project, "literary project")
    if output.is_symlink():
        raise EvidenceProjectError("output path must not be a symbolic link")
    if output.resolve() in {source_project.resolve(), literary_project.resolve()}:
        raise EvidenceProjectError(
            "Evidence output must differ from both input projects"
        )

    (
        source_report,
        literary_report,
        source_text,
        chapters,
        anchors,
        assertions,
    ) = _input_records(source_project, literary_project)
    ordered_anchors = tuple(
        sorted(
            anchors,
            key=lambda item: (
                item.evidence_start,
                item.evidence_end,
                item.anchor_id,
            ),
        )
    )
    extraction = extract_evidence_units(
        source_text,
        chapters,
        target_chars=target_chars,
        max_chars=max_chars,
    )
    if not extraction.coverage.complete:
        raise EvidenceProjectError("trusted source coverage is incomplete")
    evidence_status = {
        item.anchor_id: item.source_status for item in ordered_anchors
    }
    claim_graph = build_claim_evidence_edges(assertions, evidence_status)
    if not claim_graph.report.valid:
        raise EvidenceProjectError("Claim-Evidence graph is invalid")

    source_project_id = str(source_report.get("project_id", ""))
    literary_project_id = str(literary_report.get("project_id", ""))
    source_id = str(source_report.get("source_id", ""))
    source_sha = str(source_report.get("normalized_source_sha256", ""))
    literary_logical = str(literary_report.get("logical_sha256", ""))
    if not all(
        (
            source_project_id,
            literary_project_id,
            source_id,
            source_sha,
            literary_logical,
        )
    ):
        raise EvidenceProjectError("input reports omit required project identities")

    payloads: dict[str, bytes] = {
        "evidence-units.jsonl": _jsonl_bytes(extraction.units),
        "claim-evidence-anchors.jsonl": _jsonl_bytes(ordered_anchors),
        "claim-evidence-edges.jsonl": _jsonl_bytes(claim_graph.edges),
        "evidence-coverage.json": _json_bytes(extraction.coverage.to_dict()),
        "claim-graph-report.json": _json_bytes(claim_graph.report.to_dict()),
    }
    logical_hash = _logical_hash(
        payloads,
        source_project_id,
        literary_project_id,
        literary_logical,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent)
    )
    try:
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        metadata = {
            "evidence_project_schema_version": EVIDENCE_PROJECT_SCHEMA_VERSION,
            "evidence_sqlite_schema_version": EVIDENCE_SQLITE_SCHEMA_VERSION,
            "evidence_engine_version": EVIDENCE_ENGINE_VERSION,
            "claim_graph_version": CLAIM_GRAPH_VERSION,
            "source_project_id": source_project_id,
            "literary_project_id": literary_project_id,
            "source_id": source_id,
            "source_sha256": source_sha,
            "literary_logical_sha256": literary_logical,
            "logical_sha256": logical_hash,
        }
        database_path = temporary / "evidence.sqlite"
        _create_database(
            database_path,
            extraction.units,
            ordered_anchors,
            extraction.coverage,
            claim_graph.edges,
            claim_graph.report,
            metadata,
        )
        database_hash = sha256_file(database_path)
        result = EvidenceProjectBuildResult(
            EVIDENCE_PROJECT_REPORT_SCHEMA_VERSION,
            "completed",
            EVIDENCE_ENGINE_VERSION,
            CLAIM_GRAPH_VERSION,
            source_project_id,
            literary_project_id,
            source_id,
            source_sha,
            str(output),
            extraction.coverage.chapter_count,
            extraction.coverage.eligible_chapter_count,
            extraction.coverage.blocked_chapter_count,
            len(extraction.units),
            len(ordered_anchors),
            extraction.coverage.coverage_rate,
            extraction.coverage.complete,
            len(assertions),
            len(claim_graph.edges),
            claim_graph.report.valid,
            logical_hash,
            database_hash,
        )
        report = {
            **result.to_dict(),
            "source_project_manifest_sha256": sha256_file(
                source_project / "project-manifest.json"
            ),
            "literary_manifest_sha256": sha256_file(
                literary_project / "artifact-manifest.json"
            ),
            "literary_logical_sha256": literary_logical,
            "target_chars": target_chars,
            "max_chars": max_chars,
        }
        _write_atomic(
            temporary / "evidence-project-report.json", _json_bytes(report)
        )

        entries = []
        for path in sorted(temporary.iterdir()):
            if path.is_file():
                entries.append(
                    {
                        "path": path.name,
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
        manifest = {
            "schema_version": EVIDENCE_PROJECT_MANIFEST_SCHEMA_VERSION,
            "evidence_project_schema_version": EVIDENCE_PROJECT_SCHEMA_VERSION,
            "evidence_engine_version": EVIDENCE_ENGINE_VERSION,
            "claim_graph_version": CLAIM_GRAPH_VERSION,
            "source_project_id": source_project_id,
            "literary_project_id": literary_project_id,
            "source_id": source_id,
            "source_sha256": source_sha,
            "literary_logical_sha256": literary_logical,
            "logical_sha256": logical_hash,
            "database_sha256": database_hash,
            "files": entries,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        _write_atomic(
            temporary / "artifact-manifest.json", _json_bytes(manifest)
        )
        _install(temporary, output, replace_existing)
        return result
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_evidence_project(
    source_project_directory: str | Path,
    literary_project_directory: str | Path,
    evidence_project_directory: str | Path,
) -> EvidenceProjectVerification:
    """Verify source bindings, hashes, typed artifacts, SQLite, and coverage."""

    source_project = Path(source_project_directory)
    literary_project = Path(literary_project_directory)
    root = Path(evidence_project_directory)
    reasons: list[str] = []
    checked = 0
    source_project_id = ""
    literary_project_id = ""
    source_id = ""
    logical_hash = ""
    database_hash = ""
    try:
        _safe_directory(source_project, "source project")
        _safe_directory(literary_project, "literary project")
        _safe_directory(root, "Evidence project")
        source_verification = verify_secure_knowledge_project(source_project)
        if not source_verification.valid:
            reasons.append("EVIDENCE_SOURCE_PROJECT_INVALID")
        literary_verification = verify_literary_engine(literary_project)
        if not literary_verification.valid:
            reasons.append("EVIDENCE_LITERARY_PROJECT_INVALID")

        manifest = _load_object(
            root / "artifact-manifest.json", "Evidence manifest"
        )
        report = _load_object(
            root / "evidence-project-report.json", "Evidence report"
        )
        source_project_id = str(manifest.get("source_project_id", ""))
        literary_project_id = str(manifest.get("literary_project_id", ""))
        source_id = str(manifest.get("source_id", ""))
        logical_hash = str(manifest.get("logical_sha256", ""))
        database_hash = str(manifest.get("database_sha256", ""))
        if manifest.get("schema_version") != EVIDENCE_PROJECT_MANIFEST_SCHEMA_VERSION:
            reasons.append("EVIDENCE_MANIFEST_SCHEMA_MISMATCH")
        if report.get("schema_version") != EVIDENCE_PROJECT_REPORT_SCHEMA_VERSION:
            reasons.append("EVIDENCE_REPORT_SCHEMA_MISMATCH")
        if manifest.get("evidence_engine_version") != EVIDENCE_ENGINE_VERSION:
            reasons.append("EVIDENCE_ENGINE_VERSION_MISMATCH")
        if manifest.get("claim_graph_version") != CLAIM_GRAPH_VERSION:
            reasons.append("EVIDENCE_CLAIM_GRAPH_VERSION_MISMATCH")
        if any(
            bool(manifest.get(key)) or bool(report.get(key))
            for key in (
                "project_acceptance_performed",
                "may_accept_project",
                "may_release",
                "may_freeze",
            )
        ):
            reasons.append("EVIDENCE_AUTHORITY_BOUNDARY_VIOLATION")

        actual_names = {path.name for path in root.iterdir()}
        if actual_names != _ALLOWED_FILES:
            reasons.append("EVIDENCE_PROJECT_FILE_SET_MISMATCH")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            reasons.append("EVIDENCE_MANIFEST_FILES_INVALID")
            entries = []
        registered: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                reasons.append("EVIDENCE_MANIFEST_ENTRY_INVALID")
                continue
            relative = _safe_relative(entry.get("path"))
            if (
                relative is None
                or relative in registered
                or relative == "artifact-manifest.json"
            ):
                reasons.append("EVIDENCE_MANIFEST_PATH_INVALID")
                continue
            registered.add(relative)
            path = root / relative
            if path.is_symlink() or not path.is_file():
                reasons.append("EVIDENCE_MANIFEST_FILE_MISSING")
                continue
            checked += 1
            if entry.get("size_bytes") != path.stat().st_size:
                reasons.append("EVIDENCE_FILE_SIZE_MISMATCH")
            if entry.get("sha256") != sha256_file(path):
                reasons.append("EVIDENCE_FILE_HASH_MISMATCH")
        if registered != (_ALLOWED_FILES - {"artifact-manifest.json"}):
            reasons.append("EVIDENCE_MANIFEST_MEMBERSHIP_MISMATCH")

        (
            source_report,
            literary_report,
            source_text,
            chapters,
            literary_anchors,
            assertions,
        ) = _input_records(source_project, literary_project)
        if source_project_id != source_report.get("project_id"):
            reasons.append("EVIDENCE_SOURCE_PROJECT_BINDING_MISMATCH")
        if literary_project_id != literary_report.get("project_id"):
            reasons.append("EVIDENCE_LITERARY_PROJECT_BINDING_MISMATCH")
        if source_id != source_report.get("source_id"):
            reasons.append("EVIDENCE_SOURCE_ID_MISMATCH")
        if (
            manifest.get("source_sha256")
            != source_report.get("normalized_source_sha256")
        ):
            reasons.append("EVIDENCE_SOURCE_HASH_BINDING_MISMATCH")
        if (
            manifest.get("literary_logical_sha256")
            != literary_report.get("logical_sha256")
        ):
            reasons.append("EVIDENCE_LITERARY_LOGICAL_BINDING_MISMATCH")

        units = [
            evidence_unit_from_dict(row)
            for row in _load_jsonl(
                root / "evidence-units.jsonl", "Evidence units"
            )
        ]
        exported_anchors: list[EvidenceAnchor] = []
        for row in _load_jsonl(
            root / "claim-evidence-anchors.jsonl",
            "Claim Evidence anchors",
        ):
            item = record_from_dict("evidence", row)
            if not isinstance(item, EvidenceAnchor):
                raise EvidenceProjectError(
                    "Claim Evidence artifact contains wrong record type"
                )
            if source_text[item.evidence_start : item.evidence_end] != item.evidence_text:
                raise EvidenceProjectError(
                    "exported Claim Evidence differs from source span"
                )
            exported_anchors.append(item)
        edges = [
            edge_from_dict(row)
            for row in _load_jsonl(
                root / "claim-evidence-edges.jsonl",
                "Claim-Evidence edges",
            )
        ]
        coverage = coverage_report_from_dict(
            _load_object(root / "evidence-coverage.json", "Evidence coverage")
        )
        graph = graph_report_from_dict(
            _load_object(root / "claim-graph-report.json", "Claim graph report")
        )

        target_chars = int(report.get("target_chars", 900))
        max_chars = int(report.get("max_chars", 1500))
        recomputed_extraction = extract_evidence_units(
            source_text,
            chapters,
            target_chars=target_chars,
            max_chars=max_chars,
        )
        unit_verification = verify_evidence_units(source_text, chapters, units)
        if not unit_verification.valid:
            reasons.extend(unit_verification.reason_codes)
        if [item.to_dict() for item in units] != [
            item.to_dict() for item in recomputed_extraction.units
        ]:
            reasons.append("EVIDENCE_UNIT_RECOMPUTE_MISMATCH")
        if coverage.to_dict() != recomputed_extraction.coverage.to_dict():
            reasons.append("EVIDENCE_COVERAGE_RECOMPUTE_MISMATCH")

        expected_anchors = sorted(
            literary_anchors,
            key=lambda item: (
                item.evidence_start,
                item.evidence_end,
                item.anchor_id,
            ),
        )
        if [item.to_dict() for item in exported_anchors] != [
            item.to_dict() for item in expected_anchors
        ]:
            reasons.append("EVIDENCE_ANCHOR_RECOMPUTE_MISMATCH")
        evidence_status = {
            item.anchor_id: item.source_status for item in exported_anchors
        }
        recomputed_graph = build_claim_evidence_edges(
            assertions, evidence_status
        )
        if [item.to_dict() for item in edges] != [
            item.to_dict() for item in recomputed_graph.edges
        ]:
            reasons.append("EVIDENCE_CLAIM_EDGE_RECOMPUTE_MISMATCH")
        if graph.to_dict() != recomputed_graph.report.to_dict():
            reasons.append("EVIDENCE_CLAIM_GRAPH_RECOMPUTE_MISMATCH")

        payloads = {
            name: (root / name).read_bytes()
            for name in (*_DATA_FILES, *_REPORT_FILES)
        }
        expected_logical = _logical_hash(
            payloads,
            source_project_id,
            literary_project_id,
            str(literary_report.get("logical_sha256", "")),
        )
        if (
            logical_hash != expected_logical
            or report.get("logical_sha256") != expected_logical
        ):
            reasons.append("EVIDENCE_LOGICAL_HASH_MISMATCH")
        actual_database_hash = sha256_file(root / "evidence.sqlite")
        if (
            database_hash != actual_database_hash
            or report.get("database_sha256") != actual_database_hash
        ):
            reasons.append("EVIDENCE_DATABASE_HASH_MISMATCH")

        if report.get("evidence_unit_count") != len(units):
            reasons.append("EVIDENCE_REPORT_UNIT_COUNT_MISMATCH")
        if report.get("claim_evidence_anchor_count") != len(exported_anchors):
            reasons.append("EVIDENCE_REPORT_ANCHOR_COUNT_MISMATCH")
        if report.get("claim_edge_count") != len(edges):
            reasons.append("EVIDENCE_REPORT_EDGE_COUNT_MISMATCH")

        connection = sqlite3.connect(
            f"file:{root / 'evidence.sqlite'}?mode=ro", uri=True
        )
        try:
            metadata = {
                str(key): str(value)
                for key, value in connection.execute(
                    "SELECT key,value FROM metadata"
                )
            }
            if metadata.get("logical_sha256") != expected_logical:
                reasons.append("EVIDENCE_DATABASE_LOGICAL_MISMATCH")
            if metadata.get("evidence_engine_version") != EVIDENCE_ENGINE_VERSION:
                reasons.append("EVIDENCE_DATABASE_ENGINE_VERSION_MISMATCH")
            quick = connection.execute("PRAGMA quick_check").fetchone()
            if quick is None or quick[0] != "ok":
                reasons.append("EVIDENCE_SQLITE_QUICK_CHECK_FAILED")
            foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign:
                reasons.append("EVIDENCE_SQLITE_FOREIGN_KEY_FAILED")
            database_unit_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT evidence_id FROM evidence_units ORDER BY evidence_id"
                )
            ]
            database_anchor_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT anchor_id FROM claim_evidence_anchors ORDER BY anchor_id"
                )
            ]
            database_edge_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT edge_id FROM claim_evidence_edges ORDER BY edge_id"
                )
            ]
            if database_unit_ids != sorted(item.evidence_id for item in units):
                reasons.append("EVIDENCE_JSON_SQLITE_UNIT_MISMATCH")
            if database_anchor_ids != sorted(
                item.anchor_id for item in exported_anchors
            ):
                reasons.append("EVIDENCE_JSON_SQLITE_ANCHOR_MISMATCH")
            if database_edge_ids != sorted(item.edge_id for item in edges):
                reasons.append("EVIDENCE_JSON_SQLITE_EDGE_MISMATCH")
        finally:
            connection.close()
    except Exception as exc:
        reasons.extend(("EVIDENCE_VERIFICATION_EXCEPTION", type(exc).__name__))

    unique_reasons = tuple(dict.fromkeys(reasons))
    return EvidenceProjectVerification(
        EVIDENCE_PROJECT_VERIFICATION_SCHEMA_VERSION,
        "passed" if not unique_reasons else "failed",
        not unique_reasons,
        unique_reasons,
        checked,
        source_project_id,
        literary_project_id,
        source_id,
        logical_hash,
        database_hash,
    )


__all__ = [
    "EVIDENCE_PROJECT_MANIFEST_SCHEMA_VERSION",
    "EVIDENCE_PROJECT_REPORT_SCHEMA_VERSION",
    "EVIDENCE_PROJECT_SCHEMA_VERSION",
    "EVIDENCE_PROJECT_VERIFICATION_SCHEMA_VERSION",
    "EVIDENCE_SQLITE_SCHEMA_VERSION",
    "EvidenceProjectBuildResult",
    "EvidenceProjectError",
    "EvidenceProjectVerification",
    "build_evidence_project",
    "verify_evidence_project",
]
