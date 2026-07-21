from __future__ import annotations

from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from test_gold_benchmark import GoldBenchmarkFixture
from tkr.gold_benchmark import (
    POLICIES,
    BenchmarkError,
    evaluate_gold_benchmark,
    load_gold_cases,
    verify_benchmark_report,
)


class GoldBenchmarkAdversarialTests(GoldBenchmarkFixture):
    def test_builtin_policy_registry_and_nested_thresholds_are_immutable(self):
        with self.assertRaises(TypeError):
            POLICIES["custom"] = POLICIES["smoke"]
        with self.assertRaises(TypeError):
            POLICIES["release"].metric_floors["exact_case_accuracy"] = 0.0
        with self.assertRaises(TypeError):
            POLICIES["release"].min_refusal_by_decision["refused_unsupported"] = 0

    def test_spoofed_hard_negative_tags_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, gold, rows = self.make_benchmark(root)
            spoofed = deepcopy(rows)
            answered = next(row for row in spoofed if row["case_id"] == "A-COUNT")
            answered["tags"].append("temporal_scope")
            self.write_rows(gold, spoofed)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

            spoofed = deepcopy(rows)
            location_refusal = next(row for row in spoofed if row["case_id"] == "R-LEXICAL")
            location_refusal["tags"].append("absence_not_negative")
            self.write_rows(gold, spoofed)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

    def test_relation_direction_tag_requires_reverse_fact_in_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            spoofed = deepcopy(rows)
            direction = next(row for row in spoofed if row["case_id"] == "R-DIRECTION")
            direction["question"] = "王五击败了谁？"
            self.write_rows(gold, spoofed)
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["hard_negative_validation_error_count"], 1)
        self.assertIn(
            "METRIC_HARD_NEGATIVE_VALIDATION_ERROR_COUNT_ABOVE_POLICY_CEILING",
            report.blockers,
        )

    def test_smoke_report_cannot_satisfy_required_release_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            smoke = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            result = verify_benchmark_report(
                paths[4],
                gold,
                smoke.to_dict(),
                expected_profile="release",
            )
        self.assertFalse(result.accepted)
        self.assertIn("BENCHMARK_REQUIRED_PROFILE_MISMATCH", result.reason_codes)

    def test_invalid_required_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            smoke = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            result = verify_benchmark_report(
                paths[4],
                gold,
                smoke.to_dict(),
                expected_profile="custom-zero-threshold",
            )
        self.assertFalse(result.accepted)
        self.assertIn("BENCHMARK_REQUIRED_PROFILE_INVALID", result.reason_codes)

    def test_invalid_hash_and_duplicate_expectations_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, gold, rows = self.make_benchmark(root)
            invalid_hash = deepcopy(rows)
            invalid_hash[0]["expected_evidence_sha256"] = ["not-a-sha256"]
            self.write_rows(gold, invalid_hash)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

            duplicated = deepcopy(rows)
            duplicated[0]["expected_fact_ids"].append(duplicated[0]["expected_fact_ids"][0])
            self.write_rows(gold, duplicated)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

    def test_authority_and_extra_field_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
            forged = report.to_dict()
            forged["may_freeze"] = True
            forged["unreviewed_authority"] = True
            result = verify_benchmark_report(paths[4], gold, forged)
        self.assertFalse(result.accepted)
        self.assertIn("BENCHMARK_REPORT_FIELDS_UNEXPECTED", result.reason_codes)
        self.assertIn("BENCHMARK_FREEZE_AUTHORITY_MISMATCH", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
