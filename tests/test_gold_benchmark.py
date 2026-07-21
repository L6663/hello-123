from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_hybrid_retrieval import RetrievalFixture
from tkr.gold_benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    GOLD_SCHEMA_VERSION,
    BenchmarkError,
    evaluate_gold_benchmark,
    load_gold_cases,
    verify_benchmark_report,
)
from tkr.hybrid_retrieval import parse_predicate_query
from tkr.strict_qa import answer_strict


class GoldBenchmarkFixture(RetrievalFixture):
    def make_benchmark(self, root: Path):
        text = (
            "北门后来改称玄门。"
            "张三击败李四。"
            "玄门位于皇城北侧。"
            "守卫共有100名。"
            "工程始于2001-02-03。"
            "系统允许删除。"
            "来客共有100名。来客共有1000名。"
            "护卫共有20名。后来护卫共有30名。"
        )
        claims = [
            {"evidence": "北门后来改称玄门。", "claim_type": "alias", "subject": "北门", "object": "玄门"},
            {"evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"},
            {"evidence": "玄门位于皇城北侧。", "claim_type": "located_in", "subject": "玄门", "object": "皇城北侧"},
            {"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"},
            {"evidence": "工程始于2001-02-03。", "claim_type": "date", "subject": "工程", "value": "2001-02-03"},
            {"evidence": "系统允许删除。", "claim_type": "permission", "subject": "系统", "object": "删除", "polarity": True},
            {"evidence": "来客共有100名。", "claim_type": "count", "subject": "来客", "value": 100, "unit": "名"},
            {"evidence": "来客共有1000名。", "claim_type": "count", "subject": "来客", "value": 1000, "unit": "名"},
            {"evidence": "护卫共有20名。", "claim_type": "count", "subject": "护卫", "value": 20, "unit": "名"},
            {"evidence": "后来护卫共有30名。", "claim_type": "count", "subject": "护卫", "value": 30, "unit": "名"},
        ]
        paths = self.build(root, [text], claims)
        specs = [
            ("A-ALIAS", "北门后来叫什么？", ["answerable"]),
            ("A-DEFEATS", "张三击败了谁？", ["answerable"]),
            ("A-LOCATION", "玄门位于哪里？", ["answerable"]),
            ("A-COUNT", "守卫有多少名？", ["answerable"]),
            ("A-DATE", "工程什么时候开始？", ["answerable"]),
            ("A-PERMISSION", "系统允许删除吗？", ["answerable"]),
            ("R-OPEN-1", "张三为何背叛师门？", ["unsupported_open_predicate"]),
            ("R-OPEN-2", "玄门是谁发明的？", ["entity_only_no_predicate", "unsupported_open_predicate"]),
            ("R-DIRECTION", "李四击败了谁？", ["relation_direction"]),
            ("R-LEXICAL", "玄门有多少层？", ["lexical_distractor"]),
            ("R-ABSENCE", "系统允许进入吗？", ["absence_not_negative"]),
            ("R-CONTESTED", "来客有多少名？", ["contested_fact", "numeric_prefix"]),
            ("R-TEMPORAL", "护卫有多少名？", ["temporal_scope"]),
        ]
        rows: list[dict[str, object]] = []
        for case_id, question, tags in specs:
            packet = answer_strict(paths[4], question, retrieval_limit=100, max_citations=20)
            parsed = parse_predicate_query(question)
            rows.append(
                {
                    "gold_schema_version": GOLD_SCHEMA_VERSION,
                    "case_id": case_id,
                    "question": question,
                    "expected_decision": packet.decision,
                    "expected_predicate": parsed.predicate,
                    "expected_answer_claim": packet.answer_claim.to_dict() if packet.answer_claim else None,
                    "expected_fact_ids": [item.fact_id for item in packet.citations],
                    "expected_evidence_sha256": [item.evidence_sha256 for item in packet.citations],
                    "source_id_filter": None,
                    "tags": tags,
                }
            )
        gold = root / "gold.jsonl"
        self.write_rows(gold, rows)
        return paths, gold, rows

    @staticmethod
    def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )


