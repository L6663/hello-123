from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tkr.learning_engine import build_learning_project, query_learning_project, verify_learning_project
from tkr.literary_engine import build_literary_engine
from tkr.project_security import build_secure_engineered_project


class LearningR7CapabilityTests(unittest.TestCase):
    def _build_source(self, root: Path, filename: str, text: str) -> tuple[Path, Path]:
        source = root / filename
        source.write_text(text, encoding="utf-8")
        stem = source.stem.replace(" ", "_")
        base = root / f"base-{stem}"
        literary = root / f"literary-{stem}"
        build_secure_engineered_project(source, base, profile="balanced", state_directory=root / f"state-{stem}")
        build_literary_engine(base, literary)
        return base, literary

    def test_same_book_entities_consolidate_and_cross_book_names_are_isolated(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base_a, lit_a = self._build_source(
                root,
                "星港录_上卷.txt",
                "第一卷 星港初潮\n第一章 雾港来信\n林岚位于雾港。林岚击败裴照。\n",
            )
            base_b, lit_b = self._build_source(
                root,
                "星港录_下卷.txt",
                "第二卷 黯潮之门\n第九章 剑匣\n林岚共有三柄剑。顾川又称灰灯。\n",
            )
            base_c, lit_c = self._build_source(
                root,
                "沙海药师.txt",
                "第一章 沙丘药铺\n林岚位于沙海。林岚共有两枚药印。\n",
            )
            learning = root / "learning"
            build_learning_project(
                [lit_a, lit_b, lit_c],
                learning,
                source_projects=[base_a, base_b, base_c],
            )
            verification = verify_learning_project(learning, [lit_a, lit_b, lit_c], [base_a, base_b, base_c])
            self.assertTrue(verification.valid, verification.reason_codes)
            report = json.loads((learning / "learning-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["book_count"], 2)
            self.assertEqual(report["chapter_card_count"], 3)
            profiles = [json.loads(line) for line in (learning / "entity-learning-profiles.jsonl").read_text(encoding="utf-8").splitlines()]
            linlan = [row for row in profiles if row.get("profile_status") == "accepted" and row.get("canonical_name") == "林岚"]
            self.assertEqual(len(linlan), 2)
            star = next(row for row in linlan if row["book_title"] == "星港录")
            self.assertGreaterEqual(star["consolidated_profile_count"], 2)
            self.assertEqual(len(star["literary_project_ids"]), 2)
            ambiguous = query_learning_project(learning, "林岚学到了什么？")
            self.assertEqual(ambiguous["status"], "refused_ambiguous_book_scope")
            scoped = query_learning_project(learning, "星港录中的林岚学到了什么？")
            self.assertEqual(scoped["status"], "answered")
            self.assertEqual(len(scoped["items"]), 1)
            self.assertEqual(scoped["items"][0]["profile"]["book_title"], "星港录")

    def test_fragment_entities_are_review_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, literary = self._build_source(
                root,
                "片段过滤.txt",
                "第一章\n她虽然击败裴照。白芷当众击败裴照。顾川在塔门击败裴照。白芷击败裴照。\n",
            )
            learning = root / "learning"
            build_learning_project([literary], learning, source_projects=[base])
            profiles = [json.loads(line) for line in (learning / "entity-learning-profiles.jsonl").read_text(encoding="utf-8").splitlines()]
            accepted_names = {row["canonical_name"] for row in profiles if row["profile_status"] == "accepted"}
            self.assertIn("白芷", accepted_names)
            self.assertNotIn("她虽然", accepted_names)
            self.assertNotIn("白芷当众", accepted_names)
            self.assertNotIn("顾川在塔门", accepted_names)

    def test_queries_expand_learning_statements_and_world_rules(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, literary = self._build_source(
                root,
                "雾港星火.txt",
                "第一章 雾港来信\n林岚位于雾港。\n第二章 黯潮\n林岚击败裴照。\n",
            )
            first = root / "learning-first"
            build_learning_project([literary], first, source_projects=[base])
            tasks = [json.loads(line) for line in (first / "model-learning-tasks.jsonl").read_text(encoding="utf-8").splitlines()]
            packets = {row["source_packet_id"]: row for row in [json.loads(line) for line in (first / "chapter-source-packets.jsonl").read_text(encoding="utf-8").splitlines()]}
            observations = []
            for task in tasks:
                packet = packets[task["source_packet_id"]]
                phrase = "林岚位于雾港" if task["source_order"] == 0 else "林岚击败裴照"
                relative = packet["chapter_text"].index(phrase)
                start = packet["start_char"] + relative
                observations.append({
                    "task_id": task["task_id"],
                    "observation_type": "chapter_summary",
                    "epistemic_tier": "B",
                    "statement": "本章学习摘要：" + phrase + "。",
                    "entity_ids": task["known_entity_ids"],
                    "evidence_spans": [{"start_char": start, "end_char": start + len(phrase), "evidence_text": phrase}],
                    "evidence_anchor_ids": [],
                    "status": "proposed",
                    "may_publish_directly": False,
                })
                if task["source_order"] == 0:
                    observations.append({
                        "task_id": task["task_id"],
                        "observation_type": "world_rule",
                        "epistemic_tier": "C",
                        "statement": "雾港的航灯用于抵御黯潮。",
                        "learned_entities": [
                            {"name": "航灯", "category": "item", "aliases": []},
                            {"name": "黯潮", "category": "concept", "aliases": []},
                        ],
                        "entity_ids": task["known_entity_ids"],
                        "evidence_spans": [{"start_char": start, "end_char": start + len(phrase), "evidence_text": phrase}],
                        "evidence_anchor_ids": [],
                        "status": "proposed",
                        "may_publish_directly": False,
                    })
            observation_file = root / "observations.jsonl"
            observation_file.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in observations) + "\n", encoding="utf-8")
            learning = root / "learning"
            build_learning_project([literary], learning, source_projects=[base], observation_file=observation_file)
            chapter = query_learning_project(learning, "第1章学到了什么？")
            self.assertEqual(chapter["status"], "answered")
            self.assertTrue(chapter["items"][0]["summary_statements"])
            self.assertIn("本章学习摘要", chapter["items"][0]["summary_statements"][0])
            world = query_learning_project(learning, "世界规则学到了什么？")
            self.assertEqual(world["status"], "answered")
            rules = world["items"][0]["learning_observations"]["world_rule"]
            self.assertEqual(rules[0]["statement"], "雾港的航灯用于抵御黯潮。")
            candidates = world["items"][0]["observed_entity_candidates"]
            self.assertEqual(candidates["item"][0]["name"], "航灯")
            self.assertEqual(candidates["concept"][0]["name"], "黯潮")
            summary = query_learning_project(learning, "这本书学到了什么？")
            self.assertTrue(summary["items"][0]["chapter_summaries"])

    def test_shared_generic_alias_does_not_merge_distinct_characters(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base_a, lit_a = self._build_source(
                root,
                "别名录_上卷.txt",
                "第一章\n张青又称师父。张青击败赵甲。\n",
            )
            base_b, lit_b = self._build_source(
                root,
                "别名录_下卷.txt",
                "第二章\n李岳又称师父。李岳击败钱乙。\n",
            )
            learning = root / "learning"
            build_learning_project(
                [lit_a, lit_b],
                learning,
                source_projects=[base_a, base_b],
                book_ids=["alias-book", "alias-book"],
                book_titles=["别名录", "别名录"],
            )
            profiles = [json.loads(line) for line in (learning / "entity-learning-profiles.jsonl").read_text(encoding="utf-8").splitlines()]
            people = {
                row["canonical_name"]: row
                for row in profiles
                if row.get("profile_status") == "accepted" and row.get("canonical_name") in {"张青", "李岳"}
            }
            self.assertEqual(set(people), {"张青", "李岳"})
            self.assertEqual(people["张青"]["consolidated_profile_count"], 1)
            self.assertEqual(people["李岳"]["consolidated_profile_count"], 1)
            ambiguous = query_learning_project(learning, "别名录中的师父学到了什么？")
            self.assertEqual(ambiguous["status"], "refused_ambiguous_entity_scope")
            self.assertEqual(
                {row["canonical_name"] for row in ambiguous["items"][0]["available_entities"]},
                {"张青", "李岳"},
            )

    def test_unique_alias_bridges_to_canonical_identity_and_is_queryable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base_a, lit_a = self._build_source(
                root,
                "灰灯录_上卷.txt",
                "第一章\n顾川又称灰灯。顾川位于雾港。\n",
            )
            base_b, lit_b = self._build_source(
                root,
                "灰灯录_下卷.txt",
                "第二章\n灰灯击败裴照。\n",
            )
            learning = root / "learning"
            build_learning_project(
                [lit_a, lit_b],
                learning,
                source_projects=[base_a, base_b],
                book_ids=["gray-lamp", "gray-lamp"],
                book_titles=["灰灯录", "灰灯录"],
            )
            profiles = [json.loads(line) for line in (learning / "entity-learning-profiles.jsonl").read_text(encoding="utf-8").splitlines()]
            merged = [
                row for row in profiles
                if row.get("profile_status") == "accepted"
                and {row.get("canonical_name"), *row.get("aliases", [])} >= {"顾川", "灰灯"}
            ]
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["consolidated_profile_count"], 2)
            alias_query = query_learning_project(learning, "灰灯录中的灰灯学到了什么？")
            self.assertEqual(alias_query["status"], "answered")
            self.assertEqual(alias_query["answer_type"], "entity_learning")
            self.assertEqual(len(alias_query["items"]), 1)
            self.assertIn(alias_query["items"][0]["profile"]["canonical_name"], {"顾川", "灰灯"})

    def test_long_entity_name_suppresses_short_substring_match(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, literary = self._build_source(
                root,
                "长名录.txt",
                "第一章\n张三位于东城。张三丰位于西城。\n",
            )
            learning = root / "learning"
            build_learning_project([literary], learning, source_projects=[base])
            result = query_learning_project(learning, "张三丰学到了什么？")
            self.assertEqual(result["status"], "answered")
            self.assertEqual(result["answer_type"], "entity_learning")
            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(result["items"][0]["profile"]["canonical_name"], "张三丰")


if __name__ == "__main__":
    unittest.main()
