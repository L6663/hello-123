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

class SemanticPrecisionR5AdversarialTests(SemanticPrecisionR3Tests):
    def test_alias_substring_collisions_are_rejected(self):
        for text in (
            "二位在北原名声遐迩。",
            "两个杀招分别名为度年如月、度年如日。",
            "巨阳仙僵又称赞一声。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "alias"), [])

    def test_alias_full_marker_keeps_exact_object(self):
        rows = self.accepted("吸髓石又称之为魔石。", "alias")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subject, "吸髓石")
        self.assertEqual(rows[0].object, "魔石")

    def test_location_marker_inside_verb_is_rejected(self):
        self.assertEqual(self.accepted("他游刃有余地处理各方面的关系。", "located_in"), [])

    def test_modal_and_clause_relation_subjects_are_rejected(self):
        samples = (
            "我一定要击败他。",
            "意味着方源要战胜尊者。",
            "从正面击溃她的这股势。",
            "我知道真正有希望战胜这头落星犬的人只有方源。",
            "再一举击溃房家。",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "defeats"), [])

    def test_post_marker_negation_never_indexes(self):
        for text in ("任何失败都击败不了他。", "你是战胜不了天庭的。"):
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "defeats"), [])

    def test_permission_substring_and_function_actors_are_rejected(self):
        samples = (
            "高位者也自有权谋和手段。",
            "铁家少主这个身份，都不允许方源杀掉她。",
            "只有晋升蛊仙，才允许祭拜生母。",
            "甚至只允许我族内部通婚。",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "permission"), [])

    def test_exact_named_permission_with_full_right_marker(self):
        rows = self.accepted("族长有权利查看秘卷。", "permission")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subject, "族长")
        self.assertEqual(rows[0].object, "查看秘卷")

    def test_approximate_and_ambiguous_counts_are_rejected(self):
        for text in (
            "他的竞争对手一共有二十几人。",
            "龙人分身身上共有三千多块骨骼。",
            "这次总共五块半元石。",
            "他又花费总共八万三的元石。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "count"), [])

    def test_clause_like_count_subjects_are_rejected(self):
        for text in (
            "顿时皱起眉头：一共四位蛊仙。",
            "让方源一共有三个目标地点。",
            "失笑一声：一共五万块元石。",
            "现在一共三十六道漩涡。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "count"), [])

class SemanticPrecisionR5RealCorpusBoundaryTests(SemanticPrecisionR3Tests):
    def test_person_name_ending_zheng_is_not_truncated(self):
        rows = self.accepted("方正连续击败漠北。", "defeats")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subject, "方正")

    def test_since_prefix_preserves_named_actor(self):
        rows = self.accepted("自从明皓击溃陆畏因之后，已经过去数天。", "defeats")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subject, "明皓")

    def test_historical_original_location_is_not_published_as_current(self):
        self.assertEqual(self.accepted("倪家原本位于南疆，后来迁往他处。", "located_in"), [])

    def test_locally_named_demonstrative_entity_is_normalized(self):
        rows = self.accepted("这皮草福地位于南疆中部。", "located_in")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subject, "皮草福地")
        rows = self.accepted("这拍卖大会禁止暗换密室。", "permission")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subject, "拍卖大会")

class SemanticPrecisionR6ReportedFailureTests(SemanticPrecisionR3Tests):
    def test_ability_and_intent_are_not_published_as_victories(self):
        samples = (
            "陆川有能力击败韩岳。",
            "陆川足以战胜韩岳。",
            "陆川能够打败韩岳。",
            "陆川试图击溃韩岳。",
            "如果陆川出手，就能击败韩岳。",
            "陆川或许可以战胜韩岳。",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "defeats"), [])

    def test_permission_requests_are_not_published_as_grants(self):
        samples = (
            "陆川请求族长允许他进入内殿。",
            "请允许陆川进入内殿。",
            "陆川问是否允许进入内殿？",
            "陆川希望族长准许他离开。",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "permission"), [])

    def test_negative_naming_commands_are_not_alias_facts(self):
        samples = (
            "不许再叫陆川别名阿舟。",
            "不要给陆川起别名黑剑。",
            "禁止称陆川为叛徒。",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, "alias"), [])

    def test_pronouns_and_function_words_are_not_relation_endpoints(self):
        samples = (
            ("我击败韩岳。", "defeats"),
            ("我们战胜韩岳。", "defeats"),
            ("她位于北境。", "located_in"),
            ("则又称青帝。", "alias"),
            ("和击败韩岳。", "defeats"),
            ("在北位于南境。", "located_in"),
        )
        for text, claim_type in samples:
            with self.subTest(text=text):
                self.assertEqual(self.accepted(text, claim_type), [])
