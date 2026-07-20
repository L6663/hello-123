"""Auditable predicate-aware hybrid indexing and retrieval.

Phase 5 consumes only hash-bound Phase 4 artifacts. It combines typed Fact
lookup, exact entity/alias resolution, SQLite FTS5 when available, and a bounded
LIKE fallback. Lexical similarity may rank evidence, but it never makes a query
answerable by itself: answerability requires a supported predicate and matching
structured Facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Mapping, Sequence
import unicodedata

from .chunking import UnitSpan
from .cli import _load_units
from .entity_normalization import IdentityLink, NORMALIZER_VERSION, normalize_entities

INDEX_SCHEMA_VERSION = "tkr-hybrid-index-v1"
QUERY_PARSER_VERSION = "tkr-predicate-query-v1"
_REQUIRED_ARTIFACTS = (
    "mentions.jsonl",
    "entities.jsonl",
    "facts.jsonl",
    "timeline.jsonl",
    "conflicts.jsonl",
    "ambiguity-groups.jsonl",
)
_PUNCT_RE = re.compile(r"[\s\u3000，。！？；：、,.!?;:\-—_()（）\[\]【】{}《》〈〉\"'“”‘’]+")
_TRAILING_QUESTION_RE = re.compile(r"(?:吗|呢|么|嘛)?[？?]*$")


class RetrievalError(ValueError):
    """Raised when an index input, database, or query packet is unsafe."""


@dataclass(frozen=True, slots=True)
class PredicateQuery:
    raw_query: str
    normalized_query: str
    predicate: str
    subject: str
    object: str
    requested_role: str
    unit: str
    predicate_scope: str
    polarity: bool | None
    temporal_scope: str
    supported: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    hit_type: str
    score: float
    source_id: str
    unit_id: str
    evidence_start: int
    evidence_end: int
    evidence_text: str
    fact_id: str | None = None
    entity_id: str | None = None
    claim_type: str | None = None
    predicate_scope: str | None = None
    canonical_status: str | None = None
    subject: str | None = None
    object: str | None = None
    value: object = None
    unit: str | None = None
    polarity: bool | None = None
    temporal_marker: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QueryResult:
    query_parser_version: str
    index_schema_version: str
    index_logical_sha256: str
    intent: PredicateQuery
    answerability: str
    reason_codes: tuple[str, ...]
    resolved_entity_ids: tuple[str, ...]
    hits: tuple[RetrievalHit, ...]
    lexical_hits: tuple[RetrievalHit, ...]

    @property
    def answerable_candidate(self) -> bool:
        return self.answerability == "answerable"

    def to_dict(self) -> dict[str, object]:
        return {
            "query_parser_version": self.query_parser_version,
            "index_schema_version": self.index_schema_version,
            "index_logical_sha256": self.index_logical_sha256,
            "intent": self.intent.to_dict(),
            "answerability": self.answerability,
            "answerable_candidate": self.answerable_candidate,
            "reason_codes": list(self.reason_codes),
            "resolved_entity_ids": list(self.resolved_entity_ids),
            "hits": [item.to_dict() for item in self.hits],
            "lexical_hits": [item.to_dict() for item in self.lexical_hits],
        }


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_surface(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return _PUNCT_RE.sub("", normalized)


def _clean_capture(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = _TRAILING_QUESTION_RE.sub("", value).strip()
    return value.strip("，。！？；：、,.!?;: \t\r\n")


def _date_scope(token: str) -> str:
    if token in {"出生", "生于", "生日"}:
        return "birth_date"
    if token in {"死亡", "去世", "逝世", "卒于"}:
        return "death_date"
    if token in {"开始", "始于", "启用"}:
        return "start_date"
    if token in {"结束", "截至", "终止"}:
        return "end_date"
    if token in {"发生", "举行"}:
        return "event_date"
    return "generic_date"


def _temporal_scope(text: str) -> str:
    if re.search(r"(?:现在|如今|现有|最终|后来|之后|最新|当前)", text):
        return "current"
    if re.search(r"(?:最初|起初|原先|原本|以前|此前|过去)", text):
        return "past"
    return "any"


def parse_predicate_query(question: str) -> PredicateQuery:
    """Parse only the closed predicate set supported by Phase 3/4.

    Unsupported wording is returned as ``supported=False``. It may still receive
    lexical evidence, but cannot become answerable without a typed predicate.
    """

    if not isinstance(question, str) or not question.strip():
        raise RetrievalError("question must be a non-empty string")
    raw = unicodedata.normalize("NFKC", question).strip()
    compact = re.sub(r"\s+", "", raw)
    normalized = _normalize_surface(raw)
    temporal = _temporal_scope(compact)

    patterns: list[tuple[str, re.Pattern[str], str]] = [
        (
            "alias",
            re.compile(r"^(?P<subject>.+?)(?:后来|现在|最终|曾经)?(?:又|还)?(?:叫作|叫做|叫什么|改称什么|改名为什么|别名是什么|原名是什么)[？?]*$"),
            "object",
        ),
        (
            "alias",
            re.compile(r"^(?P<subject>.+?)(?:是否|是不是)?(?:又称|改称|改名为|别名是|原名是)(?P<object>.+?)(?:吗)?[？?]*$"),
            "boolean",
        ),
        (
            "defeats",
            re.compile(r"^谁(?:曾经|后来|最终)?(?:击败|战胜)了?(?P<object>.+?)[？?]*$"),
            "subject",
        ),
        (
            "defeats",
            re.compile(r"^(?P<subject>.+?)(?:曾经|后来|最终)?(?:击败|战胜)了?谁[？?]*$"),
            "object",
        ),
        (
            "defeats",
            re.compile(r"^(?P<subject>.+?)(?:是否|有没有|是不是)?(?:击败|战胜)了?(?P<object>.+?)(?:吗)?[？?]*$"),
            "boolean",
        ),
        (
            "located_in",
            re.compile(r"^(?P<subject>.+?)(?:位于|坐落于|属于)(?:哪里|何处|哪儿|什么地方)[？?]*$"),
            "object",
        ),
        (
            "located_in",
            re.compile(r"^(?P<subject>.+?)在(?:哪里|何处|哪儿|什么地方)[？?]*$"),
            "object",
        ),
        (
            "located_in",
            re.compile(r"^(?P<subject>.+?)(?:是否|是不是)?(?:位于|坐落于|属于)(?P<object>.+?)(?:吗)?[？?]*$"),
            "boolean",
        ),
        (
            "count",
            re.compile(r"^(?P<subject>.+?)(?:现在|目前|最初|原先|以前)?(?:一共|共有|有)?多少(?P<unit>[\u4e00-\u9fffA-Za-z]*)[？?]*$"),
            "value",
        ),
        (
            "count",
            re.compile(r"^(?P<subject>.+?)(?:的)?(?:数量|人数|总数)(?:是多少|有多少)?[？?]*$"),
            "value",
        ),
        (
            "date",
            re.compile(r"^(?P<subject>.+?)(?P<event>出生|死亡|去世|逝世|开始|结束|发生|举行)(?:于)?(?:什么时候|何时|哪天|哪一年)[？?]*$"),
            "value",
        ),
        (
            "date",
            re.compile(r"^(?P<subject>.+?)(?:什么时候|何时|哪天|哪一年)(?P<event>出生|死亡|去世|逝世|开始|结束|发生|举行)?[？?]*$"),
            "value",
        ),
        (
            "permission",
            re.compile(r"^(?P<subject>.+?)(?:是否|是不是)?(?P<verb>允许|可以|能否|禁止|不得)(?P<object>.+?)(?:吗)?[？?]*$"),
            "boolean",
        ),
    ]

    for predicate, pattern, requested_role in patterns:
        match = pattern.match(compact)
        if not match:
            continue
        groups = match.groupdict()
        subject = _clean_capture(groups.get("subject") or "")
        object_value = _clean_capture(groups.get("object") or "")
        unit = _clean_capture(groups.get("unit") or "")
        predicate_scope = ""
        polarity: bool | None = None
        if predicate == "date":
            predicate_scope = _date_scope(_clean_capture(groups.get("event") or ""))
        elif predicate == "permission":
            verb = groups.get("verb") or ""
            polarity = verb not in {"禁止", "不得"}
        if not subject and requested_role != "subject":
            break
        return PredicateQuery(
            raw_query=raw,
            normalized_query=normalized,
            predicate=predicate,
            subject=subject,
            object=object_value,
            requested_role=requested_role,
            unit=unit,
            predicate_scope=predicate_scope,
            polarity=polarity,
            temporal_scope=temporal,
            supported=True,
            reason="SUPPORTED_TYPED_PREDICATE",
        )

    return PredicateQuery(
        raw_query=raw,
        normalized_query=normalized,
        predicate="unsupported",
        subject="",
        object="",
        requested_role="",
        unit="",
        predicate_scope="",
        polarity=None,
        temporal_scope=temporal,
        supported=False,
        reason="UNSUPPORTED_OPEN_PREDICATE",
    )


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RetrievalError(f"invalid {label} JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise RetrievalError(f"{label} must be a JSON object")
    return payload


def _jsonl_bytes(rows: Sequence[object]) -> bytes:
    lines: list[str] = []
    for row in rows:
        payload = row.to_dict() if hasattr(row, "to_dict") else row
        lines.append(_canonical_json(payload))
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _load_jsonl(path: Path, label: str, *, allow_empty: bool = True) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise RetrievalError(f"blank {label} record at line {line_number}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RetrievalError(f"invalid {label} JSON at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise RetrievalError(f"{label} record at line {line_number} must be an object")
            rows.append(payload)
    if not rows and not allow_empty:
        raise RetrievalError(f"{label} JSONL is empty")
    return rows


def _require_text(row: Mapping[str, object], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise RetrievalError(f"{label}.{key} must be a non-empty string")
    return value


def _require_int(row: Mapping[str, object], key: str, label: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalError(f"{label}.{key} must be an integer")
    return value


def _unique_ids(rows: Sequence[Mapping[str, object]], key: str, label: str) -> set[str]:
    result: set[str] = set()
    for row in rows:
        value = _require_text(row, key, label)
        if value in result:
            raise RetrievalError(f"duplicate {label} identifier: {value}")
        result.add(value)
    return result


def _unit_lookup(units: Sequence[UnitSpan], source_length: int) -> dict[tuple[str, str], UnitSpan]:
    lookup: dict[tuple[str, str], UnitSpan] = {}
    for unit in units:
        key = (unit.source_id, unit.unit_id)
        if key in lookup:
            raise RetrievalError(f"duplicate Unit identifier: {key}")
        if unit.start < 0 or unit.end <= unit.start or unit.end > source_length:
            raise RetrievalError(f"invalid Unit span: {key}")
        lookup[key] = unit
    return lookup


def verify_phase4_artifacts(
    source_path: str | Path,
    units_path: str | Path,
    accepted_claims_path: str | Path,
    entity_dir: str | Path,
    *,
    identity_links_path: str | Path | None = None,
    index_mode: str = "review",
    source_id: str = "source",
) -> tuple[str, list[UnitSpan], dict[str, list[dict[str, object]]], dict[str, object]]:
    """Verify the complete Phase 4 hash chain and referential integrity."""

    if index_mode not in {"review", "canonical"}:
        raise RetrievalError("index_mode must be review or canonical")
    source_path = Path(source_path)
    units_path = Path(units_path)
    accepted_claims_path = Path(accepted_claims_path)
    entity_dir = Path(entity_dir)
    identity_path = Path(identity_links_path) if identity_links_path is not None else None

    source_bytes = source_path.read_bytes()
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RetrievalError("source must be strict UTF-8") from exc
    if not source_text:
        raise RetrievalError("source text is empty")
    units = _load_units(units_path, len(source_text), source_id)
    unit_lookup = _unit_lookup(units, len(source_text))

    report_path = entity_dir / "entity-normalization-report.json"
    report = _load_json_object(report_path, "entity normalization report")
    if report.get("status") != "completed":
        raise RetrievalError("Phase 4 report status is not completed")
    if report.get("normalizer_version") != NORMALIZER_VERSION:
        raise RetrievalError("Phase 4 normalizer version mismatch")
    if report.get("source_sha256") != _sha256_bytes(source_bytes):
        raise RetrievalError("source SHA-256 does not match Phase 4 report")
    if report.get("unit_index_sha256") != _sha256_bytes(units_path.read_bytes()):
        raise RetrievalError("Unit index SHA-256 does not match Phase 4 report")
    if report.get("accepted_claims_sha256") != _sha256_bytes(accepted_claims_path.read_bytes()):
        raise RetrievalError("accepted Claims SHA-256 does not match Phase 4 report")

    expected_identity_hash = report.get("identity_links_sha256")
    if expected_identity_hash is None:
        if identity_path is not None and identity_path.exists() and identity_path.read_bytes():
            raise RetrievalError("identity links were not bound by the Phase 4 report")
    else:
        if identity_path is None:
            raise RetrievalError("Phase 4 report requires the identity-links artifact")
        if expected_identity_hash != _sha256_bytes(identity_path.read_bytes()):
            raise RetrievalError("identity-links SHA-256 does not match Phase 4 report")

    if not bool(report.get("may_build_review_index")):
        raise RetrievalError("Phase 4 does not permit a review index")
    if index_mode == "canonical" and not bool(report.get("may_publish_canonical")):
        raise RetrievalError("Phase 4 does not permit a canonical index")

    artifact_hashes = report.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict):
        raise RetrievalError("Phase 4 report is missing artifact hashes")
    datasets: dict[str, list[dict[str, object]]] = {}
    artifact_bytes: dict[str, bytes] = {}
    for name in _REQUIRED_ARTIFACTS:
        path = entity_dir / name
        if not path.is_file():
            raise RetrievalError(f"missing Phase 4 artifact: {name}")
        data = path.read_bytes()
        expected = artifact_hashes.get(name)
        actual = _sha256_bytes(data)
        if expected != actual:
            raise RetrievalError(f"artifact SHA-256 mismatch: {name}")
        artifact_bytes[name] = data
        datasets[name] = _load_jsonl(path, name)

    # A self-consistent forged report and forged artifacts must not become an
    # authority boundary. Re-run Phase 4 from the accepted Claims and source,
    # then require byte-for-byte equality with every published artifact. This
    # also re-runs current typed Claim validation through normalize_entities().
    accepted_records = _load_jsonl(accepted_claims_path, "accepted Claim", allow_empty=False)
    identity_links = (
        [IdentityLink.from_dict(row) for row in _load_jsonl(identity_path, "identity link", allow_empty=False)]
        if identity_path is not None
        else []
    )
    regenerated = normalize_entities(
        accepted_records,
        source_text,
        units,
        identity_links=identity_links,
    )
    regenerated_datasets: dict[str, Sequence[object]] = {
        "mentions.jsonl": regenerated.mentions,
        "entities.jsonl": regenerated.entities,
        "facts.jsonl": regenerated.facts,
        "timeline.jsonl": regenerated.timeline,
        "conflicts.jsonl": regenerated.conflicts,
        "ambiguity-groups.jsonl": regenerated.ambiguity_groups,
    }
    for name, rows in regenerated_datasets.items():
        if _jsonl_bytes(rows) != artifact_bytes[name]:
            raise RetrievalError(f"Phase 4 artifact differs from fresh normalization: {name}")
    for key, value in regenerated.report.items():
        if report.get(key) != value:
            raise RetrievalError(f"Phase 4 report differs from fresh normalization: {key}")

    entity_ids = _unique_ids(datasets["entities.jsonl"], "entity_id", "entity")
    mention_ids = _unique_ids(datasets["mentions.jsonl"], "mention_id", "mention")
    fact_ids = _unique_ids(datasets["facts.jsonl"], "fact_id", "fact")
    _unique_ids(datasets["timeline.jsonl"], "event_id", "timeline event")
    _unique_ids(datasets["conflicts.jsonl"], "conflict_id", "conflict")
    _unique_ids(datasets["ambiguity-groups.jsonl"], "ambiguity_id", "ambiguity")

    for row in datasets["entities.jsonl"]:
        for mention_id in row.get("mention_ids", []):
            if mention_id not in mention_ids:
                raise RetrievalError("entity references an unknown mention")
    for row in datasets["mentions.jsonl"]:
        source = _require_text(row, "source_id", "mention")
        unit_id_value = _require_text(row, "unit_id", "mention")
        start = _require_int(row, "evidence_start", "mention")
        end = _require_int(row, "evidence_end", "mention")
        unit = unit_lookup.get((source, unit_id_value))
        if unit is None or not (unit.start <= start < end <= unit.end):
            raise RetrievalError("mention span is outside its Unit")
        surface = _require_text(row, "surface", "mention")
        if source_text[start:end] != surface:
            raise RetrievalError("mention surface does not match source span")

    for row in datasets["facts.jsonl"]:
        source = _require_text(row, "source_id", "fact")
        unit_id_value = _require_text(row, "unit_id", "fact")
        start = _require_int(row, "evidence_start", "fact")
        end = _require_int(row, "evidence_end", "fact")
        unit = unit_lookup.get((source, unit_id_value))
        if unit is None or not (unit.start <= start < end <= unit.end):
            raise RetrievalError("fact span is outside its Unit")
        evidence = source_text[start:end]
        if row.get("evidence_sha256") != _sha256_bytes(evidence.encode("utf-8")):
            raise RetrievalError("fact evidence hash does not match source span")
        for key in ("subject_entity_id", "object_entity_id"):
            value = row.get(key)
            if value is not None and value not in entity_ids:
                raise RetrievalError(f"fact references an unknown entity in {key}")

    for row in datasets["timeline.jsonl"]:
        if _require_text(row, "fact_id", "timeline event") not in fact_ids:
            raise RetrievalError("timeline event references an unknown fact")
    for row in datasets["conflicts.jsonl"]:
        for fact_id in row.get("fact_ids", []):
            if fact_id not in fact_ids:
                raise RetrievalError("conflict references an unknown fact")
        for entity_id in row.get("entity_ids", []):
            if entity_id not in entity_ids:
                raise RetrievalError("conflict references an unknown entity")
        for mention_id in row.get("mention_ids", []):
            if mention_id not in mention_ids:
                raise RetrievalError("conflict references an unknown mention")
    for row in datasets["ambiguity-groups.jsonl"]:
        for entity_id in row.get("entity_ids", []):
            if entity_id not in entity_ids:
                raise RetrievalError("ambiguity group references an unknown entity")
        for mention_id in row.get("mention_ids", []):
            if mention_id not in mention_ids:
                raise RetrievalError("ambiguity group references an unknown mention")

    return source_text, units, datasets, report


def _create_schema(connection: sqlite3.Connection) -> dict[str, bool]:
    connection.executescript(
        """
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE units(
            source_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            norm_start INTEGER NOT NULL,
            norm_end INTEGER NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY(source_id, unit_id)
        );
        CREATE TABLE entities(
            entity_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            source_ids_json TEXT NOT NULL,
            unit_ids_json TEXT NOT NULL,
            merge_basis_json TEXT NOT NULL
        );
        CREATE TABLE entity_names(
            entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            is_canonical INTEGER NOT NULL,
            PRIMARY KEY(entity_id, normalized_name)
        );
        CREATE INDEX entity_names_lookup ON entity_names(normalized_name);
        CREATE TABLE mentions(
            mention_id TEXT PRIMARY KEY,
            claim_result_id TEXT NOT NULL,
            role TEXT NOT NULL,
            surface TEXT NOT NULL,
            normalized_surface TEXT NOT NULL,
            inferred_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            evidence_start INTEGER NOT NULL,
            evidence_end INTEGER NOT NULL
        );
        CREATE TABLE facts(
            fact_id TEXT PRIMARY KEY,
            claim_result_id TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            predicate_scope TEXT NOT NULL,
            subject_entity_id TEXT,
            subject TEXT NOT NULL,
            normalized_subject TEXT NOT NULL,
            object_entity_id TEXT,
            object_text TEXT NOT NULL,
            normalized_object TEXT NOT NULL,
            value_json TEXT NOT NULL,
            value_text TEXT NOT NULL,
            unit TEXT NOT NULL,
            polarity INTEGER NOT NULL,
            source_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            evidence_start INTEGER NOT NULL,
            evidence_end INTEGER NOT NULL,
            evidence_text TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            temporal_marker TEXT NOT NULL,
            canonical_status TEXT NOT NULL
        );
        CREATE INDEX facts_subject ON facts(claim_type, subject_entity_id, normalized_subject);
        CREATE INDEX facts_object ON facts(claim_type, object_entity_id, normalized_object);
        CREATE INDEX facts_scope ON facts(claim_type, predicate_scope, canonical_status);
        CREATE TABLE timeline(
            event_id TEXT PRIMARY KEY,
            fact_id TEXT NOT NULL REFERENCES facts(fact_id),
            source_id TEXT NOT NULL,
            unit_id TEXT NOT NULL,
            source_order INTEGER NOT NULL,
            evidence_start INTEGER NOT NULL,
            evidence_end INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            predicate_scope TEXT NOT NULL,
            normalized_date TEXT,
            temporal_marker TEXT NOT NULL,
            subject_entity_id TEXT,
            object_entity_id TEXT
        );
        CREATE INDEX timeline_fact ON timeline(fact_id);
        CREATE INDEX timeline_source_order ON timeline(source_id, source_order);
        CREATE TABLE conflicts(
            conflict_id TEXT PRIMARY KEY,
            conflict_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            entity_ids_json TEXT NOT NULL,
            fact_ids_json TEXT NOT NULL,
            mention_ids_json TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        CREATE TABLE ambiguity_groups(
            ambiguity_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            normalized_surface TEXT NOT NULL,
            surfaces_json TEXT NOT NULL,
            entity_ids_json TEXT NOT NULL,
            mention_ids_json TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        CREATE INDEX ambiguity_surface ON ambiguity_groups(source_id, normalized_surface);
        """
    )
    capabilities = {"fts5": False, "trigram": False}
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE unit_fts USING fts5(source_id UNINDEXED, unit_id UNINDEXED, text, tokenize='trigram')"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE fact_fts USING fts5(fact_id UNINDEXED, text, tokenize='trigram')"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE entity_fts USING fts5(entity_id UNINDEXED, text, tokenize='trigram')"
        )
        capabilities.update({"fts5": True, "trigram": True})
    except sqlite3.OperationalError:
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE unit_fts USING fts5(source_id UNINDEXED, unit_id UNINDEXED, text)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE fact_fts USING fts5(fact_id UNINDEXED, text)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE entity_fts USING fts5(entity_id UNINDEXED, text)"
            )
            capabilities["fts5"] = True
        except sqlite3.OperationalError:
            pass
    return capabilities


def _insert_rows(
    connection: sqlite3.Connection,
    source_text: str,
    units: Sequence[UnitSpan],
    datasets: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    fts5: bool,
) -> None:
    for unit in sorted(units, key=lambda item: (item.source_id, item.start, item.end, item.unit_id)):
        text = source_text[unit.start : unit.end]
        connection.execute(
            "INSERT INTO units VALUES(?,?,?,?,?)",
            (unit.source_id, unit.unit_id, unit.start, unit.end, text),
        )
        if fts5:
            connection.execute("INSERT INTO unit_fts VALUES(?,?,?)", (unit.source_id, unit.unit_id, text))

    for row in sorted(datasets["entities.jsonl"], key=lambda item: str(item["entity_id"])):
        entity_id = str(row["entity_id"])
        canonical_name = str(row["canonical_name"])
        aliases = [str(item) for item in row.get("aliases", [])]
        if canonical_name not in aliases:
            aliases.append(canonical_name)
        aliases = sorted(set(aliases), key=lambda item: (_normalize_surface(item), item))
        connection.execute(
            "INSERT INTO entities VALUES(?,?,?,?,?,?,?,?)",
            (
                entity_id,
                canonical_name,
                _normalize_surface(canonical_name),
                str(row.get("entity_type", "unknown")),
                _canonical_json(aliases),
                _canonical_json(row.get("source_ids", [])),
                _canonical_json(row.get("unit_ids", [])),
                _canonical_json(row.get("merge_basis", [])),
            ),
        )
        for alias in aliases:
            normalized = _normalize_surface(alias)
            connection.execute(
                "INSERT OR IGNORE INTO entity_names VALUES(?,?,?,?)",
                (entity_id, alias, normalized, int(alias == canonical_name)),
            )
        if fts5:
            connection.execute("INSERT INTO entity_fts VALUES(?,?)", (entity_id, " ".join(aliases)))

    for row in sorted(datasets["mentions.jsonl"], key=lambda item: str(item["mention_id"])):
        connection.execute(
            "INSERT INTO mentions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                row["mention_id"], row["claim_result_id"], row["role"], row["surface"],
                row["normalized_surface"], row["inferred_type"], row["source_id"],
                row["unit_id"], row["evidence_start"], row["evidence_end"],
            ),
        )

    for row in sorted(datasets["facts.jsonl"], key=lambda item: str(item["fact_id"])):
        start = int(row["evidence_start"])
        end = int(row["evidence_end"])
        evidence = source_text[start:end]
        value = row.get("value")
        value_text = "" if value is None else str(value)
        connection.execute(
            "INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["fact_id"], row["claim_result_id"], row["claim_type"],
                row.get("predicate_scope", ""), row.get("subject_entity_id"), row.get("subject", ""),
                _normalize_surface(str(row.get("subject", ""))), row.get("object_entity_id"),
                row.get("object", ""), _normalize_surface(str(row.get("object", ""))),
                _canonical_json(value), value_text, row.get("unit", ""), int(bool(row.get("polarity", True))),
                row["source_id"], row["unit_id"], start, end, evidence, row["evidence_sha256"],
                row.get("temporal_marker", "none"), row.get("canonical_status", "canonical"),
            ),
        )
        if fts5:
            content = " ".join(
                item for item in (
                    str(row.get("subject", "")), str(row.get("object", "")), value_text,
                    str(row.get("unit", "")), evidence,
                ) if item
            )
            connection.execute("INSERT INTO fact_fts VALUES(?,?)", (row["fact_id"], content))

    for row in sorted(datasets["timeline.jsonl"], key=lambda item: str(item["event_id"])):
        connection.execute(
            "INSERT INTO timeline VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["event_id"], row["fact_id"], row["source_id"], row["unit_id"],
                row["source_order"], row["evidence_start"], row["evidence_end"],
                row["event_type"], row.get("predicate_scope", ""), row.get("normalized_date"),
                row.get("temporal_marker", "none"), row.get("subject_entity_id"), row.get("object_entity_id"),
            ),
        )
    for row in sorted(datasets["conflicts.jsonl"], key=lambda item: str(item["conflict_id"])):
        connection.execute(
            "INSERT INTO conflicts VALUES(?,?,?,?,?,?,?,?)",
            (
                row["conflict_id"], row["conflict_type"], row["severity"], row["status"],
                _canonical_json(row.get("entity_ids", [])), _canonical_json(row.get("fact_ids", [])),
                _canonical_json(row.get("mention_ids", [])), _canonical_json(row.get("details", {})),
            ),
        )
    for row in sorted(datasets["ambiguity-groups.jsonl"], key=lambda item: str(item["ambiguity_id"])):
        connection.execute(
            "INSERT INTO ambiguity_groups VALUES(?,?,?,?,?,?,?)",
            (
                row["ambiguity_id"], row["source_id"], row["normalized_surface"],
                _canonical_json(row.get("surfaces", [])), _canonical_json(row.get("entity_ids", [])),
                _canonical_json(row.get("mention_ids", [])), row["reason"],
            ),
        )


def build_hybrid_index(
    source_path: str | Path,
    units_path: str | Path,
    accepted_claims_path: str | Path,
    entity_dir: str | Path,
    database_path: str | Path,
    *,
    identity_links_path: str | Path | None = None,
    index_mode: str = "review",
    source_id: str = "source",
    report_path: str | Path | None = None,
) -> dict[str, object]:
    """Build an atomic SQLite index after verifying the full Phase 4 chain."""

    source_text, units, datasets, phase4_report = verify_phase4_artifacts(
        source_path,
        units_path,
        accepted_claims_path,
        entity_dir,
        identity_links_path=identity_links_path,
        index_mode=index_mode,
        source_id=source_id,
    )
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = database_path.with_name(f".{database_path.name}.tmp")
    temporary.unlink(missing_ok=True)

    logical_payload = {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "index_mode": index_mode,
        "source_sha256": phase4_report["source_sha256"],
        "unit_index_sha256": phase4_report["unit_index_sha256"],
        "accepted_claims_sha256": phase4_report["accepted_claims_sha256"],
        "identity_links_sha256": phase4_report.get("identity_links_sha256"),
        "artifact_sha256": phase4_report["artifact_sha256"],
    }
    logical_hash = _sha256_bytes(_canonical_json(logical_payload).encode("utf-8"))

    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA page_size=4096")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA foreign_keys=ON")
        capabilities = _create_schema(connection)
        _insert_rows(connection, source_text, units, datasets, fts5=capabilities["fts5"])
        metadata = {
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "query_parser_version": QUERY_PARSER_VERSION,
            "index_mode": index_mode,
            "index_logical_sha256": logical_hash,
            "source_sha256": phase4_report["source_sha256"],
            "unit_index_sha256": phase4_report["unit_index_sha256"],
            "accepted_claims_sha256": phase4_report["accepted_claims_sha256"],
            "normalizer_version": phase4_report["normalizer_version"],
            "fts5": str(int(capabilities["fts5"])),
            "trigram": str(int(capabilities["trigram"])),
        }
        connection.executemany("INSERT INTO metadata VALUES(?,?)", sorted(metadata.items()))
        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    finally:
        try:
            connection.close()
        except Exception:
            pass

    temporary.replace(database_path)
    report = {
        "status": "completed",
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "query_parser_version": QUERY_PARSER_VERSION,
        "index_mode": index_mode,
        "index_logical_sha256": logical_hash,
        "database_sha256": _sha256_bytes(database_path.read_bytes()),
        "fts5_available": capabilities["fts5"],
        "trigram_available": capabilities["trigram"],
        "unit_count": len(units),
        "entity_count": len(datasets["entities.jsonl"]),
        "fact_count": len(datasets["facts.jsonl"]),
        "timeline_event_count": len(datasets["timeline.jsonl"]),
        "conflict_count": len(datasets["conflicts.jsonl"]),
        "ambiguity_group_count": len(datasets["ambiguity-groups.jsonl"]),
        "may_answer_typed_queries": True,
        "may_answer_open_queries": False,
        "may_freeze": False,
    }
    output_report = Path(report_path) if report_path is not None else database_path.with_suffix(".report.json")
    report_temp = output_report.with_name(f".{output_report.name}.tmp")
    report_temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_temp.replace(output_report)
    return report


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return {str(key): str(value) for key, value in connection.execute("SELECT key,value FROM metadata")}
    except sqlite3.DatabaseError as exc:
        raise RetrievalError("database is not a valid Phase 5 index") from exc


def _resolve_entities(
    connection: sqlite3.Connection,
    surface: str,
    *,
    source_id: str | None,
) -> list[str]:
    normalized = _normalize_surface(surface)
    if not normalized:
        return []
    rows = connection.execute(
        "SELECT DISTINCT n.entity_id FROM entity_names n JOIN entities e ON e.entity_id=n.entity_id WHERE n.normalized_name=? ORDER BY n.entity_id",
        (normalized,),
    ).fetchall()
    entity_ids = [str(row[0]) for row in rows]
    if source_id is None:
        return entity_ids
    filtered: list[str] = []
    for entity_id in entity_ids:
        source_json = connection.execute(
            "SELECT source_ids_json FROM entities WHERE entity_id=?", (entity_id,)
        ).fetchone()
        if source_json and source_id in json.loads(source_json[0]):
            filtered.append(entity_id)
    return filtered


def _fact_rows_for_intent(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    subject_entities: Sequence[str],
    object_entities: Sequence[str],
    *,
    source_id: str | None,
) -> list[sqlite3.Row]:
    clauses = ["claim_type=?"]
    params: list[object] = [intent.predicate]
    if source_id is not None:
        clauses.append("source_id=?")
        params.append(source_id)

    normalized_subject = _normalize_surface(intent.subject)
    normalized_object = _normalize_surface(intent.object)

    if intent.predicate == "alias":
        if intent.requested_role == "boolean":
            clauses.append("normalized_subject=? AND normalized_object=?")
            params.extend((normalized_subject, normalized_object))
        elif subject_entities:
            clauses.append("(subject_entity_id IN (%s) OR object_entity_id IN (%s))" % (
                ",".join("?" for _ in subject_entities), ",".join("?" for _ in subject_entities)
            ))
            params.extend(subject_entities)
            params.extend(subject_entities)
        else:
            clauses.append("(normalized_subject=? OR normalized_object=?)")
            params.extend((normalized_subject, normalized_subject))
    elif intent.predicate == "defeats":
        if intent.requested_role == "subject":
            if object_entities:
                clauses.append("object_entity_id IN (%s)" % ",".join("?" for _ in object_entities))
                params.extend(object_entities)
            else:
                clauses.append("normalized_object=?")
                params.append(normalized_object)
        else:
            if subject_entities:
                clauses.append("subject_entity_id IN (%s)" % ",".join("?" for _ in subject_entities))
                params.extend(subject_entities)
            else:
                clauses.append("normalized_subject=?")
                params.append(normalized_subject)
            if intent.requested_role == "boolean":
                if object_entities:
                    clauses.append("object_entity_id IN (%s)" % ",".join("?" for _ in object_entities))
                    params.extend(object_entities)
                else:
                    clauses.append("normalized_object=?")
                    params.append(normalized_object)
    elif intent.predicate in {"located_in", "count", "date", "permission"}:
        if subject_entities:
            clauses.append("subject_entity_id IN (%s)" % ",".join("?" for _ in subject_entities))
            params.extend(subject_entities)
        else:
            clauses.append("normalized_subject=?")
            params.append(normalized_subject)
        if intent.predicate == "located_in" and intent.requested_role == "boolean":
            if object_entities:
                clauses.append("object_entity_id IN (%s)" % ",".join("?" for _ in object_entities))
                params.extend(object_entities)
            else:
                clauses.append("normalized_object=?")
                params.append(normalized_object)
        if intent.predicate == "count" and intent.unit:
            clauses.append("unit=?")
            params.append(intent.unit)
        if intent.predicate == "date" and intent.predicate_scope and intent.predicate_scope != "generic_date":
            clauses.append("predicate_scope=?")
            params.append(intent.predicate_scope)
        if intent.predicate == "permission":
            clauses.append("normalized_object=?")
            params.append(normalized_object)
            if intent.polarity is not None:
                clauses.append("polarity=?")
                params.append(int(intent.polarity))

    sql = "SELECT * FROM facts WHERE " + " AND ".join(clauses) + " ORDER BY evidence_start, fact_id"
    return list(connection.execute(sql, params).fetchall())


def _row_to_fact_hit(row: sqlite3.Row, score: float = 100.0) -> RetrievalHit:
    value = json.loads(row["value_json"])
    if row["claim_type"] == "count" and isinstance(value, str):
        try:
            number = Decimal(value)
            value = int(number) if number == number.to_integral_value() else float(number)
        except (InvalidOperation, ValueError, OverflowError):
            pass
    return RetrievalHit(
        hit_type="fact",
        score=score,
        source_id=row["source_id"],
        unit_id=row["unit_id"],
        evidence_start=row["evidence_start"],
        evidence_end=row["evidence_end"],
        evidence_text=row["evidence_text"],
        fact_id=row["fact_id"],
        entity_id=row["subject_entity_id"],
        claim_type=row["claim_type"],
        predicate_scope=row["predicate_scope"],
        canonical_status=row["canonical_status"],
        subject=row["subject"],
        object=row["object_text"],
        value=value,
        unit=row["unit"],
        polarity=bool(row["polarity"]),
        temporal_marker=row["temporal_marker"],
    )


def _answer_key(hit: RetrievalHit, intent: PredicateQuery) -> str:
    if intent.predicate == "defeats":
        return _normalize_surface(hit.subject if intent.requested_role == "subject" else hit.object or "")
    if intent.predicate in {"located_in", "alias"}:
        if intent.predicate == "alias":
            query_name = _normalize_surface(intent.subject)
            candidates = [hit.subject or "", hit.object or ""]
            return "|".join(sorted(_normalize_surface(item) for item in candidates if _normalize_surface(item) != query_name))
        return _normalize_surface(hit.object or "")
    if intent.predicate in {"count", "date"}:
        return _canonical_json(hit.value)
    if intent.predicate == "permission":
        return str(hit.polarity)
    return hit.fact_id or ""


def _select_most_precise_compatible_date(
    hits: Sequence[RetrievalHit],
) -> list[RetrievalHit]:
    """Collapse a Phase 4 date-precision refinement to its most precise value."""

    if not hits or any(hit.canonical_status != "compatible_variant" for hit in hits):
        return list(hits)
    values = {str(hit.value) for hit in hits}
    most_precise = max(values, key=lambda value: (value.count("-"), len(value), value))
    if not all(value == most_precise or most_precise.startswith(value + "-") for value in values):
        return list(hits)
    return [hit for hit in hits if str(hit.value) == most_precise]


def _select_temporal(hits: Sequence[RetrievalHit], scope: str) -> list[RetrievalHit]:
    ordered = sorted(hits, key=lambda item: (item.source_id, item.evidence_start, item.fact_id or ""))
    if not ordered or scope == "any":
        return list(ordered)
    by_source: dict[str, list[RetrievalHit]] = {}
    for hit in ordered:
        by_source.setdefault(hit.source_id, []).append(hit)
    selected: list[RetrievalHit] = []
    for group in by_source.values():
        selected.append(group[-1] if scope == "current" else group[0])
    return selected


def _lexical_terms(intent: PredicateQuery) -> list[str]:
    terms = [intent.subject, intent.object]
    if intent.predicate != "unsupported":
        terms.append(intent.predicate)
    terms.append(intent.raw_query)
    result: list[str] = []
    for term in terms:
        cleaned = unicodedata.normalize("NFKC", term).strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _lexical_hits(
    connection: sqlite3.Connection,
    intent: PredicateQuery,
    *,
    source_id: str | None,
    limit: int,
) -> list[RetrievalHit]:
    terms = [term for term in _lexical_terms(intent) if len(_normalize_surface(term)) >= 2]
    if not terms or limit <= 0:
        return []
    metadata = _metadata(connection)
    hits: list[RetrievalHit] = []
    seen: set[tuple[str, str]] = set()

    if metadata.get("fts5") == "1":
        for term in terms:
            try:
                rows = connection.execute(
                    "SELECT source_id,unit_id,text,bm25(unit_fts) AS rank FROM unit_fts WHERE unit_fts MATCH ? ORDER BY rank LIMIT ?",
                    (_fts_phrase(term), limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for row in rows:
                key = (str(row[0]), str(row[1]))
                if key in seen or (source_id is not None and key[0] != source_id):
                    continue
                seen.add(key)
                unit_row = connection.execute(
                    "SELECT norm_start,norm_end,text FROM units WHERE source_id=? AND unit_id=?",
                    key,
                ).fetchone()
                if unit_row is None:
                    continue
                text = str(unit_row[2])
                local = text.find(term)
                snippet_start = max(0, local - 80) if local >= 0 else 0
                snippet_end = min(len(text), (local + len(term) + 120) if local >= 0 else 240)
                hits.append(
                    RetrievalHit(
                        hit_type="unit_lexical",
                        score=max(0.0, 20.0 - float(row[3] or 0.0)),
                        source_id=key[0],
                        unit_id=key[1],
                        evidence_start=int(unit_row[0]) + snippet_start,
                        evidence_end=int(unit_row[0]) + snippet_end,
                        evidence_text=text[snippet_start:snippet_end],
                    )
                )
                if len(hits) >= limit:
                    return hits

    if len(hits) < limit:
        for term in terms:
            pattern = f"%{term}%"
            sql = "SELECT source_id,unit_id,norm_start,text FROM units WHERE text LIKE ?"
            params: list[object] = [pattern]
            if source_id is not None:
                sql += " AND source_id=?"
                params.append(source_id)
            sql += " ORDER BY source_id,norm_start LIMIT ?"
            params.append(limit)
            for row in connection.execute(sql, params):
                key = (str(row[0]), str(row[1]))
                if key in seen:
                    continue
                seen.add(key)
                text = str(row[3])
                local = text.find(term)
                snippet_start = max(0, local - 80)
                snippet_end = min(len(text), local + len(term) + 120)
                hits.append(
                    RetrievalHit(
                        hit_type="unit_lexical",
                        score=10.0,
                        source_id=key[0],
                        unit_id=key[1],
                        evidence_start=int(row[2]) + snippet_start,
                        evidence_end=int(row[2]) + snippet_end,
                        evidence_text=text[snippet_start:snippet_end],
                    )
                )
                if len(hits) >= limit:
                    return hits
    return hits


def _verify_database_report(database_path: Path, report_path: Path | None) -> dict[str, object]:
    path = report_path or database_path.with_suffix(".report.json")
    if not path.is_file():
        raise RetrievalError("index report is missing")
    report = _load_json_object(path, "index report")
    if report.get("status") != "completed":
        raise RetrievalError("index report status is not completed")
    if report.get("index_schema_version") != INDEX_SCHEMA_VERSION:
        raise RetrievalError("index report schema version mismatch")
    if report.get("database_sha256") != _sha256_bytes(database_path.read_bytes()):
        raise RetrievalError("database SHA-256 does not match index report")
    return report


def query_hybrid_index(
    database_path: str | Path,
    question: str,
    *,
    source_id: str | None = None,
    limit: int = 10,
    verify_database: bool = True,
    report_path: str | Path | None = None,
) -> QueryResult:
    """Retrieve typed evidence and make a conservative answerability decision."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 100:
        raise RetrievalError("limit must be an integer between 1 and 100")
    intent = parse_predicate_query(question)
    database_path = Path(database_path)
    report = _verify_database_report(
        database_path, Path(report_path) if report_path is not None else None
    ) if verify_database else None
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        metadata = _metadata(connection)
        if metadata.get("index_schema_version") != INDEX_SCHEMA_VERSION:
            raise RetrievalError("index schema version mismatch")
        logical_hash = metadata.get("index_logical_sha256", "")
        if report is not None and report.get("index_logical_sha256") != logical_hash:
            raise RetrievalError("index report logical hash does not match database metadata")
        lexical = tuple(_lexical_hits(connection, intent, source_id=source_id, limit=min(limit, 20)))
        if not intent.supported:
            return QueryResult(
                QUERY_PARSER_VERSION, INDEX_SCHEMA_VERSION, logical_hash, intent,
                "unsupported", ("UNSUPPORTED_OPEN_PREDICATE",), (), (), lexical,
            )

        subject_entities = _resolve_entities(connection, intent.subject, source_id=source_id) if intent.subject else []
        object_entities = _resolve_entities(connection, intent.object, source_id=source_id) if intent.object else []
        ambiguity_reasons: list[str] = []
        if intent.subject and len(subject_entities) > 1:
            ambiguity_reasons.append("AMBIGUOUS_SUBJECT_ENTITY")
        if intent.object and len(object_entities) > 1:
            ambiguity_reasons.append("AMBIGUOUS_OBJECT_ENTITY")
        resolved = tuple(sorted(set(subject_entities + object_entities)))
        if ambiguity_reasons:
            return QueryResult(
                QUERY_PARSER_VERSION, INDEX_SCHEMA_VERSION, logical_hash, intent,
                "ambiguous", tuple(ambiguity_reasons), resolved, (), lexical,
            )

        rows = _fact_rows_for_intent(
            connection, intent, subject_entities, object_entities, source_id=source_id
        )
        hits = [_row_to_fact_hit(row) for row in rows]
        if not hits:
            return QueryResult(
                QUERY_PARSER_VERSION, INDEX_SCHEMA_VERSION, logical_hash, intent,
                "not_answerable", ("NO_TYPED_FACT_MATCH",), resolved, (), lexical,
            )

        if any(hit.canonical_status == "contested" for hit in hits):
            return QueryResult(
                QUERY_PARSER_VERSION, INDEX_SCHEMA_VERSION, logical_hash, intent,
                "ambiguous", ("CONTESTED_FACTS_PRESENT",), resolved,
                tuple(hits[:limit]), lexical,
            )

        active = [hit for hit in hits if hit.canonical_status in {"canonical", "temporal_variant", "compatible_variant"}]
        if not active:
            return QueryResult(
                QUERY_PARSER_VERSION, INDEX_SCHEMA_VERSION, logical_hash, intent,
                "not_answerable", ("NO_CANONICAL_FACT_MATCH",), resolved, (), lexical,
            )

        if intent.predicate == "date":
            active = _select_most_precise_compatible_date(active)

        distinct = {_answer_key(hit, intent) for hit in active}
        if len(distinct) > 1:
            if all(hit.canonical_status == "temporal_variant" for hit in active) and intent.temporal_scope != "any":
                active = _select_temporal(active, intent.temporal_scope)
                distinct = {_answer_key(hit, intent) for hit in active}
            if len(distinct) > 1:
                reason = "TEMPORAL_SCOPE_REQUIRED" if any(
                    hit.canonical_status == "temporal_variant" for hit in active
                ) else "MULTIPLE_TYPED_ANSWERS"
                return QueryResult(
                    QUERY_PARSER_VERSION, INDEX_SCHEMA_VERSION, logical_hash, intent,
                    "ambiguous", (reason,), resolved, tuple(active[:limit]), lexical,
                )

        return QueryResult(
            QUERY_PARSER_VERSION, INDEX_SCHEMA_VERSION, logical_hash, intent,
            "answerable", ("TYPED_FACT_MATCH",), resolved, tuple(active[:limit]), lexical,
        )
    finally:
        connection.close()
