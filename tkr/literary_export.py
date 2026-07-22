"""Deterministic Notion-ready projection for Stage 7 literary knowledge.

This module does not call the Notion API.  It emits an auditable package whose
pages and relation properties can be uploaded by an external connector.  Facts,
syntheses, and interpretations are kept in separate sections so a workspace
cannot accidentally present model analysis as source canon.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Iterable, Mapping, Sequence

from .hashing import sha256_file
from .literary_engine import verify_literary_engine

NOTION_EXPORT_SCHEMA_VERSION = "tkr-literary-notion-export-v1"


class LiteraryExportError(ValueError):
    """Raised when a literary sidecar cannot be exported safely."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _jsonl_bytes(rows: Iterable[object]) -> bytes:
    lines = [_canonical_json(row) for row in rows]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _csv_bytes(rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        cooked: dict[str, object] = {}
        for field in fields:
            value = row.get(field, "")
            if isinstance(value, (list, tuple, dict)):
                value = _canonical_json(value)
            cooked[field] = value
        writer.writerow(cooked)
    return stream.getvalue().encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _chapter_label(row: sqlite3.Row) -> str:
    parts: list[str] = []
    if row["volume_ordinal"] is not None:
        parts.append(f"卷{row['volume_ordinal']}")
    if row["chapter_ordinal"] is not None:
        parts.append(f"第{row['chapter_ordinal']}章")
    heading = str(row["original_heading"] or row["normalized_heading"] or row["title"] or "").strip()
    label = " ".join(parts)
    if heading and heading not in label:
        label = f"{label}｜{heading}" if label else heading
    return label or f"章节序号 {row['source_order']}"


def _citation_block(row: sqlite3.Row) -> dict[str, object]:
    return {
        "type": "evidence",
        "anchor_id": row["anchor_id"],
        "chapter": _chapter_label(row),
        "source_id": row["source_id"],
        "unit_id": row["unit_id"],
        "evidence_start": row["evidence_start"],
        "evidence_end": row["evidence_end"],
        "quote": row["evidence_text"],
        "evidence_sha256": row["evidence_sha256"],
        "source_status": row["source_status"],
    }


def _assertion_page(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, object]:
    evidence = connection.execute(
        """
        SELECT e.* FROM assertion_evidence ae
        JOIN evidence_anchors e ON e.anchor_id=ae.anchor_id
        WHERE ae.assertion_id=? ORDER BY e.evidence_start,e.anchor_id
        """,
        (row["assertion_id"],),
    ).fetchall()
    supports = [
        str(item[0])
        for item in connection.execute(
            "SELECT supporting_assertion_id FROM assertion_support WHERE assertion_id=? ORDER BY supporting_assertion_id",
            (row["assertion_id"],),
        )
    ]
    tier_label = {"A": "原文事实", "B": "跨章节归纳", "C": "模型文学解释"}[str(row["tier"])]
    title_object = str(row["object_text"] or "")
    if not title_object:
        value = json.loads(str(row["value_json"]))
        title_object = "" if value is None else str(value)
    return {
        "page_type": "assertion",
        "page_id": row["assertion_id"],
        "title": f"{row['subject_text']}｜{row['predicate']}｜{title_object}",
        "properties": {
            "知识等级": row["tier"],
            "等级名称": tier_label,
            "断言类型": row["assertion_kind"],
            "主体实体": row["subject_entity_id"],
            "客体实体": row["object_entity_id"],
            "谓词": row["predicate"],
            "极性": bool(row["polarity"]),
            "置信度": row["confidence"],
            "归因": row["attribution"],
            "状态": row["status"],
            "修订版本": row["revision"],
            "支持断言": supports,
        },
        "sections": {
            "结论": {
                "subject": row["subject_text"],
                "predicate": row["predicate"],
                "object": row["object_text"],
                "value": json.loads(str(row["value_json"])),
            },
            "限制与不确定性": json.loads(str(row["limitations_json"])),
            "原文证据": [_citation_block(item) for item in evidence],
            "分层声明": (
                "本页是原文明确支持的事实。"
                if row["tier"] == "A"
                else "本页是跨证据归纳，不等同于原文单句定论。"
                if row["tier"] == "B"
                else "本页是模型文学解释，不代表作者明确设定或唯一解读。"
            ),
        },
    }


def _entity_page(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    aliases = [
        str(item[0])
        for item in connection.execute(
            "SELECT alias FROM aliases WHERE entity_id=? ORDER BY is_canonical DESC,normalized_alias",
            (row["entity_id"],),
        )
    ]
    assertions = connection.execute(
        """
        SELECT * FROM assertions
        WHERE subject_entity_id=? OR object_entity_id=?
        ORDER BY CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END, assertion_id
        """,
        (row["entity_id"], row["entity_id"]),
    ).fetchall()
    tier_sections: dict[str, list[str]] = {"A": [], "B": [], "C": []}
    for item in assertions:
        tier_sections[str(item["tier"])].append(str(item["assertion_id"]))
    relationships = [
        {
            "relationship_id": item["relationship_id"],
            "tier": item["tier"],
            "relation_type": item["relation_type"],
            "subject_entity_id": item["subject_entity_id"],
            "object_entity_id": item["object_entity_id"],
            "start_chapter_id": item["start_chapter_id"],
            "end_chapter_id": item["end_chapter_id"],
            "status": item["status"],
        }
        for item in connection.execute(
            "SELECT * FROM relationships WHERE subject_entity_id=? OR object_entity_id=? ORDER BY start_source_order,relationship_id",
            (row["entity_id"], row["entity_id"]),
        )
    ]
    first_label = last_label = None
    if row["first_chapter_id"]:
        chapter = connection.execute("SELECT * FROM chapters WHERE chapter_id=?", (row["first_chapter_id"],)).fetchone()
        first_label = _chapter_label(chapter) if chapter else None
    if row["last_chapter_id"]:
        chapter = connection.execute("SELECT * FROM chapters WHERE chapter_id=?", (row["last_chapter_id"],)).fetchone()
        last_label = _chapter_label(chapter) if chapter else None
    return {
        "page_type": "entity",
        "page_id": row["entity_id"],
        "title": row["canonical_name"],
        "properties": {
            "实体类型": row["entity_type"],
            "别名": aliases,
            "首次可信出场": first_label,
            "最后可信出场": last_label,
            "审核状态": row["review_status"],
        },
        "relations": relationships,
        "sections": {
            "A级原文事实": tier_sections["A"],
            "B级跨章节归纳": tier_sections["B"],
            "C级模型文学解释": tier_sections["C"],
        },
    }


def _event_page(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    components: dict[str, list[str]] = {
        "cause": [],
        "process": [],
        "outcome": [],
        "consequence": [],
        "foreshadowing": [],
    }
    for item in connection.execute(
        "SELECT assertion_id,component FROM event_assertions WHERE event_id=? ORDER BY component,assertion_id",
        (row["event_id"],),
    ):
        components[str(item["component"])].append(str(item["assertion_id"]))
    participants = [
        {"entity_id": item["entity_id"], "role": item["role"]}
        for item in connection.execute(
            "SELECT entity_id,role FROM event_entities WHERE event_id=? ORDER BY role,entity_id",
            (row["event_id"],),
        )
    ]
    evidence = connection.execute(
        """
        SELECT e.* FROM event_evidence ee
        JOIN evidence_anchors e ON e.anchor_id=ee.anchor_id
        WHERE ee.event_id=? ORDER BY e.evidence_start,e.anchor_id
        """,
        (row["event_id"],),
    ).fetchall()
    start = connection.execute("SELECT * FROM chapters WHERE chapter_id=?", (row["start_chapter_id"],)).fetchone()
    end = connection.execute("SELECT * FROM chapters WHERE chapter_id=?", (row["end_chapter_id"],)).fetchone()
    return {
        "page_type": "event",
        "page_id": row["event_id"],
        "title": row["canonical_name"],
        "properties": {
            "事件类型": row["event_type"],
            "开始章节": _chapter_label(start) if start else row["start_chapter_id"],
            "结束章节": _chapter_label(end) if end else row["end_chapter_id"],
            "审核状态": row["review_status"],
            "参与实体": participants,
        },
        "sections": {
            "起因": components["cause"],
            "过程": components["process"],
            "结果": components["outcome"],
            "直接与长期后果": components["consequence"],
            "伏笔与回收": components["foreshadowing"],
            "原文证据": [_citation_block(item) for item in evidence],
        },
    }


def _chapter_page(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    assertions = [
        str(item[0])
        for item in connection.execute(
            """
            SELECT DISTINCT a.assertion_id
            FROM assertions a
            LEFT JOIN assertion_evidence ae ON ae.assertion_id=a.assertion_id
            LEFT JOIN evidence_anchors e ON e.anchor_id=ae.anchor_id
            WHERE e.chapter_id=? OR a.temporal_start_chapter_id=? OR a.temporal_end_chapter_id=?
            ORDER BY a.assertion_id
            """,
            (row["chapter_id"], row["chapter_id"], row["chapter_id"]),
        )
    ]
    entities = [
        str(item[0])
        for item in connection.execute(
            """
            SELECT DISTINCT em.entity_id
            FROM entity_mentions em JOIN evidence_anchors e ON e.anchor_id=em.anchor_id
            WHERE e.chapter_id=? ORDER BY em.entity_id
            """,
            (row["chapter_id"],),
        )
    ]
    return {
        "page_type": "chapter",
        "page_id": row["chapter_id"],
        "title": _chapter_label(row),
        "properties": {
            "卷序": row["volume_ordinal"],
            "章节序": row["chapter_ordinal"],
            "原始标题": row["original_heading"],
            "规范标题": row["normalized_heading"],
            "源顺序": row["source_order"],
            "字符起点": row["start_char"],
            "字符终点": row["end_char"],
            "正文起点": row["body_start_char"],
            "正文终点": row["body_end_char"],
            "结构审核": row["review_status"],
            "污染状态": row["contamination_status"],
            "内容SHA256": row["content_sha256"],
        },
        "relations": {
            "实体": entities,
            "分层断言": assertions,
        },
    }


def _install(temporary: Path, output: Path, replace: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace:
        raise LiteraryExportError(f"export directory already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise LiteraryExportError("existing export directory is unsafe")
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


def export_literary_notion_package(
    sidecar_directory: str | Path,
    output_directory: str | Path,
    *,
    replace_existing: bool = False,
) -> dict[str, object]:
    """Export deterministic pages, CSV ledgers, and a relation schema."""

    sidecar = Path(sidecar_directory)
    verification = verify_literary_engine(sidecar)
    if not verification.valid:
        raise LiteraryExportError(
            "literary sidecar failed verification: " + ",".join(verification.reason_codes)
        )
    output = Path(output_directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    database = sidecar / "literary.sqlite"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        chapter_rows = connection.execute("SELECT * FROM chapters ORDER BY source_order").fetchall()
        entity_rows = connection.execute("SELECT * FROM entities ORDER BY canonical_name,entity_id").fetchall()
        assertion_rows = connection.execute(
            "SELECT * FROM assertions ORDER BY CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,assertion_id"
        ).fetchall()
        event_rows = connection.execute("SELECT * FROM events ORDER BY start_source_order,event_id").fetchall()
        chapter_pages = [_chapter_page(connection, row) for row in chapter_rows]
        entity_pages = [_entity_page(connection, row) for row in entity_rows]
        assertion_pages = [_assertion_page(connection, row) for row in assertion_rows]
        event_pages = [_event_page(connection, row) for row in event_rows]

        database_schema = {
            "schema_version": NOTION_EXPORT_SCHEMA_VERSION,
            "databases": {
                "章节索引": {
                    "primary_key": "page_id",
                    "relations": ["实体", "分层断言"],
                    "immutable_fields": ["字符起点", "字符终点", "内容SHA256"],
                },
                "实体知识图谱": {
                    "primary_key": "page_id",
                    "sections": ["A级原文事实", "B级跨章节归纳", "C级模型文学解释"],
                },
                "分层断言": {
                    "primary_key": "page_id",
                    "required_properties": ["知识等级", "归因", "状态", "修订版本"],
                    "tier_rules": {
                        "A": "must contain exact source evidence",
                        "B": "must reference at least two A supports",
                        "C": "must be explicitly marked model interpretation",
                    },
                },
                "事件时间线": {
                    "primary_key": "page_id",
                    "sections": ["起因", "过程", "结果", "直接与长期后果", "伏笔与回收"],
                },
            },
            "presentation_rule": "C级内容不得放入A级事实属性或写成作者明确结论",
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_freeze": False,
        }
        payloads: dict[str, bytes] = {
            "notion-database-schema.json": _json_bytes(database_schema),
            "notion-chapter-pages.jsonl": _jsonl_bytes(chapter_pages),
            "notion-entity-pages.jsonl": _jsonl_bytes(entity_pages),
            "notion-assertion-pages.jsonl": _jsonl_bytes(assertion_pages),
            "notion-event-pages.jsonl": _jsonl_bytes(event_pages),
            "chapter-ledger.csv": _csv_bytes(
                [page["properties"] | {"page_id": page["page_id"], "title": page["title"]} for page in chapter_pages],
                (
                    "page_id", "title", "卷序", "章节序", "原始标题", "规范标题", "源顺序",
                    "字符起点", "字符终点", "正文起点", "正文终点", "结构审核", "污染状态", "内容SHA256",
                ),
            ),
            "entity-ledger.csv": _csv_bytes(
                [page["properties"] | {"page_id": page["page_id"], "title": page["title"]} for page in entity_pages],
                ("page_id", "title", "实体类型", "别名", "首次可信出场", "最后可信出场", "审核状态"),
            ),
            "assertion-ledger.csv": _csv_bytes(
                [
                    {
                        "page_id": page["page_id"],
                        "title": page["title"],
                        **page["properties"],
                        "结论": page["sections"]["结论"],
                        "限制与不确定性": page["sections"]["限制与不确定性"],
                        "证据数量": len(page["sections"]["原文证据"]),
                    }
                    for page in assertion_pages
                ],
                (
                    "page_id", "title", "知识等级", "等级名称", "断言类型", "主体实体", "客体实体",
                    "谓词", "极性", "置信度", "归因", "状态", "修订版本", "支持断言",
                    "结论", "限制与不确定性", "证据数量",
                ),
            ),
        }
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        manifest_entries = [
            {
                "path": name,
                "size_bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            }
            for name, data in sorted(payloads.items())
        ]
        report = {
            "schema_version": NOTION_EXPORT_SCHEMA_VERSION,
            "status": "completed",
            "literary_project_id": verification.project_id,
            "literary_logical_sha256": verification.logical_sha256,
            "literary_database_sha256": verification.database_sha256,
            "chapter_page_count": len(chapter_pages),
            "entity_page_count": len(entity_pages),
            "assertion_page_count": len(assertion_pages),
            "event_page_count": len(event_pages),
            "tier_a_count": sum(row["tier"] == "A" for row in assertion_rows),
            "tier_b_count": sum(row["tier"] == "B" for row in assertion_rows),
            "tier_c_count": sum(row["tier"] == "C" for row in assertion_rows),
            "fact_interpretation_separation": True,
            "files": manifest_entries,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "notion-export-report.json", _json_bytes(report))
        all_files = [
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(temporary.iterdir())
            if path.is_file()
        ]
        manifest = {
            "schema_version": "tkr-literary-notion-manifest-v1",
            "literary_project_id": verification.project_id,
            "literary_logical_sha256": verification.logical_sha256,
            "files": all_files,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "artifact-manifest.json", _json_bytes(manifest))
        _install(temporary, output, replace_existing)
        return report
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        connection.close()


__all__ = [
    "NOTION_EXPORT_SCHEMA_VERSION",
    "LiteraryExportError",
    "export_literary_notion_package",
]
