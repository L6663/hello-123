from __future__ import annotations

import unittest

from tkr.private_artifact_guard import classify_path, scan_paths


class PrivateArtifactGuardTests(unittest.TestCase):
    def test_clean_public_paths_pass(self) -> None:
        report = scan_paths(
            [
                "README.md",
                "docs/STAGE8_FINAL_PRODUCTIZATION_ACCEPTANCE.md",
                "schemas/private-blind-attestation.schema.json",
                "tests/test_final_acceptance.py",
            ]
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["finding_count"], 0)
        self.assertFalse(report["content_scanned"])
        self.assertFalse(report["private_data_echoed"])

    def test_private_runtime_directory_is_blocked(self) -> None:
        reasons = classify_path(".tkr-private-acceptance/corpus/source.txt")
        self.assertIn("PRIVATE_RUNTIME_DIRECTORY_TRACKED", reasons)

    def test_private_gold_and_observation_artifacts_are_blocked(self) -> None:
        report = scan_paths(
            [
                "literary-benchmark-cases.jsonl",
                "nested/literary-benchmark-observations.jsonl",
                "private-blind-attestation.json",
            ]
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["finding_count"], 3)
        for finding in report["findings"]:
            self.assertIn(
                "PRIVATE_BENCHMARK_ARTIFACT_TRACKED",
                finding["reason_codes"],
            )

    def test_private_corpus_filename_is_blocked(self) -> None:
        self.assertIn(
            "PRIVATE_CORPUS_FILE_TRACKED",
            classify_path("inputs/步剑庭4.txt"),
        )
        self.assertIn(
            "PRIVATE_CORPUS_FILE_TRACKED",
            classify_path("backup/步剑庭-private.zip"),
        )

    def test_schema_and_documentation_names_are_not_false_positives(self) -> None:
        report = scan_paths(
            [
                "schemas/private-blind-attestation.schema.json",
                "docs/private-blind-attestation-format.md",
                "docs/literary-benchmark-cases-guide.md",
            ]
        )
        self.assertTrue(report["passed"])

    def test_authority_flags_remain_false(self) -> None:
        report = scan_paths([])
        self.assertFalse(report["project_acceptance_performed"])
        self.assertFalse(report["release_candidate"])
        self.assertFalse(report["may_release"])
        self.assertFalse(report["may_freeze"])


if __name__ == "__main__":
    unittest.main()
