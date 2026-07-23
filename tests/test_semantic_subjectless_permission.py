from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tkr.semantic_extraction import inspect_source_semantics


class SubjectlessPermissionExtractionTests(unittest.TestCase):
    def test_elliptical_permission_is_review_only(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text("第一章\n不能去！\n", encoding="utf-8")
            report = inspect_source_semantics(path)
            matching = [item for item in report.candidates if item.claim_type == "permission"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].validation_status, "review")
            self.assertFalse(matching[0].may_index)
            self.assertIn("PERMISSION_SUBJECT_REQUIRED", matching[0].validation_reason_codes)
            self.assertFalse(any(row.get("claim_type") == "permission" for row in report.accepted_records))

    def test_copular_can_be_phrase_is_not_a_canonical_permission(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text("第一章\n可以是幻境中飞过的鸟雀。\n", encoding="utf-8")
            report = inspect_source_semantics(path)
            matching = [item for item in report.candidates if item.claim_type == "permission"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].validation_status, "review")
            self.assertFalse(matching[0].may_index)
            self.assertFalse(any(row.get("claim_type") == "permission" for row in report.accepted_records))


if __name__ == "__main__":
    unittest.main()
