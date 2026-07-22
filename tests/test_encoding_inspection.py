from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tkr.encoding_inspection import (
    ENCODING_INSPECTION_SCHEMA_VERSION,
    EncodingInspectionError,
    inspect_source_encoding,
)


class EncodingInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def test_utf8_chinese_is_strictly_accepted(self) -> None:
        report = inspect_source_encoding(
            self._write("novel.txt", "第一章\n正文\n".encode()), block_size=1
        )
        self.assertEqual(report.schema_version, ENCODING_INSPECTION_SCHEMA_VERSION)
        self.assertEqual(report.selected_encoding, "utf-8")
        self.assertEqual(report.selection_basis, "strict_utf8")
        self.assertTrue(report.strict_decode_passed)
        self.assertEqual(report.recommended_action, "accept")
        self.assertEqual(report.line_count, 2)

    def test_utf8_bom_is_stripped_and_bound(self) -> None:
        report = inspect_source_encoding(
            self._write("bom.txt", b"\xef\xbb\xbf" + "甲\n".encode()),
            block_size=2,
        )
        self.assertEqual(report.bom, "utf-8")
        self.assertEqual(report.selected_encoding, "utf-8")
        self.assertEqual(report.decoded_character_count, 2)
        self.assertEqual(report.embedded_bom_count, 0)
        self.assertEqual(report.recommended_action, "accept")

    def test_utf16_little_endian_bom_is_supported(self) -> None:
        payload = b"\xff\xfe" + "甲\r\n乙".encode("utf-16-le")
        report = inspect_source_encoding(self._write("le.txt", payload), block_size=3)
        self.assertEqual(report.bom, "utf-16-le")
        self.assertEqual(report.selected_encoding, "utf-16-le")
        self.assertEqual(report.newline_type, "crlf")
        self.assertEqual(report.line_count, 2)
        self.assertNotIn("NUL_CHARACTERS_PRESENT", report.warnings)

    def test_utf16_big_endian_bom_is_supported(self) -> None:
        payload = b"\xfe\xff" + "甲\n乙\n".encode("utf-16-be")
        report = inspect_source_encoding(self._write("be.txt", payload), block_size=1)
        self.assertEqual(report.bom, "utf-16-be")
        self.assertEqual(report.selected_encoding, "utf-16-be")
        self.assertEqual(report.line_count, 2)

    def test_bomless_utf16_is_review_only(self) -> None:
        payload = "alpha\nbeta\n".encode("utf-16-le")
        report = inspect_source_encoding(self._write("legacy.txt", payload))
        self.assertEqual(report.selected_encoding, "utf-16-le")
        self.assertEqual(report.selection_basis, "utf16_byte_pattern")
        self.assertEqual(report.recommended_action, "review")
        self.assertIn("BOMLESS_UTF16_CANDIDATE", report.warnings)

    def test_gb18030_fallback_is_review_only(self) -> None:
        payload = "第一章：旧编码文本\n".encode("gb18030")
        report = inspect_source_encoding(self._write("legacy.txt", payload), block_size=3)
        self.assertEqual(report.selected_encoding, "gb18030")
        self.assertEqual(report.selection_basis, "gb18030_fallback")
        self.assertEqual(report.recommended_action, "review")
        self.assertIn("LEGACY_ENCODING_CANDIDATE", report.warnings)

    def test_literal_replacement_character_requires_review(self) -> None:
        report = inspect_source_encoding(
            self._write("replacement.txt", "甲\ufffd乙".encode("utf-8"))
        )
        self.assertEqual(report.replacement_character_count, 1)
        self.assertIn("REPLACEMENT_CHARACTER_PRESENT", report.warnings)
        self.assertEqual(report.recommended_action, "review")

    def test_control_and_nul_characters_require_review(self) -> None:
        report = inspect_source_encoding(self._write("control.txt", b"a\x00b\x01c"))
        self.assertEqual(report.nul_character_count, 1)
        self.assertEqual(report.control_character_count, 2)
        self.assertIn("NUL_CHARACTERS_PRESENT", report.warnings)
        self.assertIn("CONTROL_CHARACTERS_PRESENT", report.warnings)

    def test_unicode_noncharacter_requires_review(self) -> None:
        report = inspect_source_encoding(
            self._write("noncharacter.txt", "甲\ufdd0乙".encode("utf-8"))
        )
        self.assertEqual(report.noncharacter_count, 1)
        self.assertIn("UNICODE_NONCHARACTERS_PRESENT", report.warnings)

    def test_embedded_bom_requires_review(self) -> None:
        report = inspect_source_encoding(
            self._write("embedded.txt", "甲\ufeff乙".encode("utf-8"))
        )
        self.assertEqual(report.embedded_bom_count, 1)
        self.assertIn("EMBEDDED_BOM_PRESENT", report.warnings)

    def test_utf32_bom_is_explicitly_rejected(self) -> None:
        report = inspect_source_encoding(
            self._write("utf32.txt", b"\xff\xfe\x00\x00" + b"A\x00\x00\x00")
        )
        self.assertEqual(report.bom, "utf-32-le")
        self.assertFalse(report.strict_decode_passed)
        self.assertEqual(report.recommended_action, "reject")
        self.assertIn("UNSUPPORTED_BOM", report.blockers)

    def test_bytes_invalid_for_supported_decoders_are_rejected(self) -> None:
        report = inspect_source_encoding(self._write("broken.txt", b"\xff\xff\xff"))
        self.assertIsNone(report.selected_encoding)
        self.assertEqual(report.recommended_action, "reject")
        self.assertIn("NO_SUPPORTED_STRICT_DECODING", report.blockers)
        self.assertIsNotNone(report.decode_error)

    def test_unsupported_suffix_is_rejected_without_decoding(self) -> None:
        report = inspect_source_encoding(self._write("book.pdf", b"plain text"))
        self.assertEqual(report.attempted_encodings, ())
        self.assertEqual(report.recommended_action, "reject")
        self.assertIn("UNSUPPORTED_SUFFIX", report.blockers)

    def test_empty_file_remains_reviewable(self) -> None:
        report = inspect_source_encoding(self._write("empty.txt", b""))
        self.assertEqual(report.selected_encoding, "utf-8")
        self.assertEqual(report.decoded_character_count, 0)
        self.assertEqual(report.line_count, 0)
        self.assertEqual(report.recommended_action, "review")
        self.assertIn("EMPTY_FILE", report.warnings)

    def test_missing_file_and_directory_raise_domain_error(self) -> None:
        with self.assertRaisesRegex(EncodingInspectionError, "does not exist"):
            inspect_source_encoding(self.root / "missing.txt")
        with self.assertRaisesRegex(EncodingInspectionError, "not a regular file"):
            inspect_source_encoding(self.root)


if __name__ == "__main__":
    unittest.main()
