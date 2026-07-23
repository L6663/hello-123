"""Stage 6-R1 deterministic Notion hardening.

This narrow compatibility layer fixes the Stage 6 projection without changing
Stage 1-5 authority.  It makes assertion support independent of annotation
input order, removes local output paths from immutable reports, adds real
SQLite relation foreign keys, and verifies every persisted SQLite field against
the canonical JSONL projection.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping, Sequence

from . import notion_project as _project
from .notion_engine import (
    NOTION_ACTION_SCHEMA_VERSION,
    NOTION_PAGE_SCHEMA_VERSION,
    NOTION_RELATION_SCHEMA_VERSION,
    NOTION_REVIEW_SCHEMA_VERSION,
)

_APPLIED = False
_ORIGINAL_PROJECTION = _project._projection
_ORIGINAL_VERIFY = _project.verify_notion_project


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _topological_assertions(rows: Sequence[dict[str, object]]) -> tuple[dict[str, object], ...]:
    """Return a stable dependency-first order without inventing missing support.

    Unknown references and cycles remain available to the ordinary projection
    validator.  Only resolvable acyclic dependencies influence ordering.
    """

    by_id = {
        str(row.get("assertion_id")): row
        for row in rows
        if isinstance(row.get("assertion_id"), str) and row.get("assertion_id")
    }
    original_index = {str(row.get("assertion_id")): index for index, row in enumerate(rows)}
    permanent: set[str] = set()
    temporary: set[str] = set()
    ordered: list[dict[str, object]] = []

    def visit(identifier: str) -> None:
        if identifier in permanent:
            return
        if identifier in temporary:
            return
        temporary.add(identifier)
        row = by_id[identifier]
        supports = row.get("supporting_assertion_ids", [])
        if isinstance(supports, list):
            for support in sorted(str(value) for value in supports if str(value) in by_id):
                visit(support)
        temporary.remove(identifier)
        permanent.add(identifier)
        ordered.append(row)

    for identifier in sorted(by_id, key=lambda value: (original_index[value], value)):
        visit(identifier)

    represented = {id(row) for row in ordered}
    ordered.extend(row for row in rows if id(row) not in represented)
    return tuple(ordered)


def _projection(inputs, ledger_entries):
    normalized = replace(inputs, assertions=_topological_assertions(inputs.assertions))
    return _ORIGINAL_PROJECTION(normalized, ledger_entries)


def _report_to_dict(self) -> dict[str, object]:
    payload = asdict(self)
    # Local filesystem paths are execution metadata, not immutable project data.
    payload["output_directory"] = "."
    payload["literary_project_ids"] = list(self.literary_project_ids)
    payload["evidence_project_logical_sha256s"] = list(
        self.evidence_project_logical_sha256s
    )
    return payload


def _create_database(path: Path, projection, metadata: Mapping[str, str]) -> None:
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
            CREATE TABLE pages(
                page_key TEXT PRIMARY KEY,
                database_key TEXT NOT NULL,
                record_type TEXT NOT NULL,
                record_id TEXT NOT NULL,
                title TEXT NOT NULL,
                epistemic_layer TEXT NOT NULL,
                publication_status TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                properties_json TEXT NOT NULL,
                sections_json TEXT NOT NULL,
                source_lineage_json TEXT NOT NULL,
                UNIQUE(database_key,record_type,record_id)
            );
            CREATE TABLE relations(
                relation_id TEXT PRIMARY KEY,
                source_page_key TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                target_page_key TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY(source_page_key) REFERENCES pages(page_key),
                FOREIGN KEY(target_page_key) REFERENCES pages(page_key)
            );
            CREATE INDEX relation_source_type
                ON relations(source_page_key,relation_type,target_page_key);
            CREATE TABLE reviews(
                review_id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                recommended_action TEXT NOT NULL,
                affected_pages_json TEXT NOT NULL,
                affected_relations_json TEXT NOT NULL
            );
            CREATE TABLE actions(
                action_id TEXT PRIMARY KEY,
                target_type TEXT NOT NULL,
                target_key TEXT NOT NULL,
                action TEXT NOT NULL,
                notion_page_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                relation_sha256 TEXT NOT NULL,
                dependencies_json TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL
            );
            """
        )
        connection.executemany("INSERT INTO metadata VALUES(?,?)", sorted(metadata.items()))
        connection.executemany(
            "INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    item.page_key,
                    item.database_key,
                    item.record_type,
                    item.record_id,
                    item.title,
                    item.epistemic_layer,
                    item.publication_status,
                    item.content_sha256,
                    _canonical_json(item.properties),
                    _canonical_json(item.sections),
                    _canonical_json(list(item.source_lineage)),
                )
                for item in projection.pages
            ],
        )
        connection.executemany(
            "INSERT INTO relations VALUES(?,?,?,?,?)",
            [
                (
                    item.relation_id,
                    item.source_page_key,
                    item.relation_type,
                    item.target_page_key,
                    item.status,
                )
                for item in projection.relations
            ],
        )
        connection.executemany(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
            [
                (
                    item.review_id,
                    item.rule_id,
                    item.severity,
                    item.message,
                    item.recommended_action,
                    _canonical_json(list(item.affected_page_keys)),
                    _canonical_json(list(item.affected_relation_ids)),
                )
                for item in projection.reviews
            ],
        )
        connection.executemany(
            "INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (
                    item.action_id,
                    item.target_type,
                    item.target_key,
                    item.action,
                    item.notion_page_id,
                    item.content_sha256,
                    item.relation_sha256,
                    _canonical_json(list(item.dependency_page_keys)),
                    _canonical_json(list(item.reason_codes)),
                )
                for item in projection.actions
            ],
        )
        connection.commit()
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise _project.NotionProjectError("Notion SQLite foreign-key check failed")
        connection.execute("VACUUM")
    finally:
        connection.close()


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _sqlite_payloads(path: Path) -> dict[str, list[dict[str, object]]]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        pages = [
            {
                "schema_version": NOTION_PAGE_SCHEMA_VERSION,
                "page_key": row[0],
                "database_key": row[1],
                "record_type": row[2],
                "record_id": row[3],
                "title": row[4],
                "properties": json.loads(row[8]),
                "sections": json.loads(row[9]),
                "epistemic_layer": row[5],
                "publication_status": row[6],
                "source_lineage": json.loads(row[10]),
                "content_sha256": row[7],
            }
            for row in connection.execute(
                "SELECT page_key,database_key,record_type,record_id,title,"
                "epistemic_layer,publication_status,content_sha256,properties_json,"
                "sections_json,source_lineage_json FROM pages ORDER BY database_key,page_key"
            )
        ]
        relations = [
            {
                "schema_version": NOTION_RELATION_SCHEMA_VERSION,
                "relation_id": row[0],
                "source_page_key": row[1],
                "relation_type": row[2],
                "target_page_key": row[3],
                "status": row[4],
            }
            for row in connection.execute(
                "SELECT relation_id,source_page_key,relation_type,target_page_key,status "
                "FROM relations ORDER BY source_page_key,relation_type,target_page_key,relation_id"
            )
        ]
        reviews = [
            {
                "schema_version": NOTION_REVIEW_SCHEMA_VERSION,
                "review_id": row[0],
                "rule_id": row[1],
                "severity": row[2],
                "message": row[3],
                "affected_page_keys": json.loads(row[5]),
                "affected_relation_ids": json.loads(row[6]),
                "recommended_action": row[4],
            }
            for row in connection.execute(
                "SELECT review_id,rule_id,severity,message,recommended_action,"
                "affected_pages_json,affected_relations_json FROM reviews ORDER BY severity,rule_id,review_id"
            )
        ]
        actions = [
            {
                "schema_version": NOTION_ACTION_SCHEMA_VERSION,
                "action_id": row[0],
                "target_type": row[1],
                "target_key": row[2],
                "action": row[3],
                "notion_page_id": row[4],
                "content_sha256": row[5],
                "relation_sha256": row[6],
                "dependency_page_keys": json.loads(row[7]),
                "reason_codes": json.loads(row[8]),
            }
            for row in connection.execute(
                "SELECT action_id,target_type,target_key,action,notion_page_id,"
                "content_sha256,relation_sha256,dependencies_json,reason_codes_json "
                "FROM actions ORDER BY target_type,target_key,action_id"
            )
        ]
        return {
            "notion-pages.jsonl": pages,
            "notion-relations.jsonl": relations,
            "notion-review-items.jsonl": reviews,
            "notion-sync-plan.jsonl": actions,
        }
    finally:
        connection.close()