class GoldBenchmarkTests(GoldBenchmarkFixture):
    def test_smoke_profile_passes_complete_non_vacuous_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, gold, _ = self.make_benchmark(Path(directory))
            report = evaluate_gold_benchmark(paths[4], gold, profile="smoke")
        self.assertEqual(report.benchmark_schema_version, BENCHMARK_SCHEMA_VERSION)
        self.assertTrue(report.passed, report.blockers)
        self.assertFalse(report.may_certify_release)
        self.assertFalse(report.may_freeze)
        self.assertEqual(report.case_count, 13)
        self.assertEqual(report.metrics["exact_case_accuracy"], 1.0)
        self.assertEqual(report.metrics["hallucination_rate"], 0.0)
        self.assertEqual(report.blockers, ())

    def test_report_is_deterministic_and_recomputes_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            first = evaluate_gold_benchmark(paths[4], gold)
            second = evaluate_gold_benchmark(paths[4], gold)
            verification = verify_benchmark_report(paths[4], gold, first.to_dict())
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.report_id, second.report_id)
        self.assertTrue(verification.accepted)
        self.assertEqual(verification.expected_report_id, first.report_id)

    def test_release_profile_cannot_pass_with_small_smoke_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, gold, _ = self.make_benchmark(Path(directory))
            report = evaluate_gold_benchmark(paths[4], gold, profile="release")
        self.assertFalse(report.passed)
        self.assertFalse(report.may_certify_release)
        self.assertIn("GOLD_CASE_COUNT_BELOW_POLICY_MINIMUM", report.blockers)
        self.assertIn("GOLD_ALIAS_ANSWERED_COVERAGE_BELOW_POLICY_MINIMUM", report.blockers)

    def test_wrong_expected_claim_is_detected_as_wrong_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            forged = deepcopy(rows)
            count_row = next(row for row in forged if row["case_id"] == "A-COUNT")
            count_row["expected_answer_claim"]["value"] = 1000
            self.write_rows(gold, forged)
            report = evaluate_gold_benchmark(paths[4], gold)
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["wrong_answer_count"], 1)
        self.assertGreater(report.metrics["hallucination_rate"], 0.0)
        self.assertIn("METRIC_WRONG_ANSWER_COUNT_ABOVE_POLICY_CEILING", report.blockers)

    def test_overanswer_against_gold_refusal_is_a_hallucination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            forged = deepcopy(rows)
            row = next(item for item in forged if item["case_id"] == "A-COUNT")
            row["expected_decision"] = "refused_insufficient_evidence"
            row["expected_answer_claim"] = None
            row["expected_fact_ids"] = []
            row["expected_evidence_sha256"] = []
            self.write_rows(gold, forged)
            report = evaluate_gold_benchmark(paths[4], gold)
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["overanswer_count"], 1)
        self.assertIn("METRIC_OVERANSWER_COUNT_ABOVE_POLICY_CEILING", report.blockers)

    def test_policy_and_report_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            report = evaluate_gold_benchmark(paths[4], gold)
            forged = report.to_dict()
            forged["policy"]["metric_floors"]["exact_case_accuracy"] = 0.0
            forged["passed"] = True
            result = verify_benchmark_report(paths[4], gold, forged)
        self.assertFalse(result.accepted)
        self.assertIn("IMMUTABLE_POLICY_MISMATCH", result.reason_codes)
        self.assertIn("BENCHMARK_REPORT_RECOMPUTATION_MISMATCH", result.reason_codes)

    def test_gold_hash_change_invalidates_saved_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, rows = self.make_benchmark(root)
            report = evaluate_gold_benchmark(paths[4], gold)
            changed = deepcopy(rows)
            changed[0]["tags"].append("editorial-note")
            self.write_rows(gold, changed)
            result = verify_benchmark_report(paths[4], gold, report.to_dict())
        self.assertFalse(result.accepted)
        self.assertIn("GOLD_FILE_HASH_MISMATCH", result.reason_codes)

    def test_custom_threshold_fields_and_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, gold, rows = self.make_benchmark(root)
            custom = deepcopy(rows)
            custom[0]["thresholds"] = {"exact_case_accuracy": 0.0}
            self.write_rows(gold, custom)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)
            duplicate = deepcopy(rows)
            duplicate[1]["case_id"] = duplicate[0]["case_id"]
            self.write_rows(gold, duplicate)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

    def test_answerable_case_cannot_omit_claim_or_citation_expectations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, gold, rows = self.make_benchmark(root)
            missing = deepcopy(rows)
            missing[0]["expected_fact_ids"] = []
            missing[0]["expected_evidence_sha256"] = []
            self.write_rows(gold, missing)
            with self.assertRaises(BenchmarkError):
                load_gold_cases(gold)

    def test_database_tampering_cannot_produce_a_passing_benchmark(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, gold, _ = self.make_benchmark(root)
            with paths[4].open("ab") as handle:
                handle.write(b"tamper")
            report = evaluate_gold_benchmark(paths[4], gold)
        self.assertFalse(report.passed)
        self.assertGreater(report.metrics["integrity_error_count"], 0)
        self.assertGreater(report.metrics["evaluator_error_count"], 0)

    def test_unknown_profile_cannot_lower_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, gold, _ = self.make_benchmark(Path(directory))
            with self.assertRaises(BenchmarkError):
                evaluate_gold_benchmark(paths[4], gold, profile="custom-zero-threshold")


if __name__ == "__main__":
    unittest.main()
