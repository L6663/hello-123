from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest
from unittest.mock import patch

from tkr.chapter_project import build_chapter_project, verify_chapter_project
from tests.test_chapter_engine import _combined_source, _standalone_volume_source


def _jsonl(path: Path, rows: tuple[dict[str, object], ...] | list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _materialize(root: Path, source) -> Path:
    project = root / source.project_id
    (project / "source").mkdir(parents=True)
    (project / "source" / "normalized-source.txt").write_text(
        source.source_text, encoding="utf-8", newline=""
    )
    (project / "project-report.json").write_text(
        json.dumps(
            {
                "project_id": source.project_id,
                "source_id": source.source_id,
                "source_filename": source.source_filename,
                "normalized_source_sha256": source.source_sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    units = []
    headings = []
    for row in source.units:
        cooked = dict(row)
        cooked["source_id"] = source.source_id
        cooked["source_sha256"] = source.source_sha256
        units.append(cooked)
    for row in source.headings:
        cooked = dict(row)
        cooked["source_id"] = source.source_id
        cooked["source_sha256"] = source.source_sha256
        headings.append(cooked)
    _jsonl(project / "stage2-structure" / "unit-index.jsonl", units)
    _jsonl(project / "stage2-structure" / "heading-candidates.jsonl", headings)
    _jsonl(
        project / "stage2-structure" / "structure-anomalies.jsonl",
        list(source.structure_findings),
    )
    _jsonl(
        project / "stage1-anomaly" / "anomaly-candidates.jsonl",
        list(source.anomaly_findings),
    )
    return project


def _verified():
    return SimpleNamespace(valid=True, reason_codes=())


class ChapterProjectTests(unittest.TestCase):
    def _projects(self, root: Path) -> list[Path]:
        return [
            _materialize(root, _standalone_volume_source()),
            _materialize(root, _combined_source()),
        ]

    def test_build_verify_and_sqlite_bindings(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self._projects(root)
            output = root / "chapter-project"
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                report = build_chapter_project(projects, output)
                verification = verify_chapter_project(projects, output)
            self.assertEqual(report["chapter_count"], 4)
            self.assertTrue(verification.valid, verification.reason_codes)
            self.assertEqual(verification.chapter_count, 4)
            connection = sqlite3.connect(output / "chapter.sqlite")
            try:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM chapters").fetchone()[0], 4)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_bindings").fetchone()[0], 2)
                address = connection.execute(
                    "SELECT source_filename,title FROM chapters "
                    "WHERE volume_ordinal=3 AND chapter_ordinal=1"
                ).fetchone()
                self.assertEqual(address, ("combined.txt", "新章"))
            finally:
                connection.close()

    def test_repeated_projects_are_logically_and_byte_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self._projects(root)
            first = root / "first"
            second = root / "second"
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                first_report = build_chapter_project(projects, first)
                second_report = build_chapter_project(projects, second)
            self.assertEqual(first_report["logical_sha256"], second_report["logical_sha256"])
            self.assertEqual(first_report["database_sha256"], second_report["database_sha256"])
            for name in (
                "source-bindings.jsonl",
                "chapters.jsonl",
                "canonical-order.jsonl",
                "chapter-findings.jsonl",
                "chapter.sqlite",
            ):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_tampered_artifact_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self._projects(root)
            output = root / "chapter-project"
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                build_chapter_project(projects, output)
            path = output / "chapters.jsonl"
            path.write_text(path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                verification = verify_chapter_project(projects, output)
            self.assertFalse(verification.valid)
            self.assertIn(
                "CHAPTER_FILE_SIZE_MISMATCH:chapters.jsonl",
                verification.reason_codes,
            )

    def test_source_order_is_part_of_verification_binding(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self._projects(root)
            output = root / "chapter-project"
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                build_chapter_project(projects, output)
                verification = verify_chapter_project(list(reversed(projects)), output)
            self.assertFalse(verification.valid)
            self.assertIn("CHAPTER_SOURCE_PROJECT_ORDER_MISMATCH", verification.reason_codes)

    def test_unregistered_file_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            projects = self._projects(root)
            output = root / "chapter-project"
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                build_chapter_project(projects, output)
            (output / "unexpected.txt").write_text("unexpected", encoding="utf-8")
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                verification = verify_chapter_project(projects, output)
            self.assertFalse(verification.valid)
            self.assertIn("CHAPTER_DIRECTORY_FILE_SET_MISMATCH", verification.reason_codes)


if __name__ == "__main__":
    unittest.main()
