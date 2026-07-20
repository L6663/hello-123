from __future__ import annotations

import csv
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tkr.chunking import UnitSpan
from tkr.claim_validation import ClaimCandidate, validate_claim
from tkr.entity_cli import _publish
from tkr.entity_normalization import IdentityLink, normalize_entities
from tkr.hybrid_retrieval import (
    RetrievalError,
    build_hybrid_index,
    parse_predicate_query,
    query_hybrid_index,
)


class RetrievalFixture(unittest.TestCase):
    def make_project(
        self,
        root: Path,
        unit_texts: list[str],
        claims: list[dict[str, object]],
        *,
        source_id: str = "s",
        identity_links: list[dict[str, object]] | None = None,
    ) -> tuple[Path, Path, Path, Path, Path, Path | None]:
        source = "".join(unit_texts)
        source_path = root / "normalized-text.txt"
        source_path.write_text(source, encoding="utf-8")

        units: list[UnitSpan] = []
        offset = 0
        for index, text in enumerate(unit_texts, start=1):
            units.append(UnitSpan(f"u{index}", offset, offset + len(text), source_id))
            offset += len(text)

        units_path = root / "unit-index.csv"
        with units_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["source_id", "unit_id", "norm_start", "norm_end"],
            )
            writer.writeheader()
            for unit in units:
                writer.writerow(
                    {
                        "source_id": unit.source_id,
                        "unit_id": unit.unit_id,
                        "norm_start": unit.start,
                        "norm_end": unit.end,
                    }
                )

        records: list[dict[str, object]] = []
        search_cursor: dict[str, int] = {}
        for line_number, spec in enumerate(claims, start=1):
            unit_index = int(spec.get("unit_index", 1)) - 1
            unit = units[unit_index]
            evidence = str(spec["evidence"])
            explicit_start = spec.get("start")
            if explicit_start is None:
                cursor_key = f"{unit_index}:{evidence}"
                cursor = search_cursor.get(cursor_key, unit.start)
                start = source.find(evidence, cursor, unit.end)
                self.assertGreaterEqual(start, 0, evidence)
                search_cursor[cursor_key] = start + 1
            else:
                start = int(explicit_start)
            candidate = ClaimCandidate(
                claim_type=str(spec["claim_type"]),
                subject=str(spec["subject"]),
                object=str(spec.get("object", "")),
                value=spec.get("value"),
                unit=str(spec.get("unit", "")),
                polarity=bool(spec.get("polarity", True)),
                source_id=source_id,
                unit_id=unit.unit_id,
                evidence_start=start,
                evidence_end=start + len(evidence),
                evidence_text=evidence,
            )
            result = validate_claim(candidate, source, unit_span=unit, require_unit=True)
            self.assertEqual(result.status, "accepted", result.reason_codes)
            records.append(
                {
                    "candidate_line": line_number,
                    "candidate": candidate.to_dict(),
                    "validation": result.to_dict(),
                }
            )

        accepted_path = root / "claims.accepted.jsonl"
        accepted_path.write_text(
            "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        link_objects: list[IdentityLink] = []
        identity_path: Path | None = None
        if identity_links:
            for spec in identity_links:
                unit = units[int(spec["unit_index"]) - 1]
                evidence = str(spec["evidence"])
                start = source.find(evidence, unit.start, unit.end)
                self.assertGreaterEqual(start, 0, evidence)
                left = records[int(spec["left_record"])]["validation"]["result_id"]
                right = records[int(spec["right_record"])]["validation"]["result_id"]
                link_objects.append(
                    IdentityLink(
                        relation=str(spec.get("relation", "same_as")),
                        left_result_id=str(left),
                        left_role=str(spec.get("left_role", "subject")),
                        right_result_id=str(right),
                        right_role=str(spec.get("right_role", "subject")),
                        source_id=source_id,
                        unit_id=unit.unit_id,
                        evidence_start=start,
                        evidence_end=start + len(evidence),
                        evidence_text=evidence,
                    )
                )
            identity_path = root / "identity-links.jsonl"
            identity_path.write_text(
                "".join(json.dumps(asdict(link), ensure_ascii=False, sort_keys=True) + "\n" for link in link_objects),
                encoding="utf-8",
            )

        entity_dir = root / "entities"
        bundle = normalize_entities(records, source, units, identity_links=link_objects)
        _publish(
            bundle,
            entity_dir,
            accepted_path=accepted_path,
            identity_links_path=identity_path,
            units_path=units_path,
        )
        database = root / "knowledge.sqlite3"
        return source_path, units_path, accepted_path, entity_dir, database, identity_path

    def build(self, root: Path, unit_texts: list[str], claims: list[dict[str, object]], *, mode="review", identity_links=None):
        paths = self.make_project(root, unit_texts, claims, identity_links=identity_links)
        build_hybrid_index(*paths[:4], paths[4], index_mode=mode, identity_links_path=paths[5])
        return paths


class PredicateParserTests(unittest.TestCase):
    def test_supported_predicates(self):
        cases = {
            "北门后来叫什么？": ("alias", "北门", "object"),
            "张三击败了谁？": ("defeats", "张三", "object"),
            "谁击败了李四？": ("defeats", "", "subject"),
            "玄门位于哪里？": ("located_in", "玄门", "object"),
            "守卫有多少名？": ("count", "守卫", "value"),
            "工程什么时候开始？": ("date", "工程", "value"),
            "系统允许删除吗？": ("permission", "系统", "boolean"),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                parsed = parse_predicate_query(question)
                self.assertTrue(parsed.supported)
                self.assertEqual((parsed.predicate, parsed.subject, parsed.requested_role), expected)

    def test_open_predicate_is_unsupported(self):
        parsed = parse_predicate_query("北门是谁发明的？")
        self.assertFalse(parsed.supported)
        self.assertEqual(parsed.reason, "UNSUPPORTED_OPEN_PREDICATE")


class HybridRetrievalTests(RetrievalFixture):
    def test_cross_unit_alias_retrieves_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["北门后来改称玄门。", "玄门位于皇城北侧。", "第二章的玄门与第一章改称后的玄门是同一实体。"],
                [
                    {"unit_index": 1, "evidence": "北门后来改称玄门。", "claim_type": "alias", "subject": "北门", "object": "玄门"},
                    {"unit_index": 2, "evidence": "玄门位于皇城北侧。", "claim_type": "located_in", "subject": "玄门", "object": "皇城北侧"},
                ],
                identity_links=[
                    {
                        "unit_index": 3,
                        "evidence": "第二章的玄门与第一章改称后的玄门是同一实体。",
                        "left_record": 0,
                        "left_role": "object",
                        "right_record": 1,
                        "right_role": "subject",
                    }
                ],
            )
            result = query_hybrid_index(paths[4], "北门位于哪里？")
        self.assertEqual(result.answerability, "answerable")
        self.assertEqual(result.hits[0].object, "皇城北侧")
        self.assertEqual(result.hits[0].unit_id, "u2")

    def test_directional_relation_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["张三击败李四。"],
                [{"evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"}],
            )
            forward = query_hybrid_index(paths[4], "张三击败了谁？")
            reverse = query_hybrid_index(paths[4], "李四击败了谁？")
            who = query_hybrid_index(paths[4], "谁击败了李四？")
        self.assertEqual(forward.answerability, "answerable")
        self.assertEqual(forward.hits[0].object, "李四")
        self.assertEqual(who.answerability, "answerable")
        self.assertEqual(who.hits[0].subject, "张三")
        self.assertEqual(reverse.answerability, "not_answerable")

    def test_entity_mention_does_not_make_unrelated_predicate_answerable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["玄门位于皇城北侧。"],
                [{"evidence": "玄门位于皇城北侧。", "claim_type": "located_in", "subject": "玄门", "object": "皇城北侧"}],
            )
            result = query_hybrid_index(paths[4], "玄门是谁发明的？")
        self.assertEqual(result.answerability, "unsupported")
        self.assertFalse(result.answerable_candidate)

    def test_location_boolean_requires_matching_object(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["玄门位于皇城北侧。"],
                [{"evidence": "玄门位于皇城北侧。", "claim_type": "located_in", "subject": "玄门", "object": "皇城北侧"}],
            )
            true_result = query_hybrid_index(paths[4], "玄门位于皇城北侧吗？")
            false_result = query_hybrid_index(paths[4], "玄门位于火星吗？")
        self.assertEqual(true_result.answerability, "answerable")
        self.assertEqual(false_result.answerability, "not_answerable")

    def test_exact_count_is_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。"],
                [{"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"}],
            )
            result = query_hybrid_index(paths[4], "守卫有多少名？")
        self.assertEqual(result.answerability, "answerable")
        self.assertEqual(result.hits[0].value, 100)
        self.assertNotEqual(result.hits[0].value, 1000)

    def test_same_surface_across_units_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["张三击败李四。", "张三击败王五。"],
                [
                    {"unit_index": 1, "evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"},
                    {"unit_index": 2, "evidence": "张三击败王五。", "claim_type": "defeats", "subject": "张三", "object": "王五"},
                ],
            )
            result = query_hybrid_index(paths[4], "张三击败了谁？")
        self.assertEqual(result.answerability, "ambiguous")
        self.assertIn("AMBIGUOUS_SUBJECT_ENTITY", result.reason_codes)

    def test_contested_facts_are_not_a_single_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。守卫共有120名。"],
                [
                    {"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"},
                    {"evidence": "守卫共有120名。", "claim_type": "count", "subject": "守卫", "value": 120, "unit": "名"},
                ],
            )
            result = query_hybrid_index(paths[4], "守卫有多少名？")
        self.assertEqual(result.answerability, "ambiguous")
        self.assertIn("CONTESTED_FACTS_PRESENT", result.reason_codes)

    def test_temporal_scope_selects_past_or_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["守卫共有100名。后来守卫共有120名。"],
                [
                    {"evidence": "守卫共有100名。", "claim_type": "count", "subject": "守卫", "value": 100, "unit": "名"},
                    {"evidence": "后来守卫共有120名。", "claim_type": "count", "subject": "守卫", "value": 120, "unit": "名"},
                ],
            )
            unspecified = query_hybrid_index(paths[4], "守卫有多少名？")
            current = query_hybrid_index(paths[4], "守卫现在有多少名？")
            past = query_hybrid_index(paths[4], "守卫最初有多少名？")
        self.assertEqual(unspecified.answerability, "ambiguous")
        self.assertEqual(current.answerability, "answerable")
        self.assertEqual(current.hits[0].value, 120)
        self.assertEqual(past.answerability, "answerable")
        self.assertEqual(past.hits[0].value, 100)

    def test_evidence_offsets_are_exact(self):
        source = "序言。张三击败李四。尾声。"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                [source],
                [{"evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"}],
            )
            result = query_hybrid_index(paths[4], "张三击败了谁？")
        hit = result.hits[0]
        self.assertEqual(source[hit.evidence_start : hit.evidence_end], hit.evidence_text)


    def test_alias_boolean_requires_the_exact_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["北门后来改称玄门。"],
                [{"evidence": "北门后来改称玄门。", "claim_type": "alias", "subject": "北门", "object": "玄门"}],
            )
            correct = query_hybrid_index(paths[4], "北门改称玄门吗？")
            wrong = query_hybrid_index(paths[4], "北门改称太阳宫吗？")
        self.assertEqual(correct.answerability, "answerable")
        self.assertEqual(wrong.answerability, "not_answerable")

    def test_permission_and_date_predicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["系统允许删除。工程始于2001年2月3日。"],
                [
                    {"evidence": "系统允许删除。", "claim_type": "permission", "subject": "系统", "object": "删除", "polarity": True},
                    {"evidence": "工程始于2001年2月3日。", "claim_type": "date", "subject": "工程", "value": "2001-02-03"},
                ],
            )
            permission = query_hybrid_index(paths[4], "系统允许删除吗？")
            date = query_hybrid_index(paths[4], "工程什么时候开始？")
        self.assertEqual(permission.answerability, "answerable")
        self.assertTrue(permission.hits[0].polarity)
        self.assertEqual(date.answerability, "answerable")
        self.assertEqual(date.hits[0].value, "2001-02-03")

    def test_index_contains_structured_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.build(
                root,
                ["张三击败李四。"],
                [{"evidence": "张三击败李四。", "claim_type": "defeats", "subject": "张三", "object": "李四"}],
            )
            connection = sqlite3.connect(paths[4])
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            connection.close()
        self.assertTrue({"entities", "facts", "timeline", "conflicts", "ambiguity_groups"}.issubset(names))


if __name__ == "__main__":
    unittest.main()
