from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from tkr.claim_cli import main as claim_cli_main
from tkr.claim_validation import (
    ClaimCandidate,
    ClaimValidationError,
    VALIDATOR_VERSION,
    validate_claim,
)
from tkr.chunking import UnitSpan


class ClaimValidationTests(unittest.TestCase):
    def validate(
        self,
        evidence: str,
        *,
        claim_type: str,
        subject: str,
        object: str = "",
        value=None,
        unit: str = "",
        polarity: bool = True,
        prefix: str = "",
        suffix: str = "",
        unit_span: UnitSpan | None = None,
        require_unit: bool = False,
    ):
        source = prefix + evidence + suffix
        start = len(prefix)
        end = start + len(evidence)
        candidate = ClaimCandidate(
            claim_type=claim_type,
            subject=subject,
            object=object,
            value=value,
            unit=unit,
            polarity=polarity,
            source_id="s",
            unit_id="u",
            evidence_start=start,
            evidence_end=end,
            evidence_text=evidence,
        )
        return validate_claim(
            candidate,
            source,
            unit_span=unit_span,
            require_unit=require_unit,
        )

    def test_alias_exact_match_is_accepted(self):
        result = self.validate(
            "北门后来改称玄门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertEqual(result.status, "accepted")
        self.assertTrue(result.may_index)
        self.assertIn("EXACT_TYPED_ALIAS_MATCH", result.reason_codes)

    def test_alias_is_symmetric_for_equivalence(self):
        result = self.validate(
            "玄门又称北门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertEqual(result.status, "accepted")

    def test_unrelated_alias_marker_does_not_validate_wrong_pair(self):
        result = self.validate(
            "玄门并非北门，南门又称北门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("ALIAS_RELATION_NOT_FOUND", result.reason_codes)

    def test_alias_requires_relation_marker(self):
        result = self.validate(
            "北门和玄门都在城中。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertEqual(result.status, "rejected")

    def test_defeat_direction_is_preserved(self):
        result = self.validate(
            "李四击败张三。",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("RELATION_DIRECTION_MISMATCH", result.reason_codes)

    def test_defeat_exact_direction_is_accepted(self):
        result = self.validate(
            "张三在决斗中击败李四。",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "accepted")
        self.assertIn("EXACT_TYPED_DEFEAT_MATCH", result.reason_codes)

    def test_negated_defeat_is_rejected(self):
        result = self.validate(
            "张三并未击败李四。",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("NEGATED_RELATION", result.reason_codes)

    def test_location_direction_is_preserved(self):
        result = self.validate(
            "乙位于甲。",
            claim_type="located_in",
            subject="甲",
            object="乙",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("RELATION_DIRECTION_MISMATCH", result.reason_codes)

    def test_location_exact_match_is_accepted(self):
        result = self.validate(
            "甲位于乙境内。",
            claim_type="located_in",
            subject="甲",
            object="乙",
        )
        self.assertEqual(result.status, "accepted")

    def test_negated_location_is_rejected(self):
        result = self.validate(
            "甲并非位于乙。",
            claim_type="located_in",
            subject="甲",
            object="乙",
        )
        self.assertEqual(result.status, "rejected")

    def test_subjectless_permission_routes_to_review_before_polarity_evaluation(self):
        result = self.validate(
            "不可以删除。",
            claim_type="permission",
            subject="",
            object="删除",
            polarity=True,
        )
        self.assertEqual(result.status, "review")
        self.assertFalse(result.may_index)
        self.assertIn("PERMISSION_SUBJECT_REQUIRED", result.reason_codes)

    def test_negative_permission_is_accepted(self):
        result = self.validate(
            "管理员不得删除档案。",
            claim_type="permission",
            subject="管理员",
            object="删除档案",
            polarity=False,
        )
        self.assertEqual(result.status, "accepted")

    def test_positive_permission_with_actor_is_accepted(self):
        result = self.validate(
            "管理员可以删除草稿。",
            claim_type="permission",
            subject="管理员",
            object="删除草稿",
            polarity=True,
        )
        self.assertEqual(result.status, "accepted")

    def test_count_100_does_not_match_1000(self):
        result = self.validate(
            "城中共有1000名访客。",
            claim_type="count",
            subject="访客",
            value=100,
            unit="名",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("NUMERIC_VALUE_MISMATCH", result.reason_codes)

    def test_exact_arabic_count_is_accepted(self):
        result = self.validate(
            "城中共有100名访客。",
            claim_type="count",
            subject="访客",
            value=100,
            unit="名",
        )
        self.assertEqual(result.status, "accepted")

    def test_digits_inside_subject_name_are_not_competing_count_values(self):
        result = self.validate(
            "阵列00共有3枚令牌。",
            claim_type="count",
            subject="阵列00",
            value=3,
            unit="枚",
        )
        self.assertEqual(result.status, "accepted")
        self.assertNotIn("MULTIPLE_COUNT_VALUES", result.reason_codes)

    def test_ordinal_digits_inside_subject_name_are_not_count_values(self):
        result = self.validate(
            "第2阵列共有3枚令牌。",
            claim_type="count",
            subject="第2阵列",
            value=3,
            unit="枚",
        )
        self.assertEqual(result.status, "accepted")

    def test_chinese_digit_inside_count_cue_is_not_competing_value(self):
        result = self.validate(
            "阵列06一共9枚令牌。",
            claim_type="count",
            subject="阵列06",
            value=9,
            unit="枚令牌",
        )
        self.assertEqual(result.status, "accepted")

    def test_exact_chinese_count_is_accepted(self):
        result = self.validate(
            "城中共有一百名访客。",
            claim_type="count",
            subject="访客",
            value=100,
            unit="名",
        )
        self.assertEqual(result.status, "accepted")

    def test_chinese_count_mismatch_is_rejected(self):
        result = self.validate(
            "城中共有一千名访客。",
            claim_type="count",
            subject="访客",
            value="一百",
            unit="名",
        )
        self.assertEqual(result.status, "rejected")

    def test_count_unit_must_match_when_declared(self):
        result = self.validate(
            "仓库共有100箱物资。",
            claim_type="count",
            subject="物资",
            value=100,
            unit="名",
        )
        self.assertEqual(result.status, "rejected")

    def test_exact_chinese_date_is_accepted(self):
        result = self.validate(
            "张三出生于2001年2月3日。",
            claim_type="date",
            subject="张三",
            value="2001-02-03",
        )
        self.assertEqual(result.status, "accepted")

    def test_date_mismatch_is_rejected(self):
        result = self.validate(
            "张三出生于2001年2月3日。",
            claim_type="date",
            subject="张三",
            value="2001-02-04",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("DATE_VALUE_MISMATCH", result.reason_codes)

    def test_unsupported_type_routes_to_review(self):
        result = self.validate(
            "张三性格沉稳。",
            claim_type="personality",
            subject="张三",
            object="沉稳",
        )
        self.assertEqual(result.status, "review")
        self.assertFalse(result.may_index)
        self.assertFalse(result.may_freeze)

    def test_evidence_text_mismatch_is_rejected(self):
        source = "北门改称玄门。"
        candidate = ClaimCandidate(
            claim_type="alias",
            subject="北门",
            object="玄门",
            source_id="s",
            unit_id="u",
            evidence_start=0,
            evidence_end=len(source),
            evidence_text="伪造证据",
        )
        result = validate_claim(candidate, source)
        self.assertEqual(result.status, "rejected")
        self.assertIn("EVIDENCE_TEXT_MISMATCH", result.reason_codes)

    def test_evidence_outside_bound_unit_is_rejected(self):
        source = "前言。北门改称玄门。后记。"
        start = source.index("北门")
        end = start + len("北门改称玄门。")
        candidate = ClaimCandidate(
            claim_type="alias",
            subject="北门",
            object="玄门",
            source_id="s",
            unit_id="u",
            evidence_start=start,
            evidence_end=end,
            evidence_text=source[start:end],
        )
        unit = UnitSpan("u", 0, 3, "s")
        result = validate_claim(candidate, source, unit_span=unit, require_unit=True)
        self.assertEqual(result.status, "rejected")
        self.assertIn("EVIDENCE_OUTSIDE_UNIT", result.reason_codes)

    def test_missing_required_unit_is_rejected(self):
        result = self.validate(
            "北门改称玄门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
            require_unit=True,
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("UNIT_NOT_FOUND", result.reason_codes)

    def test_result_is_deterministic(self):
        first = self.validate(
            "北门改称玄门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        second = self.validate(
            "北门改称玄门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertEqual(first.result_id, second.result_id)
        self.assertEqual(first.claim_fingerprint, second.claim_fingerprint)
        self.assertEqual(first.validator_version, VALIDATOR_VERSION)

    def test_source_change_changes_validation_result_id(self):
        first = self.validate(
            "北门改称玄门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        second = self.validate(
            "北门后来改称玄门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertNotEqual(first.result_id, second.result_id)

    def test_incoming_verification_status_is_ignored(self):
        evidence = "北门改称玄门。"
        payload = {
            "claim_type": "located_in",
            "subject": "玄门",
            "object": "火星",
            "source_id": "s",
            "unit_id": "u",
            "evidence_start": 0,
            "evidence_end": len(evidence),
            "evidence_text": evidence,
            "verification_status": "entailed_deterministic",
            "may_freeze": True,
        }
        candidate = ClaimCandidate.from_dict(payload)
        result = validate_claim(candidate, evidence)
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.may_freeze)

    def test_candidate_rejects_boolean_offsets(self):
        with self.assertRaises(ClaimValidationError):
            ClaimCandidate.from_dict(
                {
                    "claim_type": "alias",
                    "subject": "北门",
                    "object": "玄门",
                    "evidence_start": False,
                    "evidence_end": 5,
                }
            )

    def test_cli_partitions_results_and_requires_unit_binding(self):
        source = "第一章\n北门改称玄门。共有100名守卫。"
        alias_start = source.index("北门")
        alias_end = alias_start + len("北门改称玄门。")
        count_start = source.index("共有")
        count_end = count_start + len("共有100名守卫。")

        candidates = [
            {
                "claim_type": "alias",
                "subject": "北门",
                "object": "玄门",
                "source_id": "novel",
                "unit_id": "c1",
                "evidence_start": alias_start,
                "evidence_end": alias_end,
                "evidence_text": source[alias_start:alias_end],
            },
            {
                "claim_type": "located_in",
                "subject": "玄门",
                "object": "火星",
                "source_id": "novel",
                "unit_id": "c1",
                "evidence_start": alias_start,
                "evidence_end": alias_end,
                "evidence_text": source[alias_start:alias_end],
            },
            {
                "claim_type": "personality",
                "subject": "守卫",
                "object": "勇敢",
                "source_id": "novel",
                "unit_id": "c1",
                "evidence_start": count_start,
                "evidence_end": count_end,
                "evidence_text": source[count_start:count_end],
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "normalized-text.txt"
            source_path.write_text(source, encoding="utf-8")
            candidates_path = root / "claims.jsonl"
            candidates_path.write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in candidates),
                encoding="utf-8",
            )
            units_path = root / "unit-index.csv"
            units_path.write_text(
                "source_id,unit_id,norm_start,norm_end\n"
                f"novel,c1,0,{len(source)}\n",
                encoding="utf-8",
            )
            outdir = root / "validated"
            exit_code = claim_cli_main(
                [
                    str(source_path),
                    str(candidates_path),
                    "--units",
                    str(units_path),
                    "--outdir",
                    str(outdir),
                ]
            )
            report = json.loads(
                (outdir / "claim-validation-report.json").read_text(encoding="utf-8")
            )
            accepted = (outdir / "claims.accepted.jsonl").read_text(encoding="utf-8").splitlines()
            rejected = (outdir / "claims.rejected.jsonl").read_text(encoding="utf-8").splitlines()
            review = (outdir / "claims.review.jsonl").read_text(encoding="utf-8").splitlines()

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["rejected_count"], 1)
        self.assertEqual(report["review_count"], 1)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(len(review), 1)


if __name__ == "__main__":
    unittest.main()
