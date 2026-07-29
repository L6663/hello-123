"""Stage 8-R7 learning-panorama project.

This layer turns verified Literary sidecars into explicit learning products.  It
never treats model synthesis as source fact.  Direct facts and exact evidence
remain Tier A; co-occurrence, chapter interpretation, motives, causality,
foreshadowing, and world rules are emitted as review tasks until independently
supported and approved.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Iterable, Mapping, Sequence

from .hashing import sha256_file
from .literary_engine import verify_literary_engine
from .project_security import verify_secure_knowledge_project

LEARNING_SYSTEM_VERSION = "tkr-learning-panorama-v2-r7"
LEARNING_REPORT_SCHEMA_VERSION = "tkr-learning-project-report-v1"
LEARNING_MANIFEST_SCHEMA_VERSION = "tkr-learning-project-manifest-v1"
LEARNING_VERIFICATION_SCHEMA_VERSION = "tkr-learning-project-verification-v1"
LEARNING_QUERY_SCHEMA_VERSION = "tkr-learning-query-packet-v1"

_DATASETS = (
    "book-catalog.json",
    "chapter-learning-cards.jsonl",
    "chapter-source-packets.jsonl",
    "entity-learning-profiles.jsonl",
    "relationship-ledger.jsonl",
    "event-ledger.jsonl",
    "storyline-ledger.jsonl",
    "model-learning-tasks.jsonl",
    "model-learning-observations.jsonl",
    "world-model.json",
    "learning-gaps.json",
)
_ALLOWED_FILES = set(_DATASETS) | {"learning-report.json", "artifact-manifest.json"}

_STOP_NAMES = frozenset({
    "我", "我们", "咱们", "你", "你们", "他", "他们", "她", "她们", "它", "它们",
    "其", "此", "这", "那", "谁", "有人", "众人", "人们", "大家", "自己", "对方",
    "则", "和", "与", "及", "并", "且", "或", "而", "在", "于", "从", "向", "往",
})
_BAD_NAME_RE = re.compile(
    r"(?:为何|怎么|什么|可以|不能|不得|能够|已经|随后|然后|因此|于是|仿佛|看来|"
    r"时候|之间|之内|见|听|让|被|所剩|目的|机会|虽然|当众|独自|忽然|缓缓|"
    r"立刻|终于|正在|曾经|随即|默默|再次|一直|仍然)"
)

_CLAUSE_NAME_RE = re.compile(
    r"(?:^|.)(?:在|于|从|向|往|进入|来到|走向|站在|位于|面对|看向|返回|离开).{1,10}$"
)
_BOOK_SUFFIX_RE = re.compile(
    r"(?:[\s_\-]*(?:第?[一二三四五六七八九十百千万零〇两0-9]+(?:卷|部|册|篇)|[上中下](?:卷|部|册|篇)?|"
    r"卷[一二三四五六七八九十百千万零〇两0-9]+|part[\s_\-]*[0-9]+|vol(?:ume)?[\s_\-]*[0-9]+|[0-9]+))$",
    re.IGNORECASE,
)
_COPY_SUFFIX_RE = re.compile(r"[\s_\-]*[（(]\s*\d+\s*[）)]$")

_FACTION_SUFFIXES = ("宗", "门", "宫", "盟", "会", "堂", "阁", "教", "院", "军", "朝", "国", "庭", "司", "家族", "氏族", "商会")
_ABILITY_SUFFIXES = ("功", "法", "术", "诀", "经", "神通", "剑法", "刀法", "心法", "秘术", "境")
_ITEM_SUFFIXES = ("剑", "刀", "枪", "鼎", "镜", "珠", "印", "符", "炉", "盒", "甲", "舟", "令", "钟", "环", "戒", "卷", "图", "碑", "钥")
_SPECIES_SUFFIXES = ("族", "兽", "妖", "魔", "灵", "龙", "凤")

_ALLOWED_OBSERVATION_TYPES = frozenset({
    "explicit_event", "character_state", "relationship", "motivation_candidate",
    "causal_candidate", "world_rule", "foreshadowing_candidate", "chapter_summary",
    "book_mainline_candidate",
})
_ALLOWED_OBSERVATION_TIERS = frozenset({"B", "C"})
_ALLOWED_LEARNED_ENTITY_CATEGORIES = frozenset({
    "character", "place", "faction", "ability", "item", "species", "concept", "unknown",
})
_STRONG_FACTION_SUFFIXES = ("宗", "盟", "会", "教", "军", "朝", "国", "庭", "司", "家族", "氏族", "商会")


class LearningProjectError(ValueError):
    """Raised when a learning panorama is unsafe or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class LearningProjectResult:
    schema_version: str
    status: str
    learning_system_version: str
    output_directory: str
    book_count: int
    literary_project_count: int
    source_count: int
    chapter_card_count: int
    complete_chapter_packet_count: int
    accepted_entity_profile_count: int
    review_entity_profile_count: int
    direct_relationship_count: int
    cooccurrence_candidate_count: int
    direct_event_count: int
    storyline_count: int
    model_learning_task_count: int
    model_learning_observation_count: int
    exact_assertion_count: int
    exact_evidence_anchor_count: int
    logical_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LearningProjectVerification:
    schema_version: str
    status: str
    valid: bool
    reason_codes: tuple[str, ...]
    checked_file_count: int
    logical_sha256: str
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    may_release: bool = False
    may_freeze: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _jsonl_bytes(rows: Iterable[Mapping[str, object]]) -> bytes:
    values = [_canonical(dict(row)) for row in rows]
    return (("\n".join(values) + "\n") if values else "").encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _load_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise LearningProjectError(f"{label} is not a safe regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LearningProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise LearningProjectError(f"{label} must be a JSON object")
    return value


def _load_jsonl(path: Path, label: str) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise LearningProjectError(f"{label} is not a safe regular file")
    result: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LearningProjectError(f"invalid {label} line {line_number}: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise LearningProjectError(f"{label} line {line_number} must be an object")
        result.append(value)
    return result


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\0".join(_canonical(part) for part in parts)
    return prefix + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _safe_name(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        return "", "review_only"
    name = value.strip()
    if not (2 <= len(name) <= 24):
        return name, "review_only"
    if name in _STOP_NAMES or any(
        name.startswith(item)
        for item in ("在", "于", "从", "向", "往", "则", "和", "与", "我", "我们", "咱们", "你", "你们", "他", "他们", "她", "她们", "它", "它们")
    ):
        return name, "review_only"
    if _BAD_NAME_RE.search(name) or _CLAUSE_NAME_RE.search(name) or re.search(r"[，。！？!?；;：:\s]", name):
        return name, "review_only"
    return name, "accepted"


def _clean_book_title(value: str) -> str:
    title = Path(value).stem.strip()
    previous = None
    while previous != title:
        previous = title
        title = _COPY_SUFFIX_RE.sub("", title).strip(" _-")
        candidate = _BOOK_SUFFIX_RE.sub("", title).strip(" _-")
        if candidate:
            title = candidate
    return title or Path(value).stem.strip() or value.strip() or "Untitled"


def _book_identity(
    *,
    explicit_id: str | None,
    explicit_title: str | None,
    source_filename: str | None,
    project_id: str,
) -> tuple[str, str]:
    title = (explicit_title or "").strip()
    if not title:
        title = _clean_book_title(source_filename or project_id)
    identifier = (explicit_id or "").strip()
    if not identifier:
        identifier = _stable_id("book_", title)
    if not re.fullmatch(r"[A-Za-z0-9._:\-\u3400-\u9fff]{3,160}", identifier):
        raise LearningProjectError("book_id contains unsupported characters")
    return identifier, title


def _name_key(value: str) -> str:
    return re.sub(r"[\s·•・_\-]", "", value).casefold()


def _learning_category(name: str, entity_type: str) -> str:
    if name.endswith(_STRONG_FACTION_SUFFIXES):
        return "faction"
    if name.endswith(_ITEM_SUFFIXES):
        return "item"
    if any(name.endswith(item) for item in ("城", "山", "谷", "海", "岛", "洲", "域", "界", "殿", "塔", "港", "关", "河", "湖", "井", "岸", "码头")):
        return "place"
    normalized_type = entity_type.strip().lower()
    if normalized_type in {"person", "character", "human", "人物", "角色"}:
        return "character"
    if normalized_type in {"place", "location", "地点", "地名"}:
        return "place"
    if normalized_type in {"faction", "organization", "organisation", "势力", "组织"}:
        return "faction"
    if normalized_type in {"ability", "skill", "technique", "能力", "功法"}:
        return "ability"
    if normalized_type in {"item", "artifact", "object", "器物", "物品"}:
        return "item"
    if normalized_type in {"species", "race", "种族", "物种"}:
        return "species"
    if name.endswith(_FACTION_SUFFIXES):
        return "faction"
    if name.endswith(_ABILITY_SUFFIXES):
        return "ability"
    if name.endswith(_SPECIES_SUFFIXES) and len(name) <= 8:
        return "species"
    if any(name.endswith(item) for item in ("宫", "门")):
        return "place"
    return "unknown"


def _refine_learning_category(profile: Mapping[str, object]) -> str:
    category = str(profile.get("learning_category", "unknown"))
    if category != "unknown":
        return category
    subject_counts = dict(profile.get("subject_predicate_counts", {}))
    object_counts = dict(profile.get("object_predicate_counts", {}))
    if int(object_counts.get("located_in", 0)) > 0:
        return "place"
    agent_predicates = {"defeats", "permission", "alias", "count", "date"}
    if any(int(subject_counts.get(item, 0)) > 0 for item in agent_predicates) or any(
        int(object_counts.get(item, 0)) > 0 for item in {"defeats", "alias", "permission"}
    ):
        return "character"
    name = str(profile.get("canonical_name", ""))
    if re.fullmatch(r"[\u3400-\u9fff]{2,4}", name):
        return "character"
    return "unknown"


def _consolidate_learning_entities(
    profiles: Sequence[Mapping[str, object]],
    cards: list[dict[str, object]],
    tasks: list[dict[str, object]],
    relationships: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    storylines: Sequence[Mapping[str, object]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[tuple[str, str], str],
]:
    """Consolidate same-book identities while preserving cross-book isolation."""
    accepted = [dict(row) for row in profiles if row.get("profile_status") == "accepted"]
    review = [dict(row) for row in profiles if row.get("profile_status") != "accepted"]
    parent = list(range(len(accepted)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    tokens_by_book: dict[tuple[str, str], int] = {}
    for index, row in enumerate(accepted):
        book_id = str(row.get("book_id", ""))
        names = [str(row.get("canonical_name", "")), *[str(item) for item in row.get("aliases", []) if isinstance(item, str)]]
        for name in names:
            key = _name_key(name)
            if not key:
                continue
            token = (book_id, key)
            if token in tokens_by_book:
                union(index, tokens_by_book[token])
            else:
                tokens_by_book[token] = index

    groups: dict[int, list[dict[str, object]]] = defaultdict(list)
    for index, row in enumerate(accepted):
        groups[find(index)].append(row)

    global_order_by_chapter = {
        str(row.get("chapter_id")): int(row.get("global_source_order", 10**12))
        for row in cards
        if isinstance(row.get("chapter_id"), str)
    }
    entity_mapping: dict[tuple[str, str], str] = {}
    consolidated: list[dict[str, object]] = []
    for members in groups.values():
        members.sort(key=lambda row: (str(row.get("literary_project_id", "")), str(row.get("source_entity_id", ""))))
        book_id = str(members[0].get("book_id", ""))
        book_title = str(members[0].get("book_title", ""))
        name_scores: Counter[str] = Counter()
        aliases: set[str] = set()
        for row in members:
            canonical_name = str(row.get("canonical_name", ""))
            name_scores[canonical_name] += max(1, int(row.get("mention_count", 0)))
            aliases.update(str(item) for item in row.get("aliases", []) if isinstance(item, str))
        canonical_name = min(
            (name for name in name_scores if name),
            key=lambda name: (-name_scores[name], len(name), name),
        )
        aliases.update(name_scores)
        aliases.discard(canonical_name)
        source_entity_ids = sorted({str(row.get("source_entity_id", row.get("entity_id", ""))) for row in members})
        literary_project_ids = sorted({str(row.get("literary_project_id", "")) for row in members})
        source_ids = sorted({str(row.get("source_id", "")) for row in members})
        learning_entity_id = _stable_id("lent_", book_id, canonical_name, sorted(_name_key(item) for item in aliases))
        chapter_ids = sorted(
            {str(item) for row in members for item in row.get("chapter_ids", []) if isinstance(item, str)},
            key=lambda item: (global_order_by_chapter.get(item, 10**12), item),
        )
        mention_anchor_ids = sorted({str(item) for row in members for item in row.get("mention_anchor_ids", []) if isinstance(item, str)})
        subject_assertion_ids = sorted({str(item) for row in members for item in row.get("subject_assertion_ids", []) if isinstance(item, str)})
        object_assertion_ids = sorted({str(item) for row in members for item in row.get("object_assertion_ids", []) if isinstance(item, str)})
        subject_counts: Counter[str] = Counter()
        object_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        for row in members:
            subject_counts.update({str(key): int(value) for key, value in dict(row.get("subject_predicate_counts", {})).items()})
            object_counts.update({str(key): int(value) for key, value in dict(row.get("object_predicate_counts", {})).items()})
            type_counts[str(row.get("entity_type", "unknown"))] += max(1, int(row.get("mention_count", 0)))
            source_entity_id = str(row.get("source_entity_id", row.get("entity_id", "")))
            entity_mapping[(str(row.get("literary_project_id", "")), source_entity_id)] = learning_entity_id
        entity_type = min(type_counts, key=lambda value: (-type_counts[value], value)) if type_counts else "unknown"
        consolidated_profile = {
            "schema_version": "tkr-entity-learning-profile-v2",
            "profile_id": _stable_id("lep_", book_id, learning_entity_id),
            "book_id": book_id,
            "book_title": book_title,
            "literary_project_ids": literary_project_ids,
            "source_ids": source_ids,
            "entity_id": learning_entity_id,
            "source_entity_ids": source_entity_ids,
            "source_profile_ids": [str(row.get("profile_id", "")) for row in members],
            "canonical_name": canonical_name,
            "aliases": sorted(aliases),
            "entity_type": entity_type,
            "learning_category": _learning_category(canonical_name, entity_type),
            "profile_status": "accepted",
            "first_chapter_id": chapter_ids[0] if chapter_ids else None,
            "last_chapter_id": chapter_ids[-1] if chapter_ids else None,
            "chapter_ids": chapter_ids,
            "mention_anchor_ids": mention_anchor_ids,
            "mention_count": sum(int(row.get("mention_count", 0)) for row in members),
            "subject_assertion_ids": subject_assertion_ids,
            "object_assertion_ids": object_assertion_ids,
            "subject_predicate_counts": dict(sorted(subject_counts.items())),
            "object_predicate_counts": dict(sorted(object_counts.items())),
            "related_entity_ids": [],
            "consolidated_profile_count": len(members),
            "limitations": [],
        }
        consolidated_profile["learning_category"] = _refine_learning_category(consolidated_profile)
        consolidated.append(consolidated_profile)

    for row in review:
        source_entity_id = str(row.get("source_entity_id", row.get("entity_id", "")))
        review_id = _stable_id("lrev_", row.get("book_id"), row.get("literary_project_id"), source_entity_id)
        row["entity_id"] = review_id
        row["source_entity_ids"] = [source_entity_id]
        row["literary_project_ids"] = [str(row.get("literary_project_id", ""))]
        row["source_ids"] = [str(row.get("source_id", ""))]
        row["consolidated_profile_count"] = 1
        consolidated.append(row)

    def remap(project_id: object, entity_id: object) -> str | None:
        if not isinstance(entity_id, str):
            return None
        return entity_mapping.get((str(project_id), entity_id))

    for card in cards:
        card["entity_ids"] = sorted({
            mapped for item in card.get("entity_ids", [])
            if (mapped := remap(card.get("literary_project_id"), item)) is not None
        })
    for task in tasks:
        task["known_entity_ids"] = sorted({
            mapped for item in task.get("known_entity_ids", [])
            if (mapped := remap(task.get("literary_project_id"), item)) is not None
        })

    remapped_relationships: list[dict[str, object]] = []
    for raw in relationships:
        row = dict(raw)
        project_id = row.get("literary_project_id")
        subject_id = remap(project_id, row.get("subject_entity_id"))
        object_id = remap(project_id, row.get("object_entity_id"))
        if subject_id is None or object_id is None or subject_id == object_id:
            continue
        row["subject_entity_id"] = subject_id
        row["object_entity_id"] = object_id
        row["relationship_id"] = _stable_id(
            "lrl_" if row.get("tier") == "A" else "lrc_",
            row.get("book_id"), subject_id, row.get("predicate"), object_id,
            row.get("chapter_ids"), row.get("assertion_ids"),
        )
        remapped_relationships.append(row)

    relation_groups: dict[tuple[object, ...], dict[str, object]] = {}
    for row in remapped_relationships:
        key = (
            row.get("book_id"), row.get("subject_entity_id"), row.get("predicate"),
            row.get("object_entity_id"), row.get("tier"), row.get("status"),
        )
        if key not in relation_groups:
            relation_groups[key] = dict(row)
            continue
        target = relation_groups[key]
        for field in ("chapter_ids", "assertion_ids", "evidence_anchor_ids", "limitations"):
            target[field] = sorted({str(item) for item in target.get(field, []) + row.get(field, []) if isinstance(item, str)})
        target["literary_project_ids"] = sorted({
            str(item) for item in [target.get("literary_project_id"), row.get("literary_project_id"), *target.get("literary_project_ids", [])]
            if item
        })
    remapped_relationships = list(relation_groups.values())

    remapped_events: list[dict[str, object]] = []
    for raw in events:
        row = dict(raw)
        project_id = row.get("literary_project_id")
        actors = [mapped for item in row.get("actor_entity_ids", []) if (mapped := remap(project_id, item)) is not None]
        targets = [mapped for item in row.get("target_entity_ids", []) if (mapped := remap(project_id, item)) is not None]
        if not actors or not targets:
            continue
        row["actor_entity_ids"] = sorted(set(actors))
        row["target_entity_ids"] = sorted(set(targets))
        row["event_id"] = _stable_id("lev_", row.get("book_id"), row.get("event_type"), row["actor_entity_ids"], row["target_entity_ids"], row.get("assertion_ids"))
        remapped_events.append(row)

    storyline_groups: dict[tuple[str, str], dict[str, object]] = {}
    for raw in storylines:
        project_id = raw.get("literary_project_id")
        entity_id = remap(project_id, raw.get("entity_id"))
        if entity_id is None:
            continue
        key = (str(raw.get("book_id", "")), entity_id)
        target = storyline_groups.setdefault(key, {
            "schema_version": "tkr-learning-storyline-v2",
            "storyline_id": _stable_id("lst_", key[0], entity_id),
            "book_id": key[0],
            "book_title": str(raw.get("book_title", "")),
            "literary_project_ids": [],
            "source_ids": [],
            "entity_id": entity_id,
            "canonical_name": "",
            "chapter_ids": [],
            "direct_facts": [],
            "direct_event_ids": [],
            "chronology_status": "source_ordered_consolidated_knowledge",
            "limitations": [
                "absence_of_a_fact_does_not_mean_the_event_did_not_happen",
                "motives_and_causal_links_require_model_learning_tasks_or_reviewed_annotations",
            ],
        })
        target["literary_project_ids"].append(str(project_id))
        target["source_ids"].append(str(raw.get("source_id", "")))
        target["chapter_ids"].extend(str(item) for item in raw.get("chapter_ids", []) if isinstance(item, str))
        target["direct_facts"].extend(dict(item) for item in raw.get("direct_facts", []) if isinstance(item, dict))
        target["direct_event_ids"].extend(str(item) for item in raw.get("direct_event_ids", []) if isinstance(item, str))
    profile_by_entity = {str(row.get("entity_id")): row for row in consolidated if row.get("profile_status") == "accepted"}
    consolidated_storylines: list[dict[str, object]] = []
    for (_, entity_id), row in storyline_groups.items():
        profile = profile_by_entity[entity_id]
        row["canonical_name"] = profile["canonical_name"]
        row["literary_project_ids"] = sorted(set(row["literary_project_ids"]))
        row["source_ids"] = sorted(set(row["source_ids"]))
        row["chapter_ids"] = sorted(set(row["chapter_ids"]), key=lambda item: (global_order_by_chapter.get(item, 10**12), item))
        fact_by_id = {str(item.get("assertion_id", "")): item for item in row["direct_facts"]}
        row["direct_facts"] = sorted(
            fact_by_id.values(),
            key=lambda item: (
                min((global_order_by_chapter.get(chapter_id, 10**12) for chapter_id in item.get("chapter_ids", [])), default=10**12),
                str(item.get("assertion_id", "")),
            ),
        )
        row["direct_event_ids"] = sorted(set(row["direct_event_ids"]))
        consolidated_storylines.append(row)

    related: dict[str, set[str]] = defaultdict(set)
    for row in remapped_relationships:
        subject = str(row.get("subject_entity_id", ""))
        object_id = str(row.get("object_entity_id", ""))
        if subject and object_id:
            related[subject].add(object_id)
            related[object_id].add(subject)
    for row in consolidated:
        if row.get("profile_status") == "accepted":
            row["related_entity_ids"] = sorted(related.get(str(row.get("entity_id")), set()))

    return consolidated, remapped_relationships, remapped_events, consolidated_storylines, entity_mapping


def _anchor_chapter_map(anchors: Sequence[Mapping[str, object]]) -> dict[str, str]:
    return {
        str(row.get("anchor_id")): str(row.get("chapter_id"))
        for row in anchors
        if isinstance(row.get("anchor_id"), str) and isinstance(row.get("chapter_id"), str)
    }


def _chapter_order(chapters: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return {
        str(row.get("chapter_id")): int(row.get("source_order", index))
        for index, row in enumerate(chapters)
        if isinstance(row.get("chapter_id"), str)
    }


def _literary_inputs(path: Path) -> dict[str, object]:
    verification = verify_literary_engine(path)
    if not verification.valid:
        raise LearningProjectError(
            "literary project failed verification: " + ",".join(verification.reason_codes)
        )
    report = _load_object(path / "literary-report.json", "literary report")
    return {
        "root": path,
        "report": report,
        "manifest_sha256": sha256_file(path / "artifact-manifest.json"),
        "chapters": _load_jsonl(path / "chapters.jsonl", "chapters"),
        "anchors": _load_jsonl(path / "evidence-anchors.jsonl", "evidence anchors"),
        "entities": _load_jsonl(path / "entities.jsonl", "entities"),
        "assertions": _load_jsonl(path / "assertions.jsonl", "assertions"),
        "relationships": _load_jsonl(path / "relationships.jsonl", "relationships"),
        "events": _load_jsonl(path / "events.jsonl", "events"),
    }



def _source_inputs(path: Path) -> dict[str, object]:
    verification = verify_secure_knowledge_project(path)
    if not verification.valid:
        raise LearningProjectError(
            "source project failed verification: " + ",".join(verification.reason_codes)
        )
    report = _load_object(path / "project-report.json", "source project report")
    source_path = path / "source" / "normalized-source.txt"
    if source_path.is_symlink() or not source_path.is_file():
        raise LearningProjectError("normalized source is not a safe regular file")
    try:
        # Preserve CRLF/LF exactly: chapter offsets and normalized-source hashes
        # are bound to stored UTF-8 bytes, not universal-newline text.
        with source_path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as exc:
        raise LearningProjectError(f"normalized source cannot be read strictly: {exc}") from exc
    normalized_sha = str(report.get("normalized_source_sha256", ""))
    if sha256(text.encode("utf-8")).hexdigest() != normalized_sha:
        raise LearningProjectError("normalized source hash differs from verified project report")
    return {
        "root": path,
        "report": report,
        "text": text,
        "manifest_sha256": sha256_file(path / "project-manifest.json"),
    }

def _logical_hash(payloads: Mapping[str, bytes], bindings: Sequence[Mapping[str, object]]) -> str:
    digest = sha256()
    digest.update(LEARNING_SYSTEM_VERSION.encode("utf-8"))
    digest.update(b"\0")
    digest.update(_canonical(list(bindings)).encode("utf-8"))
    digest.update(b"\0")
    for name in sorted(payloads):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(payloads[name]).digest())
    return digest.hexdigest()


def build_learning_project(
    literary_projects: Sequence[str | Path],
    output_directory: str | Path,
    *,
    source_projects: Sequence[str | Path] = (),
    book_ids: Sequence[str] = (),
    book_titles: Sequence[str] = (),
    observation_file: str | Path | None = None,
    replace_existing: bool = False,
    max_task_evidence: int = 12,
) -> LearningProjectResult:
    """Build an explicit learning panorama from verified Literary projects."""
    if not literary_projects:
        raise LearningProjectError("at least one literary project is required")
    if isinstance(max_task_evidence, bool) or not isinstance(max_task_evidence, int) or max_task_evidence <= 0:
        raise LearningProjectError("max_task_evidence must be a positive integer")
    inputs = [_literary_inputs(Path(item)) for item in literary_projects]
    source_inputs = [_source_inputs(Path(item)) for item in source_projects]
    if book_ids and len(book_ids) != len(inputs):
        raise LearningProjectError("book_ids must be omitted or match literary project count")
    if book_titles and len(book_titles) != len(inputs):
        raise LearningProjectError("book_titles must be omitted or match literary project count")
    source_by_id: dict[str, dict[str, object]] = {}
    for bundle in source_inputs:
        source_id = str(bundle["report"].get("source_id", ""))
        if not source_id or source_id in source_by_id:
            raise LearningProjectError("source projects must have unique non-empty source identities")
        source_by_id[source_id] = bundle

    book_by_project: dict[str, dict[str, object]] = {}
    book_catalog_map: dict[str, dict[str, object]] = {}
    for index, bundle in enumerate(inputs):
        report = bundle["report"]
        project_id = str(report.get("project_id", ""))
        source_id = str(report.get("source_id", ""))
        source_bundle = source_by_id.get(source_id)
        source_filename = None
        if source_bundle is not None:
            source_filename = str(source_bundle["report"].get("source_filename", "")) or None
        book_id, book_title = _book_identity(
            explicit_id=book_ids[index] if book_ids else None,
            explicit_title=book_titles[index] if book_titles else None,
            source_filename=source_filename,
            project_id=project_id,
        )
        context = {
            "book_id": book_id,
            "book_title": book_title,
            "literary_input_order": index,
        }
        book_by_project[project_id] = context
        catalog = book_catalog_map.setdefault(book_id, {
            "book_id": book_id,
            "book_title": book_title,
            "literary_project_ids": [],
            "source_ids": [],
            "source_filenames": [],
            "chapter_count": 0,
        })
        if catalog["book_title"] != book_title:
            raise LearningProjectError("one book_id cannot have conflicting book titles")
        catalog["literary_project_ids"].append(project_id)
        catalog["source_ids"].append(source_id)
        if source_filename:
            catalog["source_filenames"].append(source_filename)

    chapter_cards: list[dict[str, object]] = []
    source_packets: list[dict[str, object]] = []
    profiles: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    storylines: list[dict[str, object]] = []
    tasks: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    gap_codes: Counter[str] = Counter()
    world_entities: dict[str, list[dict[str, object]]] = defaultdict(list)
    bindings: list[dict[str, object]] = []
    exact_assertion_count = exact_anchor_count = 0
    source_ids: set[str] = set()

    for bundle in inputs:
        report = bundle["report"]
        chapters = bundle["chapters"]
        anchors = bundle["anchors"]
        entities = bundle["entities"]
        assertions = bundle["assertions"]
        source_id = str(report.get("source_id", ""))
        project_id = str(report.get("project_id", ""))
        book_context = book_by_project[project_id]
        book_id = str(book_context["book_id"])
        book_title = str(book_context["book_title"])
        literary_input_order = int(book_context["literary_input_order"])
        source_ids.add(source_id)
        source_bundle = source_by_id.get(source_id)
        source_binding: dict[str, object] | None = None
        if source_bundle is not None:
            source_report = source_bundle["report"]
            if str(source_report.get("normalized_source_sha256", "")) != str(report.get("source_sha256", "")):
                raise LearningProjectError("source project normalized hash does not match Literary source binding")
            source_binding = {
                "source_project_id": str(source_report.get("project_id", "")),
                "source_project_manifest_sha256": source_bundle["manifest_sha256"],
                "raw_source_sha256": str(source_report.get("raw_source_sha256", "")),
                "normalized_source_sha256": str(source_report.get("normalized_source_sha256", "")),
                "selected_encoding": str(source_report.get("selected_encoding", "")),
            }
        bindings.append({
            "literary_project_id": project_id,
            "book_id": book_id,
            "book_title": book_title,
            "literary_input_order": literary_input_order,
            "source_id": source_id,
            "source_sha256": str(report.get("source_sha256", "")),
            "literary_manifest_sha256": bundle["manifest_sha256"],
            "literary_logical_sha256": str(report.get("logical_sha256", "")),
            "source_project_binding": source_binding,
        })
        exact_assertion_count += len(assertions)
        exact_anchor_count += len(anchors)

        anchor_by_id = {str(row.get("anchor_id")): row for row in anchors if isinstance(row.get("anchor_id"), str)}
        anchor_to_chapter = _anchor_chapter_map(anchors)
        narrative_chapters = [row for row in chapters if str(row.get("unit_type", "")) == "chapter"]
        narrative_chapter_ids = {
            str(row.get("chapter_id"))
            for row in narrative_chapters
            if isinstance(row.get("chapter_id"), str)
        }
        book_catalog_map[book_id]["chapter_count"] = int(book_catalog_map[book_id]["chapter_count"]) + len(narrative_chapters)
        chapter_by_id = {str(row.get("chapter_id")): row for row in narrative_chapters if isinstance(row.get("chapter_id"), str)}
        order = _chapter_order(narrative_chapters)
        entity_by_id = {str(row.get("entity_id")): row for row in entities if isinstance(row.get("entity_id"), str)}

        assertions_by_chapter: dict[str, list[dict[str, object]]] = defaultdict(list)
        entities_by_chapter: dict[str, set[str]] = defaultdict(set)
        for assertion in assertions:
            chapter_ids = {
                anchor_to_chapter.get(str(anchor_id), "")
                for anchor_id in assertion.get("evidence_anchor_ids", [])
                if isinstance(anchor_id, str)
            } - {""}
            for chapter_id in chapter_ids & narrative_chapter_ids:
                assertions_by_chapter[chapter_id].append(assertion)
            for key in ("subject_entity_id", "object_entity_id"):
                value = assertion.get(key)
                if isinstance(value, str):
                    for chapter_id in chapter_ids & narrative_chapter_ids:
                        entities_by_chapter[chapter_id].add(value)

        for entity in entities:
            entity_id = str(entity.get("entity_id", ""))
            for anchor_id in entity.get("mention_anchor_ids", []):
                chapter_id = anchor_to_chapter.get(str(anchor_id))
                if chapter_id and chapter_id in narrative_chapter_ids:
                    entities_by_chapter[chapter_id].add(entity_id)

        for chapter in sorted(narrative_chapters, key=lambda row: (int(row.get("source_order", 0)), str(row.get("chapter_id", "")))):
            chapter_id = str(chapter.get("chapter_id", ""))
            direct = sorted(assertions_by_chapter.get(chapter_id, []), key=lambda row: str(row.get("assertion_id", "")))
            entity_ids = sorted(entities_by_chapter.get(chapter_id, set()))
            anchor_ids = sorted({
                str(anchor_id)
                for assertion in direct
                for anchor_id in assertion.get("evidence_anchor_ids", [])
                if isinstance(anchor_id, str)
            })
            predicates = dict(sorted(Counter(str(row.get("predicate", "")) for row in direct).items()))
            card_id = _stable_id("lcc_", project_id, chapter_id, anchor_ids, entity_ids)
            source_packet_id: str | None = None
            if source_bundle is not None:
                start = int(chapter.get("start_char", -1))
                end = int(chapter.get("end_char", -1))
                source_text = str(source_bundle["text"])
                if not 0 <= start < end <= len(source_text):
                    raise LearningProjectError(f"chapter span is outside bound normalized source: {chapter_id}")
                chapter_text = source_text[start:end]
                content_sha = sha256(chapter_text.encode("utf-8")).hexdigest()
                if content_sha != str(chapter.get("content_sha256", "")):
                    raise LearningProjectError(f"chapter content hash differs from Literary binding: {chapter_id}")
                source_packet_id = _stable_id("lsp_", project_id, chapter_id, content_sha)
                source_packets.append({
                    "schema_version": "tkr-chapter-source-packet-v1",
                    "source_packet_id": source_packet_id,
                "book_id": book_id,
                "book_title": book_title,
                    "literary_project_id": project_id,
                    "source_id": source_id,
                    "source_sha256": str(chapter.get("source_sha256", "")),
                    "chapter_id": chapter_id,
                    "start_char": start,
                    "end_char": end,
                    "content_sha256": content_sha,
                    "chapter_text": chapter_text,
                    "complete_chapter": True,
                    "private_local_artifact": True,
                    "may_upload_to_public_ci": False,
                })
            else:
                gap_codes["COMPLETE_CHAPTER_SOURCE_NOT_BOUND"] += 1
            chapter_cards.append({
                "schema_version": "tkr-chapter-learning-card-v1",
                "card_id": card_id,
                "book_id": book_id,
                "book_title": book_title,
                "literary_project_id": project_id,
                "source_id": source_id,
                "chapter_id": chapter_id,
                "source_order": int(chapter.get("source_order", 0)),
                "global_source_order": literary_input_order * 1_000_000_000 + int(chapter.get("source_order", 0)),
                "unit_type": "chapter",
                "volume_ordinal": chapter.get("volume_ordinal"),
                "chapter_ordinal": chapter.get("chapter_ordinal"),
                "original_heading": str(chapter.get("original_heading", "")),
                "title": str(chapter.get("title", "")),
                "entity_ids": entity_ids,
                "assertion_ids": [str(row.get("assertion_id", "")) for row in direct],
                "evidence_anchor_ids": anchor_ids,
                "predicate_counts": predicates,
                "learned_item_count": len(direct),
                "knowledge_status": "direct_facts_available" if direct else "structure_only_model_read_required",
                "source_packet_id": source_packet_id,
                "complete_chapter_available": source_packet_id is not None,
            })
            evidence_packets = []
            for anchor_id in anchor_ids[:max_task_evidence]:
                anchor = anchor_by_id.get(anchor_id, {})
                evidence_packets.append({
                    "anchor_id": anchor_id,
                    "evidence_text": str(anchor.get("evidence_text", ""))[:600],
                    "evidence_start": anchor.get("evidence_start"),
                    "evidence_end": anchor.get("evidence_end"),
                })
            tasks.append({
                "schema_version": "tkr-model-learning-task-v1",
                "task_id": _stable_id("lmt_", card_id, anchor_ids),
                "task_type": "chapter_deep_learning",
                "book_id": book_id,
                "book_title": book_title,
                "literary_project_id": project_id,
                "source_id": source_id,
                "chapter_id": chapter_id,
                "source_order": int(chapter.get("source_order", 0)),
                "global_source_order": literary_input_order * 1_000_000_000 + int(chapter.get("source_order", 0)),
                "chapter_heading": str(chapter.get("original_heading", "")) or str(chapter.get("title", "")),
                "known_entity_ids": entity_ids,
                "known_assertion_ids": [str(row.get("assertion_id", "")) for row in direct],
                "evidence_packets": evidence_packets,
                "source_packet_id": source_packet_id,
                "complete_chapter_available": source_packet_id is not None,
                "allowed_output_types": [
                    "explicit_event", "character_state", "relationship", "motivation_candidate",
                    "causal_candidate", "world_rule", "foreshadowing_candidate", "chapter_summary",
                ],
                "instruction": (
                    "Read the complete chapter source packet when available before writing learning observations. "
                    "Keep explicit facts separate from synthesis and interpretation; cite exact anchors; "
                    "do not import knowledge from other books or the web; do not publish unsupported motives or causes."
                ),
                "may_publish_directly": False,
                "requires_evidence_validation": True,
            })
            if not direct:
                gap_codes["CHAPTER_HAS_NO_TYPED_FACTS"] += 1

        accepted_profile_ids: set[str] = set()
        for entity in entities:
            entity_id = str(entity.get("entity_id", ""))
            name, profile_status = _safe_name(entity.get("canonical_name"))
            mention_anchor_ids = sorted(str(item) for item in entity.get("mention_anchor_ids", []) if isinstance(item, str))
            chapter_ids = sorted(
                {
                    anchor_to_chapter[item]
                    for item in mention_anchor_ids
                    if item in anchor_to_chapter and anchor_to_chapter[item] in narrative_chapter_ids
                },
                key=lambda item: (order.get(item, 10**12), item),
            )
            subject_assertions = [row for row in assertions if row.get("subject_entity_id") == entity_id]
            object_assertions = [row for row in assertions if row.get("object_entity_id") == entity_id]
            related_ids = sorted({
                str(row.get(key))
                for row in (*subject_assertions, *object_assertions)
                for key in ("subject_entity_id", "object_entity_id")
                if isinstance(row.get(key), str) and row.get(key) != entity_id
            })
            profile_id = _stable_id("lep_", project_id, entity_id, name)
            row = {
                "schema_version": "tkr-entity-learning-profile-v1",
                "profile_id": profile_id,
                "book_id": book_id,
                "book_title": book_title,
                "literary_project_id": project_id,
                "source_id": source_id,
                "entity_id": entity_id,
                "source_entity_id": entity_id,
                "canonical_name": name,
                "aliases": list(entity.get("aliases", [])),
                "entity_type": str(entity.get("entity_type", "unknown")),
                "learning_category": _learning_category(name, str(entity.get("entity_type", "unknown"))),
                "profile_status": profile_status,
                "first_chapter_id": chapter_ids[0] if chapter_ids else None,
                "last_chapter_id": chapter_ids[-1] if chapter_ids else None,
                "chapter_ids": chapter_ids,
                "mention_anchor_ids": mention_anchor_ids,
                "mention_count": len(mention_anchor_ids),
                "subject_assertion_ids": [str(item.get("assertion_id", "")) for item in subject_assertions],
                "object_assertion_ids": [str(item.get("assertion_id", "")) for item in object_assertions],
                "subject_predicate_counts": dict(sorted(Counter(str(item.get("predicate", "")) for item in subject_assertions).items())),
                "object_predicate_counts": dict(sorted(Counter(str(item.get("predicate", "")) for item in object_assertions).items())),
                "related_entity_ids": related_ids,
                "limitations": [] if profile_status == "accepted" else ["name_is_pronoun_function_word_or_clause_like"],
            }
            profiles.append(row)
            if profile_status == "accepted":
                accepted_profile_ids.add(entity_id)
                world_entities[str(entity.get("entity_type", "unknown"))].append({
                    "entity_id": entity_id,
                    "canonical_name": name,
                    "mention_count": len(mention_anchor_ids),
                })
            else:
                gap_codes["ENTITY_PROFILE_REQUIRES_NAME_REVIEW"] += 1

        direct_event_by_entity: dict[str, list[dict[str, object]]] = defaultdict(list)
        direct_relation_count = 0
        for assertion in assertions:
            if assertion.get("tier") != "A" or assertion.get("status") not in {"active", "contested"}:
                continue
            subject_id = assertion.get("subject_entity_id")
            object_id = assertion.get("object_entity_id")
            predicate = str(assertion.get("predicate", ""))
            evidence_ids = [str(item) for item in assertion.get("evidence_anchor_ids", []) if isinstance(item, str)]
            chapter_ids = sorted({anchor_to_chapter.get(item, "") for item in evidence_ids} - {""}, key=lambda item: (order.get(item, 10**12), item))
            if isinstance(subject_id, str) and isinstance(object_id, str) and subject_id in accepted_profile_ids and object_id in accepted_profile_ids:
                relation_id = _stable_id("lrl_", project_id, assertion.get("assertion_id"), subject_id, predicate, object_id)
                relationships.append({
                    "schema_version": "tkr-learning-relationship-v1",
                    "relationship_id": relation_id,
                    "book_id": book_id,
                    "book_title": book_title,
                    "literary_project_id": project_id,
                    "source_id": source_id,
                    "subject_entity_id": subject_id,
                    "predicate": predicate,
                    "object_entity_id": object_id,
                    "tier": "A",
                    "status": str(assertion.get("status")),
                    "chapter_ids": chapter_ids,
                    "assertion_ids": [str(assertion.get("assertion_id", ""))],
                    "evidence_anchor_ids": evidence_ids,
                    "limitations": [],
                })
                direct_relation_count += 1
            if predicate == "defeats" and isinstance(subject_id, str) and isinstance(object_id, str):
                event_id = _stable_id("lev_", project_id, assertion.get("assertion_id"))
                event = {
                    "schema_version": "tkr-learning-event-v1",
                    "event_id": event_id,
                    "book_id": book_id,
                    "book_title": book_title,
                    "literary_project_id": project_id,
                    "source_id": source_id,
                    "event_type": "defeat",
                    "actor_entity_ids": [subject_id],
                    "target_entity_ids": [object_id],
                    "chapter_ids": chapter_ids,
                    "assertion_ids": [str(assertion.get("assertion_id", ""))],
                    "evidence_anchor_ids": evidence_ids,
                    "tier": "A",
                    "status": str(assertion.get("status")),
                    "causal_status": "cause_not_inferred",
                }
                events.append(event)
                direct_event_by_entity[subject_id].append(event)
                direct_event_by_entity[object_id].append(event)

        cooccurrence_count = 0
        pair_chapters: dict[tuple[str, str], list[str]] = defaultdict(list)
        for chapter_id, ids in entities_by_chapter.items():
            accepted = sorted(item for item in ids if item in accepted_profile_ids)
            if len(accepted) > 12:
                accepted = accepted[:12]
            for left_index, left in enumerate(accepted):
                for right in accepted[left_index + 1:]:
                    pair_chapters[(left, right)].append(chapter_id)
        for (left, right), chapter_ids in sorted(pair_chapters.items()):
            unique_chapters = sorted(set(chapter_ids), key=lambda item: (order.get(item, 10**12), item))
            if len(unique_chapters) < 2:
                continue
            relationships.append({
                "schema_version": "tkr-learning-relationship-v1",
                "relationship_id": _stable_id("lrc_", project_id, left, right, unique_chapters),
                "book_id": book_id,
                "book_title": book_title,
                "literary_project_id": project_id,
                "source_id": source_id,
                "subject_entity_id": left,
                "predicate": "co_occurs",
                "object_entity_id": right,
                "tier": "candidate",
                "status": "review_only",
                "chapter_ids": unique_chapters,
                "assertion_ids": [],
                "evidence_anchor_ids": [],
                "limitations": ["co_occurrence_does_not_establish_a_relationship"],
            })
            cooccurrence_count += 1

        profile_by_id = {str(row["entity_id"]): row for row in profiles if row["literary_project_id"] == project_id}
        for entity_id in sorted(accepted_profile_ids):
            profile = profile_by_id[entity_id]
            chapter_ids = list(profile["chapter_ids"])
            assertions_for_entity = [
                row for row in assertions
                if row.get("subject_entity_id") == entity_id or row.get("object_entity_id") == entity_id
            ]
            facts = []
            for assertion in assertions_for_entity:
                evidence_ids = [str(item) for item in assertion.get("evidence_anchor_ids", []) if isinstance(item, str)]
                assertion_chapters = sorted({anchor_to_chapter.get(item, "") for item in evidence_ids} - {""}, key=lambda item: (order.get(item, 10**12), item))
                facts.append({
                    "assertion_id": str(assertion.get("assertion_id", "")),
                    "chapter_ids": assertion_chapters,
                    "predicate": str(assertion.get("predicate", "")),
                    "subject_text": str(assertion.get("subject_text", "")),
                    "object_text": str(assertion.get("object_text", "")),
                    "value": assertion.get("value"),
                    "polarity": bool(assertion.get("polarity", True)),
                    "evidence_anchor_ids": evidence_ids,
                    "status": str(assertion.get("status", "")),
                })
            facts.sort(key=lambda row: (min((order.get(item, 10**12) for item in row["chapter_ids"]), default=10**12), row["assertion_id"]))
            storylines.append({
                "schema_version": "tkr-learning-storyline-v1",
                "storyline_id": _stable_id("lst_", project_id, entity_id, chapter_ids),
                "book_id": book_id,
                "book_title": book_title,
                "literary_project_id": project_id,
                "source_id": source_id,
                "entity_id": entity_id,
                "canonical_name": profile["canonical_name"],
                "chapter_ids": chapter_ids,
                "direct_facts": facts,
                "direct_event_ids": [str(item["event_id"]) for item in direct_event_by_entity.get(entity_id, [])],
                "chronology_status": "source_ordered_direct_knowledge",
                "limitations": [
                    "absence_of_a_fact_does_not_mean_the_event_did_not_happen",
                    "motives_and_causal_links_require_model_learning_tasks_or_reviewed_annotations",
                ],
            })

    profiles, relationships, events, storylines, entity_mapping = _consolidate_learning_entities(
        profiles, chapter_cards, tasks, relationships, events, storylines
    )
    world_entities = defaultdict(list)
    for profile in profiles:
        if profile.get("profile_status") != "accepted":
            continue
        world_entities[str(profile.get("learning_category", "unknown"))].append({
            "book_id": str(profile.get("book_id", "")),
            "entity_id": str(profile.get("entity_id", "")),
            "canonical_name": str(profile.get("canonical_name", "")),
            "mention_count": int(profile.get("mention_count", 0)),
        })

    task_by_id = {str(row["task_id"]): row for row in tasks}
    packet_by_id = {str(row["source_packet_id"]): row for row in source_packets}
    accepted_entity_ids = {str(row["entity_id"]) for row in profiles if row.get("profile_status") == "accepted"}
    if observation_file is not None:
        observation_rows = _load_jsonl(Path(observation_file), "model learning observations")
        seen_observation_ids: set[str] = set()
        for index, raw in enumerate(observation_rows, 1):
            task_id = raw.get("task_id")
            if not isinstance(task_id, str) or task_id not in task_by_id:
                raise LearningProjectError(f"observation line {index} references an unknown task")
            task = task_by_id[task_id]
            observation_type = raw.get("observation_type")
            if observation_type not in _ALLOWED_OBSERVATION_TYPES:
                raise LearningProjectError(f"observation line {index} has unsupported observation_type")
            if observation_type not in task.get("allowed_output_types", []) and observation_type != "book_mainline_candidate":
                raise LearningProjectError(f"observation line {index} type is not allowed by its task")
            tier = raw.get("epistemic_tier")
            if tier not in _ALLOWED_OBSERVATION_TIERS:
                raise LearningProjectError(f"observation line {index} must remain in epistemic tier B or C")
            statement = raw.get("statement")
            if not isinstance(statement, str) or not statement.strip() or len(statement.strip()) > 4000:
                raise LearningProjectError(f"observation line {index} has an invalid statement")
            if raw.get("status", "proposed") != "proposed" or raw.get("may_publish_directly", False) is not False:
                raise LearningProjectError(f"observation line {index} claims illegal publication authority")
            chapter_id = str(task.get("chapter_id", ""))
            source_packet_id = task.get("source_packet_id")
            evidence_spans = raw.get("evidence_spans", [])
            evidence_anchor_ids = raw.get("evidence_anchor_ids", [])
            if not isinstance(evidence_spans, list) or not isinstance(evidence_anchor_ids, list):
                raise LearningProjectError(f"observation line {index} evidence fields must be arrays")
            normalized_spans: list[dict[str, object]] = []
            if evidence_spans:
                if not isinstance(source_packet_id, str) or source_packet_id not in packet_by_id:
                    raise LearningProjectError(f"observation line {index} requires a complete chapter source packet")
                packet = packet_by_id[source_packet_id]
                packet_start = int(packet["start_char"])
                packet_end = int(packet["end_char"])
                packet_text = str(packet["chapter_text"])
                for span_index, span in enumerate(evidence_spans, 1):
                    if not isinstance(span, dict):
                        raise LearningProjectError(f"observation line {index} evidence span {span_index} is not an object")
                    start = span.get("start_char")
                    end = span.get("end_char")
                    text = span.get("evidence_text")
                    if isinstance(start, bool) or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int) or not isinstance(text, str):
                        raise LearningProjectError(f"observation line {index} evidence span {span_index} is malformed")
                    if not packet_start <= start < end <= packet_end:
                        raise LearningProjectError(f"observation line {index} evidence span {span_index} is outside its chapter")
                    exact = packet_text[start - packet_start:end - packet_start]
                    if exact != text:
                        raise LearningProjectError(f"observation line {index} evidence span {span_index} is not exact source text")
                    normalized_spans.append({
                        "start_char": start,
                        "end_char": end,
                        "evidence_text": text,
                        "evidence_sha256": sha256(text.encode("utf-8")).hexdigest(),
                    })
            allowed_anchor_ids = {str(row.get("anchor_id")) for row in task.get("evidence_packets", []) if isinstance(row, dict)}
            normalized_anchor_ids = sorted({str(item) for item in evidence_anchor_ids if isinstance(item, str)})
            if any(item not in allowed_anchor_ids for item in normalized_anchor_ids):
                raise LearningProjectError(f"observation line {index} cites an anchor outside its task")
            if not normalized_spans and not normalized_anchor_ids:
                raise LearningProjectError(f"observation line {index} has no exact evidence")
            entity_ids = sorted({str(item) for item in raw.get("entity_ids", []) if isinstance(item, str)})
            if any(item not in accepted_entity_ids for item in entity_ids):
                raise LearningProjectError(f"observation line {index} references an unaccepted entity")
            learned_entities_raw = raw.get("learned_entities", [])
            if not isinstance(learned_entities_raw, list):
                raise LearningProjectError(f"observation line {index} learned_entities must be an array")
            learned_entities: list[dict[str, object]] = []
            for learned_index, learned in enumerate(learned_entities_raw, 1):
                if not isinstance(learned, dict):
                    raise LearningProjectError(f"observation line {index} learned entity {learned_index} is not an object")
                name, name_status = _safe_name(learned.get("name"))
                category = learned.get("category", "unknown")
                if name_status != "accepted" or category not in _ALLOWED_LEARNED_ENTITY_CATEGORIES:
                    raise LearningProjectError(f"observation line {index} learned entity {learned_index} is invalid")
                aliases = sorted({
                    alias_name
                    for item in learned.get("aliases", [])
                    if isinstance(item, str)
                    for alias_name, alias_status in [_safe_name(item)]
                    if alias_status == "accepted" and alias_name != name
                })
                learned_entities.append({
                    "learning_entity_candidate_id": _stable_id(
                        "lmec_", task.get("book_id"), name, category, aliases
                    ),
                    "name": name,
                    "category": category,
                    "aliases": aliases,
                    "status": "proposed",
                    "may_publish_directly": False,
                })
            normalized = {
                "schema_version": "tkr-model-learning-observation-v1",
                "task_id": task_id,
                "book_id": str(task.get("book_id", "")),
                "book_title": str(task.get("book_title", "")),
                "literary_project_id": str(task.get("literary_project_id", "")),
                "source_id": str(task.get("source_id", "")),
                "chapter_id": chapter_id,
                "source_packet_id": source_packet_id,
                "observation_type": observation_type,
                "epistemic_tier": tier,
                "statement": statement.strip(),
                "entity_ids": entity_ids,
                "learned_entities": learned_entities,
                "evidence_spans": normalized_spans,
                "evidence_anchor_ids": normalized_anchor_ids,
                "status": "proposed",
                "model_generated": True,
                "may_publish_directly": False,
                "requires_evidence_validation": True,
                "requires_human_or_independent_review": True,
            }
            observation_id = _stable_id(
                "lmo_", task_id, observation_type, tier, statement.strip(), normalized_spans, normalized_anchor_ids, entity_ids
            )
            if observation_id in seen_observation_ids:
                raise LearningProjectError(f"observation line {index} duplicates a previous observation")
            seen_observation_ids.add(observation_id)
            normalized["observation_id"] = observation_id
            observations.append(normalized)

    observations_by_chapter: dict[str, list[dict[str, object]]] = defaultdict(list)
    observations_by_entity: dict[str, list[dict[str, object]]] = defaultdict(list)
    for observation in observations:
        observations_by_chapter[str(observation["chapter_id"])].append(observation)
        for entity_id in observation["entity_ids"]:
            observations_by_entity[str(entity_id)].append(observation)
    for card in chapter_cards:
        chapter_observations = observations_by_chapter.get(str(card["chapter_id"]), [])
        card["model_observation_ids"] = [str(row["observation_id"]) for row in chapter_observations]
        card["model_observation_type_counts"] = dict(sorted(Counter(str(row["observation_type"]) for row in chapter_observations).items()))
    for storyline in storylines:
        entity_observations = observations_by_entity.get(str(storyline["entity_id"]), [])
        storyline["model_observation_ids"] = [str(row["observation_id"]) for row in entity_observations]
        storyline["model_observation_type_counts"] = dict(sorted(Counter(str(row["observation_type"]) for row in entity_observations).items()))

    book_catalog = {
        "schema_version": "tkr-learning-book-catalog-v1",
        "books": sorted(
            (
                {
                    **row,
                    "literary_project_ids": sorted(set(str(item) for item in row["literary_project_ids"])),
                    "source_ids": sorted(set(str(item) for item in row["source_ids"])),
                    "source_filenames": sorted(set(str(item) for item in row["source_filenames"])),
                }
                for row in book_catalog_map.values()
            ),
            key=lambda row: (str(row["book_title"]), str(row["book_id"])),
        ),
        "cross_book_mixing_allowed_by_default": False,
    }
    entity_name_by_id = {
        str(row.get("entity_id")): str(row.get("canonical_name", ""))
        for row in profiles
        if row.get("profile_status") == "accepted"
    }
    world_books: dict[str, dict[str, object]] = {}
    observation_dimensions = (
        "world_rule", "book_mainline_candidate", "foreshadowing_candidate", "explicit_event",
        "character_state", "relationship", "motivation_candidate", "causal_candidate", "chapter_summary",
    )
    for book in book_catalog["books"]:
        book_id = str(book["book_id"])
        book_profiles = [row for row in profiles if row.get("book_id") == book_id and row.get("profile_status") == "accepted"]
        book_relationships = [row for row in relationships if row.get("book_id") == book_id]
        book_events = [row for row in events if row.get("book_id") == book_id]
        book_observations = [row for row in observations if row.get("book_id") == book_id]
        groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for profile in book_profiles:
            groups[str(profile.get("learning_category", "unknown"))].append({
                "entity_id": str(profile.get("entity_id", "")),
                "canonical_name": str(profile.get("canonical_name", "")),
                "aliases": list(profile.get("aliases", [])),
                "mention_count": int(profile.get("mention_count", 0)),
                "chapter_count": len(profile.get("chapter_ids", [])),
            })
        observation_groups = {
            dimension: [
                {
                    "observation_id": str(row.get("observation_id", "")),
                    "chapter_id": str(row.get("chapter_id", "")),
                    "statement": str(row.get("statement", "")),
                    "entity_ids": list(row.get("entity_ids", [])),
                    "epistemic_tier": str(row.get("epistemic_tier", "")),
                    "evidence_spans": list(row.get("evidence_spans", [])),
                    "evidence_anchor_ids": list(row.get("evidence_anchor_ids", [])),
                }
                for row in book_observations
                if row.get("observation_type") == dimension
            ]
            for dimension in observation_dimensions
        }
        learned_entity_candidates: dict[tuple[str, str], dict[str, object]] = {}
        for observation in book_observations:
            for learned in observation.get("learned_entities", []):
                if not isinstance(learned, dict):
                    continue
                key = (str(learned.get("category", "unknown")), _name_key(str(learned.get("name", ""))))
                if not key[1]:
                    continue
                target = learned_entity_candidates.setdefault(key, {
                    "learning_entity_candidate_id": str(learned.get("learning_entity_candidate_id", "")),
                    "name": str(learned.get("name", "")),
                    "category": str(learned.get("category", "unknown")),
                    "aliases": [],
                    "observation_ids": [],
                    "chapter_ids": [],
                    "status": "proposed",
                    "may_publish_directly": False,
                })
                target["aliases"] = sorted(set(target["aliases"]) | {str(item) for item in learned.get("aliases", []) if isinstance(item, str)})
                target["observation_ids"] = sorted(set(target["observation_ids"]) | {str(observation.get("observation_id", ""))})
                target["chapter_ids"] = sorted(set(target["chapter_ids"]) | {str(observation.get("chapter_id", ""))})
        world_books[book_id] = {
            "book_id": book_id,
            "book_title": str(book["book_title"]),
            "entity_groups": {
                key: sorted(value, key=lambda row: (-int(row["mention_count"]), str(row["canonical_name"])))
                for key, value in sorted(groups.items())
            },
            "direct_relationships": [
                {
                    **row,
                    "subject_name": entity_name_by_id.get(str(row.get("subject_entity_id", "")), ""),
                    "object_name": entity_name_by_id.get(str(row.get("object_entity_id", "")), ""),
                }
                for row in book_relationships
                if row.get("tier") == "A"
            ],
            "direct_events": book_events,
            "learning_observations": observation_groups,
            "observed_entity_candidates": {
                category: sorted(
                    [row for (row_category, _), row in learned_entity_candidates.items() if row_category == category],
                    key=lambda row: str(row["name"]),
                )
                for category in sorted({row_category for row_category, _ in learned_entity_candidates})
            },
            "predicate_counts": dict(sorted(Counter(str(row.get("predicate", "")) for row in book_relationships if row.get("tier") == "A").items())),
            "model_observation_type_counts": dict(sorted(Counter(str(row.get("observation_type", "")) for row in book_observations).items())),
        }
    world_model = {
        "schema_version": "tkr-learning-world-model-v2",
        "learning_system_version": LEARNING_SYSTEM_VERSION,
        "book_count": len(book_catalog["books"]),
        "books": world_books,
        "entity_groups": {
            key: sorted(value, key=lambda row: (str(row.get("book_id", "")), -int(row["mention_count"]), str(row["canonical_name"])))
            for key, value in sorted(world_entities.items())
        },
        "predicate_counts": dict(sorted(Counter(str(row.get("predicate", "")) for row in relationships if row.get("tier") == "A").items())),
        "model_observation_type_counts": dict(sorted(Counter(str(row.get("observation_type", "")) for row in observations).items())),
        "limitations": [
            "entity types may remain unknown when the verified source does not classify them",
            "world rules are evidence-bound model observations and remain reviewable B/C knowledge",
            "cross-book views require explicit scope or comparison intent",
        ],
    }
    learning_gaps = {
        "schema_version": "tkr-learning-gaps-v1",
        "gap_counts": dict(sorted(gap_codes.items())),
        "open_learning_dimensions": [
            "chapter_summary", "major_event_chain", "character_motivation", "causal_link",
            "relationship_state", "world_rule", "foreshadowing_and_resolution", "book_mainline",
        ],
        "recommended_action": "execute_model_learning_tasks_with_exact_evidence_then_build_reviewed_event_character_reasoning_annotations",
    }

    chapter_cards.sort(key=lambda row: (str(row["book_id"]), int(row["global_source_order"]), str(row["card_id"])))
    source_packets.sort(key=lambda row: (str(row["book_id"]), str(row["chapter_id"]), str(row["source_packet_id"])))
    profiles.sort(key=lambda row: (str(row.get("book_id", "")), str(row["canonical_name"]), str(row["entity_id"])))
    relationships.sort(key=lambda row: (str(row.get("book_id", "")), str(row["tier"]), str(row["relationship_id"])))
    events.sort(key=lambda row: (str(row.get("book_id", "")), str(row["event_id"])))
    storylines.sort(key=lambda row: (str(row.get("book_id", "")), str(row["canonical_name"]), str(row["storyline_id"])))
    tasks.sort(key=lambda row: (str(row["book_id"]), int(row.get("global_source_order", 0)), str(row["chapter_id"]), str(row["task_id"])))
    task_order = {str(row["task_id"]): int(row.get("global_source_order", 0)) for row in tasks}
    observations.sort(key=lambda row: (str(row.get("book_id", "")), task_order.get(str(row["task_id"]), 10**12), str(row["chapter_id"]), str(row["observation_id"])))

    payloads = {
        "book-catalog.json": _json_bytes(book_catalog),
        "chapter-learning-cards.jsonl": _jsonl_bytes(chapter_cards),
        "chapter-source-packets.jsonl": _jsonl_bytes(source_packets),
        "entity-learning-profiles.jsonl": _jsonl_bytes(profiles),
        "relationship-ledger.jsonl": _jsonl_bytes(relationships),
        "event-ledger.jsonl": _jsonl_bytes(events),
        "storyline-ledger.jsonl": _jsonl_bytes(storylines),
        "model-learning-tasks.jsonl": _jsonl_bytes(tasks),
        "model-learning-observations.jsonl": _jsonl_bytes(observations),
        "world-model.json": _json_bytes(world_model),
        "learning-gaps.json": _json_bytes(learning_gaps),
    }
    logical = _logical_hash(payloads, bindings)
    accepted_profiles = sum(row["profile_status"] == "accepted" for row in profiles)
    review_profiles = len(profiles) - accepted_profiles
    result = LearningProjectResult(
        LEARNING_REPORT_SCHEMA_VERSION,
        "completed",
        LEARNING_SYSTEM_VERSION,
        str(output_directory),
        len(book_catalog["books"]),
        len(inputs),
        len(source_ids),
        len(chapter_cards),
        len(source_packets),
        accepted_profiles,
        review_profiles,
        sum(row["tier"] == "A" for row in relationships),
        sum(row["tier"] == "candidate" for row in relationships),
        len(events),
        len(storylines),
        len(tasks),
        len(observations),
        exact_assertion_count,
        exact_anchor_count,
        logical,
    )

    output = Path(output_directory)
    if output.is_symlink():
        raise LearningProjectError("output path must not be a symbolic link")
    if output.exists() and not replace_existing:
        raise LearningProjectError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for name, data in payloads.items():
            _write_atomic(temporary / name, data)
        report_payload = {
            **result.to_dict(),
            "literary_bindings": bindings,
            "corpus_cross_contamination_allowed": False,
            "web_knowledge_may_fill_source_gaps": False,
            "model_tasks_may_publish_directly": False,
            "model_observations_may_publish_directly": False,
            "chapter_source_packets_are_private_local_artifacts": True,
            "chapter_source_packets_may_upload_to_public_ci": False,
        }
        _write_atomic(temporary / "learning-report.json", _json_bytes(report_payload))
        files = []
        for path in sorted(temporary.iterdir()):
            if path.is_file():
                files.append({"path": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
        manifest = {
            "schema_version": LEARNING_MANIFEST_SCHEMA_VERSION,
            "learning_system_version": LEARNING_SYSTEM_VERSION,
            "logical_sha256": logical,
            "literary_bindings": bindings,
            "files": files,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        _write_atomic(temporary / "artifact-manifest.json", _json_bytes(manifest))
        verification = verify_learning_project(
            temporary,
            literary_projects,
            source_projects,
            book_ids=book_ids,
            book_titles=book_titles,
        )
        if not verification.valid:
            raise LearningProjectError("new learning project failed verification: " + ",".join(verification.reason_codes))
        if output.exists():
            backup = output.with_name(f".{output.name}.backup")
            if backup.exists():
                shutil.rmtree(backup)
            output.replace(backup)
            temporary.replace(output)
            shutil.rmtree(backup, ignore_errors=True)
        else:
            temporary.replace(output)
        return result
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        return None
    return value


def verify_learning_project(
    project_directory: str | Path,
    literary_projects: Sequence[str | Path] = (),
    source_projects: Sequence[str | Path] = (),
    *,
    book_ids: Sequence[str] = (),
    book_titles: Sequence[str] = (),
) -> LearningProjectVerification:
    root = Path(project_directory)
    reasons: list[str] = []
    checked = 0
    logical = ""
    try:
        if root.is_symlink() or not root.is_dir():
            raise LearningProjectError("learning project root is unsafe")
        actual = {item.name for item in root.iterdir() if item.is_file() and not item.is_symlink()}
        if actual != _ALLOWED_FILES:
            reasons.append("LEARNING_PROJECT_FILE_SET_MISMATCH")
        manifest = _load_object(root / "artifact-manifest.json", "learning manifest")
        report = _load_object(root / "learning-report.json", "learning report")
        logical = str(manifest.get("logical_sha256", ""))
        if manifest.get("schema_version") != LEARNING_MANIFEST_SCHEMA_VERSION:
            reasons.append("LEARNING_MANIFEST_SCHEMA_MISMATCH")
        if report.get("schema_version") != LEARNING_REPORT_SCHEMA_VERSION:
            reasons.append("LEARNING_REPORT_SCHEMA_MISMATCH")
        if manifest.get("learning_system_version") != LEARNING_SYSTEM_VERSION or report.get("learning_system_version") != LEARNING_SYSTEM_VERSION:
            reasons.append("LEARNING_SYSTEM_VERSION_MISMATCH")
        for payload in (manifest, report):
            if any(payload.get(key) for key in ("project_acceptance_performed", "may_accept_project", "may_release", "may_freeze")):
                reasons.append("ILLEGAL_LEARNING_AUTHORITY")
        declared: set[str] = set()
        for entry in manifest.get("files", []):
            if not isinstance(entry, dict):
                reasons.append("LEARNING_MANIFEST_RECORD_INVALID")
                continue
            relative = _safe_relative(entry.get("path"))
            if relative is None or relative in declared:
                reasons.append("LEARNING_MANIFEST_PATH_INVALID")
                continue
            declared.add(relative)
            path = root / relative
            if not path.is_file() or path.is_symlink():
                reasons.append("LEARNING_DECLARED_FILE_MISSING")
                continue
            checked += 1
            if entry.get("size_bytes") != path.stat().st_size:
                reasons.append("LEARNING_FILE_SIZE_MISMATCH")
            if entry.get("sha256") != sha256_file(path):
                reasons.append("LEARNING_FILE_HASH_MISMATCH")
        if declared | {"artifact-manifest.json"} != actual:
            reasons.append("LEARNING_MANIFEST_MEMBERSHIP_MISMATCH")
        payloads = {name: (root / name).read_bytes() for name in _DATASETS}
        bindings = report.get("literary_bindings")
        if not isinstance(bindings, list):
            bindings = []
            reasons.append("LEARNING_BINDINGS_INVALID")
        expected_logical = _logical_hash(payloads, bindings)
        if expected_logical != logical or report.get("logical_sha256") != expected_logical:
            reasons.append("LEARNING_LOGICAL_HASH_MISMATCH")

        rows = {
            name: _load_jsonl(root / name, name)
            for name in _DATASETS
            if name.endswith(".jsonl")
        }
        count_checks = {
            "book_count": len(_load_object(root / "book-catalog.json", "book catalog").get("books", [])),
            "chapter_card_count": len(rows["chapter-learning-cards.jsonl"]),
            "complete_chapter_packet_count": len(rows["chapter-source-packets.jsonl"]),
            "accepted_entity_profile_count": sum(row.get("profile_status") == "accepted" for row in rows["entity-learning-profiles.jsonl"]),
            "review_entity_profile_count": sum(row.get("profile_status") != "accepted" for row in rows["entity-learning-profiles.jsonl"]),
            "direct_relationship_count": sum(row.get("tier") == "A" for row in rows["relationship-ledger.jsonl"]),
            "cooccurrence_candidate_count": sum(row.get("tier") == "candidate" for row in rows["relationship-ledger.jsonl"]),
            "direct_event_count": len(rows["event-ledger.jsonl"]),
            "storyline_count": len(rows["storyline-ledger.jsonl"]),
            "model_learning_task_count": len(rows["model-learning-tasks.jsonl"]),
            "model_learning_observation_count": len(rows["model-learning-observations.jsonl"]),
        }
        for key, value in count_checks.items():
            if report.get(key) != value:
                reasons.append(f"LEARNING_REPORT_COUNT_MISMATCH:{key}")
        if any(row.get("may_publish_directly") is not False or row.get("requires_evidence_validation") is not True for row in rows["model-learning-tasks.jsonl"]):
            reasons.append("MODEL_LEARNING_TASK_AUTHORITY_INVALID")
        packet_ids: set[str] = set()
        for packet in rows["chapter-source-packets.jsonl"]:
            packet_id = packet.get("source_packet_id")
            text = packet.get("chapter_text")
            if not isinstance(packet_id, str) or packet_id in packet_ids or not isinstance(text, str):
                reasons.append("CHAPTER_SOURCE_PACKET_INVALID")
                continue
            packet_ids.add(packet_id)
            if packet.get("complete_chapter") is not True or packet.get("private_local_artifact") is not True or packet.get("may_upload_to_public_ci") is not False:
                reasons.append("CHAPTER_SOURCE_PACKET_AUTHORITY_INVALID")
            if packet.get("content_sha256") != sha256(text.encode("utf-8")).hexdigest():
                reasons.append("CHAPTER_SOURCE_PACKET_HASH_MISMATCH")
        for task in rows["model-learning-tasks.jsonl"]:
            source_packet_id = task.get("source_packet_id")
            if task.get("complete_chapter_available") is True and source_packet_id not in packet_ids:
                reasons.append("MODEL_TASK_SOURCE_PACKET_MISSING")

        observation_ids: set[str] = set()
        task_ids = {str(row.get("task_id")) for row in rows["model-learning-tasks.jsonl"]}
        for observation in rows["model-learning-observations.jsonl"]:
            observation_id = observation.get("observation_id")
            if not isinstance(observation_id, str) or observation_id in observation_ids:
                reasons.append("MODEL_LEARNING_OBSERVATION_ID_INVALID")
                continue
            observation_ids.add(observation_id)
            if observation.get("task_id") not in task_ids:
                reasons.append("MODEL_LEARNING_OBSERVATION_TASK_MISSING")
            if observation.get("observation_type") not in _ALLOWED_OBSERVATION_TYPES or observation.get("epistemic_tier") not in _ALLOWED_OBSERVATION_TIERS:
                reasons.append("MODEL_LEARNING_OBSERVATION_TYPE_INVALID")
            if observation.get("status") != "proposed" or observation.get("model_generated") is not True or observation.get("may_publish_directly") is not False or observation.get("requires_human_or_independent_review") is not True:
                reasons.append("MODEL_LEARNING_OBSERVATION_AUTHORITY_INVALID")
            learned_entities = observation.get("learned_entities", [])
            if not isinstance(learned_entities, list):
                reasons.append("MODEL_LEARNING_OBSERVATION_ENTITY_CANDIDATES_INVALID")
            else:
                for learned in learned_entities:
                    if not isinstance(learned, dict):
                        reasons.append("MODEL_LEARNING_OBSERVATION_ENTITY_CANDIDATES_INVALID")
                        continue
                    name, name_status = _safe_name(learned.get("name"))
                    if (
                        name_status != "accepted"
                        or learned.get("category") not in _ALLOWED_LEARNED_ENTITY_CATEGORIES
                        or learned.get("status") != "proposed"
                        or learned.get("may_publish_directly") is not False
                        or not isinstance(learned.get("learning_entity_candidate_id"), str)
                    ):
                        reasons.append("MODEL_LEARNING_OBSERVATION_ENTITY_CANDIDATES_INVALID")
            spans = observation.get("evidence_spans")
            anchors = observation.get("evidence_anchor_ids")
            if not isinstance(spans, list) or not isinstance(anchors, list) or (not spans and not anchors):
                reasons.append("MODEL_LEARNING_OBSERVATION_EVIDENCE_MISSING")
            source_packet_id = observation.get("source_packet_id")
            if spans:
                packet = next((row for row in rows["chapter-source-packets.jsonl"] if row.get("source_packet_id") == source_packet_id), None)
                if packet is None:
                    reasons.append("MODEL_LEARNING_OBSERVATION_PACKET_MISSING")
                    continue
                packet_text = str(packet.get("chapter_text", ""))
                packet_start = int(packet.get("start_char", -1))
                packet_end = int(packet.get("end_char", -1))
                for span in spans:
                    if not isinstance(span, dict):
                        reasons.append("MODEL_LEARNING_OBSERVATION_SPAN_INVALID")
                        continue
                    start = span.get("start_char")
                    end = span.get("end_char")
                    text = span.get("evidence_text")
                    if isinstance(start, bool) or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int) or not isinstance(text, str) or not packet_start <= start < end <= packet_end:
                        reasons.append("MODEL_LEARNING_OBSERVATION_SPAN_INVALID")
                        continue
                    if packet_text[start - packet_start:end - packet_start] != text or span.get("evidence_sha256") != sha256(text.encode("utf-8")).hexdigest():
                        reasons.append("MODEL_LEARNING_OBSERVATION_SPAN_HASH_MISMATCH")

        if literary_projects or source_projects:
            verified_sources: dict[str, dict[str, object]] = {}
            for item in source_projects:
                source_bundle = _source_inputs(Path(item))
                source_report = source_bundle["report"]
                source_id = str(source_report.get("source_id", ""))
                if not source_id or source_id in verified_sources:
                    reasons.append("LEARNING_SOURCE_BINDING_DUPLICATE")
                    continue
                verified_sources[source_id] = source_bundle
            expected = []
            if book_ids and len(book_ids) != len(literary_projects):
                reasons.append("LEARNING_BOOK_ID_COUNT_MISMATCH")
            if book_titles and len(book_titles) != len(literary_projects):
                reasons.append("LEARNING_BOOK_TITLE_COUNT_MISMATCH")
            for index, item in enumerate(literary_projects):
                bundle = _literary_inputs(Path(item))
                item_report = bundle["report"]
                source_id = str(item_report.get("source_id", ""))
                source_bundle = verified_sources.get(source_id)
                source_binding = None
                source_filename = None
                if source_bundle is not None:
                    source_report = source_bundle["report"]
                    source_filename = str(source_report.get("source_filename", "")) or None
                    source_binding = {
                        "source_project_id": str(source_report.get("project_id", "")),
                        "source_project_manifest_sha256": source_bundle["manifest_sha256"],
                        "raw_source_sha256": str(source_report.get("raw_source_sha256", "")),
                        "normalized_source_sha256": str(source_report.get("normalized_source_sha256", "")),
                        "selected_encoding": str(source_report.get("selected_encoding", "")),
                    }
                project_id = str(item_report.get("project_id", ""))
                book_id, book_title = _book_identity(
                    explicit_id=book_ids[index] if book_ids and index < len(book_ids) else None,
                    explicit_title=book_titles[index] if book_titles and index < len(book_titles) else None,
                    source_filename=source_filename,
                    project_id=project_id,
                )
                expected.append({
                    "literary_project_id": project_id,
                    "book_id": book_id,
                    "book_title": book_title,
                    "literary_input_order": index,
                    "source_id": source_id,
                    "source_sha256": str(item_report.get("source_sha256", "")),
                    "literary_manifest_sha256": bundle["manifest_sha256"],
                    "literary_logical_sha256": str(item_report.get("logical_sha256", "")),
                    "source_project_binding": source_binding,
                })
            if expected != bindings:
                reasons.append("LEARNING_LITERARY_BINDING_MISMATCH")
    except Exception as exc:
        reasons.extend(("LEARNING_VERIFICATION_EXCEPTION", type(exc).__name__))
    unique = tuple(dict.fromkeys(reasons))
    return LearningProjectVerification(
        LEARNING_VERIFICATION_SCHEMA_VERSION,
        "verified" if not unique else "rejected",
        not unique,
        unique if unique else (
            "LEARNING_FILE_HASH_CHAIN_VERIFIED",
            "LEARNING_LITERARY_BINDINGS_VERIFIED",
            "LEARNING_TASK_AUTHORITY_BOUNDARY_VERIFIED",
        ),
        checked,
        logical,
    )


def _observation_view(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "observation_id": str(row.get("observation_id", "")),
        "book_id": str(row.get("book_id", "")),
        "book_title": str(row.get("book_title", "")),
        "chapter_id": str(row.get("chapter_id", "")),
        "observation_type": str(row.get("observation_type", "")),
        "epistemic_tier": str(row.get("epistemic_tier", "")),
        "statement": str(row.get("statement", "")),
        "entity_ids": list(row.get("entity_ids", [])),
        "evidence_spans": list(row.get("evidence_spans", [])),
        "evidence_anchor_ids": list(row.get("evidence_anchor_ids", [])),
        "status": str(row.get("status", "")),
    }


def query_learning_project(
    project_directory: str | Path,
    question: str,
    *,
    max_items: int = 20,
    book_id: str | None = None,
) -> dict[str, object]:
    verification = verify_learning_project(project_directory)
    if not verification.valid:
        raise LearningProjectError("learning project failed verification: " + ",".join(verification.reason_codes))
    if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items <= 0:
        raise LearningProjectError("max_items must be a positive integer")
    root = Path(project_directory)
    report = _load_object(root / "learning-report.json", "learning report")
    catalog = _load_object(root / "book-catalog.json", "book catalog")
    books = [dict(row) for row in catalog.get("books", []) if isinstance(row, dict)]
    profiles = _load_jsonl(root / "entity-learning-profiles.jsonl", "entity profiles")
    storylines = _load_jsonl(root / "storyline-ledger.jsonl", "storylines")
    cards = _load_jsonl(root / "chapter-learning-cards.jsonl", "chapter cards")
    relationships = _load_jsonl(root / "relationship-ledger.jsonl", "relationships")
    events = _load_jsonl(root / "event-ledger.jsonl", "events")
    observations = _load_jsonl(root / "model-learning-observations.jsonl", "model observations")
    world = _load_object(root / "world-model.json", "world model")
    normalized = question.strip()
    cross_book_requested = any(token in normalized for token in ("跨书", "跨作品", "所有书", "全部书", "对比", "比较", "共同"))

    book_by_id = {str(row.get("book_id", "")): row for row in books}
    title_matches = [
        str(row.get("book_id", ""))
        for row in books
        if isinstance(row.get("book_title"), str) and str(row["book_title"]) and str(row["book_title"]) in normalized
    ]
    explicit_scope: list[str] = []
    if book_id is not None:
        if book_id not in book_by_id:
            raise LearningProjectError("unknown book_id")
        explicit_scope = [book_id]
    elif len(set(title_matches)) == 1:
        explicit_scope = [title_matches[0]]
    elif cross_book_requested:
        explicit_scope = list(book_by_id)
    elif len(books) == 1:
        explicit_scope = [str(books[0].get("book_id", ""))]

    matched_profiles_all = [
        row for row in profiles
        if row.get("profile_status") == "accepted"
        and isinstance(row.get("canonical_name"), str)
        and str(row["canonical_name"]) in normalized
    ]
    if not explicit_scope and matched_profiles_all:
        matched_books = sorted({str(row.get("book_id", "")) for row in matched_profiles_all})
        if len(matched_books) == 1:
            explicit_scope = matched_books
        elif len(matched_books) > 1:
            return {
                "schema_version": LEARNING_QUERY_SCHEMA_VERSION,
                "status": "refused_ambiguous_book_scope",
                "answer_type": "book_scope_required",
                "question": question,
                "book_scope": [],
                "items": [{
                    "canonical_name": str(matched_profiles_all[0].get("canonical_name", "")),
                    "available_books": [book_by_id[item] for item in matched_books if item in book_by_id],
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

    if not explicit_scope and len(books) > 1:
        return {
            "schema_version": LEARNING_QUERY_SCHEMA_VERSION,
            "status": "refused_ambiguous_book_scope",
            "answer_type": "book_scope_required",
            "question": question,
            "book_scope": [],
            "items": [{"available_books": books}],
            "limitations": ["multi-book learning queries require an explicit book scope"],
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }

    scope = set(explicit_scope)
    scoped_profiles = [row for row in profiles if row.get("book_id") in scope]
    scoped_storylines = [row for row in storylines if row.get("book_id") in scope]
    scoped_cards = [row for row in cards if row.get("book_id") in scope]
    scoped_relationships = [row for row in relationships if row.get("book_id") in scope]
    scoped_events = [row for row in events if row.get("book_id") in scope]
    scoped_observations = [row for row in observations if row.get("book_id") in scope]

    status = "answered"
    answer_type = "learning_summary"
    items: list[dict[str, object]] = []
    chapter_match = re.search(r"第\s*(\d+)\s*(?:章|节)", normalized)
    if chapter_match and any(token in normalized for token in ("学", "知识", "内容", "发生", "总结")):
        ordinal = int(chapter_match.group(1))
        answer_type = "chapter_learning"
        for card in [row for row in scoped_cards if row.get("chapter_ordinal") == ordinal][:max_items]:
            chapter_observations = [
                _observation_view(row)
                for row in scoped_observations
                if row.get("chapter_id") == card.get("chapter_id")
            ][:max_items]
            items.append({
                "book_id": card.get("book_id"),
                "book_title": card.get("book_title"),
                "chapter": card,
                "learned_statements": chapter_observations,
                "summary_statements": [row["statement"] for row in chapter_observations if row["observation_type"] == "chapter_summary"],
                "event_statements": [row["statement"] for row in chapter_observations if row["observation_type"] == "explicit_event"],
                "character_state_statements": [row["statement"] for row in chapter_observations if row["observation_type"] == "character_state"],
                "motivation_statements": [row["statement"] for row in chapter_observations if row["observation_type"] == "motivation_candidate"],
                "causal_statements": [row["statement"] for row in chapter_observations if row["observation_type"] == "causal_candidate"],
                "foreshadowing_statements": [row["statement"] for row in chapter_observations if row["observation_type"] == "foreshadowing_candidate"],
            })
    elif any(token in normalized for token in ("地点", "势力", "能力", "物品", "器物", "种族", "世界观", "世界模型", "世界规则")):
        answer_type = "world_model"
        world_books = world.get("books", {}) if isinstance(world.get("books"), dict) else {}
        items = [world_books[item] for item in explicit_scope if item in world_books][:max_items]
    elif any(token in normalized for token in ("事件链", "事件", "因果", "为什么发生", "导致")):
        answer_type = "event_and_causality_learning"
        items = [{
            "book_id": item,
            "book_title": str(book_by_id.get(item, {}).get("book_title", "")),
            "direct_events": [row for row in scoped_events if row.get("book_id") == item][:max_items],
            "event_observations": [_observation_view(row) for row in scoped_observations if row.get("book_id") == item and row.get("observation_type") == "explicit_event"][:max_items],
            "causal_observations": [_observation_view(row) for row in scoped_observations if row.get("book_id") == item and row.get("observation_type") == "causal_candidate"][:max_items],
        } for item in explicit_scope]
    elif any(token in normalized for token in ("主线", "伏笔", "动机", "关系变化", "人物变化")):
        answer_type = "deep_learning_dimension"
        wanted = []
        if "主线" in normalized:
            wanted.append("book_mainline_candidate")
        if "伏笔" in normalized:
            wanted.append("foreshadowing_candidate")
        if "动机" in normalized:
            wanted.append("motivation_candidate")
        if "关系" in normalized:
            wanted.append("relationship")
        if "人物变化" in normalized:
            wanted.append("character_state")
        items = [_observation_view(row) for row in scoped_observations if row.get("observation_type") in wanted][:max_items]
    else:
        matched_profiles = [row for row in matched_profiles_all if row.get("book_id") in scope]
        if matched_profiles:
            answer_type = "entity_learning"
            entity_ids = {str(row["entity_id"]) for row in matched_profiles}
            entity_storylines = [row for row in scoped_storylines if row.get("entity_id") in entity_ids]
            entity_relationships = [
                row for row in scoped_relationships
                if row.get("subject_entity_id") in entity_ids or row.get("object_entity_id") in entity_ids
            ]
            items = [
                {
                    "book_id": profile.get("book_id"),
                    "book_title": profile.get("book_title"),
                    "profile": profile,
                    "storyline": next((row for row in entity_storylines if row.get("entity_id") == profile.get("entity_id")), None),
                    "relationships": [
                        row for row in entity_relationships
                        if row.get("subject_entity_id") == profile.get("entity_id") or row.get("object_entity_id") == profile.get("entity_id")
                    ][:max_items],
                    "model_observations": [
                        _observation_view(row) for row in scoped_observations if profile.get("entity_id") in row.get("entity_ids", [])
                    ][:max_items],
                }
                for profile in matched_profiles[:max_items]
            ]
        else:
            items = []
            for current_book_id in explicit_scope:
                book_observations = [row for row in scoped_observations if row.get("book_id") == current_book_id]
                book_cards = [row for row in scoped_cards if row.get("book_id") == current_book_id]
                book_profiles_current = [row for row in scoped_profiles if row.get("book_id") == current_book_id and row.get("profile_status") == "accepted"]
                items.append({
                    "book_id": current_book_id,
                    "book_title": str(book_by_id.get(current_book_id, {}).get("book_title", "")),
                    "chapter_card_count": len(book_cards),
                    "accepted_entity_profile_count": len(book_profiles_current),
                    "mainline_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "book_mainline_candidate"][:max_items],
                    "chapter_summaries": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "chapter_summary"][:max_items],
                    "event_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "explicit_event"][:max_items],
                    "character_state_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "character_state"][:max_items],
                    "relationship_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "relationship"][:max_items],
                    "motivation_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "motivation_candidate"][:max_items],
                    "causal_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "causal_candidate"][:max_items],
                    "foreshadowing_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "foreshadowing_candidate"][:max_items],
                    "world_rule_statements": [str(row.get("statement", "")) for row in book_observations if row.get("observation_type") == "world_rule"][:max_items],
                    "direct_event_count": len([row for row in scoped_events if row.get("book_id") == current_book_id]),
                    "direct_relationship_count": len([row for row in scoped_relationships if row.get("book_id") == current_book_id and row.get("tier") == "A"]),
                    "model_learning_observation_count": len(book_observations),
                    "complete_chapter_packet_count": len([row for row in scoped_cards if row.get("book_id") == current_book_id and row.get("complete_chapter_available") is True]),
                    "exact_assertion_count_project_total": report.get("exact_assertion_count"),
                    "exact_evidence_anchor_count_project_total": report.get("exact_evidence_anchor_count"),
                })
    if not items:
        status = "refused_unsupported"
    return {
        "schema_version": LEARNING_QUERY_SCHEMA_VERSION,
        "status": status,
        "answer_type": answer_type,
        "question": question,
        "book_scope": explicit_scope,
        "items": items,
        "limitations": [
            "direct facts are source-bound; B/C learning observations remain reviewable and are not canonical facts",
            "web results may validate metadata but may not fill missing source knowledge",
            "cross-book entity mixing is forbidden unless explicitly requested",
        ],
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_release": False,
        "may_freeze": False,
    }


__all__ = [
    "LEARNING_SYSTEM_VERSION",
    "LearningProjectError",
    "LearningProjectResult",
    "LearningProjectVerification",
    "build_learning_project",
    "verify_learning_project",
    "query_learning_project",
]
