from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tkr.evidence_project import (
    build_evidence_project,
    verify_evidence_project,
)
from tkr.literary_engine import build_literary_engine
from tests.test_literary_engine import _make_project, _valid_verification


def _prepare(root: Path) -> tuple[Path, Path]:
    source_project = _make_project(root)
    (source_project / "project-manifest.json").write_text(
        json.dumps({"fixture": True}, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    literary_project = root / "literary"
    with patch(
        "tkr.literary_engine.verify_secure_knowledge_project",
        return_value=_valid_verification(),
    ):
        build_literary_engine(source_project, literary_project)
    return source_project, literary_project


class EvidenceProjectTests(unittest.TestCase):
    def _build(self, root: Path, name: str = "evidence"):
        source_project, literary_project = _prepare(root)
        output = root / name
        with (
            patch(
                "tkr.evidence_project.verify_secure_knowledge_project",
                return_value=_valid_verification(),
            ),
            patch(
                "tkr.evidence_project.verify_literary_engine",
                return_value=_valid_verification(),
            ),
        ):
            result = build_evidence_project(
                source_project,
                literary_project,
                output,
                target_chars=12,
                max_chars=24,
            )
        return source_project, literary_project, output, result

    def test_builds_self_contained_evidence_project(self) -> None:
        with TemporaryDirectory() as directory:
            source_project, literary_project, output, result = self._build(Path(directory))
            self.assertTrue(result.evidence_coverage_complete)
            self.assertTrue(result.claim_graph_valid)
            self.assertEqual(result.evidence_coverage_rate, 1.0)
            self.assertGreater(result.evidence_unit_count, 0)
            self.assertGreater(result.claim_evidence_anchor_count, 0)
            self.assertEqual(result.claim_edge_count, result.assertion_count)

            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "evidence-units.jsonl",
                    "claim-evidence-anchors.jsonl",
                    "claim-evidence-edges.jsonl",
                    "evidence-coverage.json",
                    "claim-graph-report.json",
                    "evidence.sqlite",
                    "evidence-project-report.json",
                    "artifact-manifest.json",
                },
            )
            anchors = [
                json.loads(line)
                for line in (output / "claim-evidence-anchors.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            edges = [
                json.loads(line)
                for line in (output / "claim-evidence-edges.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            anchor_ids = {row["anchor_id"] for row in anchors}
            self.assertTrue(all(row["evidence_id"] in anchor_ids for row in edges))

            connection = sqlite3.connect(output / "evidence.sqlite")
            try:
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM evidence_units").fetchone()[0],
                    result.evidence_unit_count,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM claim_evidence_anchors").fetchone()[0],
                    result.claim_evidence_anchor_count,
                )
            finally:
                connection.close()

            with (
                patch(
                    "tkr.evidence_project.verify_secure_knowledge_project",
                    return_value=_valid_verification(),
                ),
                patch(
                    "tkr.evidence_project.verify_literary_engine",
                    return_value=_valid_verification(),
                ),
            ):
                verification = verify_evidence_project(
                    source_project,
                    literary_project,
                    output,
                )
            self.assertTrue(verification.valid, verification.reason_codes)

    def test_repeated_builds_have_identical_logical_and_database_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_project, literary_project = _prepare(root)
            results = []
            for name in ("evidence-a", "evidence-b"):
                with (
                    patch(
                        "tkr.evidence_project.verify_secure_knowledge_project",
                        return_value=_valid_verification(),
                    ),
                    patch(
                        "tkr.evidence_project.verify_literary_engine",
                        return_value=_valid_verification(),
                    ),
                ):
                    results.append(
                        build_evidence_project(
                            source_project,
                            literary_project,
                            root / name,
                            target_chars=12,
                            max_chars=24,
                        )
                    )
            self.assertEqual(results[0].logical_sha256, results[1].logical_sha256)
            self.assertEqual(results[0].database_sha256, results[1].database_sha256)
            for filename in (
                "evidence-units.jsonl",
                "claim-evidence-anchors.jsonl",
                "claim-evidence-edges.jsonl",
                "evidence-coverage.json",
                "claim-graph-report.json",
                "evidence.sqlite",
            ):
                self.assertEqual(
                    (root / "evidence-a" / filename).read_bytes(),
                    (root / "evidence-b" / filename).read_bytes(),
                )

    def test_tampered_claim_evidence_anchor_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_project, literary_project, output, _ = self._build(root)
            path = output / "claim-evidence-anchors.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            rows[0]["evidence_text"] = rows[0]["evidence_text"] + "伪造"
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
                newline="\n",
            )
            with (
                patch(
                    "tkr.evidence_project.verify_secure_knowledge_project",
                    return_value=_valid_verification(),
                ),
                patch(
                    "tkr.evidence_project.verify_literary_engine",
                    return_value=_valid_verification(),
                ),
            ):
                verification = verify_evidence_project(
                    source_project,
                    literary_project,
                    output,
                )
            self.assertFalse(verification.valid)
            self.assertTrue(
                {
                    "EVIDENCE_FILE_SIZE_MISMATCH",
                    "EVIDENCE_FILE_HASH_MISMATCH",
                    "EVIDENCE_VERIFICATION_EXCEPTION",
                }
                & set(verification.reason_codes)
            )

    def test_unregistered_file_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_project, literary_project, output, _ = self._build(root)
            (output / "unregistered.txt").write_text("unexpected", encoding="utf-8")
            with (
                patch(
                    "tkr.evidence_project.verify_secure_knowledge_project",
                    return_value=_valid_verification(),
                ),
                patch(
                    "tkr.evidence_project.verify_literary_engine",
                    return_value=_valid_verification(),
                ),
            ):
                verification = verify_evidence_project(
                    source_project,
                    literary_project,
                    output,
                )
            self.assertFalse(verification.valid)
            self.assertIn(
                "EVIDENCE_PROJECT_FILE_SET_MISMATCH",
                verification.reason_codes,
            )


if __name__ == "__main__":
    unittest.main()
