from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from tkr.hashing import sha256_file
from tests.test_notion_project import Fixture, PatchedVerification, _read_jsonl, _write_json, _write_jsonl


class Stage6R1NotionTests(PatchedVerification):
    def test_assertion_support_is_independent_of_annotation_order(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            rows = _read_jsonl(fixture.literary / "assertions.jsonl")
            _write_jsonl(fixture.literary / "assertions.jsonl", list(reversed(rows)))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            self.assertTrue(fixture.verify(output).valid)

            pages = _read_jsonl(output / "notion-pages.jsonl")
            page_by_record = {
                row["record_id"]: row["page_key"]
                for row in pages
                if row["record_type"] == "literary_assertion"
            }
            relations = {
                (row["source_page_key"], row["relation_type"], row["target_page_key"])
                for row in _read_jsonl(output / "notion-relations.jsonl")
            }
            self.assertIn((page_by_record["las-b"], "support", page_by_record["las-a"]), relations)
            self.assertIn((page_by_record["las-c"], "support", page_by_record["las-b"]), relations)

    def test_reports_are_location_independent(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first-location"
            second = Path(directory) / "second-location"
            fixture.build(first)
            fixture.build(second)
            first_report = json.loads((first / "notion-project-report.json").read_text(encoding="utf-8"))
            second_report = json.loads((second / "notion-project-report.json").read_text(encoding="utf-8"))
            self.assertEqual(first_report["output_directory"], ".")
            self.assertEqual(first_report, second_report)

    def test_relation_table_has_two_page_foreign_keys(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            connection = sqlite3.connect(output / "notion.sqlite")
            try:
                rows = connection.execute("PRAGMA foreign_key_list(relations)").fetchall()
            finally:
                connection.close()
            self.assertEqual(sorted(row[2] for row in rows), ["pages", "pages"])

    def test_cross_store_verifier_detects_field_drift_with_rehashed_container(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)

            database = output / "notion.sqlite"
            connection = sqlite3.connect(database)
            try:
                page_key = connection.execute("SELECT page_key FROM pages ORDER BY page_key LIMIT 1").fetchone()[0]
                connection.execute("UPDATE pages SET title=? WHERE page_key=?", ("tampered-title", page_key))
                connection.commit()
            finally:
                connection.close()

            report_path = output / "notion-project-report.json"
            manifest_path = output / "artifact-manifest.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            database_hash = sha256_file(database)
            report["database_sha256"] = database_hash
            _write_json(report_path, report)
            manifest["database_sha256"] = database_hash
            for entry in manifest["files"]:
                path = output / entry["path"]
                entry["size_bytes"] = path.stat().st_size
                entry["sha256"] = sha256_file(path)
            _write_json(manifest_path, manifest)

            verification = fixture.verify(output)
            self.assertFalse(verification.valid)
            self.assertIn("NOTION_DATABASE_PAGES_ROW_MISMATCH", verification.reason_codes)


if __name__ == "__main__":
    import unittest

    unittest.main()
