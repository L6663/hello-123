from pathlib import Path

engine_path = Path("tests/test_notion_engine.py")
engine = engine_path.read_text(encoding="utf-8")
old = '''    def test_content_hash_rejects_manual_tampering(self) -> None:
        page = _page("chapters", "chapter", "chapter-1", "标题")
        with self.assertRaises(NotionEngineError):
            type(page)(**{**page.to_dict(), "source_lineage": page.source_lineage, "title": "被篡改"})
'''
new = '''    def test_content_hash_rejects_manual_tampering(self) -> None:
        page = _page("chapters", "chapter", "chapter-1", "标题")
        payload = page.to_dict()
        payload["source_lineage"] = page.source_lineage
        payload["content_sha256"] = "0" * 64
        with self.assertRaises(NotionEngineError):
            type(page)(**payload)
'''
if engine.count(old) != 1:
    raise SystemExit(f"expected one outdated tamper test, found {engine.count(old)}")
engine_path.write_text(engine.replace(old, new), encoding="utf-8", newline="\n")

project = r'''from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tkr.notion_cli import main as notion_main
from tkr.notion_engine import NOTION_LEDGER_SCHEMA_VERSION, NotionRelation, relation_set_hash
from tkr.notion_project import build_notion_project, verify_notion_project

SRC = "src-1"
PROJECT_ID = "source-project-1"
CCH1, CCH2 = "cch-1", "cch-2"
LCH1, LCH2 = "lch-1", "lch-2"
UNIT1, UNIT2 = "unit-1", "unit-2"
E1, E2, E3 = "lea-1", "lea-2", "lea-unused"
A1, B1, C1 = "las-a", "las-b", "las-c"
R_A1, R_A2, R_B, R_C, R_H = "rrn-a1", "rrn-a2", "rrn-b", "rrn-c", "rrn-h"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _verified():
    return SimpleNamespace(valid=True, graph_valid=True, reason_codes=())


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "source-project"
        self.chapter = root / "chapter-project"
        self.literary = root / "literary-project"
        self.evidence = root / "evidence-project"
        self.event = root / "event-project"
        self.character = root / "character-project"
        self.reasoning = root / "reasoning-project"
        self.event_annotations = root / "events.jsonl"
        self.character_annotations = root / "characters.jsonl"
        self.reasoning_annotations = root / "reasoning.jsonl"
        for directory in (
            self.source, self.chapter, self.literary, self.evidence,
            self.event, self.character, self.reasoning,
        ):
            directory.mkdir(parents=True)
        self.event_annotations.write_text("", encoding="utf-8")
        self.character_annotations.write_text("", encoding="utf-8")
        self.reasoning_annotations.write_text("", encoding="utf-8")
        self._materialize()

    def _materialize(self) -> None:
        _write_json(self.source / "project-report.json", {
            "project_id": PROJECT_ID,
            "source_id": SRC,
            "source_filename": "novel.txt",
            "raw_source_sha256": "1" * 64,
            "normalized_source_sha256": "2" * 64,
            "selected_encoding": "utf-8",
        })
        _write_json(self.chapter / "chapter-project-report.json", {"logical_sha256": "a" * 64})
        chapters = [
            {
                "chapter_id": CCH1, "project_id": PROJECT_ID, "source_id": SRC,
                "source_sha256": "2" * 64, "source_filename": "novel.txt",
                "unit_id": UNIT1, "unit_type": "chapter", "input_file_order": 0,
                "source_local_order": 0, "global_physical_order": 0,
                "volume_ordinal": 1, "volume_basis": "combined_heading",
                "chapter_ordinal": 1, "original_heading": "第一章 开端",
                "normalized_heading": "第一章 开端", "title": "开端",
                "start_char": 0, "end_char": 100, "start_line": 1, "end_line": 10,
                "body_start_char": 10, "body_end_char": 100,
                "content_sha256": "3" * 64, "structure_confidence": "high",
                "review_status": "accepted_candidate", "contamination_status": "clean",
                "canonical_key": "v00000001:c00000001",
            },
            {
                "chapter_id": CCH2, "project_id": PROJECT_ID, "source_id": SRC,
                "source_sha256": "2" * 64, "source_filename": "novel.txt",
                "unit_id": UNIT2, "unit_type": "chapter", "input_file_order": 0,
                "source_local_order": 1, "global_physical_order": 1,
                "volume_ordinal": 1, "volume_basis": "preceding_volume_context",
                "chapter_ordinal": 2, "original_heading": "第二章 变化",
                "normalized_heading": "第二章 变化", "title": "变化",
                "start_char": 100, "end_char": 200, "start_line": 11, "end_line": 20,
                "body_start_char": 110, "body_end_char": 200,
                "content_sha256": "4" * 64, "structure_confidence": "high",
                "review_status": "accepted_candidate", "contamination_status": "clean",
                "canonical_key": "v00000001:c00000002",
            },
        ]
        _write_jsonl(self.chapter / "chapters.jsonl", chapters)
        _write_jsonl(self.chapter / "chapter-findings.jsonl", [])

        _write_json(self.literary / "literary-report.json", {
            "project_id": "literary-project-1", "logical_sha256": "b" * 64,
        })
        _write_jsonl(self.literary / "chapters.jsonl", [
            {"chapter_id": LCH1, "source_id": SRC, "unit_id": UNIT1},
            {"chapter_id": LCH2, "source_id": SRC, "unit_id": UNIT2},
        ])
        _write_jsonl(self.literary / "entities.jsonl", [
            {"entity_id": "entity-character-1", "canonical_name": "甲"},
        ])
        assertions = [
            {
                "assertion_id": A1, "tier": "A", "subject_text": "秘密",
                "predicate": "被公开", "object_text": "", "assertion_kind": "fact",
                "polarity": True, "confidence": 1.0, "attribution": "source_fact",
                "status": "active", "revision": 1, "evidence_anchor_ids": [E1],
                "supporting_assertion_ids": [], "limitations": [],
            },
            {
                "assertion_id": B1, "tier": "B", "subject_text": "联盟",
                "predicate": "控制瓦解", "object_text": "", "assertion_kind": "synthesis",
                "polarity": True, "confidence": 0.9, "attribution": "cross_evidence_synthesis",
                "status": "active", "revision": 1, "evidence_anchor_ids": [],
                "supporting_assertion_ids": [A1], "limitations": ["归纳结论"],
            },
            {
                "assertion_id": C1, "tier": "C", "subject_text": "事件",
                "predicate": "象征权力叙事失效", "object_text": "", "assertion_kind": "interpretation",
                "polarity": True, "confidence": 0.7, "attribution": "model_interpretation",
                "status": "active", "revision": 1, "evidence_anchor_ids": [],
                "supporting_assertion_ids": [B1], "limitations": ["模型解释"],
            },
        ]
        _write_jsonl(self.literary / "assertions.jsonl", assertions)
        anchors = [
            {
                "anchor_id": E1, "source_id": SRC, "unit_id": UNIT1,
                "chapter_id": LCH1, "evidence_start": 0, "evidence_end": 5,
                "evidence_text": "秘密公开", "evidence_sha256": "5" * 64,
                "source_status": "clean",
            },
            {
                "anchor_id": E2, "source_id": SRC, "unit_id": UNIT2,
                "chapter_id": LCH2, "evidence_start": 10, "evidence_end": 16,
                "evidence_text": "联盟失控", "evidence_sha256": "6" * 64,
                "source_status": "clean",
            },
            {
                "anchor_id": E3, "source_id": SRC, "unit_id": UNIT2,
                "chapter_id": LCH2, "evidence_start": 20, "evidence_end": 23,
                "evidence_text": "未用", "evidence_sha256": "7" * 64,
                "source_status": "clean",
            },
        ]
        _write_jsonl(self.literary / "evidence-anchors.jsonl", anchors)

        _write_json(self.evidence / "evidence-project-report.json", {"logical_sha256": "c" * 64})
        _write_jsonl(
            self.evidence / "claim-evidence-anchors.jsonl",
            [row for row in anchors if row["anchor_id"] in {E1, E2}],
        )

        _write_json(self.event / "event-project-report.json", {
            "logical_sha256": "d" * 64, "graph_valid": True,
        })
        _write_jsonl(self.event / "events.jsonl", [
            {
                "event_id": "evt-1", "canonical_name": "秘密公开",
                "event_type": "mainline_change", "significance": "main_plot",
                "start_chapter_id": CCH1, "end_chapter_id": CCH2,
                "start_position": 0, "end_position": 1,
                "participant_entity_ids": ["entity-character-1"],
                "evidence_anchor_ids": [E1], "review_status": "active",
            }
        ])
        _write_jsonl(self.event / "event-components.jsonl", [
            {
                "component_id": "evc-1", "event_id": "evt-1",
                "component_type": "cause", "statement": "秘密公开引发失控",
                "evidence_anchor_ids": [E1],
            }
        ])
        _write_jsonl(self.event / "event-causal-edges.jsonl", [])
        _write_jsonl(self.event / "event-findings.jsonl", [])

        _write_json(self.character / "character-project-report.json", {
            "logical_sha256": "e" * 64, "graph_valid": True,
        })
        _write_jsonl(self.character / "characters.jsonl", [
            {
                "character_id": "chr-1", "canonical_name": "甲", "aliases": ["主角甲"],
                "scope": "core", "selection_reasons": ["main_plot_impact"],
                "first_chapter_id": CCH1, "last_chapter_id": CCH2,
                "first_position": 0, "last_position": 1,
                "review_status": "active", "evidence_anchor_ids": [E1],
            }
        ])
        _write_jsonl(self.character / "character-attributes.jsonl", [
            {
                "attribute_id": "cha-1", "character_id": "chr-1",
                "attribute_type": "choice", "tier": "A", "value": "公开秘密",
                "evidence_anchor_ids": [E1],
            }
        ])
        _write_jsonl(self.character / "character-states.jsonl", [])
        _write_jsonl(self.character / "character-relationships.jsonl", [])
        _write_jsonl(self.character / "character-event-links.jsonl", [
            {
                "link_id": "chl-1", "character_id": "chr-1", "event_id": "evt-1",
                "link_type": "participant", "evidence_anchor_ids": [E1],
            }
        ])
        _write_jsonl(self.character / "character-findings.jsonl", [])

        _write_json(self.reasoning / "reasoning-project-report.json", {
            "logical_sha256": "f" * 64, "graph_valid": True,
        })
        nodes = [
            {
                "node_id": R_A1, "layer": "A", "statement": "秘密被公开",
                "intent_tags": ["all", "fact"], "chapter_ids": [LCH1],
                "entity_ids": ["entity-character-1"], "event_ids": ["evt-1"],
                "upstream_record_ids": [A1], "support_node_ids": [],
                "evidence_anchor_ids": [E1], "independence_groups": [f"{SRC}:{LCH1}"],
                "confidence": 1.0, "attribution": "source_fact", "limitations": [],
                "alternatives": [], "counterfactual_premise": "", "inference_rule": "",
                "status": "active",
            },
            {
                "node_id": R_A2, "layer": "A", "statement": "联盟随后失控",
                "intent_tags": ["all", "fact"], "chapter_ids": [LCH2],
                "entity_ids": [], "event_ids": ["evt-1"],
                "upstream_record_ids": ["las-a2"], "support_node_ids": [],
                "evidence_anchor_ids": [E2], "independence_groups": [f"{SRC}:{LCH2}"],
                "confidence": 1.0, "attribution": "source_fact", "limitations": [],
                "alternatives": [], "counterfactual_premise": "", "inference_rule": "",
                "status": "active",
            },
            {
                "node_id": R_B, "layer": "B", "statement": "联盟控制开始瓦解",
                "intent_tags": ["all", "synthesis"], "chapter_ids": [LCH1, LCH2],
                "entity_ids": [], "event_ids": ["evt-1"], "upstream_record_ids": [],
                "support_node_ids": [R_A1, R_A2], "evidence_anchor_ids": [],
                "independence_groups": [f"{SRC}:{LCH1}", f"{SRC}:{LCH2}"],
                "confidence": 0.9, "attribution": "cross_evidence_synthesis",
                "limitations": ["原文未使用这一概括"], "alternatives": [],
                "counterfactual_premise": "", "inference_rule": "", "status": "active",
            },
            {
                "node_id": R_C, "layer": "C", "statement": "可解释为权力叙事失效",
                "intent_tags": ["all", "analysis"], "chapter_ids": [LCH1, LCH2],
                "entity_ids": [], "event_ids": ["evt-1"], "upstream_record_ids": [],
                "support_node_ids": [R_B], "evidence_anchor_ids": [],
                "independence_groups": [], "confidence": 0.7,
                "attribution": "model_interpretation", "limitations": ["模型解释"],
                "alternatives": ["也可解释为信任崩溃"], "counterfactual_premise": "",
                "inference_rule": "", "status": "active",
            },
            {
                "node_id": R_H, "layer": "H", "statement": "若秘密未公开联盟或维持更久",
                "intent_tags": ["all", "counterfactual"], "chapter_ids": [LCH1, LCH2],
                "entity_ids": [], "event_ids": ["evt-1"], "upstream_record_ids": [],
                "support_node_ids": [R_A1, R_A2], "evidence_anchor_ids": [],
                "independence_groups": [], "confidence": 0.5,
                "attribution": "counterfactual_inference", "limitations": ["其他冲突仍存在"],
                "alternatives": ["也可能因其他事件提前瓦解"],
                "counterfactual_premise": "秘密未公开", "inference_rule": "沿因果路径反向推演",
                "status": "active",
            },
        ]
        _write_jsonl(self.reasoning / "reasoning-nodes.jsonl", nodes)
        _write_jsonl(self.reasoning / "reasoning-edges.jsonl", [
            {"edge_id": "rre-1", "source_node_id": R_B, "relation": "independent_support", "target_node_id": R_A1, "status": "active"},
            {"edge_id": "rre-2", "source_node_id": R_B, "relation": "independent_support", "target_node_id": R_A2, "status": "active"},
            {"edge_id": "rre-3", "source_node_id": R_C, "relation": "derived_from", "target_node_id": R_B, "status": "active"},
            {"edge_id": "rre-4", "source_node_id": R_H, "relation": "counterfactual_premise", "target_node_id": R_A1, "status": "active"},
            {"edge_id": "rre-5", "source_node_id": R_H, "relation": "counterfactual_inference", "target_node_id": R_A2, "status": "active"},
        ])
        _write_jsonl(self.reasoning / "reasoning-findings.jsonl", [])

    @property
    def sources(self):
        return (self.source,)

    @property
    def literary_projects(self):
        return (self.literary,)

    @property
    def bindings(self):
        return ((self.source, self.literary, self.evidence),)

    def build(self, output: Path, *, ledger: Path | None = None):
        return build_notion_project(
            self.chapter, self.sources, self.literary_projects, self.bindings,
            self.event, self.event_annotations, self.character, self.character_annotations,
            self.reasoning, self.reasoning_annotations, output, ledger_path=ledger,
        )

    def verify(self, output: Path, *, ledger: Path | None = None):
        return verify_notion_project(
            self.chapter, self.sources, self.literary_projects, self.bindings,
            self.event, self.event_annotations, self.character, self.character_annotations,
            self.reasoning, self.reasoning_annotations, output, ledger_path=ledger,
        )

    def make_ledger(self, project: Path, path: Path, *, extra: bool = False) -> Path:
        pages = _read_jsonl(project / "notion-pages.jsonl")
        relations = [NotionRelation(**row) for row in _read_jsonl(project / "notion-relations.jsonl")]
        entries = [
            {
                "schema_version": NOTION_LEDGER_SCHEMA_VERSION,
                "page_key": page["page_key"],
                "notion_page_id": f"remote-{index:04d}",
                "content_sha256": page["content_sha256"],
                "relation_sha256": relation_set_hash(page["page_key"], relations),
                "archived": False,
            }
            for index, page in enumerate(pages)
        ]
        if extra:
            entries.append({
                "schema_version": NOTION_LEDGER_SCHEMA_VERSION,
                "page_key": "npg_" + "f" * 32,
                "notion_page_id": "remote-old-page",
                "content_sha256": "8" * 64,
                "relation_sha256": "9" * 64,
                "archived": False,
            })
        _write_json(path, {"schema_version": NOTION_LEDGER_SCHEMA_VERSION, "entries": entries})
        return path


class PatchedVerification(unittest.TestCase):
    def setUp(self) -> None:
        item = patch("tkr.notion_project.verify_reasoning_project", return_value=_verified())
        item.start()
        self.addCleanup(item.stop)


class NotionProjectTests(PatchedVerification):
    def test_build_and_verify_complete_projection(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            result = fixture.build(output)
            verification = fixture.verify(output)
            self.assertEqual(result.status, "completed")
            self.assertTrue(result.projection_valid)
            self.assertTrue(verification.valid)
            for database in ("facts_a", "synthesis_b", "interpretations_c", "counterfactuals_h"):
                self.assertGreater(result.database_counts[database], 0)

    def test_only_referenced_evidence_is_projected(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            evidence_ids = {
                row["record_id"] for row in _read_jsonl(output / "notion-pages.jsonl")
                if row["database_key"] == "evidence"
            }
            self.assertEqual(evidence_ids, {E1, E2})
            self.assertNotIn(E3, evidence_ids)

    def test_A_B_C_H_are_in_distinct_databases(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            expected = {"A": "facts_a", "B": "synthesis_b", "C": "interpretations_c", "H": "counterfactuals_h"}
            for row in _read_jsonl(output / "notion-pages.jsonl"):
                if row.get("epistemic_layer"):
                    self.assertEqual(row["database_key"], expected[row["epistemic_layer"]])

    def test_sqlite_matches_project_records(self) -> None:
        import sqlite3
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            result = fixture.build(output)
            connection = sqlite3.connect(output / "notion.sqlite")
            try:
                metadata = dict(connection.execute("SELECT key,value FROM metadata"))
                self.assertEqual(metadata["logical_sha256"], result.logical_sha256)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0], result.page_count)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0], result.relation_count)
            finally:
                connection.close()

    def test_repeated_build_is_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first, second = Path(directory) / "first", Path(directory) / "second"
            one, two = fixture.build(first), fixture.build(second)
            self.assertEqual(one.logical_sha256, two.logical_sha256)
            for name in (
                "notion-workspace-schema.json", "notion-pages.jsonl", "notion-relations.jsonl",
                "notion-review-items.jsonl", "notion-sync-plan.jsonl", "notion.sqlite",
            ):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_prior_ledger_yields_idempotent_noops(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first"
            fixture.build(first)
            ledger = fixture.make_ledger(first, Path(directory) / "ledger.json")
            second = Path(directory) / "second"
            fixture.build(second, ledger=ledger)
            actions = _read_jsonl(second / "notion-sync-plan.jsonl")
            self.assertTrue(actions)
            self.assertTrue(all(row["action"] == "noop" for row in actions))

    def test_title_change_updates_same_stable_page(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first"
            fixture.build(first)
            ledger = fixture.make_ledger(first, Path(directory) / "ledger.json")
            rows = _read_jsonl(fixture.character / "characters.jsonl")
            character_id = rows[0]["character_id"]
            rows[0]["canonical_name"] = "甲的新称号"
            _write_jsonl(fixture.character / "characters.jsonl", rows)
            second = Path(directory) / "second"
            fixture.build(second, ledger=ledger)
            character_page = next(
                row for row in _read_jsonl(second / "notion-pages.jsonl")
                if row["database_key"] == "characters" and row["record_id"] == character_id
            )
            action = next(
                row for row in _read_jsonl(second / "notion-sync-plan.jsonl")
                if row["target_type"] == "page" and row["target_key"] == character_page["page_key"]
            )
            self.assertEqual(action["action"], "update")
            self.assertTrue(action["notion_page_id"].startswith("remote-"))

    def test_extra_ledger_page_is_archive_candidate_and_review_page(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first"
            fixture.build(first)
            ledger = fixture.make_ledger(first, Path(directory) / "ledger.json", extra=True)
            second = Path(directory) / "second"
            result = fixture.build(second, ledger=ledger)
            actions = _read_jsonl(second / "notion-sync-plan.jsonl")
            self.assertEqual(sum(row["action"] == "archive_candidate" for row in actions), 1)
            pages = _read_jsonl(second / "notion-pages.jsonl")
            self.assertGreater(sum(row["database_key"] == "review_queue" for row in pages), 0)
            self.assertTrue(result.projection_valid)

    def test_tampered_page_artifact_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            with (output / "notion-pages.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            verification = fixture.verify(output)
            self.assertFalse(verification.valid)
            self.assertIn("NOTION_FILE_SIZE_MISMATCH", verification.reason_codes)

    def test_unregistered_file_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            (output / "extra.txt").write_text("unexpected", encoding="utf-8")
            verification = fixture.verify(output)
            self.assertFalse(verification.valid)
            self.assertIn("NOTION_PROJECT_FILE_SET_MISMATCH", verification.reason_codes)


class NotionCliTests(PatchedVerification):
    def _common(self, fixture: Fixture) -> list[str]:
        return [
            str(fixture.chapter), str(fixture.event), str(fixture.event_annotations),
            str(fixture.character), str(fixture.character_annotations),
            str(fixture.reasoning), str(fixture.reasoning_annotations),
            "--source-project", str(fixture.source),
            "--literary-project", str(fixture.literary),
            "--evidence-binding", str(fixture.source), str(fixture.literary), str(fixture.evidence),
        ]

    def _run(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stream = StringIO()
        with redirect_stdout(stream):
            code = notion_main(args)
        return code, json.loads(stream.getvalue())

    def test_build_verify_and_plan(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            code, built = self._run(["build", *self._common(fixture), "--outdir", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(built["status"], "completed")
            code, verified = self._run(["verify", str(output), *self._common(fixture)])
            self.assertEqual(code, 0)
            self.assertTrue(verified["valid"])
            code, plan = self._run(["plan", str(output), *self._common(fixture), "--action", "create", "--target-type", "page"])
            self.assertEqual(code, 0)
            self.assertGreater(plan["action_count"], 0)
            self.assertTrue(all(row["action"] == "create" for row in plan["actions"]))

    def test_plan_filter_by_database(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            code, plan = self._run(["plan", str(output), *self._common(fixture), "--database-key", "counterfactuals_h"])
            self.assertEqual(code, 0)
            self.assertGreater(plan["action_count"], 0)


if __name__ == "__main__":
    unittest.main()
'''
Path("tests/test_notion_project.py").write_text(project, encoding="utf-8", newline="\n")
