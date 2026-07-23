"""Build and verify deterministic Stage 6 Notion Knowledge System packages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from typing import Iterable, Mapping, Sequence

from .hashing import sha256_file
from .notion_engine import (
    DATABASE_KEYS,
    NOTION_ENGINE_VERSION,
    NOTION_LEDGER_SCHEMA_VERSION,
    NotionPage,
    NotionProjection,
    NotionRelation,
    NotionReviewItem,
    NotionSyncAction,
    SyncLedgerEntry,
    build_notion_projection,
    make_notion_page,
    make_notion_relation,
    make_review_item,
    notion_page_key,
)
from .reasoning_project import verify_reasoning_project

NOTION_PROJECT_SCHEMA_VERSION = "tkr-notion-project-v1"
NOTION_PROJECT_REPORT_SCHEMA_VERSION = "tkr-notion-project-report-v1"
NOTION_PROJECT_MANIFEST_SCHEMA_VERSION = "tkr-notion-project-manifest-v1"
NOTION_PROJECT_VERIFICATION_SCHEMA_VERSION = "tkr-notion-project-verification-v1"
NOTION_WORKSPACE_SCHEMA_VERSION = "tkr-notion-workspace-schema-v1"
NOTION_SQLITE_SCHEMA_VERSION = "tkr-notion-sqlite-v1"

_DATA_FILES = (
    "notion-pages.jsonl",
    "notion-relations.jsonl",
    "notion-review-items.jsonl",
    "notion-sync-plan.jsonl",
)
_ALLOWED_FILES = set(_DATA_FILES) | {
    "notion-workspace-schema.json",
    "notion.sqlite",
    "notion-project-report.json",
    "artifact-manifest.json",
}
EvidenceBinding = tuple[Path, Path, Path]


class NotionProjectError(ValueError):
    """Raised when a Notion Project is unsafe or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class NotionProjectBuildResult:
    schema_version: str
    status: str
    notion_engine_version: str
    output_directory: str
    page_count: int
    relation_count: int
    review_count: int
    blocking_review_count: int
    database_counts: dict[str, int]
    action_counts: dict[str, int]
    projection_valid: bool
    chapter_project_logical_sha256: str
    literary_project_ids: tuple[str, ...]
    evidence_project_logical_sha256s: tuple[str, ...]
    event_project_logical_sha256: str
    character_project_logical_sha256: str
    reasoning_project_logical_sha256: str
    ledger_sha256: str
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_PROJECT_REPORT_SCHEMA_VERSION:
            raise NotionProjectError("Notion Project report schema mismatch")
        if self.status not in {"completed", "review_required"}:
            raise NotionProjectError("Notion Project status is invalid")
        if self.projection_valid != (self.status == "completed"):
            raise NotionProjectError("Notion Project status and validity disagree")
        for name in ("page_count", "relation_count", "review_count", "blocking_review_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise NotionProjectError(f"{name} must be a non-negative integer")
        if any((self.project_acceptance_performed, self.may_accept_project, self.may_release, self.may_freeze)):
            raise NotionProjectError("Notion Project cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["literary_project_ids"] = list(self.literary_project_ids)
        payload["evidence_project_logical_sha256s"] = list(
            self.evidence_project_logical_sha256s
        )
        return payload


@dataclass(frozen=True, slots=True)
class NotionProjectVerification:
    schema_version: str
    status: str
    valid: bool
    projection_valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    logical_sha256: str
    database_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_PROJECT_VERIFICATION_SCHEMA_VERSION:
            raise NotionProjectError("Notion verification schema mismatch")
        if self.valid != (not self.reason_codes):
            raise NotionProjectError("Notion verification validity mismatch")
        if any((self.project_acceptance_performed, self.may_accept_project, self.may_release, self.may_freeze)):
            raise NotionProjectError("Notion verification cannot grant authority")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True, slots=True)
class _ProjectionInputs:
    chapter_logical: str
    literary_ids: tuple[str, ...]
    literary_logicals: tuple[str, ...]
    evidence_logicals: tuple[str, ...]
    event_logical: str
    character_logical: str
    reasoning_logical: str
    source_reports: tuple[dict[str, object], ...]
    chapters: tuple[dict[str, object], ...]
    chapter_findings: tuple[dict[str, object], ...]
    literary_chapters: tuple[dict[str, object], ...]
    entities: tuple[dict[str, object], ...]
    assertions: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]
    events: tuple[dict[str, object], ...]
    event_components: tuple[dict[str, object], ...]
    event_edges: tuple[dict[str, object], ...]
    event_findings: tuple[dict[str, object], ...]
    characters: tuple[dict[str, object], ...]
    character_attributes: tuple[dict[str, object], ...]
    character_states: tuple[dict[str, object], ...]
    character_relationships: tuple[dict[str, object], ...]
    character_event_links: tuple[dict[str, object], ...]
    character_findings: tuple[dict[str, object], ...]
    reasoning_nodes: tuple[dict[str, object], ...]
    reasoning_edges: tuple[dict[str, object], ...]
    reasoning_findings: tuple[dict[str, object], ...]

    @property
    def lineage(self) -> tuple[str, ...]:
        return tuple(sorted({
            self.chapter_logical,
            *self.literary_logicals,
            *self.evidence_logicals,
            self.event_logical,
            self.character_logical,
            self.reasoning_logical,
        }))


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
        raise NotionProjectError(f"{label} must be a safe directory")


def _safe_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise NotionProjectError(f"{label} must be a safe regular file")


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
        raise NotionProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise NotionProjectError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, object]]:
    _safe_file(path, label)
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise NotionProjectError(f"blank {label} record at line {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise NotionProjectError(
                    f"invalid {label} JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise NotionProjectError(
                    f"{label} record at line {line_number} must be an object"
                )
            rows.append(value)
    return rows


def _merge_rows(
    target: dict[str, dict[str, object]],
    rows: Iterable[dict[str, object]],
    key: str,
    label: str,
) -> None:
    for row in rows:
        identifier = row.get(key)
        if not isinstance(identifier, str) or not identifier:
            raise NotionProjectError(f"{label} omits {key}")
        existing = target.get(identifier)
        if existing is not None and existing != row:
            raise NotionProjectError(f"conflicting {label} ID: {identifier}")
        target[identifier] = row