def _verify(*args, **kwargs):
    result = _ORIGINAL_VERIFY(*args, **kwargs)
    root = Path(args[10] if len(args) > 10 else kwargs["notion_project_directory"])
    reasons = list(result.reason_codes)
    try:
        database = root / "notion.sqlite"
        if database.is_file() and not database.is_symlink():
            foreign_keys = sqlite3.connect(database).execute(
                "PRAGMA foreign_key_list(relations)"
            ).fetchall()
            referenced = sorted(row[2] for row in foreign_keys)
            if referenced != ["pages", "pages"]:
                reasons.append("NOTION_DATABASE_RELATION_FOREIGN_KEYS_MISSING")
            persisted = _sqlite_payloads(database)
            for filename, database_rows in persisted.items():
                jsonl = root / filename
                if jsonl.is_file() and _canonical_json(_load_jsonl(jsonl)) != _canonical_json(database_rows):
                    reasons.append(
                        "NOTION_DATABASE_"
                        + filename.removeprefix("notion-").removesuffix(".jsonl").replace("-", "_").upper()
                        + "_ROW_MISMATCH"
                    )
    except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, KeyError, IndexError):
        reasons.append("NOTION_DATABASE_CROSS_STORE_VERIFICATION_EXCEPTION")
    unique = tuple(dict.fromkeys(reasons))
    if unique == result.reason_codes:
        return result
    return replace(result, status="invalid", valid=False, reason_codes=unique)


def apply_stage6_notion_r1() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _project._projection = _projection
    _project._create_database = _create_database
    _project.NotionProjectBuildResult.to_dict = _report_to_dict
    _project.verify_notion_project = _verify
    _APPLIED = True


__all__ = ["apply_stage6_notion_r1"]
