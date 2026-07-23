"""Deterministic Notion projection and incremental-sync contracts for Stage 6.

This module does not call the Notion API.  It validates page and relation
projections, computes stable hashes, and creates a reversible sync plan from an
optional remote-ID ledger.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from typing import Final, Iterable, Mapping, Sequence

NOTION_ENGINE_VERSION: Final = "6.0.0-stage6-alpha1"
NOTION_PAGE_SCHEMA_VERSION: Final = "tkr-notion-page-v1"
NOTION_RELATION_SCHEMA_VERSION: Final = "tkr-notion-relation-v1"
NOTION_REVIEW_SCHEMA_VERSION: Final = "tkr-notion-review-item-v1"
NOTION_LEDGER_SCHEMA_VERSION: Final = "tkr-notion-sync-ledger-v1"
NOTION_ACTION_SCHEMA_VERSION: Final = "tkr-notion-sync-action-v1"
NOTION_REPORT_SCHEMA_VERSION: Final = "tkr-notion-projection-report-v1"

DATABASE_KEYS: Final = frozenset({
    "sources",
    "chapters",
    "evidence",
    "facts_a",
    "synthesis_b",
    "interpretations_c",
    "counterfactuals_h",
    "events",
    "characters",
    "review_queue",
})
LAYER_DATABASE: Final = {
    "A": "facts_a",
    "B": "synthesis_b",
    "C": "interpretations_c",
    "H": "counterfactuals_h",
}
PAGE_STATUSES: Final = frozenset({"published", "minimal", "review", "superseded"})
RELATION_STATUSES: Final = frozenset({"active", "review", "superseded"})
ACTION_TYPES: Final = frozenset({
    "create",
    "update",
    "noop",
    "review_missing_remote_id",
    "archive_candidate",
})
TARGET_TYPES: Final = frozenset({"page", "relation_set"})
BLOCKING_SEVERITIES: Final = frozenset({"high", "critical"})


class NotionEngineError(ValueError):
    """Raised when a Notion projection violates Stage 6 safety contracts."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\0".join(_canonical_json(part) for part in parts)
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise NotionEngineError(f"{name} must be {'text' if allow_empty else 'non-empty text'}")
    return value


