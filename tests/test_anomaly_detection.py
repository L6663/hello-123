from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tkr.anomaly_cli import main as anomaly_cli_main
from tkr.anomaly_detection import (
    ANOMALY_INSPECTION_SCHEMA_VERSION,
    AnomalyInspectionError,
    AnomalyPolicy,
    MarkerGroup,
    inspect_source_anomalies,
)


class AnomalyDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, text: str, encoding: str = "utf-8") -> Path:
        path = self.root / name
        path.write_bytes(text.encode(encoding))
        return path

    def test_clean_source_produces_no_candidates(self) -> None:
        report = inspect_source_anomalies(
            self._write("clean.txt", "第一章\n正文内容。\n")
        )
        self.assertEqual(report.schema_version, ANOMALY_INSPECTION_SCHEMA_VERSION)
        self.assertEqual(report.scan_status, "completed")
        self.assertEqual(report.finding_count, 0)
        self.assertEqual(report.recommended_action, "no_candidates_detected")
        self.assertFalse(report.project_acceptance_performed)
        self.assertFalse(report.may_accept_project)
        self.assertFalse(report.may_freeze)

    def test_unicode_anomaly_has_exact_span_and_deterministic_id(self) -> None:
        path = self._write("unicode.txt", "甲\ufffd乙\n")
        first = inspect_source_anomalies(path)
        second = inspect_source_anomalies(path)
        finding = first.findings[0]
        self.assertEqual(finding.rule_id, "UNICODE_REPLACEMENT_CHARACTER")
        self.assertEqual((finding.start_char, finding.end_char), (1, 2))
        self.assertEqual((finding.start_line, finding.end_line), (1, 1))
        self.assertEqual(finding.finding_id, second.findings[0].finding_id)

    def test_utf8_bom_is_not_counted_in_character_offsets(self) -> None:
        path = self.root / "bom.txt"
        path.write_bytes(b"\xef\xbb\xbf" + "甲\ufffd乙".encode("utf-8"))
        finding = inspect_source_anomalies(path).findings[0]
        self.assertEqual(finding.start_char, 1)

    def test_web_residue_and_paratext_are_separate_categories(self) -> None:
        path = self._write(
            "residue.txt",
            "作者有话说：感谢支持\n未完待续，请访问www.example.com\n",
        )
        report = inspect_source_anomalies(path)
        self.assertIn("paratext_candidate", report.category_counts)
        self.assertIn("contamination_candidate", report.category_counts)
        self.assertIn("AUTHOR_META_OR_PARATEXT_CANDIDATE", report.rule_counts)
        self.assertIn("WEB_RESIDUE_CANDIDATE", report.rule_counts)

    def test_very_long_line_is_a_structural_candidate(self) -> None:
        policy = AnomalyPolicy(max_line_characters=5)
        report = inspect_source_anomalies(
            self._write("long.txt", "一二三四五六\n"), policy=policy
        )
        self.assertEqual(report.findings[0].rule_id, "LINE_EXCEEDS_LENGTH_LIMIT")

    def test_repeated_line_run_is_reported_once_at_threshold(self) -> None:
        policy = AnomalyPolicy(repeated_line_run=3)
        report = inspect_source_anomalies(
            self._write("repeat.txt", "重复内容\n重复内容\n重复内容\n重复内容\n"),
            policy=policy,
        )
        matches = [
            finding
            for finding in report.findings
            if finding.rule_id == "REPEATED_LINE_RUN_CANDIDATE"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual((matches[0].start_line, matches[0].end_line), (3, 3))
        self.assertIn("run_length=3", matches[0].signals)

    def test_distant_duplicate_passage_is_reported(self) -> None:
        duplicate = "甲" * 20
        text = duplicate + "\n中间\n中间二\n" + duplicate + "\n"
        policy = AnomalyPolicy(
            duplicate_min_characters=10,
            duplicate_min_line_distance=3,
        )
        report = inspect_source_anomalies(
            self._write("duplicate.txt", text), policy=policy
        )
        matches = [
            finding
            for finding in report.findings
            if finding.rule_id == "DISTANT_DUPLICATE_PASSAGE_CANDIDATE"
        ]
        self.assertEqual(len(matches), 1)
        self.assertIn("first_line=1", matches[0].signals)

    def test_abrupt_script_shift_is_low_confidence_candidate(self) -> None:
        chinese = "这是一个完全由中文构成的长段落" * 8
        english = "This is a long ASCII-only paragraph with words and letters. " * 4
        policy = AnomalyPolicy(script_shift_min_characters=40)
        report = inspect_source_anomalies(
            self._write("shift.txt", chinese + "\n" + english + "\n"),
            policy=policy,
        )
        matches = [
            finding
            for finding in report.findings
            if finding.rule_id == "ABRUPT_SCRIPT_PROFILE_SHIFT_CANDIDATE"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].confidence, "medium")
        self.assertEqual(matches[0].severity, "low")

    def test_custom_marker_cluster_requires_multiple_groups(self) -> None:
        groups = (
            MarkerGroup("modern", ("董事会", "经理")),
            MarkerGroup("digital", ("邮件", "直播")),
        )
        policy = AnomalyPolicy(marker_min_total=3, marker_min_groups=2)
        report = inspect_source_anomalies(
            self._write("markers.txt", "董事会通知经理查看邮件。\n"),
            policy=policy,
            marker_groups=groups,
        )
        matches = [
            finding
            for finding in report.findings
            if finding.rule_id == "CUSTOM_MARKER_CLUSTER_CANDIDATE"
        ]
        self.assertEqual(len(matches), 1)
        self.assertIn("groups=modern,digital", matches[0].signals)

    def test_finding_limit_is_explicit_and_never_silent(self) -> None:
        policy = AnomalyPolicy(max_findings=1)
        report = inspect_source_anomalies(
            self._write("limit.txt", "\ufffd\ufffd\ufffd"), policy=policy
        )
        self.assertEqual(report.finding_count, 1)
        self.assertIn("FINDING_LIMIT_REACHED", report.warnings)
        self.assertEqual(
            report.recommended_action,
            "review_candidates_incomplete_due_to_limit",
        )

    def test_unsupported_source_returns_blocked_report(self) -> None:
        path = self.root / "source.pdf"
        path.write_bytes(b"plain text")
        report = inspect_source_anomalies(path)
        self.assertEqual(report.scan_status, "blocked")
        self.assertEqual(report.finding_count, 0)
        self.assertIn("UNSUPPORTED_SUFFIX", report.blockers)
        self.assertFalse(report.may_accept_project)

    def test_invalid_policy_and_marker_groups_raise_domain_error(self) -> None:
        with self.assertRaises(AnomalyInspectionError):
            AnomalyPolicy(max_findings=0)
        with self.assertRaises(AnomalyInspectionError):
            MarkerGroup("", ("x",))
        path = self._write("source.txt", "正文")
        groups = (
            MarkerGroup("same", ("甲",)),
            MarkerGroup("same", ("乙",)),
        )
        with self.assertRaisesRegex(AnomalyInspectionError, "unique"):
            inspect_source_anomalies(path, marker_groups=groups)

    def test_cli_writes_atomic_json_report(self) -> None:
        source = self._write("cli.txt", "未完待续\n")
        output = self.root / "report.json"
        result = anomaly_cli_main([str(source), "--output", str(output)])
        self.assertEqual(result, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["scan_status"], "completed")
        self.assertFalse(payload["project_acceptance_performed"])
        self.assertFalse((self.root / ".report.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
