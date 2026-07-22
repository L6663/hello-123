"""Deterministic, evidence-first querying for the Stage 7 literary engine.

The query layer answers only from indexed literary records.  It exposes the
A/B/C epistemic tier of every returned assertion and never converts a C-tier
interpretation into a source fact.  Open wording may retrieve candidate evidence,
but unsupported synthesis is refused rather than invented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Mapping, Sequence
import unicodedata

from .hashing import sha256_file
from .literary_engine import (
    LITERARY_INDEX_SCHEMA_VERSION,
    LiteraryEngineError,
    verify_literary_engine,
)
from .literary_models import LITERARY_SYSTEM_VERSION

LITERARY_QUERY_SCHEMA_VERSION = "tkr-literary-query-v1"
LITERARY_CITATION_SCHEMA_VERSION = "tkr-literary-citation-v1"
LITERARY_QUERY_PARSER_VERSION = "tkr-literary-query-parser-v1"


class LiteraryQueryError(ValueError):
    """Raised when a literary query or sidecar is malformed."""


@dataclass(frozen=True, slots=True)
class LiteraryQueryIntent:
    intent_type: str
    raw_question: str
    normalized_question: str
    subject: str
    object: str
    volume_ordinal: int | None
    chapter_ordinal: int | None
    event_component: str
    requested_tier: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LiteraryCitation:
    citation_id: str
    citation_schema_version: str
    anchor_id: str
    source_id: str
    chapter_id: str
    unit_id: str
    volume_ordinal: int | None
    chapter_ordinal: int | None
    original_heading: str
    normalized_heading: str
    evidence_start: int
    evidence_end: int
    evidence_text: str
    evidence_sha256: str
    evidence_role: str
    source_status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LiteraryAnswerItem:
    record_type: str
    record_id: str
    tier: str | None
    classification: str
    subject: str
    predicate: str
    object: str
    value: object
    confidence: float | None
    attribution: str
    status: str
    chapter_id: str | None
    volume_ordinal: int | None
    chapter_ordinal: int | None
    support_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["support_ids"] = list(self.support_ids)
        payload["citation_ids"] = list(self.citation_ids)
        return payload


@dataclass(frozen=True, slots=True)
class LiteraryQueryPacket:
    schema_version: str
    query_parser_version: str
    literary_system_version: str
    literary_index_schema_version: str
    literary_logical_sha256: str
    database_sha256: str
    question: str
    intent: LiteraryQueryIntent
    decision: str
    refusal_kind: str | None
    reason_codes: tuple[str, ...]
    answer_text: str
    answer_items: tuple[LiteraryAnswerItem, ...]
    citations: tuple[LiteraryCitation, ...]
    fact_count: int
    synthesis_count: int
    interpretation_count: int
    may_present: bool
    may_accept_project: bool
    may_freeze: bool
    packet_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "query_parser_version": self.query_parser_version,
            "literary_system_version": self.literary_system_version,
            "literary_index_schema_version": self.literary_index_schema_version,
            "literary_logical_sha256": self.literary_logical_sha256,
            "database_sha256": self.database_sha256,
            "question": self.question,
            "intent": self.intent.to_dict(),
            "decision": self.decision,
            "refusal_kind": self.refusal_kind,
            "reason_codes": list(self.reason_codes),
            "answer_text": self.answer_text,
            "answer_items": [item.to_dict() for item in self.answer_items],
            "citations": [item.to_dict() for item in self.citations],
            "fact_count": self.fact_count,
            "synthesis_count": self.synthesis_count,
            "interpretation_count": self.interpretation_count,
            "may_present": self.may_present,
            "may_accept_project": self.may_accept_project,
            "may_freeze": self.may_freeze,
            "packet_id": self.packet_id,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"[\s\u3000，。！？；：、,.!?;:\-—_()（）\[\]【】{}《》〈〉\"'“”‘’]+", "", text)


def _clean(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    return value.strip("，。！？；：、,.!?;: \t\r\n")


def parse_literary_query(question: str) -> LiteraryQueryIntent:
    if not isinstance(question, str) or not question.strip():
        raise LiteraryQueryError("question must be a non-empty string")
    raw = unicodedata.normalize("NFKC", question).strip()
    compact = re.sub(r"\s+", "", raw)
    normalized = _normalized(raw)

    tier_match = re.search(r"(?:只看|限定|按)?([ABC])级", compact, re.IGNORECASE)
    requested_tier = tier_match.group(1).upper() if tier_match else None

    patterns: list[tuple[str, re.Pattern[str]]] = [
        (
            "relationship_at",
            re.compile(
                r"^(?P<subject>.+?)(?:与|和|跟)(?P<object>.+?)(?:在)?(?:第)?(?:(?P<volume>\d+)卷)?(?:第)?(?P<chapter>\d+)章(?:时|期间)?(?:是什么关系|关系如何|处于什么关系)[？?]*$"
            ),
        ),
        (
            "first_appearance",
            re.compile(r"^(?P<subject>.+?)(?:第一次|首次)(?:出现|出场)(?:在|是)?(?:哪一章|哪里|何处)[？?]*$"),
        ),
        (
            "last_appearance",
            re.compile(r"^(?P<subject>.+?)(?:最后一次|最后)(?:出现|出场)(?:在|是)?(?:哪一章|哪里|何处)[？?]*$"),
        ),
        (
            "occurrence_count",
            re.compile(r"^(?P<subject>.+?)(?:一共|总共)?(?:出现过|出现|被提到)(?:多少次|几次)[？?]*$"),
        ),
        (
            "classification",
            re.compile(r"^(?P<subject>.+?)(?:是|属于)(?:原文事实|事实|归纳|解释|模型见解)(?:还是|吗|么)?.*$"),
        ),
        (
            "evidence",
            re.compile(r"^(?P<subject>.+?)(?:有哪些证据|证据是什么|依据是什么|原文依据是什么|在哪有证据)[？?]*$"),
        ),
        (
            "event_cause",
            re.compile(r"^(?P<subject>.+?)(?:为什么|为何|因何)(?:发生|失败|成功|复生|失势|决裂|合作)?[？?]*$"),
        ),
        (
            "event_process",
            re.compile(r"^(?P<subject>.+?)(?:如何|怎么)(?:发生|完成|实现|复生|失败|成功)?[？?]*$"),
        ),
        (
            "event_outcome",
            re.compile(r"^(?P<subject>.+?)(?:结果是什么|最终结果如何|结局如何)[？?]*$"),
        ),
        (
            "event_consequence",
            re.compile(r"^(?P<subject>.+?)(?:导致什么|造成什么|有什么后果|长期影响是什么)[？?]*$"),
        ),
        (
            "event_foreshadowing",
            re.compile(r"^(?P<subject>.+?)(?:伏笔在哪里|有哪些伏笔|何时铺垫|在哪里回收)[？?]*$"),
        ),
        (
            "entity_profile",
            re.compile(r"^(?P<subject>.+?)(?:是谁|是什么人物|是什么势力|是什么术法|是什么地点|是什么)[？?]*$"),
        ),
        (
            "quote_search",
            re.compile(r"^(?:查找|检索|找出|原文搜索|对话搜索)(?P<subject>.+?)[？?]*$"),
        ),
    ]
    for intent_type, pattern in patterns:
        match = pattern.match(compact)
        if not match:
            continue
        groups = match.groupdict()
        subject = _clean(groups.get("subject") or "")
        object_text = _clean(groups.get("object") or "")
        volume = groups.get("volume")
        chapter = groups.get("chapter")
        component = {
            "event_cause": "cause",
            "event_process": "process",
            "event_outcome": "outcome",
            "event_consequence": "consequence",
            "event_foreshadowing": "foreshadowing",
        }.get(intent_type, "")
        return LiteraryQueryIntent(
            intent_type,
            raw,
            normalized,
            subject,
            object_text,
            int(volume) if volume else None,
            int(chapter) if chapter else None,
            component,
            requested_tier,
        )

    return LiteraryQueryIntent(
        "open_evidence_search",
        raw,
        normalized,
        _clean(raw),
        "",
        None,
        None,
        "",
        requested_tier,
    )


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return {str(key): str(value) for key, value in connection.execute("SELECT key,value FROM metadata")}
    except sqlite3.DatabaseError as exc:
        raise LiteraryQueryError("database is not a valid literary index") from exc


def _resolve_entity(connection: sqlite3.Connection, surface: str) -> list[sqlite3.Row]:
    normalized = _normalized(surface)
    if not normalized:
        return []
    return list(
        connection.execute(
            """
            SELECT DISTINCT e.*
            FROM aliases a JOIN entities e ON e.entity_id=a.entity_id
            WHERE a.normalized_alias=?
            ORDER BY e.entity_id
            """,
            (normalized,),
        ).fetchall()
    )


def _citation(row: sqlite3.Row, ordinal: int) -> LiteraryCitation:
    return LiteraryCitation(
        f"E{ordinal}",
        LITERARY_CITATION_SCHEMA_VERSION,
        str(row["anchor_id"]),
        str(row["source_id"]),
        str(row["chapter_id"]),
        str(row["unit_id"]),
        row["volume_ordinal"],
        row["chapter_ordinal"],
        str(row["original_heading"]),
        str(row["normalized_heading"]),
        int(row["evidence_start"]),
        int(row["evidence_end"]),
        str(row["evidence_text"]),
        str(row["evidence_sha256"]),
        str(row["evidence_role"]),
        str(row["source_status"]),
    )


def _chapter_label(volume: object, chapter: object, heading: object) -> str:
    parts: list[str] = []
    if isinstance(volume, int):
        parts.append(f"卷{volume}")
    if isinstance(chapter, int):
        parts.append(f"第{chapter}章")
    label = " ".join(parts)
    heading_text = str(heading or "").strip()
    if heading_text and heading_text not in label:
        label = f"{label}（{heading_text}）" if label else heading_text
    return label or "未规范编号章节"


def _assertion_rows(
    connection: sqlite3.Connection,
    entity_ids: Sequence[str],
    subject_text: str,
    *,
    component: str = "",
    requested_tier: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    clauses = ["a.status IN ('active','contested','needs_review')"]
    params: list[object] = []
    if entity_ids:
        marks = ",".join("?" for _ in entity_ids)
        clauses.append(f"(a.subject_entity_id IN ({marks}) OR a.object_entity_id IN ({marks}))")
        params.extend(entity_ids)
        params.extend(entity_ids)
    else:
        normalized = _normalized(subject_text)
        clauses.append(
            "(replace(lower(a.subject_text),' ','') LIKE ? OR replace(lower(a.object_text),' ','') LIKE ? OR replace(lower(a.predicate),' ','') LIKE ?)"
        )
        pattern = f"%{normalized}%"
        params.extend((pattern, pattern, pattern))
    if requested_tier:
        clauses.append("a.tier=?")
        params.append(requested_tier)
    if component:
        clauses.append(
            "EXISTS(SELECT 1 FROM event_assertions ea WHERE ea.assertion_id=a.assertion_id AND ea.component=?)"
        )
        params.append(component)
    sql = (
        "SELECT a.* FROM assertions a WHERE "
        + " AND ".join(clauses)
        + " ORDER BY CASE a.tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END, a.confidence DESC, a.assertion_id LIMIT ?"
    )
    params.append(limit)
    return list(connection.execute(sql, params).fetchall())


def _assertion_evidence(connection: sqlite3.Connection, assertion_ids: Sequence[str]) -> list[sqlite3.Row]:
    if not assertion_ids:
        return []
    marks = ",".join("?" for _ in assertion_ids)
    return list(
        connection.execute(
            f"""
            SELECT ae.assertion_id, e.*
            FROM assertion_evidence ae
            JOIN evidence_anchors e ON e.anchor_id=ae.anchor_id
            WHERE ae.assertion_id IN ({marks})
            ORDER BY e.source_id,e.evidence_start,e.anchor_id
            """,
            list(assertion_ids),
        ).fetchall()
    )


def _support_ids(connection: sqlite3.Connection, assertion_id: str) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT supporting_assertion_id FROM assertion_support WHERE assertion_id=? ORDER BY supporting_assertion_id",
            (assertion_id,),
        )
    )


def _classification(tier: str) -> str:
    return {
        "A": "原文事实",
        "B": "跨证据归纳",
        "C": "模型文学解释",
    }.get(tier, "未知层级")


def _items_from_assertions(
    connection: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
    citation_ids_by_assertion: Mapping[str, tuple[str, ...]],
) -> list[LiteraryAnswerItem]:
    result: list[LiteraryAnswerItem] = []
    for row in rows:
        assertion_identifier = str(row["assertion_id"])
        start_chapter = row["temporal_start_chapter_id"]
        volume = chapter = None
        if start_chapter:
            chapter_row = connection.execute(
                "SELECT volume_ordinal,chapter_ordinal FROM chapters WHERE chapter_id=?",
                (start_chapter,),
            ).fetchone()
            if chapter_row:
                volume, chapter = chapter_row[0], chapter_row[1]
        result.append(
            LiteraryAnswerItem(
                "assertion",
                assertion_identifier,
                str(row["tier"]),
                _classification(str(row["tier"])),
                str(row["subject_text"]),
                str(row["predicate"]),
                str(row["object_text"]),
                json.loads(str(row["value_json"])),
                float(row["confidence"]),
                str(row["attribution"]),
                str(row["status"]),
                str(start_chapter) if start_chapter else None,
                volume,
                chapter,
                _support_ids(connection, assertion_identifier),
                citation_ids_by_assertion.get(assertion_identifier, ()),
            )
        )
    return result


def _packet_id(payload: Mapping[str, object]) -> str:
    return "lqp_" + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:32]


def _make_packet(
    *,
    metadata: Mapping[str, str],
    database: Path,
    question: str,
    intent: LiteraryQueryIntent,
    decision: str,
    refusal_kind: str | None,
    reasons: Sequence[str],
    answer_text: str,
    items: Sequence[LiteraryAnswerItem],
    citations: Sequence[LiteraryCitation],
) -> LiteraryQueryPacket:
    counts = {
        tier: sum(item.tier == tier for item in items)
        for tier in ("A", "B", "C")
    }
    base: dict[str, object] = {
        "schema_version": LITERARY_QUERY_SCHEMA_VERSION,
        "query_parser_version": LITERARY_QUERY_PARSER_VERSION,
        "literary_system_version": LITERARY_SYSTEM_VERSION,
        "literary_index_schema_version": LITERARY_INDEX_SCHEMA_VERSION,
        "literary_logical_sha256": metadata.get("logical_sha256", ""),
        "database_sha256": sha256_file(database),
        "question": question,
        "intent": intent.to_dict(),
        "decision": decision,
        "refusal_kind": refusal_kind,
        "reason_codes": list(reasons),
        "answer_text": answer_text,
        "answer_items": [item.to_dict() for item in items],
        "citations": [item.to_dict() for item in citations],
        "fact_count": counts["A"],
        "synthesis_count": counts["B"],
        "interpretation_count": counts["C"],
        "may_present": True,
        "may_accept_project": False,
        "may_freeze": False,
    }
    identifier = _packet_id(base)
    return LiteraryQueryPacket(
        LITERARY_QUERY_SCHEMA_VERSION,
        LITERARY_QUERY_PARSER_VERSION,
        LITERARY_SYSTEM_VERSION,
        LITERARY_INDEX_SCHEMA_VERSION,
        str(base["literary_logical_sha256"]),
        str(base["database_sha256"]),
        question,
        intent,
        decision,
        refusal_kind,
        tuple(dict.fromkeys(reasons)),
        answer_text,
        tuple(items),
        tuple(citations),
        counts["A"],
        counts["B"],
        counts["C"],
        True,
        False,
        False,
        identifier,
    )


def _refuse(
    metadata: Mapping[str, str],
    database: Path,
    question: str,
    intent: LiteraryQueryIntent,
    kind: str,
    reasons: Sequence[str],
    message: str,
    *,
    items: Sequence[LiteraryAnswerItem] = (),
    citations: Sequence[LiteraryCitation] = (),
) -> LiteraryQueryPacket:
    return _make_packet(
        metadata=metadata,
        database=database,
        question=question,
        intent=intent,
        decision="refused",
        refusal_kind=kind,
        reasons=reasons,
        answer_text=message,
        items=items,
        citations=citations,
    )


def _first_or_last(
    connection: sqlite3.Connection,
    entity_row: sqlite3.Row,
    *,
    last: bool,
) -> tuple[str, LiteraryAnswerItem] | None:
    chapter_id = entity_row["last_chapter_id"] if last else entity_row["first_chapter_id"]
    if not chapter_id:
        return None
    chapter = connection.execute("SELECT * FROM chapters WHERE chapter_id=?", (chapter_id,)).fetchone()
    if chapter is None:
        return None
    label = _chapter_label(chapter["volume_ordinal"], chapter["chapter_ordinal"], chapter["original_heading"] or chapter["normalized_heading"])
    predicate = "last_appearance" if last else "first_appearance"
    item = LiteraryAnswerItem(
        "entity",
        str(entity_row["entity_id"]),
        "A",
        "原文位置事实",
        str(entity_row["canonical_name"]),
        predicate,
        label,
        chapter["source_order"],
        1.0,
        "source_index",
        str(entity_row["review_status"]),
        str(chapter_id),
        chapter["volume_ordinal"],
        chapter["chapter_ordinal"],
        (),
        (),
    )
    return label, item


def _relationship_at(
    connection: sqlite3.Connection,
    intent: LiteraryQueryIntent,
    subject_entities: Sequence[sqlite3.Row],
    object_entities: Sequence[sqlite3.Row],
) -> list[LiteraryAnswerItem]:
    if len(subject_entities) != 1 or len(object_entities) != 1:
        return []
    clauses = ["subject_entity_id=?", "object_entity_id=?", "status IN ('active','ended','contested')"]
    params: list[object] = [subject_entities[0]["entity_id"], object_entities[0]["entity_id"]]
    source_order: int | None = None
    if intent.chapter_ordinal is not None:
        chapter_rows = connection.execute(
            """
            SELECT * FROM chapters
            WHERE chapter_ordinal=? AND (? IS NULL OR volume_ordinal=?)
            ORDER BY source_order
            """,
            (intent.chapter_ordinal, intent.volume_ordinal, intent.volume_ordinal),
        ).fetchall()
        if len(chapter_rows) != 1:
            return []
        source_order = int(chapter_rows[0]["source_order"])
        clauses.append("(start_source_order IS NULL OR start_source_order<=?)")
        clauses.append("(end_source_order IS NULL OR end_source_order>=?)")
        params.extend((source_order, source_order))
    rows = connection.execute(
        "SELECT * FROM relationships WHERE " + " AND ".join(clauses) + " ORDER BY tier,relationship_id",
        params,
    ).fetchall()
    items: list[LiteraryAnswerItem] = []
    for row in rows:
        evidence_ids = tuple(
            str(item[0])
            for item in connection.execute(
                "SELECT anchor_id FROM relationship_evidence WHERE relationship_id=? ORDER BY anchor_id",
                (row["relationship_id"],),
            )
        )
        reason_ids = tuple(
            str(item[0])
            for item in connection.execute(
                "SELECT assertion_id FROM relationship_reasons WHERE relationship_id=? ORDER BY assertion_id",
                (row["relationship_id"],),
            )
        )
        items.append(
            LiteraryAnswerItem(
                "relationship",
                str(row["relationship_id"]),
                str(row["tier"]),
                _classification(str(row["tier"])),
                str(subject_entities[0]["canonical_name"]),
                str(row["relation_type"]),
                str(object_entities[0]["canonical_name"]),
                source_order,
                None,
                "relationship_interval",
                str(row["status"]),
                str(row["start_chapter_id"]) if row["start_chapter_id"] else None,
                intent.volume_ordinal,
                intent.chapter_ordinal,
                reason_ids,
                evidence_ids,
            )
        )
    return items


def _lexical_evidence(
    connection: sqlite3.Connection,
    text: str,
    *,
    limit: int,
) -> list[sqlite3.Row]:
    metadata = _metadata(connection)
    rows: list[sqlite3.Row] = []
    if metadata.get("fts5") == "1" and len(_normalized(text)) >= 2:
        phrase = '"' + text.replace('"', '""') + '"'
        try:
            matches = connection.execute(
                "SELECT record_type,record_id,bm25(literary_fts) rank FROM literary_fts WHERE literary_fts MATCH ? ORDER BY rank LIMIT ?",
                (phrase, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            matches = []
        anchor_ids = [str(row["record_id"]) for row in matches if row["record_type"] == "evidence"]
        if anchor_ids:
            marks = ",".join("?" for _ in anchor_ids)
            rows.extend(
                connection.execute(
                    f"SELECT * FROM evidence_anchors WHERE anchor_id IN ({marks}) ORDER BY evidence_start",
                    anchor_ids,
                ).fetchall()
            )
    if len(rows) < limit:
        pattern = f"%{text}%"
        seen = {str(row["anchor_id"]) for row in rows}
        for row in connection.execute(
            "SELECT * FROM evidence_anchors WHERE evidence_text LIKE ? ORDER BY evidence_start LIMIT ?",
            (pattern, limit),
        ):
            if str(row["anchor_id"]) not in seen:
                rows.append(row)
                seen.add(str(row["anchor_id"]))
    return rows[:limit]


def query_literary_engine(
    output_directory: str | Path,
    question: str,
    *,
    max_items: int = 20,
    max_citations: int = 12,
) -> LiteraryQueryPacket:
    """Answer a literary query from indexed facts/syntheses/interpretations or refuse."""

    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 100:
        raise LiteraryQueryError("max_items must be an integer between 1 and 100")
    if isinstance(max_citations, bool) or not isinstance(max_citations, int) or not 1 <= max_citations <= 50:
        raise LiteraryQueryError("max_citations must be an integer between 1 and 50")
    root = Path(output_directory)
    verification = verify_literary_engine(root)
    if not verification.valid:
        raise LiteraryQueryError(
            "literary sidecar failed verification: " + ",".join(verification.reason_codes)
        )
    database = root / "literary.sqlite"
    intent = parse_literary_query(question)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        metadata = _metadata(connection)
        if metadata.get("literary_system_version") != LITERARY_SYSTEM_VERSION:
            raise LiteraryQueryError("literary system version mismatch")
        if metadata.get("literary_index_schema_version") != LITERARY_INDEX_SCHEMA_VERSION:
            raise LiteraryQueryError("literary index schema version mismatch")

        subject_entities = _resolve_entity(connection, intent.subject) if intent.subject else []
        if len(subject_entities) > 1:
            return _refuse(
                metadata,
                database,
                question,
                intent,
                "ambiguous_entity",
                ("AMBIGUOUS_SUBJECT_ENTITY",),
                "该名称对应多个实体，当前证据不足以确定用户所指对象。",
            )

        if intent.intent_type == "relationship_at":
            object_entities = _resolve_entity(connection, intent.object)
            if len(object_entities) != 1 or len(subject_entities) != 1:
                return _refuse(
                    metadata,
                    database,
                    question,
                    intent,
                    "entity_not_resolved",
                    ("RELATIONSHIP_ENDPOINT_NOT_UNIQUELY_RESOLVED",),
                    "无法唯一确定关系两端的实体。",
                )
            items = _relationship_at(connection, intent, subject_entities, object_entities)
            if not items:
                return _refuse(
                    metadata,
                    database,
                    question,
                    intent,
                    "insufficient_temporal_relationship_evidence",
                    ("NO_RELATIONSHIP_INTERVAL_MATCH",),
                    "当前知识库没有记录该章节时点的关系状态。",
                )
            anchor_ids = tuple(dict.fromkeys(cid for item in items for cid in item.citation_ids))
            citations: list[LiteraryCitation] = []
            if anchor_ids:
                marks = ",".join("?" for _ in anchor_ids)
                for ordinal, row in enumerate(
                    connection.execute(
                        f"SELECT * FROM evidence_anchors WHERE anchor_id IN ({marks}) ORDER BY evidence_start",
                        list(anchor_ids),
                    ),
                    start=1,
                ):
                    citations.append(_citation(row, ordinal))
            rewritten_items = [
                LiteraryAnswerItem(
                    **{
                        **item.to_dict(),
                        "support_ids": item.support_ids,
                        "citation_ids": tuple(
                            citation.citation_id
                            for citation in citations
                            if citation.anchor_id in item.citation_ids
                        ),
                    }
                )
                for item in items
            ]
            description = "；".join(
                f"{item.subject}—{item.predicate}—{item.object}（{item.classification}）"
                for item in rewritten_items
            )
            return _make_packet(
                metadata=metadata,
                database=database,
                question=question,
                intent=intent,
                decision="answered",
                refusal_kind=None,
                reasons=("TEMPORAL_RELATIONSHIP_MATCH", "TIER_EXPLICIT"),
                answer_text=description,
                items=rewritten_items,
                citations=citations,
            )

        if intent.intent_type in {"first_appearance", "last_appearance"}:
            if len(subject_entities) != 1:
                return _refuse(
                    metadata,
                    database,
                    question,
                    intent,
                    "entity_not_resolved",
                    ("ENTITY_NOT_FOUND",),
                    "当前实体索引中没有找到该人物或对象。",
                )
            result = _first_or_last(
                connection,
                subject_entities[0],
                last=intent.intent_type == "last_appearance",
            )
            if result is None:
                return _refuse(
                    metadata,
                    database,
                    question,
                    intent,
                    "missing_chapter_address",
                    ("ENTITY_APPEARANCE_ADDRESS_MISSING",),
                    "该实体存在，但缺少可验证的章节位置。",
                )
            label, item = result
            qualifier = "最后可信出场" if intent.intent_type == "last_appearance" else "首次出场"
            return _make_packet(
                metadata=metadata,
                database=database,
                question=question,
                intent=intent,
                decision="answered",
                refusal_kind=None,
                reasons=("ENTITY_APPEARANCE_INDEX_MATCH",),
                answer_text=f"{item.subject}的{qualifier}位置是{label}。",
                items=(item,),
                citations=(),
            )

        if intent.intent_type == "occurrence_count":
            if len(subject_entities) != 1:
                return _refuse(
                    metadata,
                    database,
                    question,
                    intent,
                    "entity_not_resolved",
                    ("ENTITY_NOT_FOUND",),
                    "当前实体索引中没有找到该人物或对象。",
                )
            count = connection.execute(
                "SELECT COUNT(*) FROM entity_mentions WHERE entity_id=?",
                (subject_entities[0]["entity_id"],),
            ).fetchone()[0]
            item = LiteraryAnswerItem(
                "entity",
                str(subject_entities[0]["entity_id"]),
                "A",
                "索引计数事实",
                str(subject_entities[0]["canonical_name"]),
                "mention_count",
                "",
                int(count),
                1.0,
                "source_index",
                str(subject_entities[0]["review_status"]),
                None,
                None,
                None,
                (),
                (),
            )
            return _make_packet(
                metadata=metadata,
                database=database,
                question=question,
                intent=intent,
                decision="answered",
                refusal_kind=None,
                reasons=("ENTITY_MENTION_COUNT",),
                answer_text=f"{item.subject}在当前实体提及索引中共有{count}处可验证提及。",
                items=(item,),
                citations=(),
            )

        component = intent.event_component
        entity_ids = [str(row["entity_id"]) for row in subject_entities]
        assertion_rows = _assertion_rows(
            connection,
            entity_ids,
            intent.subject,
            component=component,
            requested_tier=intent.requested_tier,
            limit=max_items,
        )
        evidence_rows = _assertion_evidence(
            connection,
            [str(row["assertion_id"]) for row in assertion_rows],
        )
        citations: list[LiteraryCitation] = []
        citation_ids_by_assertion: dict[str, list[str]] = {}
        seen_anchors: set[str] = set()
        for row in evidence_rows:
            anchor_identifier = str(row["anchor_id"])
            assertion_identifier = str(row["assertion_id"])
            if anchor_identifier not in seen_anchors and len(citations) < max_citations:
                citation = _citation(row, len(citations) + 1)
                citations.append(citation)
                seen_anchors.add(anchor_identifier)
            citation_id = next(
                (item.citation_id for item in citations if item.anchor_id == anchor_identifier),
                None,
            )
            if citation_id is not None:
                citation_ids_by_assertion.setdefault(assertion_identifier, []).append(citation_id)
        items = _items_from_assertions(
            connection,
            assertion_rows,
            {key: tuple(value) for key, value in citation_ids_by_assertion.items()},
        )

        if intent.intent_type == "quote_search":
            lexical_rows = _lexical_evidence(connection, intent.subject, limit=max_citations)
            lexical_citations = [_citation(row, ordinal) for ordinal, row in enumerate(lexical_rows, start=1)]
            if not lexical_citations:
                return _refuse(
                    metadata,
                    database,
                    question,
                    intent,
                    "no_exact_text_match",
                    ("NO_SOURCE_TEXT_MATCH",),
                    "当前可信正文中没有找到该原文片段。",
                )
            return _make_packet(
                metadata=metadata,
                database=database,
                question=question,
                intent=intent,
                decision="answered",
                refusal_kind=None,
                reasons=("EXACT_SOURCE_TEXT_MATCH",),
                answer_text=f"找到{len(lexical_citations)}处可追溯原文。",
                items=(),
                citations=lexical_citations,
            )

        if not items:
            lexical_rows = _lexical_evidence(connection, intent.subject, limit=max_citations)
            lexical_citations = [_citation(row, ordinal) for ordinal, row in enumerate(lexical_rows, start=1)]
            if lexical_citations:
                return _refuse(
                    metadata,
                    database,
                    question,
                    intent,
                    "evidence_without_supported_conclusion",
                    ("LEXICAL_EVIDENCE_FOUND", "NO_TYPED_LITERARY_ASSERTION"),
                    "找到了相关原文，但尚无经过分层验证的结论，因此不直接作答。",
                    citations=lexical_citations,
                )
            return _refuse(
                metadata,
                database,
                question,
                intent,
                "insufficient_evidence",
                ("NO_LITERARY_ASSERTION_MATCH", "NO_SOURCE_TEXT_MATCH"),
                "当前可信语料和文学索引不足以回答该问题。",
            )

        tier_labels = "、".join(
            f"{tier}级{sum(item.tier == tier for item in items)}条"
            for tier in ("A", "B", "C")
            if any(item.tier == tier for item in items)
        )
        if intent.intent_type == "classification":
            answer_text = "；".join(
                f"{item.subject}{item.predicate}{item.object or item.value}：{item.classification}"
                for item in items
            )
        elif component:
            answer_text = f"检索到{tier_labels}与事件{component}相关的分层结论。"
        elif intent.intent_type == "entity_profile":
            answer_text = f"检索到{tier_labels}关于{intent.subject}的知识；事实、归纳与解释已分开返回。"
        elif intent.intent_type == "evidence":
            answer_text = f"检索到{len(citations)}条精确证据，支撑{tier_labels}。"
        else:
            answer_text = f"检索到{tier_labels}；系统不把B/C级内容表述为原文定论。"
        return _make_packet(
            metadata=metadata,
            database=database,
            question=question,
            intent=intent,
            decision="answered",
            refusal_kind=None,
            reasons=("LITERARY_ASSERTION_MATCH", "EPISTEMIC_TIERS_SEPARATED", "EXACT_EVIDENCE_ATTACHED"),
            answer_text=answer_text,
            items=items,
            citations=citations,
        )
    finally:
        connection.close()


__all__ = [
    "LITERARY_CITATION_SCHEMA_VERSION",
    "LITERARY_QUERY_PARSER_VERSION",
    "LITERARY_QUERY_SCHEMA_VERSION",
    "LiteraryAnswerItem",
    "LiteraryCitation",
    "LiteraryQueryError",
    "LiteraryQueryIntent",
    "LiteraryQueryPacket",
    "parse_literary_query",
    "query_literary_engine",
]
