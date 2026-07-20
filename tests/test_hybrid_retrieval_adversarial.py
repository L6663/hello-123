from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tkr.hybrid_retrieval import RetrievalError, build_hybrid_index, query_hybrid_index
from test_hybrid_retrieval import RetrievalFixture


class HybridRetrievalAdversarialTests(RetrievalFixture):
    def basic_project(self, root: Path):
        return self.make_project(
            root,
            ["张三击败李四。"],
            [{"evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"}],
        )

    def test_tampered_fact_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            facts_path = paths[3] / "facts.jsonl"
            facts_path.write_text(facts_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with self.assertRaises(RetrievalError):
                build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])

    def test_tampered_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            paths[0].write_text("李四击败张三。", encoding="utf-8")
            with self.assertRaises(RetrievalError):
                build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])

    def test_tampered_unit_index_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            paths[1].write_text(paths[1].read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(RetrievalError):
                build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])

    def test_tampered_accepted_claims_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            paths[2].write_text(paths[2].read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(RetrievalError):
                build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])

    def test_canonical_mode_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.make_project(
                root,
                ["张三击败李四。", "张三击败王五。"],
                [
                    {"unit_index": 1, "evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"},
                    {"unit_index": 2, "evidence": "张三击败王五。", "claim_type": "defeats", "subject": "张三", "object": "王五"},
                ],
            )
            with self.assertRaises(RetrievalError):
                build_hybrid_index(*paths[:4], paths[4], index_mode="canonical", identity_links_path=paths[5])
            build_hybrid_index(*paths[:4], paths[4], index_mode="review", identity_links_path=paths[5])

    def test_boolean_reverse_relation_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            result = query_hybrid_index(paths[4], "李四击败张三吗？")
        self.assertEqual(result.answerability, "not_answerable")

    def test_sql_metacharacters_are_data_not_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            result = query_hybrid_index(paths[4], "张三'; DROP TABLE facts;--击败了谁？")
            followup = query_hybrid_index(paths[4], "张三击败了谁？")
        self.assertIn(result.answerability, {"not_answerable", "ambiguous"})
        self.assertEqual(followup.answerability, "answerable")

    def test_lexical_hit_does_not_override_typed_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.make_project(
                root,
                ["玄门位于皇城北侧。火星只是传说中的地点。"],
                [{"evidence": "玄门位于皇城北侧。", "claim_type": "located_in", "subject": "玄门", "object": "皇城北侧"}],
            )
            build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            result = query_hybrid_index(paths[4], "玄门位于火星吗？")
        self.assertEqual(result.answerability, "not_answerable")
        self.assertFalse(result.answerable_candidate)
        self.assertTrue(result.lexical_hits)

    def test_rebuild_has_same_logical_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            first = build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            second_db = root / "second.sqlite3"
            second = build_hybrid_index(*paths[:4], second_db, identity_links_path=paths[5])
        self.assertEqual(first["index_logical_sha256"], second["index_logical_sha256"])


    def test_database_tamper_is_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            with paths[4].open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaises(RetrievalError):
                query_hybrid_index(paths[4], "张三击败了谁？")

    def test_lexical_offsets_match_the_returned_snippet(self):
        source = "序言。玄门位于皇城北侧。火星只是传说中的地点。尾声。"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.make_project(
                root,
                [source],
                [{"evidence": "玄门位于皇城北侧。", "claim_type": "located_in", "subject": "玄门", "object": "皇城北侧"}],
            )
            build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            result = query_hybrid_index(paths[4], "玄门位于火星吗？")
        for hit in result.lexical_hits:
            self.assertEqual(source[hit.evidence_start : hit.evidence_end], hit.evidence_text)

    def test_invalid_limit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.basic_project(root)
            build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            with self.assertRaises(RetrievalError):
                query_hybrid_index(paths[4], "张三击败了谁？", limit=0)

    def test_unmarked_third_value_stays_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.make_project(
                root,
                ["守卫共有100名。后来守卫共有120名。守卫共有130名。"],
                [
                    {"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"},
                    {"evidence": "后来守卫共有120名。", "claim_type": "count", "subject": "守卫", "value": 120, "unit": "名"},
                    {"evidence": "守卫共有130名。", "claim_type": "count", "subject": "守卫", "value": 130, "unit": "名"},
                ],
            )
            build_hybrid_index(*paths[:4], paths[4], identity_links_path=paths[5])
            result = query_hybrid_index(paths[4], "守卫现在有多少名？")
        self.assertEqual(result.answerability, "ambiguous")


if __name__ == "__main__":
    unittest.main()
