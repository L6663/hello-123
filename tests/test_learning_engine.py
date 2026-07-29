from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tkr.learning_engine import build_learning_project, query_learning_project, verify_learning_project
from tkr.literary_engine import build_literary_engine
from tkr.project_security import build_secure_engineered_project


class LearningPanoramaTests(unittest.TestCase):
    def build_chain(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "story.txt"
        source.write_text(
            "第一章 初入北境\n"
            "陆川又称阿舟。陆川位于北境。\n"
            "第二章 雪夜决战\n"
            "陆川击败韩岳。\n"
            "第三章 剑匣\n"
            "陆川共有三柄剑。\n",
            encoding="utf-8",
        )
        base = root / "base"
        literary = root / "literary"
        learning = root / "learning"
        build_secure_engineered_project(source, base, profile="balanced", state_directory=root / "state")
        build_literary_engine(base, literary)
        build_learning_project([literary], learning, source_projects=[base])
        return base, literary, learning

    def test_build_verify_and_learning_products(self) -> None:
        with TemporaryDirectory() as directory:
            base, literary, learning = self.build_chain(Path(directory))
            verification = verify_learning_project(learning, [literary], [base])
            self.assertTrue(verification.valid, verification.reason_codes)
            report = json.loads((learning / "learning-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["chapter_card_count"], 3)
            self.assertEqual(report["complete_chapter_packet_count"], 3)
            self.assertGreaterEqual(report["accepted_entity_profile_count"], 3)
            self.assertEqual(report["direct_event_count"], 1)
            self.assertEqual(report["model_learning_task_count"], 3)
            tasks = [json.loads(line) for line in (learning / "model-learning-tasks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(row["may_publish_directly"] is False for row in tasks))
            self.assertTrue(all(row["requires_evidence_validation"] is True for row in tasks))
            self.assertTrue(all(row["complete_chapter_available"] is True for row in tasks))
            packets = [json.loads(line) for line in (learning / "chapter-source-packets.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(packets), 3)
            self.assertTrue(all(row["complete_chapter"] is True for row in packets))
            self.assertTrue(all(row["may_upload_to_public_ci"] is False for row in packets))

    def test_entity_and_summary_queries(self) -> None:
        with TemporaryDirectory() as directory:
            _, _, learning = self.build_chain(Path(directory))
            entity = query_learning_project(learning, "陆川学到了什么？")
            self.assertEqual(entity["status"], "answered")
            self.assertEqual(entity["answer_type"], "entity_learning")
            self.assertEqual(entity["items"][0]["profile"]["canonical_name"], "陆川")
            self.assertTrue(entity["items"][0]["storyline"]["direct_facts"])
            summary = query_learning_project(learning, "这本书学到了什么？")
            self.assertEqual(summary["answer_type"], "learning_summary")
            self.assertEqual(summary["items"][0]["chapter_card_count"], 3)

    def test_invalid_entity_names_remain_review_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "story.txt"
            source.write_text("第一章\n我击败韩岳。陆川击败韩岳。\n", encoding="utf-8")
            base = root / "base"
            literary = root / "literary"
            learning = root / "learning"
            build_secure_engineered_project(source, base, profile="balanced", state_directory=root / "state")
            build_literary_engine(base, literary)
            build_learning_project([literary], learning, source_projects=[base])
            profiles = [json.loads(line) for line in (learning / "entity-learning-profiles.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertFalse(any(row["canonical_name"] == "我" and row["profile_status"] == "accepted" for row in profiles))
            self.assertTrue(any(row["canonical_name"] == "陆川" and row["profile_status"] == "accepted" for row in profiles))

    def test_learning_project_can_degrade_without_source_packets(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, literary, _ = self.build_chain(root)
            learning = root / "learning-without-source"
            build_learning_project([literary], learning)
            verification = verify_learning_project(learning, [literary])
            self.assertTrue(verification.valid, verification.reason_codes)
            report = json.loads((learning / "learning-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["complete_chapter_packet_count"], 0)
            tasks = [json.loads(line) for line in (learning / "model-learning-tasks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(tasks)
            self.assertTrue(all(row["complete_chapter_available"] is False for row in tasks))

    def test_evidence_bound_model_observations_are_integrated_but_not_published(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, literary, learning = self.build_chain(root)
            tasks = [json.loads(line) for line in (learning / "model-learning-tasks.jsonl").read_text(encoding="utf-8").splitlines()]
            task = next(row for row in tasks if row["complete_chapter_available"] is True)
            packets = [json.loads(line) for line in (learning / "chapter-source-packets.jsonl").read_text(encoding="utf-8").splitlines()]
            packet = next(row for row in packets if row["source_packet_id"] == task["source_packet_id"])
            text = packet["chapter_text"]
            phrase = "陆川又称阿舟"
            relative = text.index(phrase)
            start = packet["start_char"] + relative
            observations = root / "observations.jsonl"
            observations.write_text(json.dumps({
                "task_id": task["task_id"],
                "observation_type": "chapter_summary",
                "epistemic_tier": "B",
                "statement": "本章介绍陆川的别名与初始位置。",
                "entity_ids": task["known_entity_ids"],
                "evidence_spans": [{
                    "start_char": start,
                    "end_char": start + len(phrase),
                    "evidence_text": phrase,
                }],
                "evidence_anchor_ids": [],
                "status": "proposed",
                "may_publish_directly": False,
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            build_learning_project(
                [literary], learning, source_projects=[base], observation_file=observations, replace_existing=True
            )
            verification = verify_learning_project(learning, [literary], [base])
            self.assertTrue(verification.valid, verification.reason_codes)
            rows = [json.loads(line) for line in (learning / "model-learning-observations.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["epistemic_tier"], "B")
            self.assertEqual(rows[0]["status"], "proposed")
            self.assertFalse(rows[0]["may_publish_directly"])
            self.assertTrue(rows[0]["requires_human_or_independent_review"])
            summary = query_learning_project(learning, "这本书学到了什么？")
            self.assertEqual(summary["items"][0]["model_learning_observation_count"], 1)

    def test_model_observation_with_inexact_evidence_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base, literary, learning = self.build_chain(root)
            task = json.loads((learning / "model-learning-tasks.jsonl").read_text(encoding="utf-8").splitlines()[0])
            packet = json.loads((learning / "chapter-source-packets.jsonl").read_text(encoding="utf-8").splitlines()[0])
            observations = root / "bad-observations.jsonl"
            observations.write_text(json.dumps({
                "task_id": task["task_id"],
                "observation_type": "chapter_summary",
                "epistemic_tier": "B",
                "statement": "错误证据不能进入学习层。",
                "entity_ids": [],
                "evidence_spans": [{
                    "start_char": packet["start_char"],
                    "end_char": packet["start_char"] + 2,
                    "evidence_text": "错文",
                }],
                "evidence_anchor_ids": [],
                "status": "proposed",
                "may_publish_directly": False,
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_learning_project(
                    [literary], root / "bad-learning", source_projects=[base], observation_file=observations
                )


if __name__ == "__main__":
    unittest.main()
