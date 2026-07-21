from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from test_hybrid_retrieval import RetrievalFixture
from tkr.hybrid_retrieval import RetrievalError
from tkr.strict_qa import (
    QA_SCHEMA_VERSION,
    answer_strict,
    verify_strict_packet,
)


class StrictQATests(RetrievalFixture):
    def test_exact_count_answer_has_fact_citation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。"],
                [{"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"}],
            )
            packet = answer_strict(paths[4], "守卫有多少名？")

        self.assertEqual(packet.qa_schema_version, QA_SCHEMA_VERSION)
        self.assertEqual(packet.decision, "answered")
        self.assertEqual(packet.answer_claim.value, 100)
        self.assertEqual(packet.answer_text, "守卫共有100名。[E1]")
        self.assertEqual(len(packet.citations), 1)
        self.assertEqual(packet.citations[0].evidence_text, "守卫共有100名。")
        self.assertEqual(packet.citations[0].claim_type, "count")
        self.assertEqual(packet.citation_entailment, "entailed_structured")
        self.assertFalse(packet.may_freeze)

    def test_cross_unit_alias_can_answer_location_with_location_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["北门后来改称玄门。", "玄门位于皇城北侧。", "第二章的玄门与第一章改称后的玄门是同一实体。"],
                [
                    {"unit_index": 1, "evidence": "北门后来改称玄门。", "claim_type": "alias", "subject": "北门", "object": "玄门"},
                    {"unit_index": 2, "evidence": "玄门位于皇城北侧。", "claim_type": "located_in", "subject": "玄门", "object": "皇城北侧"},
                ],
                identity_links=[
                    {
                        "unit_index": 3,
                        "evidence": "第二章的玄门与第一章改称后的玄门是同一实体。",
                        "left_record": 0,
                        "left_role": "object",
                        "right_record": 1,
                        "right_role": "subject",
                    }
                ],
            )
            packet = answer_strict(paths[4], "北门位于哪里？")

        self.assertEqual(packet.decision, "answered")
        self.assertEqual(packet.answer_claim.object, "皇城北侧")
        self.assertEqual(packet.answer_text, "北门位于皇城北侧。[E1]")
        self.assertEqual(packet.citations[0].unit_id, "u2")
        self.assertEqual(packet.citations[0].claim_type, "located_in")

    def test_directional_answer_does_not_reverse_relation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["张三击败李四。"],
                [{"evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"}],
            )
            forward = answer_strict(paths[4], "张三击败了谁？")
            who = answer_strict(paths[4], "谁击败了李四？")
            reverse = answer_strict(paths[4], "李四击败了谁？")

        self.assertEqual(forward.answer_text, "张三击败了李四。[E1]")
        self.assertEqual(who.answer_text, "张三击败了李四。[E1]")
        self.assertEqual(reverse.decision, "refused_insufficient_evidence")
        self.assertEqual(reverse.citations, ())

    def test_positive_permission_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["系统允许删除。"],
                [{"evidence": "系统允许删除。", "claim_type": "permission", "subject": "系统", "object": "删除", "polarity": True}],
            )
            packet = answer_strict(paths[4], "系统允许删除吗？")

        self.assertEqual(packet.decision, "answered")
        self.assertTrue(packet.answer_claim.boolean_answer)
        self.assertEqual(packet.answer_text, "是。系统允许删除。[E1]")

    def test_explicit_opposite_permission_supports_no_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["系统禁止删除。"],
                [{"evidence": "系统禁止删除。", "claim_type": "permission", "subject": "系统", "object": "删除", "polarity": False}],
            )
            packet = answer_strict(paths[4], "系统允许删除吗？")

        self.assertEqual(packet.decision, "answered")
        self.assertFalse(packet.answer_claim.boolean_answer)
        self.assertFalse(packet.answer_claim.fact_polarity)
        self.assertEqual(packet.answer_text, "否。系统禁止删除。[E1]")
        self.assertIn("CITATIONS_STRUCTURALLY_ENTAILED", packet.reason_codes)

    def test_absence_is_not_used_as_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["系统位于北城。"],
                [{"evidence": "系统位于北城。", "claim_type": "located_in", "subject": "系统", "object": "北城"}],
            )
            packet = answer_strict(paths[4], "系统允许删除吗？")

        self.assertEqual(packet.decision, "refused_insufficient_evidence")
        self.assertIsNone(packet.answer_claim)
        self.assertEqual(packet.citations, ())

    def test_unsupported_open_question_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["玄门位于北城。"],
                [{"evidence": "玄门位于北城。", "claim_type": "located_in", "subject": "玄门", "object": "北城"}],
            )
            packet = answer_strict(paths[4], "玄门是谁发明的？")

        self.assertEqual(packet.decision, "refused_unsupported")
        self.assertIn("REFUSAL_UNSUPPORTED_PREDICATE", packet.reason_codes)
        self.assertIsNone(packet.answer_claim)
        self.assertEqual(packet.citations, ())
        self.assertEqual(packet.citation_entailment, "not_applicable")

    def test_supported_question_without_matching_fact_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["玄门位于北城。"],
                [{"evidence": "玄门位于北城。", "claim_type": "located_in", "subject": "玄门", "object": "北城"}],
            )
            packet = answer_strict(paths[4], "玄门有多少层？")

        self.assertEqual(packet.decision, "refused_insufficient_evidence")
        self.assertIn("REFUSAL_INSUFFICIENT_TYPED_EVIDENCE", packet.reason_codes)

    def test_contested_facts_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。守卫共有120名。"],
                [
                    {"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"},
                    {"evidence": "守卫共有120名。", "claim_type": "count", "subject": "守卫", "value": 120, "unit": "名"},
                ],
            )
            packet = answer_strict(paths[4], "守卫有多少名？")

        self.assertEqual(packet.decision, "refused_ambiguous")
        self.assertIn("CONTESTED_FACTS_PRESENT", packet.reason_codes)
        self.assertEqual(packet.citations, ())

    def test_temporal_scope_selects_current_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。后来守卫共有120名。"],
                [
                    {"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"},
                    {"evidence": "后来守卫共有120名。", "claim_type": "count", "subject": "守卫", "value": 120, "unit": "名"},
                ],
            )
            unspecified = answer_strict(paths[4], "守卫有多少名？")
            current = answer_strict(paths[4], "守卫现在有多少名？")
            past = answer_strict(paths[4], "守卫最初有多少名？")

        self.assertEqual(unspecified.decision, "refused_ambiguous")
        self.assertEqual(current.answer_claim.value, 120)
        self.assertEqual(current.answer_text, "守卫共有120名。[E1]")
        self.assertEqual(past.answer_claim.value, 100)

    def test_compatible_date_refinement_uses_most_precise_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["工程始于2001-02。工程始于2001-02-03。"],
                [
                    {"evidence": "工程始于2001-02。", "claim_type": "date", "subject": "工程", "value": "2001-02"},
                    {"evidence": "工程始于2001-02-03。", "claim_type": "date", "subject": "工程", "value": "2001-02-03"},
                ],
            )
            packet = answer_strict(paths[4], "工程什么时候开始？")

        self.assertEqual(packet.decision, "answered")
        self.assertEqual(packet.answer_claim.value, "2001-02-03")
        self.assertEqual(packet.answer_text, "工程的开始日期是2001-02-03。[E1]")

    def test_packet_is_deterministic_and_recomputes_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。"],
                [{"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"}],
            )
            first = answer_strict(paths[4], "守卫有多少名？")
            second = answer_strict(paths[4], "守卫有多少名？")
            verification = verify_strict_packet(paths[4], first.to_dict())

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.packet_id, second.packet_id)
        self.assertTrue(verification.accepted)
        self.assertEqual(verification.expected_packet_id, first.packet_id)

    def test_refusal_packet_also_recomputes_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["玄门位于北城。"],
                [{"evidence": "玄门位于北城。", "claim_type": "located_in", "subject": "玄门", "object": "北城"}],
            )
            packet = answer_strict(paths[4], "玄门是谁发明的？")
            verification = verify_strict_packet(paths[4], packet.to_dict())

        self.assertTrue(verification.accepted)
        self.assertEqual(packet.decision, "refused_unsupported")

    def test_database_tampering_blocks_answer_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。"],
                [{"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"}],
            )
            with paths[4].open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaises(RetrievalError):
                answer_strict(paths[4], "守卫有多少名？")

    def test_saved_packet_is_plain_canonical_json_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。"],
                [{"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"}],
            )
            packet = answer_strict(paths[4], "守卫有多少名？")
            serialized = json.dumps(packet.to_dict(), ensure_ascii=False, sort_keys=True)
            restored = json.loads(serialized)
            verification = verify_strict_packet(paths[4], restored)

        self.assertTrue(verification.accepted)


if __name__ == "__main__":
    unittest.main()
