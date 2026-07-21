from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from test_hybrid_retrieval import RetrievalFixture
from tkr.strict_qa import StrictQAError, answer_strict, verify_strict_packet


class StrictQAAdversarialTests(RetrievalFixture):
    def make_answer(self, root: Path):
        paths = self.build(
            root,
            ["守卫共有100名。"],
            [{"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"}],
        )
        packet = answer_strict(paths[4], "守卫有多少名？")
        return paths, packet.to_dict()

    def test_forged_answer_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["answer_text"] = "守卫共有1000名。[E1]"
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("ANSWER_TEXT_NOT_ENTAILED", result.reason_codes)

    def test_forged_structured_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["answer_claim"]["value"] = 1000
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("ANSWER_CLAIM_NOT_ENTAILED", result.reason_codes)

    def test_forged_citation_offset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["citations"][0]["evidence_start"] += 1
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("CITATIONS_NOT_ENTAILED", result.reason_codes)

    def test_forged_citation_text_and_hash_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["citations"][0]["evidence_text"] = "守卫共有1000名。"
            payload["citations"][0]["evidence_sha256"] = "0" * 64
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("CITATIONS_NOT_ENTAILED", result.reason_codes)

    def test_dropping_all_citations_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["citations"] = []
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("CITATIONS_NOT_ENTAILED", result.reason_codes)

    def test_adding_unsupported_claim_to_answer_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["answer_text"] = "守卫共有100名，而且都来自月球。[E1]"
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("ANSWER_TEXT_NOT_ENTAILED", result.reason_codes)

    def test_forged_may_freeze_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["may_freeze"] = True
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("FREEZE_AUTHORITY_MISMATCH", result.reason_codes)

    def test_forged_decision_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["decision"] = "refused_insufficient_evidence"
            payload["answered"] = False
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("DECISION_MISMATCH", result.reason_codes)

    def test_forged_packet_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["packet_id"] = "qa_" + "0" * 24
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("PACKET_ID_MISMATCH", result.reason_codes)

    def test_missing_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            del payload["database_sha256"]
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("PACKET_FIELDS_MISSING", result.reason_codes)

    def test_unexpected_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            payload["free_form_note"] = "trusted"
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("PACKET_FIELDS_UNEXPECTED", result.reason_codes)

    def test_refusal_cannot_be_converted_to_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["玄门位于北城。"],
                [{"evidence": "玄门位于北城。", "claim_type": "located_in", "subject": "玄门", "object": "北城"}],
            )
            payload = answer_strict(paths[4], "玄门是谁发明的？").to_dict()
            payload["decision"] = "answered"
            payload["answered"] = True
            payload["answer_text"] = "玄门由张三发明。"
            payload["answer_claim"] = {"predicate": "invented_by", "subject": "玄门", "object": "张三"}
            result = verify_strict_packet(paths[4], payload)
        self.assertFalse(result.accepted)
        self.assertIn("DECISION_MISMATCH", result.reason_codes)
        self.assertIn("ANSWER_TEXT_NOT_ENTAILED", result.reason_codes)

    def test_lexical_presence_cannot_create_answer_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["玄门位于北城。玄门的石阶共有九级，但这不是建筑层数。"],
                [{"evidence": "玄门位于北城。", "claim_type": "located_in", "subject": "玄门", "object": "北城"}],
            )
            packet = answer_strict(paths[4], "玄门有多少层？")
        self.assertEqual(packet.decision, "refused_insufficient_evidence")
        self.assertIsNone(packet.answer_claim)
        self.assertEqual(packet.citations, ())

    def test_semantic_packet_copy_with_single_nested_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, payload = self.make_answer(Path(directory))
            forged = deepcopy(payload)
            forged["citations"][0]["canonical_status"] = "contested"
            result = verify_strict_packet(paths[4], forged)
        self.assertFalse(result.accepted)
        self.assertIn("CITATIONS_NOT_ENTAILED", result.reason_codes)

    def test_integrity_bypass_is_rejected_before_answer_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。"],
                [{"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"}],
            )
            with self.assertRaises(StrictQAError):
                answer_strict(paths[4], "守卫有多少名？", verify_database=False)


if __name__ == "__main__":
    unittest.main()
