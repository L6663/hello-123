from __future__ import annotations

import unittest

from tkr.claim_validation import ClaimCandidate, validate_claim


class ClaimValidationAdversarialTests(unittest.TestCase):
    def validate(self, evidence: str, **kwargs):
        candidate = ClaimCandidate(
            source_id="s",
            unit_id="u",
            evidence_start=0,
            evidence_end=len(evidence),
            evidence_text=evidence,
            **kwargs,
        )
        return validate_claim(candidate, evidence)

    def test_rumored_defeat_routes_to_review(self):
        result = self.validate(
            "据说张三击败李四。",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "review")
        self.assertIn("MODAL_REPORTED_OR_QUESTION_ASSERTION", result.reason_codes)

    def test_hypothetical_defeat_routes_to_review(self):
        result = self.validate(
            "如果张三击败李四，城门就会打开。",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "review")

    def test_question_does_not_validate_fact(self):
        result = self.validate(
            "张三击败李四了吗？",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "review")

    def test_reported_alias_routes_to_review(self):
        result = self.validate(
            "传闻北门改称玄门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertEqual(result.status, "review")

    def test_conflicting_relation_directions_route_to_review(self):
        result = self.validate(
            "张三击败李四。李四后来击败张三。",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "review")
        self.assertIn("CONFLICTING_RELATION_ASSERTIONS", result.reason_codes)

    def test_conflicting_permission_routes_to_review(self):
        result = self.validate(
            "管理员可以删除草稿。管理员不得删除草稿。",
            claim_type="permission",
            subject="管理员",
            object="删除草稿",
            polarity=True,
        )
        self.assertEqual(result.status, "review")

    def test_multiple_count_values_route_to_review(self):
        result = self.validate(
            "最初共有100名守卫。后来共有120名守卫。",
            claim_type="count",
            subject="守卫",
            value=100,
            unit="名",
        )
        self.assertEqual(result.status, "review")
        self.assertIn("MULTIPLE_COUNT_VALUES", result.reason_codes)

    def test_reported_count_routes_to_review(self):
        result = self.validate(
            "据说城中共有100名守卫。",
            claim_type="count",
            subject="守卫",
            value=100,
            unit="名",
        )
        self.assertEqual(result.status, "review")

    def test_multiple_dates_route_to_review(self):
        result = self.validate(
            "档案记载事件发生于2001年2月3日。另一记录称事件发生于2001年2月4日。",
            claim_type="date",
            subject="事件",
            value="2001-02-03",
        )
        self.assertEqual(result.status, "review")
        self.assertIn("MULTIPLE_DATE_VALUES", result.reason_codes)

    def test_invalid_calendar_date_is_rejected(self):
        result = self.validate(
            "事件发生于2001年2月28日。",
            claim_type="date",
            subject="事件",
            value="2001-02-31",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("DATE_SUBJECT_AND_VALUE_REQUIRED", result.reason_codes)

    def test_accepted_claim_is_not_final_freeze_authority(self):
        result = self.validate(
            "张三击败李四。",
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        self.assertEqual(result.status, "accepted")
        self.assertTrue(result.may_index)
        self.assertFalse(result.may_freeze)

    def test_relation_does_not_cross_comma_to_unrelated_marker(self):
        result = self.validate(
            "玄门并非北门，南门又称北门。",
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("ALIAS_RELATION_NOT_FOUND", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