def _require_tuple_text(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(not isinstance(item, str) or not item for item in values):
        raise NotionEngineError(f"{name} must be a tuple of non-empty strings")
    if len(values) != len(set(values)):
        raise NotionEngineError(f"{name} must not contain duplicates")
    return values


def notion_page_key(database_key: str, record_type: str, record_id: str) -> str:
    if database_key not in DATABASE_KEYS:
        raise NotionEngineError(f"unsupported Notion database key: {database_key}")
    _require_text(record_type, "record_type")
    _require_text(record_id, "record_id")
    return stable_id("npg_", NOTION_PAGE_SCHEMA_VERSION, database_key, record_type, record_id)


def notion_relation_id(source_page_key: str, relation_type: str, target_page_key: str) -> str:
    return stable_id(
        "nrl_",
        NOTION_RELATION_SCHEMA_VERSION,
        source_page_key,
        relation_type,
        target_page_key,
    )


def _content_hash_payload(
    *,
    database_key: str,
    record_type: str,
    record_id: str,
    title: str,
    properties: Mapping[str, object],
    sections: Mapping[str, object],
    epistemic_layer: str,
    publication_status: str,
    source_lineage: Sequence[str],
) -> str:
    return sha256(
        _canonical_json({
            "database_key": database_key,
            "record_type": record_type,
            "record_id": record_id,
            "title": title,
            "properties": properties,
            "sections": sections,
            "epistemic_layer": epistemic_layer,
            "publication_status": publication_status,
            "source_lineage": sorted(source_lineage),
        }).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class NotionPage:
    schema_version: str
    page_key: str
    database_key: str
    record_type: str
    record_id: str
    title: str
    properties: dict[str, object]
    sections: dict[str, object]
    epistemic_layer: str
    publication_status: str
    source_lineage: tuple[str, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_PAGE_SCHEMA_VERSION:
            raise NotionEngineError("Notion page schema mismatch")
        expected_key = notion_page_key(self.database_key, self.record_type, self.record_id)
        if self.page_key != expected_key:
            raise NotionEngineError("Notion page key is not deterministic")
        _require_text(self.title, "title")
        if not isinstance(self.properties, dict) or not isinstance(self.sections, dict):
            raise NotionEngineError("properties and sections must be objects")
        if self.epistemic_layer not in {"", "A", "B", "C", "H"}:
            raise NotionEngineError("unsupported epistemic layer")
        if self.publication_status not in PAGE_STATUSES:
            raise NotionEngineError("unsupported page publication status")
        _require_tuple_text(self.source_lineage, "source_lineage")
        if self.epistemic_layer:
            if LAYER_DATABASE[self.epistemic_layer] != self.database_key:
                raise NotionEngineError("epistemic layer is assigned to the wrong database")
        elif self.database_key in set(LAYER_DATABASE.values()):
            raise NotionEngineError("epistemic database page must declare its layer")
        expected_hash = _content_hash_payload(
            database_key=self.database_key,
            record_type=self.record_type,
            record_id=self.record_id,
            title=self.title,
            properties=self.properties,
            sections=self.sections,
            epistemic_layer=self.epistemic_layer,
            publication_status=self.publication_status,
            source_lineage=self.source_lineage,
        )
        if self.content_sha256 != expected_hash:
            raise NotionEngineError("Notion page content hash mismatch")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source_lineage"] = list(self.source_lineage)
        return payload


def make_notion_page(
    database_key: str,
    record_type: str,
    record_id: str,
    title: str,
    *,
    properties: Mapping[str, object],
    sections: Mapping[str, object],
    epistemic_layer: str = "",
    publication_status: str = "published",
    source_lineage: Sequence[str],
) -> NotionPage:
    lineage = tuple(sorted(set(source_lineage)))
    page_key = notion_page_key(database_key, record_type, record_id)
    content_hash = _content_hash_payload(
        database_key=database_key,
        record_type=record_type,
        record_id=record_id,
        title=title,
        properties=dict(properties),
        sections=dict(sections),
        epistemic_layer=epistemic_layer,
        publication_status=publication_status,
        source_lineage=lineage,
    )
    return NotionPage(
        NOTION_PAGE_SCHEMA_VERSION,
        page_key,
        database_key,
        record_type,
        record_id,
        title,
        dict(properties),
        dict(sections),
        epistemic_layer,
        publication_status,
        lineage,
        content_hash,
    )


@dataclass(frozen=True, slots=True)
class NotionRelation:
    schema_version: str
    relation_id: str
    source_page_key: str
    relation_type: str
    target_page_key: str
    status: str

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_RELATION_SCHEMA_VERSION:
            raise NotionEngineError("Notion relation schema mismatch")
        for name in ("source_page_key", "relation_type", "target_page_key"):
            _require_text(getattr(self, name), name)
        if self.source_page_key == self.target_page_key:
            raise NotionEngineError("Notion relation endpoints must differ")
        expected = notion_relation_id(
            self.source_page_key, self.relation_type, self.target_page_key
        )
        if self.relation_id != expected:
            raise NotionEngineError("Notion relation ID is not deterministic")
        if self.status not in RELATION_STATUSES:
            raise NotionEngineError("unsupported Notion relation status")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def make_notion_relation(
    source_page_key: str,
    relation_type: str,
    target_page_key: str,
    *,
    status: str = "active",
) -> NotionRelation:
    return NotionRelation(
        NOTION_RELATION_SCHEMA_VERSION,
        notion_relation_id(source_page_key, relation_type, target_page_key),
        source_page_key,
        relation_type,
        target_page_key,
        status,
    )


@dataclass(frozen=True, slots=True)
class NotionReviewItem:
    schema_version: str
    review_id: str
    rule_id: str
    severity: str
    message: str
    affected_page_keys: tuple[str, ...]
    affected_relation_ids: tuple[str, ...]
    recommended_action: str

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_REVIEW_SCHEMA_VERSION:
            raise NotionEngineError("Notion review item schema mismatch")
        for name in ("review_id", "rule_id", "severity", "message", "recommended_action"):
            _require_text(getattr(self, name), name)
        for name in ("affected_page_keys", "affected_relation_ids"):
            _require_tuple_text(getattr(self, name), name)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["affected_page_keys"] = list(self.affected_page_keys)
        payload["affected_relation_ids"] = list(self.affected_relation_ids)
        return payload


def make_review_item(
    rule_id: str,
    severity: str,
    message: str,
    *,
    affected_page_keys: Iterable[str] = (),
    affected_relation_ids: Iterable[str] = (),
    recommended_action: str,
) -> NotionReviewItem:
    pages = tuple(sorted(set(affected_page_keys)))
    relations = tuple(sorted(set(affected_relation_ids)))
    return NotionReviewItem(
        NOTION_REVIEW_SCHEMA_VERSION,
        stable_id("nrv_", NOTION_REVIEW_SCHEMA_VERSION, rule_id, pages, relations, message),
        rule_id,
        severity,
        message,
        pages,
        relations,
        recommended_action,
    )


@dataclass(frozen=True, slots=True)
class SyncLedgerEntry:
    schema_version: str
    page_key: str
    notion_page_id: str
    content_sha256: str
    relation_sha256: str
    archived: bool

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_LEDGER_SCHEMA_VERSION:
            raise NotionEngineError("Notion sync ledger schema mismatch")
        _require_text(self.page_key, "page_key")
        _require_text(self.notion_page_id, "notion_page_id", allow_empty=True)
        for name in ("content_sha256", "relation_sha256"):
            value = getattr(self, name)
            if value and (not isinstance(value, str) or len(value) != 64):
                raise NotionEngineError(f"{name} must be empty or SHA-256")
        if not isinstance(self.archived, bool):
            raise NotionEngineError("archived must be boolean")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NotionSyncAction:
    schema_version: str
    action_id: str
    target_type: str
    target_key: str
    action: str
    notion_page_id: str
    content_sha256: str
    relation_sha256: str
    dependency_page_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_ACTION_SCHEMA_VERSION:
            raise NotionEngineError("Notion sync action schema mismatch")
        if self.target_type not in TARGET_TYPES:
            raise NotionEngineError("unsupported sync target type")
        _require_text(self.target_key, "target_key")
        if self.action not in ACTION_TYPES:
            raise NotionEngineError("unsupported sync action")
        _require_text(self.notion_page_id, "notion_page_id", allow_empty=True)
        for name in ("content_sha256", "relation_sha256"):
            value = getattr(self, name)
            if value and (not isinstance(value, str) or len(value) != 64):
                raise NotionEngineError(f"{name} must be empty or SHA-256")
        for name in ("dependency_page_keys", "reason_codes"):
            _require_tuple_text(getattr(self, name), name)
        expected = stable_id(
            "nsa_",
            NOTION_ACTION_SCHEMA_VERSION,
            self.target_type,
            self.target_key,
            self.action,
            self.content_sha256,
            self.relation_sha256,
            self.dependency_page_keys,
        )
        if self.action_id != expected:
            raise NotionEngineError("sync action ID is not deterministic")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["dependency_page_keys"] = list(self.dependency_page_keys)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def _action(
    target_type: str,
    target_key: str,
    action: str,
    *,
    notion_page_id: str = "",
    content_sha256: str = "",
    relation_sha256: str = "",
    dependency_page_keys: Iterable[str] = (),
    reason_codes: Iterable[str] = (),
) -> NotionSyncAction:
    dependencies = tuple(sorted(set(dependency_page_keys)))
    reasons = tuple(sorted(set(reason_codes)))
    return NotionSyncAction(
        NOTION_ACTION_SCHEMA_VERSION,
        stable_id(
            "nsa_",
            NOTION_ACTION_SCHEMA_VERSION,
            target_type,
            target_key,
            action,
            content_sha256,
            relation_sha256,
            dependencies,
        ),
        target_type,
        target_key,
        action,
        notion_page_id,
        content_sha256,
        relation_sha256,
        dependencies,
        reasons,
    )


def relation_set_hash(page_key: str, relations: Sequence[NotionRelation]) -> str:
    rows = [
        item.to_dict()
        for item in sorted(
            (item for item in relations if item.source_page_key == page_key and item.status == "active"),
            key=lambda item: (item.relation_type, item.target_page_key, item.relation_id),
        )
    ]
    return sha256(_canonical_json(rows).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class NotionProjectionReport:
    schema_version: str
    status: str
    projection_valid: bool
    page_count: int
    relation_count: int
    review_count: int
    blocking_review_count: int
    database_counts: dict[str, int]
    action_counts: dict[str, int]
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != NOTION_REPORT_SCHEMA_VERSION:
            raise NotionEngineError("Notion projection report schema mismatch")
        if self.status not in {"completed", "review_required"}:
            raise NotionEngineError("invalid Notion projection status")
        if self.projection_valid != (self.status == "completed"):
            raise NotionEngineError("Notion projection status and validity disagree")
        for name in ("page_count", "relation_count", "review_count", "blocking_review_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise NotionEngineError(f"{name} must be a non-negative integer")
        if any((self.project_acceptance_performed, self.may_accept_project, self.may_release, self.may_freeze)):
            raise NotionEngineError("Notion projection cannot grant release authority")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NotionProjection:
    pages: tuple[NotionPage, ...]
    relations: tuple[NotionRelation, ...]
    reviews: tuple[NotionReviewItem, ...]
    actions: tuple[NotionSyncAction, ...]
    report: NotionProjectionReport


def build_notion_projection(
    pages: Sequence[NotionPage],
    relations: Sequence[NotionRelation],
    *,
    ledger_entries: Sequence[SyncLedgerEntry] = (),
    upstream_review_items: Sequence[NotionReviewItem] = (),
) -> NotionProjection:
    """Validate pages/relations and build a deterministic incremental sync plan."""
    sorted_pages = tuple(sorted(pages, key=lambda item: (item.database_key, item.page_key)))
    sorted_relations = tuple(sorted(
        relations,
        key=lambda item: (item.source_page_key, item.relation_type, item.target_page_key, item.relation_id),
    ))
    reviews = list(upstream_review_items)
    page_by_key: dict[str, NotionPage] = {}
    for page in sorted_pages:
        if page.page_key in page_by_key:
            reviews.append(make_review_item(
                "DUPLICATE_NOTION_PAGE_KEY",
                "critical",
                f"duplicate page key: {page.page_key}",
                affected_page_keys=(page.page_key,),
                recommended_action="deduplicate_page_projection",
            ))
        else:
            page_by_key[page.page_key] = page

    relation_ids: set[str] = set()
    for relation in sorted_relations:
        if relation.relation_id in relation_ids:
            reviews.append(make_review_item(
                "DUPLICATE_NOTION_RELATION_ID",
                "critical",
                f"duplicate relation ID: {relation.relation_id}",
                affected_relation_ids=(relation.relation_id,),
                recommended_action="deduplicate_relation_projection",
            ))
        relation_ids.add(relation.relation_id)
        missing = [
            value
            for value in (relation.source_page_key, relation.target_page_key)
            if value not in page_by_key
        ]
        if missing:
            reviews.append(make_review_item(
                "UNRESOLVED_NOTION_RELATION_ENDPOINT",
                "high",
                "one or more relation endpoints are absent from the projection",
                affected_page_keys=missing,
                affected_relation_ids=(relation.relation_id,),
                recommended_action="project_or_review_missing_relation_endpoints",
            ))

    ledger_by_key: dict[str, SyncLedgerEntry] = {}
    remote_owner: dict[str, str] = {}
    for entry in sorted(ledger_entries, key=lambda item: item.page_key):
        if entry.page_key in ledger_by_key:
            reviews.append(make_review_item(
                "DUPLICATE_LEDGER_PAGE_KEY",
                "critical",
                f"duplicate ledger page key: {entry.page_key}",
                affected_page_keys=(entry.page_key,),
                recommended_action="deduplicate_sync_ledger",
            ))
            continue
        ledger_by_key[entry.page_key] = entry
        if entry.notion_page_id:
            owner = remote_owner.get(entry.notion_page_id)
            if owner is not None and owner != entry.page_key:
                reviews.append(make_review_item(
                    "REMOTE_NOTION_PAGE_ID_REUSED",
                    "critical",
                    f"remote page ID is assigned to multiple stable page keys: {entry.notion_page_id}",
                    affected_page_keys=(owner, entry.page_key),
                    recommended_action="repair_remote_page_identity_mapping",
                ))
            else:
                remote_owner[entry.notion_page_id] = entry.page_key

    actions: list[NotionSyncAction] = []
    active_relations = [item for item in sorted_relations if item.status == "active"]
    for page in sorted_pages:
        ledger = ledger_by_key.get(page.page_key)
        current_relation_hash = relation_set_hash(page.page_key, active_relations)
        if ledger is None:
            page_action = "create"
            notion_page_id = ""
            page_reasons = ("PAGE_KEY_NOT_IN_LEDGER",)
        elif not ledger.notion_page_id:
            page_action = "review_missing_remote_id"
            notion_page_id = ""
            page_reasons = ("LEDGER_ENTRY_MISSING_REMOTE_PAGE_ID",)
        elif ledger.archived:
            page_action = "update"
            notion_page_id = ledger.notion_page_id
            page_reasons = ("RESTORE_ARCHIVED_PAGE",)
        elif ledger.content_sha256 == page.content_sha256:
            page_action = "noop"
            notion_page_id = ledger.notion_page_id
            page_reasons = ()
        else:
            page_action = "update"
            notion_page_id = ledger.notion_page_id
            page_reasons = ("CONTENT_HASH_CHANGED",)
        actions.append(_action(
            "page",
            page.page_key,
            page_action,
            notion_page_id=notion_page_id,
            content_sha256=page.content_sha256,
            relation_sha256=current_relation_hash,
            reason_codes=page_reasons,
        ))

        dependencies = {
            relation.source_page_key
            for relation in active_relations
            if relation.source_page_key == page.page_key
        } | {
            relation.target_page_key
            for relation in active_relations
            if relation.source_page_key == page.page_key
        }
        if not dependencies:
            continue
        unresolved = sorted(value for value in dependencies if value not in page_by_key)
        if unresolved:
            relation_action = "review_missing_remote_id"
            relation_reasons = ("RELATION_ENDPOINT_NOT_PROJECTED",)
        elif ledger is None:
            relation_action = "create"
            relation_reasons = ("RELATIONS_APPLY_AFTER_PAGE_CREATION",)
        elif not ledger.notion_page_id:
            relation_action = "review_missing_remote_id"
            relation_reasons = ("SOURCE_REMOTE_PAGE_ID_MISSING",)
        elif ledger.relation_sha256 == current_relation_hash and not ledger.archived:
            relation_action = "noop"
            relation_reasons = ()
        else:
            relation_action = "update"
            relation_reasons = ("RELATION_HASH_CHANGED",)
        actions.append(_action(
            "relation_set",
            page.page_key,
            relation_action,
            notion_page_id="" if ledger is None else ledger.notion_page_id,
            content_sha256=page.content_sha256,
            relation_sha256=current_relation_hash,
            dependency_page_keys=dependencies,
            reason_codes=relation_reasons,
        ))

    for page_key, ledger in sorted(ledger_by_key.items()):
        if page_key in page_by_key or ledger.archived:
            continue
        actions.append(_action(
            "page",
            page_key,
            "archive_candidate",
            notion_page_id=ledger.notion_page_id,
            content_sha256=ledger.content_sha256,
            relation_sha256=ledger.relation_sha256,
            reason_codes=("PAGE_ABSENT_FROM_CURRENT_PROJECTION", "EXPLICIT_ARCHIVE_APPROVAL_REQUIRED"),
        ))
        reviews.append(make_review_item(
            "NOTION_ARCHIVE_CANDIDATE",
            "medium",
            "ledger page is absent from the current projection; no remote deletion was performed",
            affected_page_keys=(page_key,),
            recommended_action="review_and_explicitly_authorize_reversible_archive",
        ))

    reviews.sort(key=lambda item: (item.severity, item.rule_id, item.review_id))
    actions.sort(key=lambda item: (item.target_type, item.target_key, item.action, item.action_id))
    blocking = sum(item.severity in BLOCKING_SEVERITIES for item in reviews)
    database_counts = {
        key: sum(item.database_key == key for item in sorted_pages)
        for key in sorted(DATABASE_KEYS)
    }
    action_counts = {
        key: sum(item.action == key for item in actions)
        for key in sorted(ACTION_TYPES)
    }
    valid = blocking == 0
    report = NotionProjectionReport(
        NOTION_REPORT_SCHEMA_VERSION,
        "completed" if valid else "review_required",
        valid,
        len(sorted_pages),
        len(sorted_relations),
        len(reviews),
        blocking,
        database_counts,
        action_counts,
    )
    return NotionProjection(
        sorted_pages,
        sorted_relations,
        tuple(reviews),
        tuple(actions),
        report,
    )


__all__ = [
    "ACTION_TYPES",
    "DATABASE_KEYS",
    "LAYER_DATABASE",
    "NOTION_ACTION_SCHEMA_VERSION",
    "NOTION_ENGINE_VERSION",
    "NOTION_LEDGER_SCHEMA_VERSION",
    "NOTION_PAGE_SCHEMA_VERSION",
    "NOTION_RELATION_SCHEMA_VERSION",
    "NOTION_REPORT_SCHEMA_VERSION",
    "NOTION_REVIEW_SCHEMA_VERSION",
    "NotionEngineError",
    "NotionPage",
    "NotionProjection",
    "NotionProjectionReport",
    "NotionRelation",
    "NotionReviewItem",
    "NotionSyncAction",
    "SyncLedgerEntry",
    "build_notion_projection",
    "make_notion_page",
    "make_notion_relation",
    "make_review_item",
    "notion_page_key",
    "notion_relation_id",
    "relation_set_hash",
    "stable_id",
]
