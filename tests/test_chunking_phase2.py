from __future__ import annotations

import csv
import json
from pathlib import Path
import random
import tempfile
import unittest

from tkr.chunking import (
    Chunk,
    ChunkConfig,
    ChunkValidationError,
    UnitSpan,
    chunk_units,
    stream_chunk_artifacts,
    validate_chunk_file,
)
from tkr.cli import _load_units, main as cli_main


class ChunkingPhase2Tests(unittest.TestCase):
    def test_streaming_artifacts_match_batch_records(self):
        text = ("第一段。第二段！第三段？\n\n" * 100) + "结尾。"
        units = [UnitSpan("u1", 0, len(text), "s1")]
        config = ChunkConfig(90, 12)
        batch, batch_report = chunk_units(text, units, config)

        with tempfile.TemporaryDirectory() as directory:
            chunks_path, report_path, stream_report = stream_chunk_artifacts(
                text, units, config, directory
            )
            rows = [
                Chunk.from_dict(json.loads(line))
                for line in chunks_path.read_text(encoding="utf-8").splitlines()
            ]
            stored_report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual([item.to_dict() for item in rows], [item.to_dict() for item in batch])
        self.assertEqual(stream_report, batch_report)
        self.assertEqual(stored_report, batch_report)

    def test_stream_report_accounts_for_unique_coverage(self):
        text = "甲乙丙丁。" * 200
        units = [UnitSpan("u1", 0, len(text), "s1")]
        config = ChunkConfig(80, 10)
        with tempfile.TemporaryDirectory() as directory:
            _, _, report = stream_chunk_artifacts(text, units, config, directory)
        self.assertEqual(report["covered_new_characters"], len(text))
        self.assertTrue(report["coverage_ok"])
        self.assertGreater(report["total_overlap_characters"], 0)
        self.assertEqual(report["normalized_text_sha256"].__class__, str)

    def test_admission_csv_prefers_body_spans(self):
        text = "标题一\n正文甲甲。\n标题二\n正文乙乙。"
        second_title = text.index("标题二")
        first_body = text.index("正文甲甲。")
        second_body = text.index("正文乙乙。")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_path = root / "unit-index.csv"
            with index_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "source_id",
                        "unit_id",
                        "norm_start",
                        "norm_end",
                        "body_start",
                        "body_end",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "source_id": "novel",
                        "unit_id": "c1",
                        "norm_start": 0,
                        "norm_end": second_title,
                        "body_start": first_body,
                        "body_end": second_title,
                    }
                )
                writer.writerow(
                    {
                        "source_id": "novel",
                        "unit_id": "c2",
                        "norm_start": second_title,
                        "norm_end": len(text),
                        "body_start": second_body,
                        "body_end": len(text),
                    }
                )
            units = _load_units(index_path, len(text), "fallback")

        self.assertEqual(units[0], UnitSpan("c1", first_body, second_title, "novel"))
        self.assertEqual(units[1], UnitSpan("c2", second_body, len(text), "novel"))

    def test_jsonl_unit_index_is_supported(self):
        text = "甲" * 40 + "乙" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "units.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"unit_id": "a", "norm_start": 0, "norm_end": 40}),
                        json.dumps({"unit_id": "b", "norm_start": 40, "norm_end": 80}),
                    ]
                ),
                encoding="utf-8",
            )
            units = _load_units(path, len(text), "s")
        self.assertEqual(units, [UnitSpan("a", 0, 40, "s"), UnitSpan("b", 40, 80, "s")])

    def test_cli_accepts_admission_csv(self):
        text = "标题\n" + ("正文。" * 100)
        body_start = text.index("正文")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "normalized-text.txt"
            input_path.write_text(text, encoding="utf-8")
            units_path = root / "unit-index.csv"
            units_path.write_text(
                "source_id,unit_id,norm_start,norm_end,body_start,body_end\n"
                f"s,c1,0,{len(text)},{body_start},{len(text)}\n",
                encoding="utf-8",
            )
            outdir = root / "chunks"
            result = cli_main(
                [
                    str(input_path),
                    "--units",
                    str(units_path),
                    "--max-chars",
                    "60",
                    "--overlap-chars",
                    "8",
                    "--outdir",
                    str(outdir),
                ]
            )
            first = json.loads((outdir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(result, 0)
        self.assertEqual(first["norm_start"], body_start)
        self.assertFalse(first["text"].startswith("标题"))

    def test_closing_quote_is_kept_with_sentence_boundary(self):
        text = ("甲" * 55) + "。”" + ("乙" * 80)
        units = [UnitSpan("u", 0, len(text), "s")]
        chunks, _ = chunk_units(text, units, ChunkConfig(80, 8))
        self.assertEqual(chunks[0].end_boundary, "sentence")
        self.assertTrue(chunks[0].text.endswith("。”"))
        self.assertFalse(chunks[1].text.startswith("”"))

    def test_decimal_period_is_not_treated_as_sentence_end(self):
        text = "Value 3.14 remains stable and continues for a while. Tail."
        units = [UnitSpan("u", 0, len(text), "s")]
        chunks, _ = chunk_units(text, units, ChunkConfig(10, 1))
        self.assertNotEqual(chunks[0].text, "Value 3.")
        self.assertFalse(chunks[0].text.endswith("3."))

    def test_stream_validator_rejects_reordered_records(self):
        text = "甲乙丙丁。" * 100
        units = [UnitSpan("u", 0, len(text), "s")]
        config = ChunkConfig(50, 5)
        chunks, _ = chunk_units(text, units, config)
        self.assertGreater(len(chunks), 2)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chunks.jsonl"
            reordered = [chunks[1], chunks[0], *chunks[2:]]
            path.write_text(
                "".join(
                    json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
                    for chunk in reordered
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ChunkValidationError):
                validate_chunk_file(path, text, units, config)

    def test_stream_validator_rejects_blank_record(self):
        text = "甲" * 100
        units = [UnitSpan("u", 0, len(text), "s")]
        config = ChunkConfig(60, 5)
        chunks, _ = chunk_units(text, units, config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chunks.jsonl"
            path.write_text(
                json.dumps(chunks[0].to_dict(), ensure_ascii=False) + "\n\n",
                encoding="utf-8",
            )
            with self.assertRaises(ChunkValidationError):
                validate_chunk_file(path, text, units, config)

    def test_randomized_chunking_invariants(self):
        rng = random.Random(20260720)
        alphabet = "甲乙丙丁天地玄黄ABCD 。，！？；：\n\n”」…123."
        for case in range(250):
            length = rng.randint(1, 2500)
            text = "".join(rng.choice(alphabet) for _ in range(length))
            max_chars = rng.randint(1, min(220, max(1, length)))
            overlap = rng.randint(0, max_chars - 1)
            units = [UnitSpan(f"u{case}", 0, len(text), "fuzz")]
            chunks, report = chunk_units(text, units, ChunkConfig(max_chars, overlap))
            self.assertTrue(report["coverage_ok"])
            self.assertEqual(report["covered_new_characters"], len(text))
            self.assertTrue(all(0 < chunk.length <= max_chars for chunk in chunks))
            self.assertTrue(
                all(0 <= chunk.overlap_with_previous <= overlap for chunk in chunks)
            )
            rebuilt = "".join(
                chunk.text[chunk.overlap_with_previous :] for chunk in chunks
            )
            self.assertEqual(rebuilt, text)

    def test_streaming_scale_smoke(self):
        text = ("长篇小说中的一句话。另一句话！\n\n" * 25000) + "终章。"
        units = [UnitSpan("novel", 0, len(text), "scale")]
        config = ChunkConfig(1400, 180)
        with tempfile.TemporaryDirectory() as directory:
            chunks_path, _, report = stream_chunk_artifacts(text, units, config, directory)
            line_count = sum(1 for _ in chunks_path.open("r", encoding="utf-8"))
        self.assertEqual(line_count, report["chunk_count"])
        self.assertLessEqual(report["max_observed_length"], 1400)
        self.assertLessEqual(report["max_observed_overlap"], 180)
        self.assertEqual(report["covered_new_characters"], len(text))


if __name__ == "__main__":
    unittest.main()