def _report_logical(path: Path, filename: str, label: str) -> tuple[dict[str, object], str]:
    report = _load_object(path / filename, label)
    logical = report.get("logical_sha256")
    if not isinstance(logical, str) or len(logical) != 64:
        raise NotionProjectError(f"{label} omits logical_sha256")
    return report, logical


def _inputs(
    chapter_project: Path,
    source_projects: Sequence[Path],
    literary_projects: Sequence[Path],
    evidence_bindings: Sequence[EvidenceBinding],
    event_project: Path,
    event_annotations: Path,
    character_project: Path,
    character_annotations: Path,
    reasoning_project: Path,
    reasoning_annotations: Path,
) -> _ProjectionInputs:
    verification = verify_reasoning_project(
        chapter_project,
        source_projects,
        literary_projects,
        evidence_bindings,
        event_project,
        event_annotations,
        character_project,
        character_annotations,
        reasoning_annotations,
        reasoning_project,
    )
    if not verification.valid:
        raise NotionProjectError(
            "Reasoning Project failed verification: " + ",".join(verification.reason_codes)
        )
    reasoning_report, reasoning_logical = _report_logical(
        reasoning_project, "reasoning-project-report.json", "Reasoning Project report"
    )
    if not bool(reasoning_report.get("graph_valid")):
        raise NotionProjectError("review-required Reasoning Project cannot publish accepted knowledge")
    chapter_report, chapter_logical = _report_logical(
        chapter_project, "chapter-project-report.json", "Chapter Project report"
    )
    event_report, event_logical = _report_logical(
        event_project, "event-project-report.json", "Event Project report"
    )
    character_report, character_logical = _report_logical(
        character_project, "character-project-report.json", "Character Project report"
    )
    if not bool(event_report.get("graph_valid")) or not bool(character_report.get("graph_valid")):
        raise NotionProjectError("review-required Event or Character Project cannot publish accepted knowledge")

    source_reports = tuple(
        _load_object(path / "project-report.json", f"source project report {index}")
        for index, path in enumerate(source_projects)
    )
    literary_ids: list[str] = []
    literary_logicals: list[str] = []
    literary_chapters: list[dict[str, object]] = []
    entities: dict[str, dict[str, object]] = {}
    assertions: dict[str, dict[str, object]] = {}
    evidence: dict[str, dict[str, object]] = {}
    for index, path in enumerate(literary_projects):
        report, logical = _report_logical(path, "literary-report.json", f"literary report {index}")
        project_id = report.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise NotionProjectError("literary report omits project_id")
        literary_ids.append(project_id)
        literary_logicals.append(logical)
        literary_chapters.extend(_load_jsonl(path / "chapters.jsonl", "literary chapters"))
        _merge_rows(entities, _load_jsonl(path / "entities.jsonl", "literary entities"), "entity_id", "entity")
        _merge_rows(assertions, _load_jsonl(path / "assertions.jsonl", "literary assertions"), "assertion_id", "assertion")
        _merge_rows(evidence, _load_jsonl(path / "evidence-anchors.jsonl", "literary evidence"), "anchor_id", "Evidence Anchor")
    if len(literary_ids) != len(set(literary_ids)):
        raise NotionProjectError("literary project IDs must be unique")

    evidence_logicals: list[str] = []
    for index, (_, _, path) in enumerate(evidence_bindings):
        _, logical = _report_logical(
            path, "evidence-project-report.json", f"Evidence Project report {index}"
        )
        evidence_logicals.append(logical)
        _merge_rows(
            evidence,
            _load_jsonl(path / "claim-evidence-anchors.jsonl", "Claim Evidence anchors"),
            "anchor_id",
            "Evidence Anchor",
        )

    return _ProjectionInputs(
        chapter_logical,
        tuple(literary_ids),
        tuple(literary_logicals),
        tuple(evidence_logicals),
        event_logical,
        character_logical,
        reasoning_logical,
        source_reports,
        tuple(_load_jsonl(chapter_project / "chapters.jsonl", "canonical chapters")),
        tuple(_load_jsonl(chapter_project / "chapter-findings.jsonl", "chapter findings")),
        tuple(literary_chapters),
        tuple(entities.values()),
        tuple(assertions.values()),
        tuple(evidence.values()),
        tuple(_load_jsonl(event_project / "events.jsonl", "events")),
        tuple(_load_jsonl(event_project / "event-components.jsonl", "event components")),
        tuple(_load_jsonl(event_project / "event-causal-edges.jsonl", "event edges")),
        tuple(_load_jsonl(event_project / "event-findings.jsonl", "event findings")),
        tuple(_load_jsonl(character_project / "characters.jsonl", "characters")),
        tuple(_load_jsonl(character_project / "character-attributes.jsonl", "character attributes")),
        tuple(_load_jsonl(character_project / "character-states.jsonl", "character states")),
        tuple(_load_jsonl(character_project / "character-relationships.jsonl", "character relationships")),
        tuple(_load_jsonl(character_project / "character-event-links.jsonl", "character event links")),
        tuple(_load_jsonl(character_project / "character-findings.jsonl", "character findings")),
        tuple(_load_jsonl(reasoning_project / "reasoning-nodes.jsonl", "reasoning nodes")),
        tuple(_load_jsonl(reasoning_project / "reasoning-edges.jsonl", "reasoning edges")),
        tuple(_load_jsonl(reasoning_project / "reasoning-findings.jsonl", "reasoning findings")),
    )


def _ledger(path: Path | None) -> tuple[tuple[SyncLedgerEntry, ...], str]:
    if path is None:
        return (), ""
    _safe_file(path, "Notion sync ledger")
    digest = sha256_file(path)
    payload = _load_object(path, "Notion sync ledger")
    if payload.get("schema_version") != NOTION_LEDGER_SCHEMA_VERSION:
        raise NotionProjectError("Notion sync ledger schema mismatch")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise NotionProjectError("Notion sync ledger entries must be an array")
    result: list[SyncLedgerEntry] = []
    for row in entries:
        if not isinstance(row, dict):
            raise NotionProjectError("Notion sync ledger entry must be an object")
        try:
            result.append(SyncLedgerEntry(**row))
        except (TypeError, ValueError) as exc:
            raise NotionProjectError(f"invalid Notion sync ledger entry: {exc}") from exc
    return tuple(result), digest


