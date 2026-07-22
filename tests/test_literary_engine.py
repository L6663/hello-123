from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tkr.literary_engine import (
    LiteraryEngineError,
    build_literary_engine,
    verify_literary_engine,
)
from tkr.literary_export import export_literary_notion_package
from tkr.literary_models import (
    ASSERTION_SCHEMA_VERSION,
    EVIDENCE_ANCHOR_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
    RELATIONSHIP_SCHEMA_VERSION,
    EvidenceAnchor,
    KnowledgeAssertion,
    LiteraryModelError,
    assertion_id,
    event_id,
    evidence_anchor_id,
    relationship_id,
)
from tkr.literary_query import parse_literary_query, query_literary_engine


SOURCE = (
    "卷1 1章 初见\n"
    "青石门又称青云门。\n"
    "林舟击败赵衡。\n"
    "\n"
    "卷1 2章 北山\n"
    "青云门位于北山。\n"
)
SOURCE_ID = "src_stage7_fixture"
SOURCE_SHA = sha256(SOURCE.encode("utf-8")).hexdigest()


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _span(text: str) -> tuple[int, int]:
    start = SOURCE.index(text)
    return start, start + len(text)


def _unit_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    second_start = SOURCE.index("卷1 2章")
    heading1_end = SOURCE.index("\n")
    heading2_end = SOURCE.index("\n", second_start)
    ranges = [
        ("unit_1", "hdg_1", 0, second_start, heading1_end + 1, 1, "初见"),
        ("unit_2", "hdg_2", second_start, len(SOURCE), heading2_end + 1, 2, "北山"),
    ]
    units: list[dict[str, object]] = []
    headings: list[dict[str, object]] = []
    for unit_id, heading_id, start, end, body_start, ordinal, title in ranges:
        content = SOURCE[start:end]
        heading_end = SOURCE.index("\n", start)
        raw_heading = SOURCE[start:heading_end]
        units.append(
            {
                "schema_version": "tkr-unit-index-v1",
                "unit_id": unit_id,
                "source_id": SOURCE_ID,
                "source_sha256": SOURCE_SHA,
                "unit_type": "chapter",
                "hierarchy_level": 1,
                "ordinal": ordinal,
                "ordinal_text": str(ordinal),
                "title": title,
                "parent_unit_id": None,
                "heading_id": heading_id,
                "start_char": start,
                "end_char": end,
                "start_line": 1 if ordinal == 1 else 5,
                "end_line": 4 if ordinal == 1 else 7,
                "heading_start_char": start,
                "heading_end_char": heading_end,
                "body_start_char": body_start,
                "body_end_char": end,
                "character_count": end - start,
                "content_sha256": sha256(content.encode("utf-8")).hexdigest(),
                "structure_confidence": "high",
                "review_status": "accepted_candidate",
            }
        )
        headings.append(
            {
                "schema_version": "tkr-heading-candidate-v1",
                "heading_id": heading_id,
                "source_id": SOURCE_ID,
                "source_sha256": SOURCE_SHA,
                "rule_id": "FIXTURE_COMBINED_HEADING",
                "unit_type": "chapter",
                "hierarchy_level": 1,
                "ordinal": ordinal,
                "ordinal_text": str(ordinal),
                "title": title,
                "raw_heading": raw_heading,
                "boundary_start_char": start,
                "start_char": start,
                "end_char": heading_end,
                "heading_end_char": heading_end,
                "body_start_char": body_start,
                "start_line": 1 if ordinal == 1 else 5,
                "end_line": 1 if ordinal == 1 else 5,
                "confidence": "high",
                "accepted_as_boundary": True,
                "signals": ["container_ordinal=1"],
            }
        )
    return units, headings


def _mention(mention_id: str, entity: str, unit_id: str, surface: str) -> dict[str, object]:
    start, end = _span(surface)
    return {
        "mention_id": mention_id,
        "claim_result_id": f"claim_{mention_id}",
        "role": "subject",
        "surface": surface,
        "normalized_surface": surface,
        "inferred_type": entity,
        "source_id": SOURCE_ID,
        "unit_id": unit_id,
        "evidence_start": start,
        "evidence_end": end,
    }


