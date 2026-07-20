from __future__ import annotations

from dataclasses import replace
import csv
import json
from pathlib import Path
import tempfile
import unittest

from tkr.chunking import UnitSpan
from tkr.claim_validation import ClaimCandidate, validate_claim
from tkr.entity_cli import main as entity_cli_main
from tkr.entity_normalization import (
    EntityNormalizationError,
    IdentityLink,
    normalize_entities,
)


class EntityNormalizationTests(unittest.TestCase):
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
        evidence_end = evidence_start + len(evidence)
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
            evidence_end=evidence_end,
            evidence_text=evidence,
        )
        result = validate_claim(candidate, source, unit_span=unit, require_unit=True)
        self.assertEqual(result.status, "accepted", result.reason_codes)
        return {
            "candidate_line": 1,
            "candidate": candidate.to_dict(),
            "validation": result.to_dict(),
        }

    def one_unit(self, source: str) -> UnitSpan:
        return UnitSpan("u1", 0, len(source), "s")

    def test_alias_claim_merges_two_names(self):
        source = "北门后来改称玄门。"
        unit = self.one_unit(source)
        record = self.record(
            source,
            source,
            unit,
            claim_type="alias",
            subject="北门",
            object="玄门",
        )
        bundle = normalize_entities([record], source, [unit])
        self.assertEqual(len(bundle.entities), 1)
        self.assertEqual(set(bundle.entities[0].aliases), {"北门", "玄门"})
        self.assertEqual(bundle.report["blocker_conflict_count"], 0)

    def test_same_surface_in_same_unit_is_locally_continuous(self):
        source = "张三击败李四。张三击败王五。"
        unit = self.one_unit(source)
        first = self.record(
            source,
            "张三击败李四。",
            unit,
            claim_type="defeats",
            subject="张三",
            object="李四",
        )
        second_start = source.index("张三击败王五。")
        second = self.record(
            source,
            "张三击败王五。",
            unit,
            claim_type="defeats",
            subject="张三",
            object="王五",
            start=second_start,
        )
        bundle = normalize_entities([first, second], source, [unit])
        zhang_entities = [entity for entity in bundle.entities if "张三" in entity.aliases]
        self.assertEqual(len(zhang_entities), 1)

    def test_same_surface_across_units_remains_ambiguous(self):
        first_text = "张三击败李四。"
        second_text = "张三击败王五。"
        source = first_text + second_text
        u1 = UnitSpan("u1", 0, len(first_text), "s")
        u2 = UnitSpan("u2", len(first_text), len(source), "s")
        first = self.record(
            source, first_text, u1, claim_type="defeats", subject="张三", object="李四"
        )
        second = self.record(
            source,
            second_text,
            u2,
            claim_type="defeats",
            subject="张三",
            object="王五",
            start=len(first_text),
        )
        bundle = normalize_entities([first, second], source, [u1, u2])
        groups = [item for item in bundle.ambiguity_groups if item.normalized_surface == "张三"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].entity_ids), 2)

    def test_evidence_bound_same_as_merges_cross_unit_homonym(self):
        first_text = "张三击败李四。"
        second_text = "张三击败王五。"
        link_text = "第二章的张三正是第一章的张三。"
        source = first_text + second_text + link_text
        u1 = UnitSpan("u1", 0, len(first_text), "s")
        u2 = UnitSpan("u2", len(first_text), len(first_text) + len(second_text), "s")
        u3 = UnitSpan("u3", len(first_text) + len(second_text), len(source), "s")
        first = self.record(
            source, first_text, u1, claim_type="defeats", subject="张三", object="李四"
        )
        second = self.record(
            source,
            second_text,
            u2,
            claim_type="defeats",
            subject="张三",
            object="王五",
            start=len(first_text),
        )
        link = IdentityLink(
            relation="same_as",
            left_result_id=first["validation"]["result_id"],
            left_role="subject",
            right_result_id=second["validation"]["result_id"],
            right_role="subject",
            source_id="s",
            unit_id="u3",
            evidence_start=u3.start,
            evidence_end=u3.end,
            evidence_text=link_text,
        )
        bundle = normalize_entities([first, second], source, [u1, u2, u3], identity_links=[link])
        zhang_entities = [entity for entity in bundle.entities if "张三" in entity.aliases]
        self.assertEqual(len(zhang_entities), 1)
        self.assertFalse(any(item.normalized_surface == "张三" for item in bundle.ambiguity_groups))

    def test_different_from_keeps_homonyms_separate(self):
        first_text = "张三击败李四。"
        second_text = "张三击败王五。"
        link_text = "第二章的张三与第一章的张三同名不同人。"
        source = first_text + second_text + link_text
        u1 = UnitSpan("u1", 0, len(first_text), "s")
        u2 = UnitSpan("u2", len(first_text), len(first_text) + len(second_text), "s")
        u3 = UnitSpan("u3", len(first_text) + len(second_text), len(source), "s")
        first = self.record(source, first_text, u1, claim_type="defeats", subject="张三", object="李四")
        second = self.record(
            source, second_text, u2, claim_type="defeats", subject="张三", object="王五", start=u2.start
        )
        link = IdentityLink(
            "different_from",
            first["validation"]["result_id"],
            "subject",
            second["validation"]["result_id"],
            "subject",
            "s",
            "u3",
            u3.start,
            u3.end,
            link_text,
        )
        bundle = normalize_entities([first, second], source, [u1, u2, u3], identity_links=[link])
        group = next(item for item in bundle.ambiguity_groups if item.normalized_surface == "张三")
        self.assertEqual(len(group.entity_ids), 2)

    def test_same_as_and_different_from_contradiction_is_blocker(self):
        first_text = "张三击败李四。"
        second_text = "张三击败王五。"
        same_text = "第二章的张三正是第一章的张三。"
        diff_text = "第二章的张三与第一章的张三同名不同人。"
        source = first_text + second_text + same_text + diff_text
        u1 = UnitSpan("u1", 0, len(first_text), "s")
        u2 = UnitSpan("u2", u1.end, u1.end + len(second_text), "s")
        u3 = UnitSpan("u3", u2.end, u2.end + len(same_text), "s")
        u4 = UnitSpan("u4", u3.end, len(source), "s")
        first = self.record(source, first_text, u1, claim_type="defeats", subject="张三", object="李四")
        second = self.record(source, second_text, u2, claim_type="defeats", subject="张三", object="王五", start=u2.start)
        ids = (first["validation"]["result_id"], second["validation"]["result_id"])
        same = IdentityLink("same_as", ids[0], "subject", ids[1], "subject", "s", "u3", u3.start, u3.end, same_text)
        different = IdentityLink("different_from", ids[0], "subject", ids[1], "subject", "s", "u4", u4.start, u4.end, diff_text)
        bundle = normalize_entities(
            [first, second], source, [u1, u2, u3, u4], identity_links=[same, different]
        )
        self.assertGreater(bundle.report["blocker_conflict_count"], 0)
        self.assertFalse(bundle.report["may_build_index"])

    def test_alias_type_conflict_is_blocked(self):
        source = "张三击败李四。宫殿位于玄门。张三又称玄门。"
        unit = self.one_unit(source)
        defeat = self.record(source, "张三击败李四。", unit, claim_type="defeats", subject="张三", object="李四")
        location = self.record(source, "宫殿位于玄门。", unit, claim_type="located_in", subject="宫殿", object="玄门")
        alias = self.record(source, "张三又称玄门。", unit, claim_type="alias", subject="张三", object="玄门")
        bundle = normalize_entities([defeat, location, alias], source, [unit])
        self.assertTrue(any(item.conflict_type == "ENTITY_TYPE_CONFLICT" for item in bundle.conflicts))
        self.assertFalse(bundle.report["may_build_index"])

    def test_forged_validation_artifact_is_rejected(self):
        source = "北门改称玄门。"
        unit = self.one_unit(source)
        record = self.record(source, source, unit, claim_type="alias", subject="北门", object="玄门")
        record["validation"]["result_id"] = "clv_forged"
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([record], source, [unit])

    def test_source_change_invalidates_upstream_acceptance(self):
        source = "北门改称玄门。"
        unit = self.one_unit(source)
        record = self.record(source, source, unit, claim_type="alias", subject="北门", object="玄门")
        changed = "北门并非玄门。"
        changed_unit = self.one_unit(changed)
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([record], changed, [changed_unit])

    def test_count_change_with_later_marker_is_temporal(self):
        source = "守卫共有100名。后来守卫共有120名。"
        unit = self.one_unit(source)
        first = self.record(source, "守卫共有100名。", unit, claim_type="count", subject="守卫", value=100, unit_name="名")
        later_text = "后来守卫共有120名。"
        second = self.record(source, later_text, unit, claim_type="count", subject="守卫", value=120, unit_name="名", start=source.index(later_text))
        bundle = normalize_entities([first, second], source, [unit])
        conflict = next(item for item in bundle.conflicts if item.conflict_type == "COUNT_TEMPORAL_TRANSITION")
        self.assertEqual(conflict.status, "resolved_temporal")
        self.assertTrue(all(fact.canonical_status == "temporal_variant" for fact in bundle.facts))

    def test_count_change_without_marker_is_contested(self):
        source = "守卫共有100名。守卫共有120名。"
        unit = self.one_unit(source)
        first = self.record(source, "守卫共有100名。", unit, claim_type="count", subject="守卫", value=100, unit_name="名")
        second_text = "守卫共有120名。"
        second = self.record(source, second_text, unit, claim_type="count", subject="守卫", value=120, unit_name="名", start=source.index(second_text))
        bundle = normalize_entities([first, second], source, [unit])
        self.assertTrue(any(item.conflict_type == "MULTIPLE_COUNT_VALUES" for item in bundle.conflicts))
        self.assertEqual(bundle.report["contested_fact_count"], 2)

    def test_permission_polarity_conflict_is_contested(self):
        source = "管理员可以删除草稿。管理员不得删除草稿。"
        unit = self.one_unit(source)
        positive = self.record(source, "管理员可以删除草稿。", unit, claim_type="permission", subject="管理员", object="删除草稿", polarity=True)
        negative_text = "管理员不得删除草稿。"
        negative = self.record(source, negative_text, unit, claim_type="permission", subject="管理员", object="删除草稿", polarity=False, start=source.index(negative_text))
        bundle = normalize_entities([positive, negative], source, [unit])
        self.assertTrue(any(item.conflict_type == "PERMISSION_POLARITY_CONFLICT" for item in bundle.conflicts))

    def test_permission_later_change_is_temporal(self):
        source = "管理员可以删除草稿。后来管理员不得删除草稿。"
        unit = self.one_unit(source)
        positive = self.record(source, "管理员可以删除草稿。", unit, claim_type="permission", subject="管理员", object="删除草稿", polarity=True)
        later = "后来管理员不得删除草稿。"
        negative = self.record(source, later, unit, claim_type="permission", subject="管理员", object="删除草稿", polarity=False, start=source.index(later))
        bundle = normalize_entities([positive, negative], source, [unit])
        self.assertTrue(any(item.conflict_type == "PERMISSION_POLARITY_TRANSITION" for item in bundle.conflicts))

    def test_location_change_is_temporal_only_with_marker(self):
        source = "张三位于北城。后来张三位于南城。"
        unit = self.one_unit(source)
        first = self.record(source, "张三位于北城。", unit, claim_type="located_in", subject="张三", object="北城")
        later = "后来张三位于南城。"
        second = self.record(source, later, unit, claim_type="located_in", subject="张三", object="南城", start=source.index(later))
        bundle = normalize_entities([first, second], source, [unit])
        self.assertTrue(any(item.conflict_type == "LOCATION_TEMPORAL_TRANSITION" for item in bundle.conflicts))

    def test_reciprocal_defeats_without_time_is_unresolved(self):
        source = "张三击败李四。李四击败张三。"
        unit = self.one_unit(source)
        first = self.record(source, "张三击败李四。", unit, claim_type="defeats", subject="张三", object="李四")
        second_text = "李四击败张三。"
        second = self.record(source, second_text, unit, claim_type="defeats", subject="李四", object="张三", start=source.index(second_text))
        bundle = normalize_entities([first, second], source, [unit])
        self.assertTrue(any(item.conflict_type == "RECIPROCAL_DEFEATS_UNRESOLVED" for item in bundle.conflicts))

    def test_multiple_dates_are_contested(self):
        source = "张三出生于2001年2月3日。张三出生于2002年2月3日。"
        unit = self.one_unit(source)
        first = self.record(source, "张三出生于2001年2月3日。", unit, claim_type="date", subject="张三", value="2001-02-03")
        second_text = "张三出生于2002年2月3日。"
        second = self.record(source, second_text, unit, claim_type="date", subject="张三", value="2002-02-03", start=source.index(second_text))
        bundle = normalize_entities([first, second], source, [unit])
        self.assertTrue(any(item.conflict_type == "MULTIPLE_DATE_VALUES" for item in bundle.conflicts))

    def test_timeline_is_in_source_order_and_keeps_dates(self):
        source = "张三出生于2001年2月3日。张三击败李四。"
        unit = self.one_unit(source)
        date_record = self.record(source, "张三出生于2001年2月3日。", unit, claim_type="date", subject="张三", value="2001-02-03")
        defeat_text = "张三击败李四。"
        defeat = self.record(source, defeat_text, unit, claim_type="defeats", subject="张三", object="李四", start=source.index(defeat_text))
        bundle = normalize_entities([defeat, date_record], source, [unit])
        self.assertEqual([item.source_order for item in bundle.timeline], [1, 2])
        self.assertEqual(bundle.timeline[0].normalized_date, "2001-02-03")
        self.assertIsNone(bundle.timeline[1].normalized_date)

    def test_results_are_deterministic(self):
        source = "北门后来改称玄门。玄门位于北城。"
        unit = self.one_unit(source)
        alias = self.record(source, "北门后来改称玄门。", unit, claim_type="alias", subject="北门", object="玄门")
        location_text = "玄门位于北城。"
        location = self.record(source, location_text, unit, claim_type="located_in", subject="玄门", object="北城", start=source.index(location_text))
        first = normalize_entities([alias, location], source, [unit])
        second = normalize_entities([alias, location], source, [unit])
        self.assertEqual([item.to_dict() for item in first.entities], [item.to_dict() for item in second.entities])
        self.assertEqual([item.to_dict() for item in first.facts], [item.to_dict() for item in second.facts])
        self.assertEqual(first.report, second.report)

    def test_invalid_identity_link_evidence_is_rejected(self):
        source = "张三击败李四。张三击败王五。两者是同一人。"
        unit = self.one_unit(source)
        first = self.record(source, "张三击败李四。", unit, claim_type="defeats", subject="张三", object="李四")
        second_text = "张三击败王五。"
        second = self.record(source, second_text, unit, claim_type="defeats", subject="张三", object="王五", start=source.index(second_text))
        link_text = "两者是同一人。"
        start = source.index(link_text)
        link = IdentityLink(
            "same_as",
            first["validation"]["result_id"],
            "subject",
            second["validation"]["result_id"],
            "subject",
            "s",
            "u1",
            start,
            start + len(link_text),
            "伪造证据",
        )
        with self.assertRaises(EntityNormalizationError):
            normalize_entities([first, second], source, [unit], identity_links=[link])

    def test_report_never_grants_freeze(self):
        source = "北门改称玄门。"
        unit = self.one_unit(source)
        record = self.record(source, source, unit, claim_type="alias", subject="北门", object="玄门")
        bundle = normalize_entities([record], source, [unit])
        self.assertFalse(bundle.report["may_freeze"])

    def test_cli_writes_hash_bound_artifacts(self):
        source = "北门改称玄门。玄门位于北城。"
        unit = self.one_unit(source)
        alias = self.record(source, "北门改称玄门。", unit, claim_type="alias", subject="北门", object="玄门")
        location_text = "玄门位于北城。"
        location = self.record(source, location_text, unit, claim_type="located_in", subject="玄门", object="北城", start=source.index(location_text))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "normalized.txt"
            accepted_path = root / "claims.accepted.jsonl"
            units_path = root / "units.csv"
            outdir = root / "normalized"
            source_path.write_text(source, encoding="utf-8")
            accepted_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in [alias, location]),
                encoding="utf-8",
            )
            with units_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_id", "unit_id", "norm_start", "norm_end"])
                writer.writeheader()
                writer.writerow({"source_id": "s", "unit_id": "u1", "norm_start": 0, "norm_end": len(source)})
            result = entity_cli_main(
                [
                    str(source_path),
                    str(accepted_path),
                    "--units",
                    str(units_path),
                    "--outdir",
                    str(outdir),
                ]
            )
            report = json.loads((outdir / "entity-normalization-report.json").read_text(encoding="utf-8"))
            for name, digest in report["artifact_sha256"].items():
                self.assertEqual(__import__("hashlib").sha256((outdir / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