def _chapter_title(row: Mapping[str, object]) -> str:
    parts: list[str] = []
    if isinstance(row.get("volume_ordinal"), int):
        parts.append(f"卷{row['volume_ordinal']}")
    if isinstance(row.get("chapter_ordinal"), int):
        parts.append(f"第{row['chapter_ordinal']}章")
    heading = str(row.get("original_heading") or row.get("normalized_heading") or row.get("title") or "").strip()
    base = " ".join(parts)
    return f"{base}｜{heading}" if base and heading and heading not in base else base or heading or str(row.get("chapter_id"))


def _assertion_title(row: Mapping[str, object]) -> str:
    subject = str(row.get("subject_text") or row.get("subject_entity_id") or "断言")
    predicate = str(row.get("predicate") or row.get("assertion_kind") or "")
    target = str(row.get("object_text") or row.get("object_entity_id") or "")
    return "｜".join(value for value in (subject, predicate, target) if value)


def _epistemic_disclosure(layer: str) -> str:
    return {
        "A": "本页是原文明确支持的事实，并链接 exact Evidence Anchors。",
        "B": "本页是跨证据归纳，不等同于原文单句定论。",
        "C": "本页是模型文学解释，不代表作者明确设定或唯一解读。",
        "H": "本页是反事实推演，不属于原作剧情。",
    }[layer]


def _finding_review(row: Mapping[str, object], origin: str) -> NotionReviewItem:
    rule = str(row.get("rule_id") or row.get("finding_type") or "UPSTREAM_REVIEW_FINDING")
    severity = str(row.get("severity") or "medium")
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "medium"
    identifier = str(row.get("finding_id") or row.get("review_id") or "")
    message = str(row.get("message") or row.get("recommended_action") or rule)
    return make_review_item(
        f"{origin}:{rule}",
        severity,
        message,
        recommended_action=str(row.get("recommended_action") or "review_upstream_finding"),
        affected_page_keys=(),
        affected_relation_ids=(),
    )


def _workspace_schema() -> dict[str, object]:
    databases = {
        "sources": "来源与工程身份",
        "chapters": "章节物理顺序、候选规范顺序与结构状态",
        "evidence": "被发布知识记录引用的精确 Evidence Anchors",
        "facts_a": "A级原文事实",
        "synthesis_b": "B级跨证据归纳",
        "interpretations_c": "C级模型文学解释",
        "counterfactuals_h": "H级非原作反事实推演",
        "events": "重大事件与因果结构",
        "characters": "核心、重要与最小占位人物",
        "review_queue": "冲突、污染、同步与审查项",
    }
    return {
        "schema_version": NOTION_WORKSPACE_SCHEMA_VERSION,
        "notion_engine_version": NOTION_ENGINE_VERSION,
        "databases": [
            {
                "database_key": key,
                "title": title,
                "stable_identity_property": "page_key",
                "content_hash_property": "content_sha256",
                "relation_hash_property": "relation_sha256",
                "automatic_deletion_allowed": False,
            }
            for key, title in databases.items()
        ],
        "epistemic_database_map": {
            "A": "facts_a",
            "B": "synthesis_b",
            "C": "interpretations_c",
            "H": "counterfactuals_h",
        },
        "sync_phases": ["upsert_pages", "resolve_page_ids", "apply_relations"],
        "archive_requires_explicit_approval": True,
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_release": False,
        "may_freeze": False,
    }