def _fact(
    fact_id: str,
    claim_type: str,
    subject: str,
    object_text: str,
    evidence: str,
    unit_id: str,
    subject_entity_id: str,
    object_entity_id: str | None,
) -> dict[str, object]:
    start, end = _span(evidence)
    return {
        "fact_id": fact_id,
        "claim_result_id": f"claim_{fact_id}",
        "claim_type": claim_type,
        "predicate_scope": "",
        "subject_entity_id": subject_entity_id,
        "subject": subject,
        "object_entity_id": object_entity_id,
        "object": object_text,
        "value": None,
        "unit": "",
        "polarity": True,
        "source_id": SOURCE_ID,
        "unit_id": unit_id,
        "evidence_start": start,
        "evidence_end": end,
        "evidence_sha256": sha256(evidence.encode("utf-8")).hexdigest(),
        "temporal_marker": "none",
        "canonical_status": "canonical",
        "conflict_ids": [],
    }


def _make_project(root: Path) -> Path:
    project = root / "project"
    (project / "source").mkdir(parents=True)
    (project / "source" / "normalized-source.txt").write_text(SOURCE, encoding="utf-8", newline="")
    (project / "project-report.json").write_text(
        json.dumps(
            {
                "project_id": "kpr_stage7_fixture",
                "source_id": SOURCE_ID,
                "normalized_source_sha256": SOURCE_SHA,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    units, headings = _unit_rows()
    _jsonl(project / "stage2-structure" / "unit-index.jsonl", units)
    _jsonl(project / "stage2-structure" / "heading-candidates.jsonl", headings)
    _jsonl(project / "stage1-anomaly" / "anomaly-candidates.jsonl", [])

    mentions = [
        _mention("m_gate_old", "faction", "unit_1", "青石门"),
        _mention("m_gate_new", "faction", "unit_1", "青云门"),
        _mention("m_lin", "person", "unit_1", "林舟"),
        _mention("m_zhao", "person", "unit_1", "赵衡"),
        _mention("m_gate_ch2", "faction", "unit_2", "青云门"),
        _mention("m_mountain", "place", "unit_2", "北山"),
    ]
    entities = [
        {
            "entity_id": "e_gate",
            "canonical_name": "青云门",
            "aliases": ["青云门", "青石门"],
            "entity_type": "faction",
            "mention_ids": ["m_gate_old", "m_gate_new", "m_gate_ch2"],
            "source_ids": [SOURCE_ID],
            "unit_ids": ["unit_1", "unit_2"],
            "merge_basis": ["alias_fact"],
        },
        {
            "entity_id": "e_lin",
            "canonical_name": "林舟",
            "aliases": ["林舟"],
            "entity_type": "person",
            "mention_ids": ["m_lin"],
            "source_ids": [SOURCE_ID],
            "unit_ids": ["unit_1"],
            "merge_basis": [],
        },
        {
            "entity_id": "e_zhao",
            "canonical_name": "赵衡",
            "aliases": ["赵衡"],
            "entity_type": "person",
            "mention_ids": ["m_zhao"],
            "source_ids": [SOURCE_ID],
            "unit_ids": ["unit_1"],
            "merge_basis": [],
        },
        {
            "entity_id": "e_mountain",
            "canonical_name": "北山",
            "aliases": ["北山"],
            "entity_type": "place",
            "mention_ids": ["m_mountain"],
            "source_ids": [SOURCE_ID],
            "unit_ids": ["unit_2"],
            "merge_basis": [],
        },
    ]
    facts = [
        _fact("f_alias", "alias", "青石门", "青云门", "青石门又称青云门。", "unit_1", "e_gate", "e_gate"),
        _fact("f_defeat", "defeats", "林舟", "赵衡", "林舟击败赵衡。", "unit_1", "e_lin", "e_zhao"),
        _fact("f_located", "located_in", "青云门", "北山", "青云门位于北山。", "unit_2", "e_gate", "e_mountain"),
    ]
    _jsonl(project / "bridge" / "entity" / "mentions.jsonl", mentions)
    _jsonl(project / "bridge" / "entity" / "entities.jsonl", entities)
    _jsonl(project / "bridge" / "entity" / "facts.jsonl", facts)
    return project


def _valid_verification():
    return SimpleNamespace(valid=True, reason_codes=())


class LiteraryModelTests(unittest.TestCase):
    def test_a_requires_exact_evidence(self) -> None:
        with self.assertRaises(LiteraryModelError):
            KnowledgeAssertion(
                ASSERTION_SCHEMA_VERSION,
                "las_" + "0" * 32,
                "A",
                "fact",
                None,
                "林舟",
                "身份",
                None,
                "剑客",
                None,
                True,
                None,
                None,
                1.0,
                (),
                (),
                (),
                "source_explicit",
                "active",
                1,
            )

    def test_b_requires_multiple_a_supports(self) -> None:
        with self.assertRaises(LiteraryModelError):
            KnowledgeAssertion(
                ASSERTION_SCHEMA_VERSION,
                "las_" + "1" * 32,
                "B",
                "synthesis",
                None,
                "林舟",
                "长期行为模式",
                None,
                "谨慎",
                None,
                True,
                None,
                None,
                0.8,
                (),
                ("las_one",),
                ("只由单条事实支持",),
                "cross_evidence_synthesis",
                "active",
                1,
            )

    def test_c_cannot_claim_definitive_author_intent(self) -> None:
        with self.assertRaises(LiteraryModelError):
            KnowledgeAssertion(
                ASSERTION_SCHEMA_VERSION,
                "las_" + "2" * 32,
                "C",
                "interpretation",
                None,
                "作者",
                "author_intended",
                None,
                "唯一含义",
                None,
                True,
                None,
                None,
                0.7,
                (),
                ("las_fact",),
                ("属于模型解释",),
                "model_interpretation",
                "active",
                1,
            )

    def test_query_parser_supports_temporal_relationship(self) -> None:
        intent = parse_literary_query("林舟与赵衡在第1卷第1章时是什么关系？")
        self.assertEqual(intent.intent_type, "relationship_at")
        self.assertEqual(intent.volume_ordinal, 1)
        self.assertEqual(intent.chapter_ordinal, 1)
        self.assertEqual(intent.subject, "林舟")
        self.assertEqual(intent.object, "赵衡")


class LiteraryEngineIntegrationTests(unittest.TestCase):
    def _build_base(self, root: Path) -> tuple[Path, Path]:
        project = _make_project(root)
        sidecar = root / "literary"
        with patch("tkr.literary_engine.verify_secure_knowledge_project", return_value=_valid_verification()):
            result = build_literary_engine(project, sidecar)
        self.assertEqual(result.status, "completed")
        return project, sidecar

    def test_build_verify_and_chapter_addresses(self) -> None:
        with TemporaryDirectory() as directory:
            _, sidecar = self._build_base(Path(directory))
            verification = verify_literary_engine(sidecar)
            self.assertTrue(verification.valid, verification.reason_codes)
            chapters = [json.loads(line) for line in (sidecar / "chapters.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["chapter_ordinal"] for row in chapters], [1, 2])
            self.assertEqual([row["volume_ordinal"] for row in chapters], [1, 1])
            assertions = [json.loads(line) for line in (sidecar / "assertions.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["tier"] for row in assertions}, {"A"})
            self.assertTrue(all(row["evidence_anchor_ids"] for row in assertions))

    def test_first_appearance_profile_and_open_refusal(self) -> None:
        with TemporaryDirectory() as directory:
            _, sidecar = self._build_base(Path(directory))
            first = query_literary_engine(sidecar, "林舟首次出场在哪一章？")
            self.assertEqual(first.decision, "answered")
            self.assertEqual(first.answer_items[0].volume_ordinal, 1)
            self.assertEqual(first.answer_items[0].chapter_ordinal, 1)

            profile = query_literary_engine(sidecar, "林舟是谁？")
            self.assertEqual(profile.decision, "answered")
            self.assertGreaterEqual(profile.fact_count, 1)
            self.assertEqual(profile.synthesis_count, 0)
            self.assertEqual(profile.interpretation_count, 0)
            self.assertTrue(profile.citations)

            refused = query_literary_engine(sidecar, "林舟为什么代表绝对正义？")
            self.assertEqual(refused.decision, "refused")
            self.assertIn(refused.refusal_kind, {"evidence_without_supported_conclusion", "insufficient_evidence"})

    def test_enriched_tiers_relationship_event_and_notion_export(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project, base = self._build_base(root)
            assertions = [json.loads(line) for line in (base / "assertions.jsonl").read_text(encoding="utf-8").splitlines()]
            anchors = [json.loads(line) for line in (base / "evidence-anchors.jsonl").read_text(encoding="utf-8").splitlines()]
            chapters = [json.loads(line) for line in (base / "chapters.jsonl").read_text(encoding="utf-8").splitlines()]
            a_ids = [row["assertion_id"] for row in assertions]
            anchor_ids = [row["anchor_id"] for row in anchors]
            chapter1 = chapters[0]

            b_id = assertion_id(
                "B", "synthesis", "林舟", "行为模式", "主动对抗赵衡", None, True, (), a_ids[:2]
            )
            c_id = assertion_id(
                "C", "interpretation", "林舟", "文学意义", "行动可解释为承担风险", None, True, (), (b_id,)
            )
            rel_id = relationship_id("e_lin", "敌对", "e_zhao", chapter1["chapter_id"], chapter1["chapter_id"], "A")
            ev_id = event_id("林舟击败赵衡", chapter1["chapter_id"], chapter1["chapter_id"])
            annotations = [
                {
                    "record_type": "assertion",
                    "record": {
                        "schema_version": ASSERTION_SCHEMA_VERSION,
                        "assertion_id": b_id,
                        "tier": "B",
                        "assertion_kind": "synthesis",
                        "subject_entity_id": "e_lin",
                        "subject_text": "林舟",
                        "predicate": "行为模式",
                        "object_entity_id": None,
                        "object_text": "主动对抗赵衡",
                        "value": None,
                        "polarity": True,
                        "temporal_start_chapter_id": chapter1["chapter_id"],
                        "temporal_end_chapter_id": chapter1["chapter_id"],
                        "confidence": 0.91,
                        "evidence_anchor_ids": [],
                        "supporting_assertion_ids": a_ids[:2],
                        "limitations": ["这是跨事实归纳，不是原文单句定论"],
                        "attribution": "cross_evidence_synthesis",
                        "status": "active",
                        "revision": 1,
                    },
                },
                {
                    "record_type": "assertion",
                    "record": {
                        "schema_version": ASSERTION_SCHEMA_VERSION,
                        "assertion_id": c_id,
                        "tier": "C",
                        "assertion_kind": "interpretation",
                        "subject_entity_id": "e_lin",
                        "subject_text": "林舟",
                        "predicate": "文学意义",
                        "object_entity_id": None,
                        "object_text": "行动可解释为承担风险",
                        "value": None,
                        "polarity": True,
                        "temporal_start_chapter_id": chapter1["chapter_id"],
                        "temporal_end_chapter_id": chapter1["chapter_id"],
                        "confidence": 0.78,
                        "evidence_anchor_ids": [],
                        "supporting_assertion_ids": [b_id],
                        "limitations": ["模型文学解释，不代表作者明确意图"],
                        "attribution": "model_interpretation",
                        "status": "active",
                        "revision": 1,
                    },
                },
                {
                    "record_type": "relationship",
                    "record": {
                        "schema_version": RELATIONSHIP_SCHEMA_VERSION,
                        "relationship_id": rel_id,
                        "tier": "A",
                        "subject_entity_id": "e_lin",
                        "relation_type": "敌对",
                        "object_entity_id": "e_zhao",
                        "start_chapter_id": chapter1["chapter_id"],
                        "end_chapter_id": chapter1["chapter_id"],
                        "start_source_order": 0,
                        "end_source_order": 0,
                        "change_reason_assertion_ids": [a_ids[1]],
                        "evidence_anchor_ids": [anchor_ids[1]],
                        "status": "ended",
                    },
                },
                {
                    "record_type": "event",
                    "record": {
                        "schema_version": EVENT_SCHEMA_VERSION,
                        "event_id": ev_id,
                        "canonical_name": "林舟击败赵衡",
                        "event_type": "battle",
                        "start_chapter_id": chapter1["chapter_id"],
                        "end_chapter_id": chapter1["chapter_id"],
                        "start_source_order": 0,
                        "end_source_order": 0,
                        "place_entity_ids": [],
                        "participant_entity_ids": ["e_lin", "e_zhao"],
                        "cause_assertion_ids": [a_ids[0]],
                        "process_assertion_ids": [a_ids[1]],
                        "outcome_assertion_ids": [a_ids[1]],
                        "consequence_assertion_ids": [b_id],
                        "foreshadowing_assertion_ids": [],
                        "evidence_anchor_ids": [anchor_ids[1]],
                        "review_status": "accepted",
                    },
                },
            ]
            annotation_path = root / "annotations.jsonl"
            _jsonl(annotation_path, annotations)
            enriched = root / "enriched"
            with patch("tkr.literary_engine.verify_secure_knowledge_project", return_value=_valid_verification()):
                result = build_literary_engine(project, enriched, annotations_path=annotation_path)
            self.assertEqual((result.tier_a_count, result.tier_b_count, result.tier_c_count), (3, 1, 1))

            profile = query_literary_engine(enriched, "林舟是谁？")
            self.assertEqual(profile.decision, "answered")
            self.assertEqual(profile.fact_count, 1)
            self.assertEqual(profile.synthesis_count, 1)
            self.assertEqual(profile.interpretation_count, 1)
            self.assertIn("事实、归纳与解释已分开返回", profile.answer_text)

            relationship = query_literary_engine(enriched, "林舟与赵衡在第1卷第1章时是什么关系？")
            self.assertEqual(relationship.decision, "answered")
            self.assertEqual(relationship.answer_items[0].predicate, "敌对")

            cause = query_literary_engine(enriched, "林舟击败赵衡为什么发生？")
            self.assertEqual(cause.decision, "answered")

            notion = root / "notion"
            export = export_literary_notion_package(enriched, notion)
            self.assertTrue(export["fact_interpretation_separation"])
            pages = [json.loads(line) for line in (notion / "notion-assertion-pages.jsonl").read_text(encoding="utf-8").splitlines()]
            c_pages = [page for page in pages if page["properties"]["知识等级"] == "C"]
            self.assertEqual(len(c_pages), 1)
            self.assertIn("不代表作者明确设定", c_pages[0]["sections"]["分层声明"])

    def test_annotation_anchor_must_match_source_slice(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project, base = self._build_base(root)
            chapter = json.loads((base / "chapters.jsonl").read_text(encoding="utf-8").splitlines()[0])
            fake_text = "伪造证据"
            fake_hash = sha256(fake_text.encode("utf-8")).hexdigest()
            fake_anchor = EvidenceAnchor(
                EVIDENCE_ANCHOR_SCHEMA_VERSION,
                evidence_anchor_id(SOURCE_SHA, chapter["unit_id"], 0, len(fake_text), fake_hash),
                SOURCE_ID,
                SOURCE_SHA,
                chapter["unit_id"],
                chapter["chapter_id"],
                1,
                1,
                chapter["original_heading"],
                chapter["normalized_heading"],
                0,
                len(fake_text),
                fake_text,
                fake_hash,
                chapter["content_sha256"],
                "direct_fact",
                "clean",
            )
            annotation_path = root / "forged.jsonl"
            _jsonl(annotation_path, [{"record_type": "evidence", "record": fake_anchor.to_dict()}])
            with patch("tkr.literary_engine.verify_secure_knowledge_project", return_value=_valid_verification()):
                with self.assertRaisesRegex(LiteraryEngineError, "differs from the bound source span"):
                    build_literary_engine(project, root / "rejected", annotations_path=annotation_path)

    def test_tampered_sidecar_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            _, sidecar = self._build_base(Path(directory))
            assertion_path = sidecar / "assertions.jsonl"
            assertion_path.write_text(assertion_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            verification = verify_literary_engine(sidecar)
            self.assertFalse(verification.valid)
            self.assertIn("LITERARY_FILE_SIZE_MISMATCH", verification.reason_codes)


if __name__ == "__main__":
    unittest.main()
