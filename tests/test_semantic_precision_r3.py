from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tkr.semantic_extraction import inspect_source_semantics


class SemanticPrecisionR3Tests(unittest.TestCase):
    def scan(self, text: str):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text(text, encoding="utf-8")
            return inspect_source_semantics(path)

    def accepted(self, text: str, claim_type: str):
        report = self.scan(text)
        return [row for row in report.candidates if row.claim_type == claim_type and row.may_index]

    def test_bare_gong_compounds_are_not_counts(self):
        for text in ("二人共乘一船。", "此事人神共愤。", "钟声共鸣九次。", "他与任九霄共战三场。"):
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "count"), [])
        rows = self.accepted("反对者一共有三人。", "count")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].value, 3)

    def test_immediate_bare_gong_number_remains_supported(self):
        rows = self.accepted("花间游共二十四变。", "count")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].value, 24)

    def test_broad_ability_modals_do_not_publish_permission_facts(self):
        for text in ("我可以离开。", "他能够全身而退。", "我不能理解。", "此剑可破万法。"):
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "permission"), [])

    def test_explicit_normative_permission_remains_supported(self):
        self.assertEqual(len(self.accepted("守门人允许陆川进入内殿。", "permission")), 1)
        self.assertEqual(len(self.accepted("山门禁止外人通行。", "permission")), 1)

    def test_clause_fragments_do_not_publish_relations(self):
        samples = (
            ("任九霄已经被击败了。", "defeats"),
            ("众妖见姬瑶月轻描淡写间击败蝎夫人。", "defeats"),
            ("经纬针法虽称得上不凡。", "alias"),
            ("因地处背阴幽谷，常年有雾。", "located_in"),
        )
        for text, claim_type in samples:
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, claim_type), [])

    def test_simple_named_relations_remain_supported(self):
        self.assertEqual(len(self.accepted("陆川击败韩岳。", "defeats")), 1)
        self.assertEqual(len(self.accepted("玄霄又称青帝。", "alias")), 1)
        self.assertEqual(len(self.accepted("听雪楼位于北境。", "located_in")), 1)

    def test_enumeration_tail_is_not_count_subject(self):
        self.assertEqual(
            self.accepted("分八寒地狱，八热地狱，近边地狱，孤独地狱共十八路。", "count"),
            [],
        )

    def test_count_unit_stops_at_classifier(self):
        rows = self.accepted("十人中一共有三人受你劝导。", "count")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].unit, "人")

    def test_conjunction_is_not_permission_actor(self):
        self.assertEqual(self.accepted("书却不可以再度转换。", "permission"), [])

    def test_descriptive_count_prefix_collapses_to_named_work(self):
        rows = self.accepted("青丘狐族至高绝学狐如意法共分九篇。", "count")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subject, "狐如意法")


if __name__ == "__main__":
    unittest.main()
