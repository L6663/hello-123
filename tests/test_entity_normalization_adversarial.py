from __future__ import annotations

import unittest

from tkr.chunking import UnitSpan
from tkr.claim_validation import ClaimCandidate, validate_claim
from tkr.entity_normalization import (
    EntityNormalizationError,
    IdentityLink,
    normalize_entities,
)


class EntityNormalizationAdversarialTests(unittest.TestCase):
    def record(
        self,
        source: str,
        evidence: str,
        unit: UnitSpan,
        *,
        claim_type: str,
        subject: str,
        object: str = "",
        value=None,
        unit_name: str = "",
        polarity: bool = True,
        start: int | None = None,
    ) -> dict[str, object]:
        evidence_start = source.index(evidence) if start is None else start
        candidate = ClaimCandidate(
            claim_type=claim_type,
            subject=subject,
            object=object,
            value=value,
            unit=unit_name,
            polarity=polarity,
            source_id=unit.source_id,
            unit_id=unit.unit_id,
            evidence_start=evidence_start,
            evidence_end=evidence_start + len(evidence),
            evidence_text=evidence,
        )
        result = validate_claim(candidate, source, unit_span=unit, require_unit=True)
        self.assertEqual(result.status, "accepted", result.reason_codes)
        return {
            "candidate_line": 1,
            "candidate": candidate.to_dict(),
            "validation": result.to_dict(),
        }

    def test_negative_same_identity_phrase_validates_different_from(self):
        first = "张三击败李四。"
        second = "张三击败王五。"
        link_text = "第二章的张三与第一章的张三并非同一人。"
        source = first + second + link_text
        u1 = UnitSpan("u1", 0, len(first), "s")
        u2 = UnitSpan("u2", u1.end, u1.end + len(second), "s")
        u3 = UnitSpan("u3", u2.end, len(source), "s")
        one = self.record(source, first, u1, claim_type="defeats", subject="张三", object="李四")
        two = self.record(source, second, u2, claim_type="defeats", subject="张三", object="王五", start=u2.start)
        link = IdentityLink(
            "different_from",
            one["validation"]["result_id"],
            "subject",
            two["validation"]["result_id"],
            "subject",
            "s",
            "u3",
            u3.start,
            u3.end,
            link_text,
        )
        bundle = normalize_entities([one, two], source, [u1, u2, u3], identity_links=[link])
        ambiguity = next(item for item in bundle.ambiguity_groups if item.normalized_surface == "张三")
        self.assertEqual(len(ambiguity.entity_ids), 2)

    def test_unrelated_same_marker_cannot_merge_entities(self):
        first = "张三击败王五。"
        second = "李四击败赵六。"
        link_text = "张三谈到天气正是晴朗，李四站在旁边。"
        source = first + second + link_text
        u1 = UnitSpan("u1", 0, len(first), "s")
        u2 = UnitSpan("u2", u1.end, u1.end + len(second), "s")
        u3 = UnitSpan("u3", u2.end, len(source), "s")
        one = self.record(source, first, u1, claim_type="defeats", subject="张三", object="王五")
        two = self.record(source, second, u2, claim_type="defeats", subject="李四", object="赵六", start=u2.start)
        link = IdentityLink(
            "same_as",
            one["validation"]["result_id"],
            "subject",
            two["validation"]["result_id"],
            "subject",
            "s",
            "u3",
            u3.start,
            u3.end,
            link_text,
        )
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([one, two], source, [u1, u2, u3], identity_links=[link])

    def test_modal_identity_link_is_rejected(self):
        first = "张三击败王五。"
        second = "李四击败赵六。"
        link_text = "据说张三正是李四。"
        source = first + second + link_text
        u1 = UnitSpan("u1", 0, len(first), "s")
        u2 = UnitSpan("u2", u1.end, u1.end + len(second), "s")
        u3 = UnitSpan("u3", u2.end, len(source), "s")
        one = self.record(source, first, u1, claim_type="defeats", subject="张三", object="王五")
        two = self.record(source, second, u2, claim_type="defeats", subject="李四", object="赵六", start=u2.start)
        link = IdentityLink(
            "same_as",
            one["validation"]["result_id"],
            "subject",
            two["validation"]["result_id"],
            "subject",
            "s",
            "u3",
            u3.start,
            u3.end,
            link_text,
        )
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([one, two], source, [u1, u2, u3], identity_links=[link])

    def test_cross_source_identity_link_is_rejected(self):
        first = "甲击败乙。"
        second = "丙击败丁。"
        link_text = "甲正是丙。"
        source = first + second + link_text
        a1 = UnitSpan("u1", 0, len(first), "novel-a")
        b1 = UnitSpan("u1", a1.end, a1.end + len(second), "novel-b")
        a2 = UnitSpan("u2", b1.end, len(source), "novel-a")
        one = self.record(source, first, a1, claim_type="defeats", subject="甲", object="乙")
        two = self.record(source, second, b1, claim_type="defeats", subject="丙", object="丁", start=b1.start)
        link = IdentityLink(
            "same_as",
            one["validation"]["result_id"],
            "subject",
            two["validation"]["result_id"],
            "subject",
            "novel-a",
            "u2",
            a2.start,
            a2.end,
            link_text,
        )
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([one, two], source, [a1, b1, a2], identity_links=[link])

    def test_same_name_in_different_sources_is_not_one_ambiguity_group(self):
        first = "张三击败李四。"
        second = "张三击败王五。"
        source = first + second
        a = UnitSpan("u1", 0, len(first), "novel-a")
        b = UnitSpan("u1", a.end, len(source), "novel-b")
        one = self.record(source, first, a, claim_type="defeats", subject="张三", object="李四")
        two = self.record(source, second, b, claim_type="defeats", subject="张三", object="王五", start=b.start)
        bundle = normalize_entities([one, two], source, [a, b])
        self.assertFalse(any(item.normalized_surface == "张三" for item in bundle.ambiguity_groups))

    def test_unrelated_later_word_does_not_resolve_count_conflict(self):
        first = "后来天气转晴。守卫共有100名。"
        second = "夜色降临。守卫共有120名。"
        source = first + second
        unit = UnitSpan("u1", 0, len(source), "s")
        one = self.record(source, first, unit, claim_type="count", subject="守卫", value=100, unit_name="名")
        two = self.record(source, second, unit, claim_type="count", subject="守卫", value=120, unit_name="名", start=len(first))
        bundle = normalize_entities([one, two], source, [unit])
        self.assertTrue(any(item.conflict_type == "MULTIPLE_COUNT_VALUES" for item in bundle.conflicts))
        self.assertFalse(any(item.conflict_type == "COUNT_TEMPORAL_TRANSITION" for item in bundle.conflicts))

    def test_later_marker_on_first_fact_does_not_resolve_future_conflict(self):
        first = "后来守卫共有100名。"
        second = "守卫共有120名。"
        source = first + second
        unit = UnitSpan("u1", 0, len(source), "s")
        one = self.record(source, first, unit, claim_type="count", subject="守卫", value=100, unit_name="名")
        two = self.record(source, second, unit, claim_type="count", subject="守卫", value=120, unit_name="名", start=len(first))
        bundle = normalize_entities([one, two], source, [unit])
        self.assertTrue(any(item.conflict_type == "MULTIPLE_COUNT_VALUES" for item in bundle.conflicts))

    def test_different_date_predicates_do_not_conflict(self):
        first = "工程始于2001年2月3日。"
        second = "工程截至2002年2月3日。"
        source = first + second
        unit = UnitSpan("u1", 0, len(source), "s")
        one = self.record(source, first, unit, claim_type="date", subject="工程", value="2001-02-03")
        two = self.record(source, second, unit, claim_type="date", subject="工程", value="2002-02-03", start=len(first))
        bundle = normalize_entities([one, two], source, [unit])
        self.assertFalse(any(item.conflict_type == "MULTIPLE_DATE_VALUES" for item in bundle.conflicts))
        self.assertEqual({fact.predicate_scope for fact in bundle.facts}, {"start_date", "end_date"})

    def test_date_precision_refinement_is_not_contradiction(self):
        first = "张三出生于2001-02。"
        second = "张三出生于2001-02-03。"
        source = first + second
        unit = UnitSpan("u1", 0, len(source), "s")
        one = self.record(source, first, unit, claim_type="date", subject="张三", value="2001-02")
        two = self.record(source, second, unit, claim_type="date", subject="张三", value="2001-02-03", start=len(first))
        bundle = normalize_entities([one, two], source, [unit])
        refinement = next(item for item in bundle.conflicts if item.conflict_type == "DATE_PRECISION_REFINEMENT")
        self.assertEqual(refinement.status, "resolved_precision")
        self.assertTrue(all(fact.canonical_status == "compatible_variant" for fact in bundle.facts))

    def test_mention_offsets_point_to_exact_surface(self):
        source = "序言。张三在决斗中击败李四。尾声。"
        unit = UnitSpan("u1", 0, len(source), "s")
        record = self.record(
            source,
            "张三在决斗中击败李四。",
            unit,
            claim_type="defeats",
            subject="张三",
            object="李四",
            start=source.index("张三"),
        )
        bundle = normalize_entities([record], source, [unit])
        for mention in bundle.mentions:
            self.assertEqual(source[mention.evidence_start : mention.evidence_end], mention.surface)

    def test_timeline_order_resets_per_source(self):
        a1_text = "甲击败乙。"
        b1_text = "丙击败丁。"
        a2_text = "甲击败戊。"
        b2_text = "丙击败己。"
        source = a1_text + b1_text + a2_text + b2_text
        offsets = [0, len(a1_text), len(a1_text) + len(b1_text), len(a1_text) + len(b1_text) + len(a2_text)]
        units = [
            UnitSpan("u1", offsets[0], offsets[1], "a"),
            UnitSpan("u1", offsets[1], offsets[2], "b"),
            UnitSpan("u2", offsets[2], offsets[3], "a"),
            UnitSpan("u2", offsets[3], len(source), "b"),
        ]
        records = [
            self.record(source, a1_text, units[0], claim_type="defeats", subject="甲", object="乙", start=offsets[0]),
            self.record(source, b1_text, units[1], claim_type="defeats", subject="丙", object="丁", start=offsets[1]),
            self.record(source, a2_text, units[2], claim_type="defeats", subject="甲", object="戊", start=offsets[2]),
            self.record(source, b2_text, units[3], claim_type="defeats", subject="丙", object="己", start=offsets[3]),
        ]
        bundle = normalize_entities(records, source, units)
        by_source = {}
        for event in bundle.timeline:
            by_source.setdefault(event.source_id, []).append(event.source_order)
        self.assertEqual(by_source, {"a": [1, 2], "b": [1, 2]})

    def test_blocked_alias_marks_alias_fact_contested(self):
        source = "张三击败李四。宫殿位于玄门。张三又称玄门。"
        unit = UnitSpan("u1", 0, len(source), "s")
        defeat = self.record(source, "张三击败李四。", unit, claim_type="defeats", subject="张三", object="李四")
        location = self.record(source, "宫殿位于玄门。", unit, claim_type="located_in", subject="宫殿", object="玄门")
        alias_text = "张三又称玄门。"
        alias = self.record(source, alias_text, unit, claim_type="alias", subject="张三", object="玄门", start=source.index(alias_text))
        bundle = normalize_entities([defeat, location, alias], source, [unit])
        alias_fact = next(fact for fact in bundle.facts if fact.claim_result_id == alias["validation"]["result_id"])
        self.assertEqual(alias_fact.canonical_status, "contested")
        self.assertTrue(alias_fact.conflict_ids)

    def test_duplicate_unit_identity_is_rejected(self):
        source = "甲击败乙。"
        unit = UnitSpan("u1", 0, len(source), "s")
        record = self.record(source, source, unit, claim_type="defeats", subject="甲", object="乙")
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([record], source, [unit, unit])

    def test_duplicate_identity_link_is_rejected(self):
        first = "张三击败李四。"
        second = "张三击败王五。"
        link_text = "第二章的张三正是第一章的张三。"
        source = first + second + link_text
        u1 = UnitSpan("u1", 0, len(first), "s")
        u2 = UnitSpan("u2", u1.end, u1.end + len(second), "s")
        u3 = UnitSpan("u3", u2.end, len(source), "s")
        one = self.record(source, first, u1, claim_type="defeats", subject="张三", object="李四")
        two = self.record(source, second, u2, claim_type="defeats", subject="张三", object="王五", start=u2.start)
        link = IdentityLink("same_as", one["validation"]["result_id"], "subject", two["validation"]["result_id"], "subject", "s", "u3", u3.start, u3.end, link_text)
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([one, two], source, [u1, u2, u3], identity_links=[link, link])

    def test_canonical_publish_is_blocked_by_ambiguity(self):
        first = "张三击败李四。"
        second = "张三击败王五。"
        source = first + second
        u1 = UnitSpan("u1", 0, len(first), "s")
        u2 = UnitSpan("u2", u1.end, len(source), "s")
        one = self.record(source, first, u1, claim_type="defeats", subject="张三", object="李四")
        two = self.record(source, second, u2, claim_type="defeats", subject="张三", object="王五", start=u2.start)
        bundle = normalize_entities([one, two], source, [u1, u2])
        self.assertTrue(bundle.report["may_build_review_index"])
        self.assertFalse(bundle.report["may_publish_canonical"])

    def test_subjectless_permissions_in_different_sources_do_not_conflict(self):
        first = "可以删除。"
        second = "不可以删除。"
        source = first + second
        a = UnitSpan("u1", 0, len(first), "a")
        b = UnitSpan("u1", a.end, len(source), "b")
        positive = self.record(source, first, a, claim_type="permission", subject="", object="删除", polarity=True)
        negative = self.record(source, second, b, claim_type="permission", subject="", object="删除", polarity=False, start=b.start)
        bundle = normalize_entities([positive, negative], source, [a, b])
        self.assertFalse(any(item.conflict_type.startswith("PERMISSION_POLARITY") for item in bundle.conflicts))

    def test_thousand_claim_scale_smoke(self):
        count = 1000
        parts = [f"张三击败对手{index}。" for index in range(count)]
        source = "".join(parts)
        unit = UnitSpan("u1", 0, len(source), "scale")
        records = []
        offset = 0
        for index, text in enumerate(parts):
            records.append(
                self.record(
                    source,
                    text,
                    unit,
                    claim_type="defeats",
                    subject="张三",
                    object=f"对手{index}",
                    start=offset,
                )
            )
            offset += len(text)
        bundle = normalize_entities(records, source, [unit])
        self.assertEqual(len(bundle.facts), count)
        self.assertEqual(len(bundle.mentions), count * 2)
        self.assertEqual(len(bundle.entities), count + 1)
        self.assertEqual(bundle.report["conflict_count"], 0)



if __name__ == "__main__":
    unittest.main()
