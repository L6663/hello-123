from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tkr.evidence_project import build_evidence_project, verify_evidence_project
from tkr.literary_engine import build_literary_engine, verify_literary_engine
from tkr.learning_engine import build_learning_project, verify_learning_project
from tkr.project_security import build_secure_engineered_project, verify_secure_knowledge_project


class LegacyEncodingEvidenceContractTests(unittest.TestCase):
    def test_gb18030_uses_raw_and_normalized_hashes_at_their_correct_layers(self) -> None:
        text = (
            "第一章 开始\r\n"
            "云澈击败萧玉。\r\n"
            "第二章 继续\r\n"
            "天毒珠位于玄天大陆。\r\n"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "legacy.txt"
            source.write_bytes(text.encode("gb18030"))
            base = root / "base"
            literary = root / "literary"
            evidence = root / "evidence"
            learning = root / "learning"

            build_secure_engineered_project(
                source,
                base,
                profile="balanced",
                state_directory=root / "state",
            )
            self.assertTrue(verify_secure_knowledge_project(base).valid)
            source_report = json.loads((base / "project-report.json").read_text(encoding="utf-8"))
            self.assertEqual(source_report["selected_encoding"], "gb18030")
            self.assertNotEqual(
                source_report["raw_source_sha256"],
                source_report["normalized_source_sha256"],
            )

            build_literary_engine(base, literary)
            self.assertTrue(verify_literary_engine(literary).valid)
            chapters = [
                json.loads(line)
                for line in (literary / "chapters.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(chapters)
            self.assertEqual(
                {row["source_sha256"] for row in chapters},
                {source_report["normalized_source_sha256"]},
            )

            result = build_evidence_project(base, literary, evidence)
            self.assertGreater(result.evidence_unit_count, 0)
            self.assertTrue(verify_evidence_project(base, literary, evidence).valid)

            build_learning_project([literary], learning, source_projects=[base])
            learning_verification = verify_learning_project(learning, [literary], [base])
            self.assertTrue(learning_verification.valid, learning_verification.reason_codes)
            learning_report = json.loads((learning / "learning-report.json").read_text(encoding="utf-8"))
            self.assertEqual(
                learning_report["complete_chapter_packet_count"],
                learning_report["chapter_card_count"],
            )


if __name__ == "__main__":
    unittest.main()