def _projection(inputs: _ProjectionInputs, ledger_entries: Sequence[SyncLedgerEntry]) -> NotionProjection:
    lineage = inputs.lineage
    pages: list[NotionPage] = []
    relations: list[NotionRelation] = []
    reviews: list[NotionReviewItem] = []
    record_page: dict[str, str] = {}

    source_page_by_project: dict[str, str] = {}
    for row in inputs.source_reports:
        project_id = str(row.get("project_id") or row.get("source_id"))
        title = str(row.get("source_filename") or row.get("source_id") or project_id)
        page = make_notion_page(
            "sources", "source_project", project_id, title,
            properties={
                "project_id": project_id,
                "source_id": row.get("source_id"),
                "source_filename": row.get("source_filename"),
                "raw_source_sha256": row.get("raw_source_sha256"),
                "normalized_source_sha256": row.get("normalized_source_sha256"),
                "selected_encoding": row.get("selected_encoding"),
            },
            sections={"工程报告": row},
            source_lineage=lineage,
        )
        pages.append(page)
        record_page[project_id] = page.page_key
        source_page_by_project[project_id] = page.page_key

    chapter_page_by_id: dict[str, str] = {}
    chapter_page_by_unit: dict[tuple[str, str], str] = {}
    for row in inputs.chapters:
        chapter_id = str(row["chapter_id"])
        page = make_notion_page(
            "chapters", "chapter", chapter_id, _chapter_title(row),
            properties={
                "project_id": row.get("project_id"),
                "source_id": row.get("source_id"),
                "source_filename": row.get("source_filename"),
                "volume_ordinal": row.get("volume_ordinal"),
                "chapter_ordinal": row.get("chapter_ordinal"),
                "physical_order": row.get("global_physical_order"),
                "canonical_key": row.get("canonical_key"),
                "review_status": row.get("review_status"),
                "contamination_status": row.get("contamination_status"),
                "content_sha256": row.get("content_sha256"),
            },
            sections={"章节记录": row},
            publication_status=(
                "published"
                if row.get("review_status") not in {"review", "review_only"}
                and row.get("contamination_status") == "clean"
                else "review"
            ),
            source_lineage=lineage,
        )
        pages.append(page)
        record_page[chapter_id] = page.page_key
        chapter_page_by_id[chapter_id] = page.page_key
        source_id = row.get("source_id")
        unit_id = row.get("unit_id")
        if isinstance(source_id, str) and isinstance(unit_id, str):
            chapter_page_by_unit[(source_id, unit_id)] = page.page_key
        source_page = source_page_by_project.get(str(row.get("project_id")))
        if source_page:
            relations.append(make_notion_relation(page.page_key, "source", source_page))

    literary_chapter_to_canonical: dict[str, str] = {}
    for row in inputs.literary_chapters:
        chapter_id = row.get("chapter_id")
        source_id = row.get("source_id")
        unit_id = row.get("unit_id")
        if isinstance(chapter_id, str) and isinstance(source_id, str) and isinstance(unit_id, str):
            target = chapter_page_by_unit.get((source_id, unit_id))
            if target:
                literary_chapter_to_canonical[chapter_id] = target

    entity_name: dict[str, str] = {}
    for row in inputs.entities:
        entity_id = row.get("entity_id")
        name = row.get("canonical_name")
        if isinstance(entity_id, str) and isinstance(name, str):
            entity_name[entity_id] = name

    character_page_by_id: dict[str, str] = {}
    character_page_by_name: dict[str, str] = {}
    attributes_by_character: dict[str, list[dict[str, object]]] = {}
    states_by_character: dict[str, list[dict[str, object]]] = {}
    relationships_by_character: dict[str, list[dict[str, object]]] = {}
    links_by_character: dict[str, list[dict[str, object]]] = {}
    for row in inputs.character_attributes:
        attributes_by_character.setdefault(str(row.get("character_id")), []).append(row)
    for row in inputs.character_states:
        states_by_character.setdefault(str(row.get("character_id")), []).append(row)
    for row in inputs.character_relationships:
        relationships_by_character.setdefault(str(row.get("subject_character_id")), []).append(row)
        relationships_by_character.setdefault(str(row.get("object_character_id")), []).append(row)
    for row in inputs.character_event_links:
        links_by_character.setdefault(str(row.get("character_id")), []).append(row)
    for row in inputs.characters:
        character_id = str(row["character_id"])
        scope = str(row.get("scope") or "placeholder")
        page = make_notion_page(
            "characters", "character", character_id, str(row.get("canonical_name") or character_id),
            properties={
                "scope": scope,
                "aliases": row.get("aliases", []),
                "selection_reasons": row.get("selection_reasons", []),
                "review_status": row.get("review_status"),
                "first_position": row.get("first_position"),
                "last_position": row.get("last_position"),
            },
            sections={
                "人物记录": row,
                "属性": sorted(attributes_by_character.get(character_id, []), key=lambda item: str(item.get("attribute_id"))),
                "状态时间线": sorted(states_by_character.get(character_id, []), key=lambda item: (int(item.get("start_position", 0)), str(item.get("state_id")))),
                "重大关系": sorted(relationships_by_character.get(character_id, []), key=lambda item: str(item.get("relationship_id"))),
                "重大事件": sorted(links_by_character.get(character_id, []), key=lambda item: str(item.get("link_id"))),
                "范围声明": (
                    "占位人物仅保留最小身份、章节与必要事件记录。"
                    if scope == "placeholder"
                    else "本人物因对主线、核心人物、重大事件、主要势力或世界状态具有实质影响而建模。"
                ),
            },
            publication_status="minimal" if scope == "placeholder" else "published",
            source_lineage=lineage,
        )
        pages.append(page)
        record_page[character_id] = page.page_key
        character_page_by_id[character_id] = page.page_key
        names = [str(row.get("canonical_name") or ""), *[str(value) for value in row.get("aliases", []) if isinstance(value, str)]]
        for name in names:
            if name:
                folded = name.casefold()
                previous = character_page_by_name.get(folded)
                if previous is not None and previous != page.page_key:
                    reviews.append(make_review_item(
                        "CHARACTER_NAME_COLLISION_IN_NOTION_PROJECTION", "high",
                        f"character alias maps to multiple pages: {name}",
                        affected_page_keys=(previous, page.page_key),
                        recommended_action="review_character_identity_before_sync",
                    ))
                else:
                    character_page_by_name[folded] = page.page_key
        for chapter_field, relation_type in (("first_chapter_id", "first_chapter"), ("last_chapter_id", "last_chapter")):
            target = chapter_page_by_id.get(str(row.get(chapter_field)))
            if target:
                relations.append(make_notion_relation(page.page_key, relation_type, target))

    event_components: dict[str, list[dict[str, object]]] = {}
    event_edges: dict[str, list[dict[str, object]]] = {}
    for row in inputs.event_components:
        event_components.setdefault(str(row.get("event_id")), []).append(row)
    for row in inputs.event_edges:
        event_edges.setdefault(str(row.get("source_event_id")), []).append(row)
        event_edges.setdefault(str(row.get("target_event_id")), []).append(row)
    event_page_by_id: dict[str, str] = {}
    for row in inputs.events:
        event_id = str(row["event_id"])
        page = make_notion_page(
            "events", "event", event_id, str(row.get("canonical_name") or event_id),
            properties={
                "event_type": row.get("event_type"),
                "significance": row.get("significance"),
                "start_position": row.get("start_position"),
                "end_position": row.get("end_position"),
                "review_status": row.get("review_status"),
            },
            sections={
                "事件记录": row,
                "起因过程结果与后果": sorted(event_components.get(event_id, []), key=lambda item: (str(item.get("component_type")), str(item.get("component_id")))),
                "因果边": sorted(event_edges.get(event_id, []), key=lambda item: str(item.get("edge_id"))),
            },
            publication_status="published" if row.get("review_status") == "active" else "review",
            source_lineage=lineage,
        )
        pages.append(page)
        record_page[event_id] = page.page_key
        event_page_by_id[event_id] = page.page_key
        for chapter_field, relation_type in (("start_chapter_id", "start_chapter"), ("end_chapter_id", "end_chapter")):
            target = chapter_page_by_id.get(str(row.get(chapter_field)))
            if target:
                relations.append(make_notion_relation(page.page_key, relation_type, target))

    for row in inputs.character_event_links:
        character = character_page_by_id.get(str(row.get("character_id")))
        event = event_page_by_id.get(str(row.get("event_id")))
        if character and event:
            relations.append(make_notion_relation(character, "major_event", event))
            relations.append(make_notion_relation(event, "character", character))

    referenced_evidence: set[str] = set()
    for collection in (
        inputs.assertions,
        inputs.events,
        inputs.event_components,
        inputs.event_edges,
        inputs.characters,
        inputs.character_attributes,
        inputs.character_states,
        inputs.character_relationships,
        inputs.character_event_links,
        inputs.reasoning_nodes,
    ):
        for row in collection:
            values = row.get("evidence_anchor_ids", [])
            if isinstance(values, list):
                referenced_evidence.update(value for value in values if isinstance(value, str) and value)

    evidence_by_id = {str(row.get("anchor_id")): row for row in inputs.evidence}
    evidence_page_by_id: dict[str, str] = {}
    for anchor_id in sorted(referenced_evidence):
        row = evidence_by_id.get(anchor_id)
        if row is None:
            reviews.append(make_review_item(
                "PUBLISHED_RECORD_REFERENCES_MISSING_EVIDENCE", "critical",
                f"referenced Evidence Anchor is missing: {anchor_id}",
                recommended_action="restore_or_remove_invalid_evidence_reference",
            ))
            continue
        chapter_target = chapter_page_by_id.get(str(row.get("chapter_id")))
        if chapter_target is None:
            chapter_target = literary_chapter_to_canonical.get(str(row.get("chapter_id")))
        if chapter_target is None:
            source_id = row.get("source_id")
            unit_id = row.get("unit_id")
            if isinstance(source_id, str) and isinstance(unit_id, str):
                chapter_target = chapter_page_by_unit.get((source_id, unit_id))
        quote = str(row.get("evidence_text") or row.get("quote") or "")
        title = f"证据｜{anchor_id[:16]}｜{quote[:32]}"
        page = make_notion_page(
            "evidence", "evidence_anchor", anchor_id, title,
            properties={
                "source_id": row.get("source_id"),
                "unit_id": row.get("unit_id"),
                "chapter_id": row.get("chapter_id"),
                "evidence_start": row.get("evidence_start"),
                "evidence_end": row.get("evidence_end"),
                "evidence_sha256": row.get("evidence_sha256"),
                "source_status": row.get("source_status"),
            },
            sections={"原文证据": row},
            publication_status="published" if row.get("source_status") in {None, "clean"} else "review",
            source_lineage=lineage,
        )
        pages.append(page)
        record_page[anchor_id] = page.page_key
        evidence_page_by_id[anchor_id] = page.page_key
        if chapter_target:
            relations.append(make_notion_relation(page.page_key, "chapter", chapter_target))
        else:
            reviews.append(make_review_item(
                "EVIDENCE_CHAPTER_RELATION_UNRESOLVED", "high",
                f"Evidence Anchor cannot resolve a canonical chapter: {anchor_id}",
                affected_page_keys=(page.page_key,),
                recommended_action="map_literary_chapter_to_canonical_chapter",
            ))

    assertion_page_by_id: dict[str, str] = {}
    for row in inputs.assertions:
        assertion_id = str(row["assertion_id"])
        layer = str(row.get("tier") or "")
        if layer not in {"A", "B", "C"}:
            reviews.append(make_review_item(
                "ASSERTION_LAYER_UNSUPPORTED_FOR_NOTION", "high",
                f"assertion has unsupported layer: {assertion_id}",
                recommended_action="review_assertion_tier",
            ))
            continue
        database = {"A": "facts_a", "B": "synthesis_b", "C": "interpretations_c"}[layer]
        page = make_notion_page(
            database, "literary_assertion", assertion_id, _assertion_title(row),
            properties={
                "layer": layer,
                "assertion_kind": row.get("assertion_kind"),
                "predicate": row.get("predicate"),
                "polarity": row.get("polarity"),
                "confidence": row.get("confidence"),
                "attribution": row.get("attribution"),
                "status": row.get("status"),
                "revision": row.get("revision"),
            },
            sections={
                "知识记录": row,
                "分层声明": _epistemic_disclosure(layer),
                "限制与不确定性": row.get("limitations", []),
            },
            epistemic_layer=layer,
            publication_status="published" if row.get("status") == "active" else "review",
            source_lineage=lineage,
        )
        pages.append(page)
        record_page[assertion_id] = page.page_key
        assertion_page_by_id[assertion_id] = page.page_key
        for anchor_id in row.get("evidence_anchor_ids", []):
            target = evidence_page_by_id.get(str(anchor_id))
            if target:
                relations.append(make_notion_relation(page.page_key, "evidence", target))
        for support_id in row.get("supporting_assertion_ids", []):
            target = notion_page_key(database if layer == "A" else "facts_a", "literary_assertion", str(support_id))
            if str(support_id) in assertion_page_by_id:
                target = assertion_page_by_id[str(support_id)]
            relations.append(make_notion_relation(page.page_key, "support", target))

    reasoning_page_by_id: dict[str, str] = {}
    for row in inputs.reasoning_nodes:
        node_id = str(row["node_id"])
        layer = str(row.get("layer") or "")
        database = {"A": "facts_a", "B": "synthesis_b", "C": "interpretations_c", "H": "counterfactuals_h"}.get(layer)
        if database is None:
            reviews.append(make_review_item(
                "REASONING_LAYER_UNSUPPORTED_FOR_NOTION", "critical",
                f"reasoning node has unsupported layer: {node_id}",
                recommended_action="repair_reasoning_layer",
            ))
            continue
        page = make_notion_page(
            database, "reasoning_node", node_id, str(row.get("statement") or node_id),
            properties={
                "layer": layer,
                "intent_tags": row.get("intent_tags", []),
                "confidence": row.get("confidence"),
                "attribution": row.get("attribution"),
                "status": row.get("status"),
            },
            sections={
                "推理记录": row,
                "分层声明": _epistemic_disclosure(layer),
                "限制": row.get("limitations", []),
                "替代解读或结果": row.get("alternatives", []),
                "反事实前提": row.get("counterfactual_premise", ""),
                "推演规则": row.get("inference_rule", ""),
            },
            epistemic_layer=layer,
            publication_status="published" if row.get("status") == "active" else "review",
            source_lineage=lineage,
        )
        pages.append(page)
        record_page[node_id] = page.page_key
        reasoning_page_by_id[node_id] = page.page_key
        for anchor_id in row.get("evidence_anchor_ids", []):
            target = evidence_page_by_id.get(str(anchor_id))
            if target:
                relations.append(make_notion_relation(page.page_key, "evidence", target))
        for chapter_id in row.get("chapter_ids", []):
            target = chapter_page_by_id.get(str(chapter_id)) or literary_chapter_to_canonical.get(str(chapter_id))
            if target:
                relations.append(make_notion_relation(page.page_key, "chapter", target))
        for event_id in row.get("event_ids", []):
            target = event_page_by_id.get(str(event_id))
            if target:
                relations.append(make_notion_relation(page.page_key, "event", target))
        for entity_id in row.get("entity_ids", []):
            target = character_page_by_id.get(str(entity_id))
            if target is None:
                name = entity_name.get(str(entity_id), "")
                target = character_page_by_name.get(name.casefold()) if name else None
            if target:
                relations.append(make_notion_relation(page.page_key, "character", target))

    for row in inputs.reasoning_edges:
        source = reasoning_page_by_id.get(str(row.get("source_node_id")))
        target = reasoning_page_by_id.get(str(row.get("target_node_id")))
        if source and target:
            relations.append(make_notion_relation(source, str(row.get("relation") or "support"), target))
        else:
            reviews.append(make_review_item(
                "REASONING_RELATION_PAGE_UNRESOLVED", "high",
                f"reasoning relation endpoints do not both resolve: {row.get('edge_id')}",
                affected_page_keys=tuple(value for value in (source, target) if value),
                recommended_action="project_all_reasoning_nodes_before_relations",
            ))

    # Link event Evidence and participants using scoped character resolution.
    for row in inputs.events:
        source = event_page_by_id.get(str(row.get("event_id")))
        if not source:
            continue
        for anchor_id in row.get("evidence_anchor_ids", []):
            target = evidence_page_by_id.get(str(anchor_id))
            if target:
                relations.append(make_notion_relation(source, "evidence", target))
        for entity_id in row.get("participant_entity_ids", []):
            name = entity_name.get(str(entity_id), "")
            target = character_page_by_name.get(name.casefold()) if name else None
            if target:
                relations.append(make_notion_relation(source, "participant", target))

    for row in inputs.characters:
        source = character_page_by_id.get(str(row.get("character_id")))
        if not source:
            continue
        for anchor_id in row.get("evidence_anchor_ids", []):
            target = evidence_page_by_id.get(str(anchor_id))
            if target:
                relations.append(make_notion_relation(source, "evidence", target))

    for origin, findings in (
        ("chapter", inputs.chapter_findings),
        ("event", inputs.event_findings),
        ("character", inputs.character_findings),
        ("reasoning", inputs.reasoning_findings),
    ):
        reviews.extend(_finding_review(row, origin) for row in findings)

    # First pass obtains projection-generated review items; second pass projects them
    # into the Review Queue while retaining the same review records.
    initial = build_notion_projection(pages, relations, ledger_entries=ledger_entries, upstream_review_items=reviews)
    review_pages: list[NotionPage] = []
    review_relations: list[NotionRelation] = []
    existing_page_keys = {page.page_key for page in pages}
    for item in initial.reviews:
        page = make_notion_page(
            "review_queue", "review_item", item.review_id, f"{item.severity.upper()}｜{item.rule_id}",
            properties={
                "rule_id": item.rule_id,
                "severity": item.severity,
                "recommended_action": item.recommended_action,
            },
            sections={"审查说明": item.message, "审查记录": item.to_dict()},
            publication_status="review",
            source_lineage=lineage,
        )
        review_pages.append(page)
        for target in item.affected_page_keys:
            if target in existing_page_keys:
                review_relations.append(make_notion_relation(page.page_key, "affected_page", target))
    return build_notion_projection(
        (*pages, *review_pages),
        (*relations, *review_relations),
        ledger_entries=ledger_entries,
        upstream_review_items=reviews,
    )


