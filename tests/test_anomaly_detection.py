from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tkr.anomaly_artifacts import publish_anomaly_artifacts
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
            self._write("clean.txt", "第一章\n正文内容。\n"),
            policy=AnomalyPolicy(window_characters=20, window_stride=20, window_min_characters=10),
        )
        self.assertEqual(report.schema_version, ANOMALY_INSPECTION_SCHEMA_VERSION)
        self.assertEqual(report.scan_status, "completed")
        self.assertEqual(report.finding_count, 0)
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

    def test_long_line_repeated_and_duplicate_rules(self) -> None:
        duplicate = "甲" * 20
        text = "重复\n重复\n重复\n" + duplicate + "\n中间\n中间二\n" + duplicate + "\n"
        policy = AnomalyPolicy(
            max_line_characters=10,
            duplicate_min_characters=10,
            duplicate_min_line_distance=3,
            window_characters=100,
            window_stride=100,
            window_min_characters=50,
        )
        report = inspect_source_anomalies(self._write("rules.txt", text), policy=policy)
        self.assertIn("LINE_EXCEEDS_LENGTH_LIMIT", report.rule_counts)
        self.assertIn("REPEATED_LINE_RUN_CANDIDATE", report.rule_counts)
        self.assertIn("DISTANT_DUPLICATE_PASSAGE_CANDIDATE", report.rule_counts)

    def test_script_shift_remains_candidate(self) -> None:
        chinese = "这是一个完全由中文构成的长段落" * 8
        english = "This is a long ASCII-only paragraph with words and letters. " * 4
        policy = AnomalyPolicy(
            script_shift_min_characters=40,
            window_characters=400,
            window_stride=400,
            window_min_characters=200,
        )
        report = inspect_source_anomalies(
            self._write("shift.txt", chinese + "\n" + english + "\n"), policy=policy
        )
        self.assertIn("ABRUPT_SCRIPT_PROFILE_SHIFT_CANDIDATE", report.rule_counts)

    def test_custom_marker_cluster_requires_multiple_groups(self) -> None:
        groups = (
            MarkerGroup("modern", ("董事会", "经理")),
            MarkerGroup("digital", ("邮件", "直播")),
        )
        policy = AnomalyPolicy(
            marker_min_total=3,
            marker_min_groups=2,
            window_characters=100,
            window_stride=100,
            window_min_characters=50,
        )
        report = inspect_source_anomalies(
            self._write("markers.txt", "董事会通知经理查看邮件。\n"),
            policy=policy,
            marker_groups=groups,
        )
        self.assertIn("CUSTOM_MARKER_CLUSTER_CANDIDATE", report.rule_counts)

    def test_same_language_cross_work_shift_uses_multiple_signals(self) -> None:
        first = (
            "青云宗弟子守在剑阁，灵气沿着丹田运转，众人准备进入秘境。"
            "掌门命令内门弟子携带灵石与法器，前往玄天山谷修炼剑意。"
        ) * 6
        second = (
            "华星公司董事会召开会议，经理通过邮件通知办公室员工。"
            "记者使用手机进行直播，警察驾驶汽车抵达医院和学校。"
        ) * 6
        policy = AnomalyPolicy(
            window_characters=len(first),
            window_stride=len(first),
            window_min_characters=100,
            same_language_max_cosine_similarity=0.45,
            same_language_min_entity_union=2,
            same_language_max_entity_jaccard=0.20,
            same_language_min_register_delta=0.55,
            same_language_min_signals=2,
        )
        report = inspect_source_anomalies(
            self._write("cross.txt", first + second), policy=policy
        )
        matches = [
            finding
            for finding in report.findings
            if finding.rule_id == "SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE"
        ]
        self.assertEqual(len(matches), 1)
        self.assertIn("register=xianxia->modern", matches[0].signals)

    def test_separator_delimited_paragraph_mosaic_emits_one_block_candidate(self) -> None:
        pollution = [
            item * 6
            for item in (
                "黑衣刺客潜入王府寻找密函。", "星际舰队启动量子跃迁引擎。",
                "幼儿园老师分发彩色积木。", "证券交易大厅发布季度财报。",
                "远古巨龙守护熔岩洞穴。", "侦探检查雨夜留下的轮胎印。",
                "厨师把奶油加入巧克力蛋糕。", "机器人维修轨道空间站。",
                "将军命骑兵包围北方城池。", "医生查看病人的影像报告。",
                "海盗升起风帆驶向群岛。", "程序员修复数据库连接故障。",
                "考古队记录沙漠遗址的壁画。", "气象站发布沿海风暴预警。",
            )
        ]
        text = (
            "第一章 测试\n\n青云宗弟子守在剑阁。\n\n"
            + "\n\n".join(pollution)
            + "\n\n----------\n\n第二章 正常\n\n"
            + "青云宗弟子修炼剑意。\n\n青云宗长老传授功法。\n"
        )
        report = inspect_source_anomalies(self._write("mosaic.txt", text))
        matches = [item for item in report.findings if item.rule_id == "SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE"]
        self.assertEqual(len(matches), 1)
        self.assertIn("detector=source_adaptive_paragraph_mosaic", matches[0].signals)
        self.assertTrue(matches[0].evidence_preview.startswith("黑衣刺客"))

    def test_separator_delimited_coherent_chapters_do_not_emit_mosaic_candidate(self) -> None:
        first = "\n\n".join(["青云宗弟子在剑阁修炼灵气与剑意。"] * 12)
        second = "\n\n".join(["青云宗长老带领弟子进入秘境寻找灵石。"] * 12)
        text = f"第一章 起\n\n{first}\n\n----------\n\n第二章 承\n\n{second}\n"
        report = inspect_source_anomalies(self._write("coherent-blocks.txt", text))
        self.assertNotIn("SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE", report.rule_counts)

    def test_single_physical_line_is_still_window_scanned(self) -> None:
        first = "灵气真元丹田元婴宗门法器剑意功法灵石秘境金丹筑基神识" * 20
        second = "公司董事会经理电话邮件网络直播办公室警察汽车手机电脑合同记者" * 20
        size = len(first)
        policy = AnomalyPolicy(
            max_line_characters=100_000,
            window_characters=size,
            window_stride=size,
            window_min_characters=100,
            same_language_max_cosine_similarity=0.30,
            same_language_min_entity_union=1,
            same_language_min_register_delta=0.50,
            same_language_min_signals=2,
        )
        report = inspect_source_anomalies(
            self._write("one-line.txt", first + second), policy=policy
        )
        self.assertGreaterEqual(report.window_count, 2)
        self.assertIn("SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE", report.rule_counts)

    def test_clean_same_register_windows_do_not_raise_cross_work_candidate(self) -> None:
        first = "青云宗弟子在玄天山修炼灵气与剑意。" * 20
        second = "青云宗长老带领弟子进入秘境寻找灵石。" * 20
        size = len(first)
        policy = AnomalyPolicy(
            window_characters=size,
            window_stride=size,
            window_min_characters=100,
            same_language_max_cosine_similarity=0.05,
            same_language_min_signals=3,
        )
        report = inspect_source_anomalies(
            self._write("same.txt", first + second), policy=policy
        )
        self.assertNotIn("SAME_LANGUAGE_CORPUS_SHIFT_CANDIDATE", report.rule_counts)

    def test_finding_limit_is_explicit(self) -> None:
        report = inspect_source_anomalies(
            self._write("limit.txt", "\ufffd\ufffd\ufffd"),
            policy=AnomalyPolicy(max_findings=1),
        )
        self.assertEqual(report.finding_count, 1)
        self.assertIn("FINDING_LIMIT_REACHED", report.warnings)

    def test_unsupported_source_returns_blocked_report(self) -> None:
        path = self.root / "source.pdf"
        path.write_bytes(b"plain text")
        report = inspect_source_anomalies(path)
        self.assertEqual(report.scan_status, "blocked")
        self.assertIn("UNSUPPORTED_SUFFIX", report.blockers)

    def test_policy_validation(self) -> None:
        with self.assertRaises(AnomalyInspectionError):
            AnomalyPolicy(window_stride=801, window_characters=800)
        with self.assertRaises(AnomalyInspectionError):
            AnomalyPolicy(same_language_min_signals=0)

    def test_standard_artifact_set_and_manifest_are_deterministic(self) -> None:
        report = inspect_source_anomalies(self._write("artifacts.txt", "未完待续\n"))
        outdir = self.root / "out"
        first = publish_anomaly_artifacts(report, outdir)
        second = publish_anomaly_artifacts(report, outdir)
        expected = {
            "anomaly-report.json",
            "anomaly-candidates.jsonl",
            "contamination-candidates.jsonl",
            "non-body-content.jsonl",
            "structural-anomalies.jsonl",
            "anomaly-ledger.csv",
            "stage-result.json",
            "artifact-manifest.json",
        }
        self.assertEqual({path.name for path in outdir.iterdir()}, expected)
        self.assertEqual(first, second)
        self.assertFalse(any(path.name.startswith(".") for path in outdir.iterdir()))

    def test_cli_outdir_writes_artifacts(self) -> None:
        source = self._write("cli.txt", "未完待续\n")
        outdir = self.root / "cli-out"
        result = anomaly_cli_main([str(source), "--outdir", str(outdir)])
        self.assertEqual(result, 0)
        manifest = json.loads(
            (outdir / "artifact-manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["project_acceptance_performed"])


if __name__ == "__main__":
    unittest.main()
