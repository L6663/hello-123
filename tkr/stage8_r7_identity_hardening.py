"""Stage 8-R7 identity consolidation and query hardening.

The public R7 learning engine consolidates identities across files in the same
book. This patch preserves that capability while preventing generic titles or
shared aliases from merging unrelated characters. It also makes aliases
queryable and rejects ambiguous same-book aliases instead of returning a mixed
profile.

The module follows the package's existing remediation pattern: ``tkr.__init__``
installs the patch once, and no acceptance, publication, release, or freeze
authority is granted by the patch.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence

_GENERIC_IDENTITY_ALIASES = frozenset({
    "师父", "师尊", "师叔", "师伯", "师兄", "师姐", "师弟", "师妹",
    "父亲", "母亲", "兄长", "姐姐", "弟弟", "妹妹", "爷爷", "奶奶",
    "殿下", "陛下", "大人", "公子", "姑娘", "小姐", "少爷", "主人",
    "老祖", "宗主", "门主", "掌门", "长老", "将军", "城主", "阁主",
    "前辈", "先生", "夫人", "道友", "恩人", "仇人", "那人", "此人",
})

_PATCH_MARKER = "_stage8_r7_identity_hardening_applied"


def _identity_alias_key(engine: object, value: object) -> str | None:
    """Return a merge-safe alias key or ``None`` for titles and clauses."""
    name, status = engine._safe_name(value)
    if status != "accepted" or name in _GENERIC_IDENTITY_ALIASES:
        return None
    key = engine._name_key(name)
    return key if len(key) >= 2 else None


def _query_names(engine: object, profile: Mapping[str, object]) -> list[str]:
    values: list[str] = []
    canonical, status = engine._safe_name(profile.get("canonical_name"))
    if status == "accepted":
        values.append(canonical)
    for raw in profile.get("aliases", []):
        alias, alias_status = engine._safe_name(raw)
        if alias_status == "accepted" and alias not in values:
            values.append(alias)
    return sorted(values, key=lambda item: (-len(engine._name_key(item)), item))


def _matched_records(
    engine: object,
    profiles: Sequence[Mapping[str, object]],
    question: str,
) -> list[tuple[dict[str, object], str]]:
    candidates: list[tuple[dict[str, object], str]] = []
    for raw in profiles:
        if raw.get("profile_status") != "accepted":
            continue
        row = dict(raw)
        for name in _query_names(engine, row):
            if name in question:
                candidates.append((row, name))
                break

    # Chinese entity names have no mandatory token boundary. When both 张三 and
    # 张三丰 occur as canonical entities, a query for 张三丰 must not also select
    # 张三 merely because it is a prefix of the longer name.
    result: list[tuple[dict[str, object], str]] = []
    for row, matched_name in candidates:
        matched_key = engine._name_key(matched_name)
        shadowed = any(
            row.get("book_id") == other.get("book_id")
            and row.get("entity_id") != other.get("entity_id")
            and matched_key != engine._name_key(other_name)
            and matched_key in engine._name_key(other_name)
            for other, other_name in candidates
        )
        if not shadowed:
            result.append((row, matched_name))
    return result


def _ambiguous_entity_packet(
    engine: object,
    question: str,
    explicit_scope: Sequence[str],
    groups: Sequence[tuple[str, str, Sequence[tuple[dict[str, object], str]]]],
) -> dict[str, object]:
    return {
        "schema_version": engine.LEARNING_QUERY_SCHEMA_VERSION,
        "status": "refused_ambiguous_entity_scope",
        "answer_type": "entity_scope_required",
        "question": question,
        "book_scope": list(explicit_scope),
        "items": [{
            "book_id": book_id,
            "matched_name": matched_name,
            "available_entities": [
                {
                    "entity_id": str(row.get("entity_id", "")),
                    "canonical_name": str(row.get("canonical_name", "")),
                    "aliases": list(row.get("aliases", [])),
                }
                for row, _ in records
            ],
        } for book_id, matched_name, records in groups],
        "limitations": [
            "the requested name or alias maps to multiple isolated entities",
            "specify a canonical entity name instead of a shared title or alias",
        ],
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_release": False,
        "may_freeze": False,
    }


def apply_stage8_r7_identity_hardening() -> None:
    """Install R7 identity hardening exactly once."""
    from . import learning_engine as engine

    if getattr(engine, _PATCH_MARKER, False):
        return

    original_consolidate = engine._consolidate_learning_entities
    original_query = engine.query_learning_project

    def hardened_consolidate(
        profiles: Sequence[Mapping[str, object]],
        cards: list[dict[str, object]],
        tasks: list[dict[str, object]],
        relationships: Sequence[Mapping[str, object]],
        events: Sequence[Mapping[str, object]],
        storylines: Sequence[Mapping[str, object]],
    ):
        accepted = [dict(row) for row in profiles if row.get("profile_status") == "accepted"]
        canonical_targets: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in accepted:
            key = engine._name_key(str(row.get("canonical_name", "")))
            if key:
                canonical_targets[(str(row.get("book_id", "")), key)].add(
                    str(row.get("source_profile_id", row.get("profile_id", "")))
                )

        originals_by_profile_id = {
            str(row.get("profile_id", "")): dict(row)
            for row in profiles
            if isinstance(row.get("profile_id"), str)
        }
        sanitized: list[dict[str, object]] = []
        for raw in profiles:
            row = dict(raw)
            if row.get("profile_status") == "accepted":
                book_id = str(row.get("book_id", ""))
                canonical_key = engine._name_key(str(row.get("canonical_name", "")))
                merge_aliases: list[str] = []
                for alias in row.get("aliases", []):
                    key = _identity_alias_key(engine, alias)
                    if key is None:
                        continue
                    # An alias may bridge to an exact canonical identity only.
                    # Alias-to-alias collisions are not sufficient evidence.
                    targets = canonical_targets.get((book_id, key), set())
                    if key == canonical_key or targets:
                        merge_aliases.append(str(alias))
                row["aliases"] = merge_aliases
            sanitized.append(row)

        result = original_consolidate(
            sanitized, cards, tasks, relationships, events, storylines
        )
        consolidated = result[0]

        # Restore every source alias for audit/query visibility after merge
        # decisions have been made using only safe evidence.
        for profile in consolidated:
            if profile.get("profile_status") != "accepted":
                continue
            aliases: set[str] = {
                str(item) for item in profile.get("aliases", []) if isinstance(item, str)
            }
            canonical = str(profile.get("canonical_name", ""))
            for source_profile_id in profile.get("source_profile_ids", []):
                source = originals_by_profile_id.get(str(source_profile_id))
                if source is None:
                    continue
                source_name = str(source.get("canonical_name", ""))
                if source_name and source_name != canonical:
                    aliases.add(source_name)
                aliases.update(
                    str(item) for item in source.get("aliases", []) if isinstance(item, str)
                )
            aliases.discard(canonical)
            profile["aliases"] = sorted(aliases)
        return result

    def hardened_query(
        project_directory,
        question: str,
        *,
        max_items: int = 20,
        book_id: str | None = None,
    ) -> dict[str, object]:
        verification = engine.verify_learning_project(project_directory)
        if not verification.valid:
            raise engine.LearningProjectError(
                "learning project failed verification: " + ",".join(verification.reason_codes)
            )
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items <= 0:
            raise engine.LearningProjectError("max_items must be a positive integer")

        root = engine.Path(project_directory)
        catalog = engine._load_object(root / "book-catalog.json", "book catalog")
        books = [dict(row) for row in catalog.get("books", []) if isinstance(row, dict)]
        profiles = engine._load_jsonl(root / "entity-learning-profiles.jsonl", "entity profiles")
        normalized = question.strip()
        matched = _matched_records(engine, profiles, normalized)
        book_by_id = {str(row.get("book_id", "")): row for row in books}
        title_matches = [
            str(row.get("book_id", ""))
            for row in books
            if isinstance(row.get("book_title"), str)
            and str(row["book_title"])
            and str(row["book_title"]) in normalized
        ]
        cross_book_requested = any(
            token in normalized
            for token in ("跨书", "跨作品", "所有书", "全部书", "对比", "比较", "共同")
        )

        explicit_scope: list[str] = []
        if book_id is not None:
            if book_id not in book_by_id:
                raise engine.LearningProjectError("unknown book_id")
            explicit_scope = [book_id]
        elif len(set(title_matches)) == 1:
            explicit_scope = [title_matches[0]]
        elif cross_book_requested:
            explicit_scope = list(book_by_id)
        elif len(books) == 1:
            explicit_scope = [str(books[0].get("book_id", ""))]
        elif matched:
            matched_books = sorted({str(row.get("book_id", "")) for row, _ in matched})
            if len(matched_books) == 1:
                explicit_scope = matched_books

        scope_set = set(explicit_scope)
        scoped_matches = (
            [(row, name) for row, name in matched if row.get("book_id") in scope_set]
            if explicit_scope else matched
        )

        grouped: dict[tuple[str, str], list[tuple[dict[str, object], str]]] = defaultdict(list)
        for row, matched_name in scoped_matches:
            grouped[(str(row.get("book_id", "")), engine._name_key(matched_name))].append(
                (row, matched_name)
            )
        ambiguous_groups: list[tuple[str, str, Sequence[tuple[dict[str, object], str]]]] = []
        for (current_book_id, _), records in grouped.items():
            entity_ids = {str(row.get("entity_id", "")) for row, _ in records}
            if len(entity_ids) > 1:
                ambiguous_groups.append((current_book_id, records[0][1], records))
        if ambiguous_groups:
            return _ambiguous_entity_packet(engine, question, explicit_scope, ambiguous_groups)

        if not explicit_scope and matched:
            matched_books = sorted({str(row.get("book_id", "")) for row, _ in matched})
            if len(matched_books) > 1:
                return {
                    "schema_version": engine.LEARNING_QUERY_SCHEMA_VERSION,
                    "status": "refused_ambiguous_book_scope",
                    "answer_type": "book_scope_required",
                    "question": question,
                    "book_scope": [],
                    "items": [{
                        "matched_name": matched[0][1],
                        "available_books": [
                            book_by_id[item] for item in matched_books if item in book_by_id
                        ],
                    }],
                    "limitations": [
                        "same-name entities from different books are isolated",
                        "specify a book title or --book-id, or explicitly request cross-book comparison",
                    ],
                    "project_acceptance_performed": False,
                    "may_accept_project": False,
                    "may_release": False,
                    "may_freeze": False,
                }

        selected = scoped_matches if explicit_scope else matched
        rewritten = question
        for row, matched_name in selected:
            canonical = str(row.get("canonical_name", ""))
            if canonical and matched_name != canonical:
                rewritten = rewritten.replace(matched_name, canonical)

        inferred_book_id = book_id
        if inferred_book_id is None and len(explicit_scope) == 1:
            inferred_book_id = explicit_scope[0]
        packet = original_query(
            project_directory,
            rewritten,
            max_items=max_items,
            book_id=inferred_book_id,
        )

        if selected and packet.get("answer_type") == "entity_learning":
            selected_ids = {str(row.get("entity_id", "")) for row, _ in selected}
            packet["items"] = [
                item for item in packet.get("items", [])
                if isinstance(item, dict)
                and isinstance(item.get("profile"), dict)
                and str(item["profile"].get("entity_id", "")) in selected_ids
            ][:max_items]
            packet["question"] = question
            if not packet["items"]:
                packet["status"] = "refused_unsupported"
        return packet

    engine._consolidate_learning_entities = hardened_consolidate
    engine.query_learning_project = hardened_query
    setattr(engine, _PATCH_MARKER, True)


__all__ = ["apply_stage8_r7_identity_hardening"]