def _workspace_payloads(projection: NotionProjection) -> dict[str, bytes]:
    return {
        "notion-workspace-schema.json": _json_bytes(_workspace_schema()),
        "notion-pages.jsonl": _jsonl_bytes(projection.pages),
        "notion-relations.jsonl": _jsonl_bytes(projection.relations),
        "notion-review-items.jsonl": _jsonl_bytes(projection.reviews),
        "notion-sync-plan.jsonl": _jsonl_bytes(projection.actions),
    }


def _logical_hash(payloads: Mapping[str, bytes], inputs: _ProjectionInputs, ledger_sha: str) -> str:
    digest = sha256()
    digest.update(NOTION_PROJECT_SCHEMA_VERSION.encode("utf-8"))
    for label, value in (
        ("chapter", inputs.chapter_logical),
        ("event", inputs.event_logical),
        ("character", inputs.character_logical),
        ("reasoning", inputs.reasoning_logical),
        ("ledger", ledger_sha),
    ):
        digest.update(b"\0")
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
    for value in inputs.literary_logicals:
        digest.update(b"\0literary\0")
        digest.update(value.encode("utf-8"))
    for value in inputs.evidence_logicals:
        digest.update(b"\0evidence\0")
        digest.update(value.encode("utf-8"))
    for name in sorted(payloads):
        digest.update(b"\0file\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payloads[name])
    return digest.hexdigest()


def _create_database(path: Path, projection: NotionProjection, metadata: Mapping[str, str]) -> None:
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
                status TEXT NOT NULL
            );
            CREATE INDEX relation_source_type ON relations(source_page_key,relation_type,target_page_key);
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
        for item in projection.pages:
            connection.execute(
                "INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.page_key, item.database_key, item.record_type, item.record_id,
                    item.title, item.epistemic_layer, item.publication_status,
                    item.content_sha256, _canonical_json(item.properties),
                    _canonical_json(item.sections), _canonical_json(list(item.source_lineage)),
                ),
            )
        for item in projection.relations:
            connection.execute(
                "INSERT INTO relations VALUES(?,?,?,?,?)",
                (item.relation_id, item.source_page_key, item.relation_type, item.target_page_key, item.status),
            )
        for item in projection.reviews:
            connection.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                (
                    item.review_id, item.rule_id, item.severity, item.message,
                    item.recommended_action, _canonical_json(list(item.affected_page_keys)),
                    _canonical_json(list(item.affected_relation_ids)),
                ),
            )
        for item in projection.actions:
            connection.execute(
                "INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    item.action_id, item.target_type, item.target_key, item.action,
                    item.notion_page_id, item.content_sha256, item.relation_sha256,
                    _canonical_json(list(item.dependency_page_keys)),
                    _canonical_json(list(item.reason_codes)),
                ),
            )
        connection.commit()
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise NotionProjectError("Notion SQLite foreign-key check failed")
        connection.execute("VACUUM")
    finally:
        connection.close()


