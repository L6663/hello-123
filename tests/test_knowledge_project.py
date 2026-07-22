from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tkr.knowledge_models import KnowledgeProjectError, KnowledgeProjectPolicy
from tkr.knowledge_project import build_knowledge_project, verify_knowledge_project
from tkr.knowledge_query import answer_knowledge_project, verify_knowledge_answer
from tkr.project_cli import main


CORPUS = (
    "玄霄又称青帝。"
    "陆川击败韩岳。"
    "听雪楼位于北境。"
    "守门人允许陆川进入内殿。"
    "剑阵共有十二柄飞剑。"
    "大战发生于2026年7月22日。"
)


class KnowledgeProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temp.name)
        cls.source = cls.root / "corpus.txt"
        cls.source.write_text(CORPUS, encoding="utf-8")
        cls.project = cls.root / "project"
        cls.report = build_knowledge_project(cls.source, cls.project)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def copy_project(self, name: str) -> Path:
        destination = self.root / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(self.project, destination)
        return destination

    def test_build_report_is_non_acceptance(self):
        self.assertEqual(self.report.status, "completed")
        self.assertTrue(self.report.may_query_typed)
        self.assertFalse(self.report.may_answer_open_queries)
        self.assertFalse(self.report.project_acceptance_performed)
        self.assertFalse(self.report.may_accept_project)
        self.assertFalse(self.report.release_candidate)
        self.assertFalse(self.report.may_freeze)

    def test_all_large_stage_artifacts_exist(self):
        expected = [
            "source/source-metadata.json",
            "stage1-anomaly/anomaly-report.json",
            "stage2-structure/structure-report.json",
            "stage3-semantics/semantic-report.json",
            "bridge/accepted-claims.jsonl",
            "bridge/entity/entity-normalization-report.json",
            "index/knowledge.sqlite",
            "index/knowledge.report.json",
            "project-report.json",
            "project-manifest.json",
        ]
        for relative in expected:
            self.assertTrue((self.project / relative).is_file(), relative)

    def test_project_verification(self):
        result = verify_knowledge_project(self.project)
        self.assertTrue(result.valid)
        self.assertTrue(result.may_query_typed)
        self.assertIn("PROJECT_HASH_CHAIN_VERIFIED", result.reason_codes)

    def test_six_predicates_reach_index(self):
        report = json.loads((self.project / "project-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["accepted_claim_count"], 6)
        self.assertEqual(report["fact_count"], 6)

    def test_alias_query(self):
        packet = answer_knowledge_project(self.project, "玄霄叫什么？")
        self.assertEqual(packet.qa_packet["decision"], "answered")
        self.assertIn("青帝", packet.qa_packet["answer_text"])
        self.assertTrue(packet.qa_packet["citations"])

    def test_defeat_query(self):
        packet = answer_knowledge_project(self.project, "陆川击败了谁？")
        self.assertEqual(packet.qa_packet["decision"], "answered")
        self.assertIn("韩岳", packet.qa_packet["answer_text"])

    def test_location_query(self):
        packet = answer_knowledge_project(self.project, "听雪楼位于哪里？")
        self.assertEqual(packet.qa_packet["decision"], "answered")
        self.assertIn("北境", packet.qa_packet["answer_text"])

    def test_unsupported_query_refuses(self):
        packet = answer_knowledge_project(self.project, "这部作品表达了什么主题？")
        self.assertEqual(packet.qa_packet["decision"], "refused_unsupported")
        self.assertFalse(packet.qa_packet["answered"])

    def test_missing_fact_refuses(self):
        packet = answer_knowledge_project(self.project, "陌生人击败了谁？")
        self.assertEqual(packet.qa_packet["decision"], "refused_insufficient_evidence")

    def test_answer_packet_verification(self):
        packet = answer_knowledge_project(self.project, "陆川击败了谁？")
        verification = verify_knowledge_answer(self.project, packet.to_dict())
        self.assertTrue(verification.accepted)
        self.assertTrue(verification.project_valid)
        self.assertTrue(verification.strict_packet_valid)

    def test_answer_packet_is_deterministic(self):
        first = answer_knowledge_project(self.project, "陆川击败了谁？")
        second = answer_knowledge_project(self.project, "陆川击败了谁？")
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_tampered_answer_is_rejected(self):
        payload = answer_knowledge_project(self.project, "陆川击败了谁？").to_dict()
        payload["qa_packet"]["answer_text"] = "伪造答案。"
        result = verify_knowledge_answer(self.project, payload)
        self.assertFalse(result.accepted)

    def test_tampered_project_file_is_rejected(self):
        project = self.copy_project("tampered-source")
        with (project / "bridge" / "normalized-source.txt").open("a", encoding="utf-8") as handle:
            handle.write("篡改")
        self.assertFalse(verify_knowledge_project(project).valid)

    def test_tampered_database_is_rejected(self):
        project = self.copy_project("tampered-db")
        with (project / "index" / "knowledge.sqlite").open("ab") as handle:
            handle.write(b"tamper")
        self.assertFalse(verify_knowledge_project(project).valid)
        with self.assertRaises(KnowledgeProjectError):
            answer_knowledge_project(project, "陆川击败了谁？")

    def test_tampered_manifest_path_is_rejected(self):
        project = self.copy_project("tampered-manifest")
        path = project / "project-manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["files"][0]["path"] = "../escape"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertFalse(verify_knowledge_project(project).valid)

    def test_existing_project_requires_explicit_mode(self):
        with self.assertRaises(KnowledgeProjectError):
            build_knowledge_project(self.source, self.project)

    def test_verified_reuse(self):
        reused = build_knowledge_project(
            self.source,
            self.project,
            policy=KnowledgeProjectPolicy(reuse_verified_project=True),
        )
        self.assertEqual(reused.project_id, self.report.project_id)

    def test_reuse_rejects_changed_source(self):
        changed = self.root / "changed.txt"
        changed.write_text(CORPUS + "新增。", encoding="utf-8")
        with self.assertRaises(KnowledgeProjectError):
            build_knowledge_project(
                changed,
                self.project,
                policy=KnowledgeProjectPolicy(reuse_verified_project=True),
            )

    def test_force_rebuild(self):
        destination = self.root / "force-project"
        first = build_knowledge_project(self.source, destination)
        second = build_knowledge_project(
            self.source,
            destination,
            policy=KnowledgeProjectPolicy(replace_existing_project=True),
        )
        self.assertEqual(first.project_id, second.project_id)
        self.assertTrue(verify_knowledge_project(destination).valid)

    def test_utf16_source_build(self):
        source = self.root / "utf16.txt"
        source.write_bytes(b"\xff\xfe" + CORPUS.encode("utf-16-le"))
        destination = self.root / "utf16-project"
        report = build_knowledge_project(source, destination)
        self.assertEqual(report.selected_encoding, "utf-16-le")
        self.assertNotEqual(report.raw_source_sha256, report.normalized_source_sha256)
        self.assertTrue(verify_knowledge_project(destination).valid)

    def test_no_accepted_claims_blocks_index(self):
        source = self.root / "no-claims.txt"
        source.write_text("这里只是一段没有支持谓词的正文。", encoding="utf-8")
        with self.assertRaises(KnowledgeProjectError):
            build_knowledge_project(source, self.root / "no-claims-project")

    def test_canonical_clean_project(self):
        destination = self.root / "canonical-project"
        report = build_knowledge_project(
            self.source,
            destination,
            policy=KnowledgeProjectPolicy(index_mode="canonical"),
        )
        self.assertEqual(report.index_mode, "canonical")
        self.assertTrue(verify_knowledge_project(destination).valid)

    def test_canonical_project_blocks_paratext(self):
        source = self.root / "paratext.txt"
        source.write_text("陆川击败韩岳。\n请记住本站。", encoding="utf-8")
        with self.assertRaises(KnowledgeProjectError):
            build_knowledge_project(
                source,
                self.root / "paratext-project",
                policy=KnowledgeProjectPolicy(index_mode="canonical"),
            )

    def test_policy_validation(self):
        with self.assertRaises(KnowledgeProjectError):
            KnowledgeProjectPolicy(max_candidates=0)
        with self.assertRaises(KnowledgeProjectError):
            KnowledgeProjectPolicy(reuse_verified_project=True, replace_existing_project=True)

    def test_project_id_is_deterministic(self):
        destination = self.root / "deterministic-project"
        report = build_knowledge_project(self.source, destination)
        self.assertEqual(report.project_id, self.report.project_id)
        self.assertEqual(report.index_logical_sha256, self.report.index_logical_sha256)

    def test_cli_query_and_verify(self):
        answer_path = self.root / "answer.json"
        verify_path = self.root / "verify.json"
        self.assertEqual(
            main(["query", str(self.project), "陆川击败了谁？", "--output", str(answer_path)]),
            0,
        )
        self.assertEqual(main(["verify", str(self.project), "--output", str(verify_path)]), 0)
        self.assertTrue(json.loads(answer_path.read_text(encoding="utf-8"))["qa_packet"]["answered"])
        self.assertTrue(json.loads(verify_path.read_text(encoding="utf-8"))["valid"])

    def test_cli_verify_answer(self):
        packet_path = self.root / "saved-answer.json"
        packet_path.write_text(
            json.dumps(answer_knowledge_project(self.project, "陆川击败了谁？").to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )
        result_path = self.root / "answer-verification.json"
        self.assertEqual(
            main(["verify-answer", str(self.project), str(packet_path), "--output", str(result_path)]),
            0,
        )
        self.assertTrue(json.loads(result_path.read_text(encoding="utf-8"))["accepted"])


if __name__ == "__main__":
    unittest.main()
