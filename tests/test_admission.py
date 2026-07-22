from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from tkr.admission import (
    AdmissionError,
    SOURCE_IDENTITY_SCHEMA_VERSION,
    inspect_source_identity,
)


class SourceIdentityAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def test_supported_txt_is_accepted_for_encoding_inspection(self) -> None:
        payload = "第一章\n正文\n".encode("utf-8")
        path = self._write("novel.txt", payload)
        report = inspect_source_identity(path, block_size=3)
        self.assertEqual(report.schema_version, SOURCE_IDENTITY_SCHEMA_VERSION)
        self.assertEqual(report.sha256, sha256(payload).hexdigest())
        self.assertEqual(report.source_id, f"source_sha256_{report.sha256}")
        self.assertEqual(report.admission_status, "accepted_for_encoding_inspection")
        self.assertEqual(report.newline_type, "lf")
        self.assertEqual(report.line_count, 2)
        self.assertTrue(report.line_count_reliable)
        self.assertEqual(report.lf_count, 2)
        self.assertEqual(report.crlf_count, 0)
        self.assertEqual(report.cr_count, 0)

    def test_markdown_suffix_is_case_insensitive(self) -> None:
        report = inspect_source_identity(self._write("notes.MD", b"# title"))
        self.assertEqual(report.suffix, ".md")
        self.assertTrue(report.suffix_supported)
        self.assertEqual(report.line_count, 1)

    def test_crlf_split_across_blocks_is_counted_once(self) -> None:
        path = self._write("windows.txt", b"a\r\nb\r\n")
        report = inspect_source_identity(path, block_size=2)
        self.assertEqual(report.newline_type, "crlf")
        self.assertEqual(report.crlf_count, 2)
        self.assertEqual(report.lf_count, 0)
        self.assertEqual(report.cr_count, 0)
        self.assertEqual(report.line_count, 2)

    def test_mixed_newlines_require_review(self) -> None:
        report = inspect_source_identity(self._write("mixed.txt", b"a\nb\r\nc\r"))
        self.assertEqual(report.newline_type, "mixed")
        self.assertEqual(report.line_count, 3)
        self.assertEqual(report.admission_status, "review")
        self.assertIn("MIXED_NEWLINES", report.warnings)

    def test_single_line_without_terminator_counts_as_one(self) -> None:
        report = inspect_source_identity(self._write("single.txt", b"one line"))
        self.assertEqual(report.newline_type, "none")
        self.assertEqual(report.line_count, 1)

    def test_empty_supported_file_requires_review(self) -> None:
        report = inspect_source_identity(self._write("empty.txt", b""))
        self.assertTrue(report.empty_file)
        self.assertEqual(report.size_bytes, 0)
        self.assertEqual(report.line_count, 0)
        self.assertEqual(report.admission_status, "review")
        self.assertIn("EMPTY_FILE", report.warnings)

    def test_nul_bytes_defer_line_count_to_encoding_stage(self) -> None:
        payload = "甲\n乙\n".encode("utf-16-le")
        report = inspect_source_identity(self._write("utf16.txt", payload), block_size=3)
        self.assertTrue(report.contains_nul)
        self.assertIsNone(report.line_count)
        self.assertFalse(report.line_count_reliable)
        self.assertEqual(report.admission_status, "review")
        self.assertIn("NUL_BYTES_PRESENT", report.warnings)

    def test_unsupported_suffix_is_not_admitted(self) -> None:
        report = inspect_source_identity(self._write("archive.pdf", b"%PDF"))
        self.assertFalse(report.suffix_supported)
        self.assertEqual(report.admission_status, "unsupported")
        self.assertEqual(report.blockers, ("UNSUPPORTED_SUFFIX",))

    def test_same_bytes_have_same_content_source_id(self) -> None:
        first = inspect_source_identity(self._write("a.txt", b"same"))
        second = inspect_source_identity(self._write("b.md", b"same"))
        self.assertEqual(first.source_id, second.source_id)
        self.assertNotEqual(first.filename, second.filename)

    def test_report_is_json_serializable_shape(self) -> None:
        report = inspect_source_identity(self._write("shape.txt", b"x\n"))
        mapping = report.to_dict()
        self.assertEqual(mapping["filename"], "shape.txt")
        self.assertEqual(mapping["warnings"], ())
        self.assertEqual(mapping["blockers"], ())

    def test_missing_file_and_directory_raise_admission_error(self) -> None:
        with self.assertRaisesRegex(AdmissionError, "does not exist"):
            inspect_source_identity(self.root / "missing.txt")
        with self.assertRaisesRegex(AdmissionError, "not a regular file"):
            inspect_source_identity(self.root)


if __name__ == "__main__":
    unittest.main()
