from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tkr.chapter_project import _source_input
from tkr.evidence_project import _input_records


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _verified() -> SimpleNamespace:
    return SimpleNamespace(valid=True, reason_codes=())


class ExactSourceNewlineTests(unittest.TestCase):
    def test_chapter_project_preserves_crlf_source_binding(self) -> None:
        with TemporaryDirectory() as directory:
            project = Path(directory) / "source"
            text = "第一章 开始\r\n正文。\r\n"
            digest = sha256(text.encode("utf-8")).hexdigest()
            source_path = project / "source" / "normalized-source.txt"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(text.encode("utf-8"))
            _write_json(
                project / "project-report.json",
                {
                    "project_id": "kpr_crlf_chapter",
                    "source_id": "src_crlf_chapter",
                    "source_filename": "fixture.txt",
                    "normalized_source_sha256": digest,
                },
            )
            _write_jsonl(project / "stage2-structure" / "unit-index.jsonl", [{}])
            _write_jsonl(project / "stage2-structure" / "heading-candidates.jsonl", [])
            _write_jsonl(project / "stage1-anomaly" / "anomaly-candidates.jsonl", [])
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                loaded, _ = _source_input(project, 0)
            self.assertEqual(loaded.source_text, text)
            self.assertEqual(sha256(loaded.source_text.encode("utf-8")).hexdigest(), digest)

    def test_evidence_project_preserves_crlf_source_binding(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_project = root / "source-project"
            literary_project = root / "literary-project"
            text = "第一章 开始\r\n正文。\r\n"
            digest = sha256(text.encode("utf-8")).hexdigest()
            source_path = source_project / "source" / "normalized-source.txt"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(text.encode("utf-8"))
            _write_json(
                source_project / "project-report.json",
                {
                    "source_id": "src_crlf_evidence",
                    "normalized_source_sha256": digest,
                },
            )
            _write_json(
                literary_project / "literary-report.json",
                {
                    "source_id": "src_crlf_evidence",
                    "source_sha256": digest,
                },
            )
            _write_jsonl(literary_project / "chapters.jsonl", [])
            _write_jsonl(literary_project / "evidence-anchors.jsonl", [])
            _write_jsonl(literary_project / "assertions.jsonl", [])
            with (
                patch("tkr.evidence_project.verify_secure_knowledge_project", return_value=_verified()),
                patch("tkr.evidence_project.verify_literary_engine", return_value=_verified()),
            ):
                _, _, loaded, chapters, anchors, assertions = _input_records(
                    source_project, literary_project
                )
            self.assertEqual(loaded, text)
            self.assertEqual(sha256(loaded.encode("utf-8")).hexdigest(), digest)
            self.assertEqual(chapters, [])
            self.assertEqual(anchors, [])
            self.assertEqual(assertions, [])


if __name__ == "__main__":
    unittest.main()
