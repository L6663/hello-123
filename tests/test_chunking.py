from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from tkr.chunking import (
    ChunkConfig,
    ChunkValidationError,
    UnitSpan,
    chunk_units,
    validate_chunk_config,
    validate_chunks,
    write_chunk_artifacts,
)
from tkr.cli import main as cli_main


class ChunkingTests(unittest.TestCase):
    def make_chunks(self, text: str, max_chars: int = 1400, overlap: int = 180):
        units = [UnitSpan("u1", 0, len(text), "s1")]
        config = ChunkConfig(max_chars=max_chars, overlap_chars=overlap)
        chunks, report = chunk_units(text, units, config)
        validate_chunks(chunks, text, units, config)
        return chunks, report, units, config

    def assert_full_coverage(self, chunks, start: int, end: int):
        self.assertEqual(chunks[0].norm_start, start)
        self.assertEqual(chunks[-1].norm_end, end)
        for previous, current in zip(chunks, chunks[1:]):
            self.assertLessEqual(current.norm_start, previous.norm_end)
            self.assertGreater(current.norm_end, previous.norm_end)

    def test_rejects_boolean_max_chars(self):
        with self.assertRaises(TypeError):
            validate_chunk_config(True, 0)

    def test_rejects_non_integer_overlap(self):
        with self.assertRaises(TypeError):
            validate_chunk_config(100, 1.5)  # type: ignore[arg-type]

    def test_rejects_zero_max_chars(self):
        with self.assertRaises(ValueError):
            validate_chunk_config(0, 0)

    def test_rejects_negative_overlap(self):
        with self.assertRaises(ValueError):
            validate_chunk_config(100, -1)

    def test_rejects_overlap_equal_to_max(self):
        with self.assertRaises(ValueError):
            validate_chunk_config(100, 100)

    def test_small_text_is_one_exact_chunk(self):
        text = "短文本。"
        chunks, report, _, _ = self.make_chunks(text, 100, 10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, text)
        self.assertEqual(report["max_observed_length"], len(text))

    def test_text_exactly_max_chars(self):
        text = "甲" * 64
        chunks, _, _, _ = self.make_chunks(text, 64, 8)
        self.assertEqual([chunk.length for chunk in chunks], [64])

    def test_text_one_over_max_chars(self):
        text = "甲" * 65
        chunks, _, _, _ = self.make_chunks(text, 64, 8)
        self.assertEqual(chunks[0].length, 64)
        self.assertTrue(all(chunk.length <= 64 for chunk in chunks))
        self.assert_full_coverage(chunks, 0, len(text))

    def test_three_thousand_char_paragraphs_never_exceed_budget(self):
        text = ("甲" * 1000) + "\n\n" + ("乙" * 1000) + "\n\n" + ("丙" * 1000)
        chunks, report, _, _ = self.make_chunks(text, 1400, 180)
        self.assertTrue(all(0 < chunk.length <= 1400 for chunk in chunks))
        self.assertTrue(all(0 <= chunk.overlap_with_previous <= 180 for chunk in chunks))
        self.assertLessEqual(report["max_observed_length"], 1400)
        self.assertLessEqual(report["max_observed_overlap"], 180)
        self.assert_full_coverage(chunks, 0, len(text))

    def test_five_thousand_char_paragraph_uses_hard_splits(self):
        text = "无" * 5000
        chunks, report, _, _ = self.make_chunks(text, 1400, 180)
        self.assertGreater(len(chunks), 3)
        self.assertGreater(report["hard_split_count"], 0)
        self.assertTrue(all(chunk.length <= 1400 for chunk in chunks))

    def test_ten_thousand_chars_without_punctuation_terminates(self):
        text = "A" * 10000
        chunks, _, _, _ = self.make_chunks(text, 1400, 180)
        self.assertLess(len(chunks), 20)
        self.assert_full_coverage(chunks, 0, len(text))

    def test_overlap_zero_produces_contiguous_chunks(self):
        text = "A" * 300
        chunks, _, _, _ = self.make_chunks(text, 100, 0)
        for previous, current in zip(chunks, chunks[1:]):
            self.assertEqual(current.norm_start, previous.norm_end)
            self.assertEqual(current.overlap_with_previous, 0)

    def test_max_chars_one_is_supported(self):
        text = "甲乙丙丁"
        chunks, _, _, _ = self.make_chunks(text, 1, 0)
        self.assertEqual([chunk.text for chunk in chunks], list(text))

    def test_prefers_chinese_sentence_boundaries(self):
        text = "甲" * 45 + "。" + "乙" * 45 + "。" + "丙" * 45
        chunks, _, _, _ = self.make_chunks(text, 100, 10)
        self.assertEqual(chunks[0].end_boundary, "sentence")
        self.assertTrue(chunks[0].text.endswith("。"))

    def test_prefers_english_sentence_boundaries(self):
        text = ("alpha " * 12) + "." + (" beta" * 20)
        chunks, _, _, _ = self.make_chunks(text, 100, 10)
        self.assertIn(chunks[0].end_boundary, {"sentence", "whitespace"})
        self.assertTrue(all(chunk.length <= 100 for chunk in chunks))

    def test_prefers_paragraph_boundary(self):
        text = "甲" * 60 + "\n\n" + "乙" * 80
        chunks, _, _, _ = self.make_chunks(text, 100, 10)
        self.assertEqual(chunks[0].end_boundary, "paragraph")
        self.assertTrue(chunks[0].text.endswith("\n\n"))

    def test_mixed_language_and_unicode(self):
        text = "第一幕。Dragon arrives!𠀀随后离开。" * 20
        chunks, _, _, _ = self.make_chunks(text, 90, 12)
        self.assertEqual("".join(chunk.text[chunk.overlap_with_previous :] for chunk in chunks), text)

    def test_no_trailing_newline(self):
        text = "第一段。\n\n第二段没有尾换行"
        chunks, _, _, _ = self.make_chunks(text, 12, 2)
        self.assertEqual(chunks[-1].norm_end, len(text))
        self.assertTrue(chunks[-1].text.endswith("尾换行"))

    def test_multiple_units_never_cross_boundaries(self):
        text = "甲" * 100 + "乙" * 100
        units = [
            UnitSpan("u1", 0, 100, "s"),
            UnitSpan("u2", 100, 200, "s"),
        ]
        config = ChunkConfig(64, 8)
        chunks, report = chunk_units(text, units, config)
        self.assertEqual(report["unit_count"], 2)
        for chunk in chunks:
            if chunk.unit_id == "u1":
                self.assertLessEqual(chunk.norm_end, 100)
            else:
                self.assertGreaterEqual(chunk.norm_start, 100)

    def test_overlapping_units_are_rejected(self):
        text = "甲" * 100
        units = [UnitSpan("u1", 0, 60), UnitSpan("u2", 50, 100)]
        with self.assertRaises(ValueError):
            chunk_units(text, units, ChunkConfig(20, 2))

    def test_chunk_ids_are_deterministic(self):
        text = "甲乙丙。" * 100
        first, _, _, _ = self.make_chunks(text, 80, 10)
        second, _, _, _ = self.make_chunks(text, 80, 10)
        self.assertEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])

    def test_text_change_changes_affected_id(self):
        first, _, _, _ = self.make_chunks("甲" * 100, 60, 10)
        second, _, _, _ = self.make_chunks("乙" + "甲" * 99, 60, 10)
        self.assertNotEqual(first[0].chunk_id, second[0].chunk_id)

    def test_validator_rejects_tampered_text(self):
        text = "甲" * 100
        chunks, _, units, config = self.make_chunks(text, 60, 10)
        tampered = [replace(chunks[0], text="伪造" + chunks[0].text[2:]), *chunks[1:]]
        with self.assertRaises(ChunkValidationError):
            validate_chunks(tampered, text, units, config)

    def test_validator_rejects_tampered_length(self):
        text = "甲" * 100
        chunks, _, units, config = self.make_chunks(text, 60, 10)
        tampered = [replace(chunks[0], length=999), *chunks[1:]]
        with self.assertRaises(ChunkValidationError):
            validate_chunks(tampered, text, units, config)

    def test_validator_rejects_gap(self):
        text = "甲" * 200
        chunks, _, units, config = self.make_chunks(text, 80, 10)
        second = chunks[1]
        tampered = [chunks[0], replace(second, norm_start=chunks[0].norm_end + 1), *chunks[2:]]
        with self.assertRaises(ChunkValidationError):
            validate_chunks(tampered, text, units, config)

    def test_validator_rejects_duplicate_id(self):
        text = "甲" * 200
        chunks, _, units, config = self.make_chunks(text, 80, 10)
        tampered = [chunks[0], replace(chunks[1], chunk_id=chunks[0].chunk_id), *chunks[2:]]
        with self.assertRaises(ChunkValidationError):
            validate_chunks(tampered, text, units, config)

    def test_artifacts_are_compact_and_valid_json(self):
        text = "甲乙丙。" * 30
        chunks, report, _, _ = self.make_chunks(text, 40, 5)
        with tempfile.TemporaryDirectory() as directory:
            chunks_path, report_path = write_chunk_artifacts(chunks, report, directory)
            rows = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
            stored_report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), len(chunks))
        self.assertEqual(stored_report["status"], "accepted")
        self.assertNotIn("generated_at", stored_report)

    def test_cli_whole_file_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "normalized.txt"
            input_path.write_text("甲乙丙。" * 50, encoding="utf-8")
            outdir = root / "out"
            result = cli_main(
                [
                    str(input_path),
                    "--max-chars",
                    "50",
                    "--overlap-chars",
                    "5",
                    "--outdir",
                    str(outdir),
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue((outdir / "chunks.jsonl").exists())
            self.assertTrue((outdir / "chunking-report.json").exists())


if __name__ == "__main__":
    unittest.main()