def _install(temporary: Path, output: Path, replace_existing: bool) -> None:
    if not output.exists():
        temporary.replace(output)
        return
    if not replace_existing:
        raise NotionProjectError(f"output directory already exists: {output}")
    if output.is_symlink() or not output.is_dir():
        raise NotionProjectError("existing output is unsafe")
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


def build_notion_project(
    chapter_project_directory: str | Path,
    source_project_directories: Sequence[str | Path],
    literary_project_directories: Sequence[str | Path],
    evidence_bindings: Sequence[tuple[str | Path, str | Path, str | Path]],
    event_project_directory: str | Path,
    event_annotations_path: str | Path,
    character_project_directory: str | Path,
    character_annotations_path: str | Path,
    reasoning_project_directory: str | Path,
    reasoning_annotations_path: str | Path,
    output_directory: str | Path,
    *,
    ledger_path: str | Path | None = None,
    replace_existing: bool = False,
) -> NotionProjectBuildResult:
    chapter_project = Path(chapter_project_directory)
    sources = tuple(Path(value) for value in source_project_directories)
    literary = tuple(Path(value) for value in literary_project_directories)
    bindings = tuple((Path(a), Path(b), Path(c)) for a, b, c in evidence_bindings)
    event_project = Path(event_project_directory)
    event_annotations = Path(event_annotations_path)
    character_project = Path(character_project_directory)
    character_annotations = Path(character_annotations_path)
    reasoning_project = Path(reasoning_project_directory)
    reasoning_annotations = Path(reasoning_annotations_path)
    output = Path(output_directory)
    ledger_file = None if ledger_path is None else Path(ledger_path)
    for path, label in (
        (chapter_project, "Chapter Project"),
        (event_project, "Event Project"),
        (character_project, "Character Project"),
        (reasoning_project, "Reasoning Project"),
    ):
        _safe_directory(path, label)
    for path, label in (
        (event_annotations, "event annotations"),
        (character_annotations, "character annotations"),
        (reasoning_annotations, "reasoning annotations"),
    ):
        _safe_file(path, label)
    if output.is_symlink():
        raise NotionProjectError("output path must not be a symbolic link")

    inputs = _inputs(
        chapter_project, sources, literary, bindings, event_project,
        event_annotations, character_project, character_annotations,
        reasoning_project, reasoning_annotations,
    )
    ledger_entries, ledger_sha = _ledger(ledger_file)
    projection = _projection(inputs, ledger_entries)
    payloads = _workspace_payloads(projection)
    logical = _logical_hash(payloads, inputs, ledger_sha)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        database_path = temporary / "notion.sqlite"
        metadata = {
            "notion_project_schema_version": NOTION_PROJECT_SCHEMA_VERSION,
            "notion_sqlite_schema_version": NOTION_SQLITE_SCHEMA_VERSION,
            "notion_engine_version": NOTION_ENGINE_VERSION,
            "chapter_project_logical_sha256": inputs.chapter_logical,
            "event_project_logical_sha256": inputs.event_logical,
            "character_project_logical_sha256": inputs.character_logical,
            "reasoning_project_logical_sha256": inputs.reasoning_logical,
            "ledger_sha256": ledger_sha,
            "logical_sha256": logical,
        }
        _create_database(database_path, projection, metadata)
        database_hash = sha256_file(database_path)
        result = NotionProjectBuildResult(
            NOTION_PROJECT_REPORT_SCHEMA_VERSION,
            projection.report.status,
            NOTION_ENGINE_VERSION,
            str(output),
            projection.report.page_count,
            projection.report.relation_count,
            projection.report.review_count,
            projection.report.blocking_review_count,
            projection.report.database_counts,
            projection.report.action_counts,
            projection.report.projection_valid,
            inputs.chapter_logical,
            inputs.literary_ids,
            inputs.evidence_logicals,
            inputs.event_logical,
            inputs.character_logical,
            inputs.reasoning_logical,
            ledger_sha,
            logical,
            database_hash,
        )
        report = {
            **result.to_dict(),
            "literary_logical_sha256s": list(inputs.literary_logicals),
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "notion-project-report.json", _json_bytes(report))
        entries = []
        for path in sorted(temporary.iterdir()):
            if path.is_file():
                entries.append({
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
        manifest = {
            "schema_version": NOTION_PROJECT_MANIFEST_SCHEMA_VERSION,
            "notion_project_schema_version": NOTION_PROJECT_SCHEMA_VERSION,
            "notion_engine_version": NOTION_ENGINE_VERSION,
            "chapter_project_logical_sha256": inputs.chapter_logical,
            "literary_project_ids": list(inputs.literary_ids),
            "literary_logical_sha256s": list(inputs.literary_logicals),
            "evidence_project_logical_sha256s": list(inputs.evidence_logicals),
            "event_project_logical_sha256": inputs.event_logical,
            "character_project_logical_sha256": inputs.character_logical,
            "reasoning_project_logical_sha256": inputs.reasoning_logical,
            "ledger_sha256": ledger_sha,
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
        raise NotionProjectError("Notion manifest files must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise NotionProjectError("Notion manifest entry must be an object")
        relative = _safe_relative(entry.get("path"))
        if relative is None or relative in result or relative == "artifact-manifest.json":
            raise NotionProjectError("Notion manifest path is invalid")
        result[relative] = entry
    return result


def verify_notion_project(
    chapter_project_directory: str | Path,
    source_project_directories: Sequence[str | Path],
    literary_project_directories: Sequence[str | Path],
    evidence_bindings: Sequence[tuple[str | Path, str | Path, str | Path]],
    event_project_directory: str | Path,
    event_annotations_path: str | Path,
    character_project_directory: str | Path,
    character_annotations_path: str | Path,
    reasoning_project_directory: str | Path,
    reasoning_annotations_path: str | Path,
    notion_project_directory: str | Path,
    *,
    ledger_path: str | Path | None = None,
) -> NotionProjectVerification:
    root = Path(notion_project_directory)
    reasons: list[str] = []
    checked = 0
    logical = ""
    database_hash = ""
    projection_valid = False
    try:
        _safe_directory(root, "Notion Project")
        inputs = _inputs(
            Path(chapter_project_directory),
            tuple(Path(value) for value in source_project_directories),
            tuple(Path(value) for value in literary_project_directories),
            tuple((Path(a), Path(b), Path(c)) for a, b, c in evidence_bindings),
            Path(event_project_directory), Path(event_annotations_path),
            Path(character_project_directory), Path(character_annotations_path),
            Path(reasoning_project_directory), Path(reasoning_annotations_path),
        )
        ledger_entries, ledger_sha = _ledger(None if ledger_path is None else Path(ledger_path))
        projection = _projection(inputs, ledger_entries)
        projection_valid = projection.report.projection_valid
        expected_payloads = _workspace_payloads(projection)
        expected_logical = _logical_hash(expected_payloads, inputs, ledger_sha)
        manifest = _load_object(root / "artifact-manifest.json", "Notion manifest")
        report = _load_object(root / "notion-project-report.json", "Notion report")
        logical = str(manifest.get("logical_sha256", ""))
        database_hash = str(manifest.get("database_sha256", ""))
        if manifest.get("schema_version") != NOTION_PROJECT_MANIFEST_SCHEMA_VERSION:
            reasons.append("NOTION_MANIFEST_SCHEMA_MISMATCH")
        if report.get("schema_version") != NOTION_PROJECT_REPORT_SCHEMA_VERSION:
            reasons.append("NOTION_REPORT_SCHEMA_MISMATCH")
        if manifest.get("notion_engine_version") != NOTION_ENGINE_VERSION:
            reasons.append("NOTION_ENGINE_VERSION_MISMATCH")
        if any(
            bool(manifest.get(key)) or bool(report.get(key))
            for key in ("project_acceptance_performed", "may_accept_project", "may_release", "may_freeze")
        ):
            reasons.append("NOTION_AUTHORITY_BOUNDARY_VIOLATION")
        if set(path.name for path in root.iterdir()) != _ALLOWED_FILES:
            reasons.append("NOTION_PROJECT_FILE_SET_MISMATCH")
        file_map = _manifest_file_map(manifest)
        if set(file_map) != (_ALLOWED_FILES - {"artifact-manifest.json"}):
            reasons.append("NOTION_MANIFEST_MEMBERSHIP_MISMATCH")
        for relative, entry in file_map.items():
            path = root / relative
            if path.is_symlink() or not path.is_file():
                reasons.append("NOTION_MANIFEST_FILE_MISSING")
                continue
            checked += 1
            if entry.get("size_bytes") != path.stat().st_size:
                reasons.append("NOTION_FILE_SIZE_MISMATCH")
            if entry.get("sha256") != sha256_file(path):
                reasons.append("NOTION_FILE_HASH_MISMATCH")
        for name, expected in expected_payloads.items():
            path = root / name
            if path.is_file() and path.read_bytes() != expected:
                reasons.append("NOTION_ARTIFACT_CONTENT_MISMATCH")
        if logical != expected_logical or report.get("logical_sha256") != expected_logical:
            reasons.append("NOTION_LOGICAL_HASH_MISMATCH")
        binding_checks = {
            "chapter_project_logical_sha256": inputs.chapter_logical,
            "literary_project_ids": list(inputs.literary_ids),
            "literary_logical_sha256s": list(inputs.literary_logicals),
            "evidence_project_logical_sha256s": list(inputs.evidence_logicals),
            "event_project_logical_sha256": inputs.event_logical,
            "character_project_logical_sha256": inputs.character_logical,
            "reasoning_project_logical_sha256": inputs.reasoning_logical,
            "ledger_sha256": ledger_sha,
        }
        for key, expected in binding_checks.items():
            if manifest.get(key) != expected:
                reasons.append("NOTION_UPSTREAM_BINDING_MISMATCH")
            if key in report and report.get(key) != expected:
                reasons.append("NOTION_REPORT_BINDING_MISMATCH")
        for key, expected in (
            ("page_count", projection.report.page_count),
            ("relation_count", projection.report.relation_count),
            ("review_count", projection.report.review_count),
            ("blocking_review_count", projection.report.blocking_review_count),
            ("database_counts", projection.report.database_counts),
            ("action_counts", projection.report.action_counts),
            ("projection_valid", projection.report.projection_valid),
            ("status", projection.report.status),
        ):
            if report.get(key) != expected:
                reasons.append("NOTION_REPORT_COUNT_OR_STATUS_MISMATCH")
        database_path = root / "notion.sqlite"
        if not database_path.is_file() or database_path.is_symlink():
            reasons.append("NOTION_DATABASE_MISSING")
        else:
            actual_hash = sha256_file(database_path)
            if actual_hash != database_hash or report.get("database_sha256") != database_hash:
                reasons.append("NOTION_DATABASE_HASH_MISMATCH")
            connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    reasons.append("NOTION_DATABASE_INTEGRITY_FAILED")
                metadata = dict(connection.execute("SELECT key,value FROM metadata"))
                if metadata.get("logical_sha256") != expected_logical:
                    reasons.append("NOTION_DATABASE_METADATA_MISMATCH")
                page_keys = [row[0] for row in connection.execute("SELECT page_key FROM pages ORDER BY database_key,page_key")]
                if page_keys != [item.page_key for item in projection.pages]:
                    reasons.append("NOTION_DATABASE_PAGE_MISMATCH")
                relation_ids = [row[0] for row in connection.execute("SELECT relation_id FROM relations ORDER BY source_page_key,relation_type,target_page_key,relation_id")]
                if relation_ids != [item.relation_id for item in projection.relations]:
                    reasons.append("NOTION_DATABASE_RELATION_MISMATCH")
            finally:
                connection.close()
    except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, NotionProjectError, ValueError) as exc:
        reasons.append("NOTION_VERIFICATION_EXCEPTION:" + type(exc).__name__)
    unique = tuple(dict.fromkeys(reasons))
    return NotionProjectVerification(
        NOTION_PROJECT_VERIFICATION_SCHEMA_VERSION,
        "valid" if not unique else "invalid",
        not unique,
        projection_valid,
        unique,
        checked,
        logical,
        database_hash,
    )


__all__ = [
    "EvidenceBinding",
    "NOTION_PROJECT_MANIFEST_SCHEMA_VERSION",
    "NOTION_PROJECT_REPORT_SCHEMA_VERSION",
    "NOTION_PROJECT_SCHEMA_VERSION",
    "NOTION_PROJECT_VERIFICATION_SCHEMA_VERSION",
    "NOTION_SQLITE_SCHEMA_VERSION",
    "NOTION_WORKSPACE_SCHEMA_VERSION",
    "NotionProjectBuildResult",
    "NotionProjectError",
    "NotionProjectVerification",
    "build_notion_project",
    "verify_notion_project",
]
