from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tkr.semantic_extraction import inspect_source_semantics


class SubjectlessPermissionExtractionTests(unittest.TestCase):
    def scan(self, text: str):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text(text, encoding="utf-8")
            return inspect_source_semantics(path)

    def test_elliptical_ability_modal_is_not_a_typed_permission_candidate(self) -> None:
        report = self.scan("第一章\n不能去！\n")
        matching = [item for item in report.candidates if item.claim_type == "permission"]
        self.assertEqual(matching, [])
        self.assertFalse(any(row.get("claim_type") == "permission" for row in report.accepted_records))

    def test_copular_can_be_phrase_is_not_a_typed_permission_candidate(self) -> None:
        report = self.scan("第一章\n可以是幻境中飞过的鸟雀。\n")
        matching = [item for item in report.candidates if item.claim_type == "permission"]
        self.assertEqual(matching, [])
        self.assertFalse(any(row.get("claim_type") == "permission" for row in report.accepted_records))

    def test_explicit_subjectless_normative_cue_is_not_auto_published(self) -> None:
        report = self.scan("第一章\n禁止通行！\n")
        matching = [item for item in report.candidates if item.claim_type == "permission"]
        self.assertEqual(matching, [])
        self.assertFalse(any(row.get("claim_type") == "permission" for row in report.accepted_records))


if __name__ == "__main__":
    unittest.main()
