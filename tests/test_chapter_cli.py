from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tkr.chapter_cli import main
from tkr.chapter_project import build_chapter_project
from tests.test_chapter_project import _materialize
from tests.test_chapter_engine import _combined_source, _standalone_volume_source


def _verified():
    return SimpleNamespace(valid=True, reason_codes=())


class ChapterCliTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[list[Path], Path]:
        projects = [
            _materialize(root, _standalone_volume_source()),
            _materialize(root, _combined_source()),
        ]
        output = root / "chapter-project"
        with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
            build_chapter_project(projects, output)
        return projects, output

    def _run(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stream = StringIO()
        with redirect_stdout(stream):
            code = main(args)
        return code, json.loads(stream.getvalue())

    def test_query_by_address_returns_exact_source_location(self) -> None:
        with TemporaryDirectory() as directory:
            projects, output = self._fixture(Path(directory))
            args = [
                "query",
                str(output),
                "--source-project",
                str(projects[0]),
                "--source-project",
                str(projects[1]),
                "--address",
                "3",
                "1",
            ]
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                code, payload = self._run(args)
            self.assertEqual(code, 0)
            self.assertEqual(payload["decision"], "answered")
            self.assertEqual(len(payload["chapters"]), 1)
            chapter = payload["chapters"][0]
            self.assertEqual(chapter["source_filename"], "combined.txt")
            self.assertEqual(chapter["title"], "新章")
            self.assertIsInstance(chapter["start_char"], int)
            self.assertIsInstance(chapter["content_sha256"], str)

    def test_physical_and_canonical_neighbor_directions_are_separate(self) -> None:
        with TemporaryDirectory() as directory:
            projects, output = self._fixture(Path(directory))
            chapters = [
                json.loads(line)
                for line in (output / "chapters.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            target = next(
                item
                for item in chapters
                if item["volume_ordinal"] == 2 and item["chapter_ordinal"] == 2
            )
            common = [
                "query",
                str(output),
                "--source-project",
                str(projects[0]),
                "--source-project",
                str(projects[1]),
                "--chapter-id",
                target["chapter_id"],
            ]
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                physical_code, physical = self._run([*common, "--neighbors", "physical"])
                canonical_code, canonical = self._run([*common, "--neighbors", "canonical"])
            self.assertEqual((physical_code, canonical_code), (0, 0))
            self.assertIsNone(physical["neighbors"]["previous"])
            self.assertEqual(
                physical["neighbors"]["next"]["chapter_ordinal"],
                1,
            )
            self.assertEqual(
                canonical["neighbors"]["previous"]["chapter_ordinal"],
                1,
            )
            self.assertEqual(
                physical["neighbors"]["next"]["chapter_id"],
                canonical["neighbors"]["previous"]["chapter_id"],
            )
            self.assertEqual(
                (
                    canonical["neighbors"]["next"]["volume_ordinal"],
                    canonical["neighbors"]["next"]["chapter_ordinal"],
                ),
                (3, 1),
            )

    def test_missing_address_refuses_instead_of_guessing(self) -> None:
        with TemporaryDirectory() as directory:
            projects, output = self._fixture(Path(directory))
            args = [
                "query",
                str(output),
                "--source-project",
                str(projects[0]),
                "--source-project",
                str(projects[1]),
                "--address",
                "9",
                "999",
            ]
            with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
                code, payload = self._run(args)
            self.assertEqual(code, 2)
            self.assertEqual(payload["decision"], "refused")
            self.assertIn("CHAPTER_ADDRESS_NOT_FOUND", payload["reason_codes"])


if __name__ == "__main__":
    unittest.main()
