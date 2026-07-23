from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tkr.notion_cli import main as notion_main
from tkr.notion_engine import (
    NOTION_LEDGER_SCHEMA_VERSION,
    NotionRelation,
    relation_set_hash,
)
from tkr.notion_project import (
    NotionProjectError,
    build_notion_project,
    verify_notion_project,
)
from tests.test_reasoning_project import Fixture as ReasoningFixture

SRC = "src-1"
CH1 = "lch-1"
CH2 = "lch-2"
E1 = "lea-1"
E2 = "lea-2"
E3 = "lea-unused"
CCH1 = "cch-1"
CCH2 = "cch-2"
UNIT1 = "unit-1"
UNIT2 = "unit-2"
PROJECT_ID = "source-project-1"


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


def _verified(graph_valid: bool = True):
    return SimpleNamespace(valid=True, graph_valid=graph_valid, reason_codes=())


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.base = ReasoningFixture(root)
        self.reasoning = root / "reasoning-project"
        self._augment_upstream()
        self.base.build(self.reasoning)

    def _augment_upstream(self) -> None:
        _write_json(
            self.base.source / "project-report.json",
            {
                "project_id": PROJECT_ID,
                "source_id": SRC,
                "source_filename": "novel.txt",
                "raw_source_sha256": "1" * 64,
                "normalized_source_sha256": "2" * 64,
                "selected_encoding": "utf-8",
            },
        )
        chapters = [
            {
                "schema_version": "tkr-canonical-chapter-v1",
                "chapter_id": CCH1,
                "project_id": PROJECT_ID,
                "input_file_order": 0,
                "source_id": SRC,
                "source_sha256": "2" * 64,
                "source_filename": "novel.txt",
                "unit_id": UNIT1,
                "unit_type": "chapter",
                "source_local_order": 0,
                "global_physical_order": 0,
                "volume_ordinal": 1,
                "volume_basis": "combined_heading",
                "chapter_ordinal": 1,
                "original_heading": "第一章 开端",
                "normalized_heading": "第一章 开端",
                "title": "开端",
                "start_char": 0,
                "end_char": 100,
                "start_line": 1,
                "end_line": 10,
                "body_start_char": 10,
                "body_end_char": 100,
                "content_sha256": "3" * 64,
                "structure_confidence": "high",
                "review_status": "accepted_candidate",
                "contamination_status": "clean",
                "canonical_key": "v00000001:c00000001",
            },
            {
                "schema_version": "tkr-canonical-chapter-v1",
                "chapter_id": CCH2,
                "project_id": PROJECT_ID,
                "input_file_order": 0,
                "source_id": SRC,
                "source_sha256": "2" * 64,
                "source_filename": "novel.txt",
                "unit_id": UNIT2,
                "unit_type": "chapter",
                "source_local_order": 1,
                "global_physical_order": 1,
                "volume_ordinal": 1,
                "volume_basis": "preceding_volume_context",
                "chapter_ordinal": 2,
                "original_heading": "第二章 变化",
                "normalized_heading": "第二章 变化",
                "title": "变化",
                "start_char": 100,
                "end_char": 200,
                "start_line": 11,
                "end_line": 20,
                "body_start_char": 110,
                "body_end_char": 200,
                "content_sha256": "4" * 64,
                "structure_confidence": "high",
                "review_status": "accepted_candidate",
                "contamination_status": "clean",
                "canonical_key": "v00000001:c00000002",
            },
        ]
        _write_jsonl(self.base.chapter / "chapters.jsonl", chapters)
        _write_jsonl(self.base.chapter / "chapter-findings.jsonl", [])
        _write_jsonl(
            self.base.literary / "chapters.jsonl",
            [
                {"chapter_id": CH1, "source_id": SRC, "unit_id": UNIT1},
                {"chapter_id": CH2, "source_id": SRC, "unit_id": UNIT2},
            ],
        )
        _write_jsonl(
            self.base.literary / "entities.jsonl",
            [{"entity_id": "entity-character-1", "canonical_name": "甲"}],
        )
        anchors = _read_jsonl(self.base.literary / "evidence-anchors.jsonl")
        for row in anchors:
            row["unit_id"] = UNIT1 if row["anchor_id"] == E1 else UNIT2
            row["source_status"] = "clean"
            row["evidence_sha256"] = ("5" if row["anchor_id"] == E1 else "6") * 64
        anchors.append(
            {
                "anchor_id": E3,
                "source_id": SRC,
                "unit_id": UNIT2,
                "chapter_id": CH2,
                "evidence_start": 50,
                "evidence_end": 55,
                "evidence_text": "未引用",
                "evidence_sha256": "7" * 64,
                "source_status": "clean",
            }
        )
        _write_jsonl(self.base.literary / "evidence-anchors.jsonl", anchors)
        claim_anchors = [row for row in anchors if row["anchor_id"] in {E1, E2}]
        _write_jsonl(self.base.evidence / "claim-evidence-anchors.jsonl", claim_anchors)
        events = _read_jsonl(self.base.event / "events.jsonl")
        events[0].update(
            {
                "start_chapter_id": CCH1,
                "end_chapter_id": CCH2,
                "start_position": 0,
                "end_position": 1,
                "event_type": "mainline_change",
                "significance": "main_plot",
                "participant_entity_ids": ["entity-character-1"],
                "review_status": "active",
            }
        )
        _write_jsonl(self.base.event / "events.jsonl", events)
        _write_jsonl(self.base.event / "event-findings.jsonl", [])
        characters = _read_jsonl(self.base.character / "characters.jsonl")
        characters[0].update(
            {
                "canonical_name": "甲",
                "aliases": ["主角甲"],
                "scope": "core",
                "selection_reasons": ["main_plot_impact"],
                "first_chapter_id": CCH1,
                "last_chapter_id": CCH2,
                "first_position": 0,
                "last_position": 1,
                "review_status": "active",
                "evidence_anchor_ids": [E1],
            }
        )
        _write_jsonl(self.base.character / "characters.jsonl", characters)
        _write_jsonl(self.base.character / "character-findings.jsonl", [])

    @property
    def bindings(self):
        return self.base.bindings

    @property
    def sources(self):
        return self.base.sources

    @property
    def literary_projects(self):
        return self.base.literary_projects

    def build(self, output: Path, *, ledger: Path | None = None):
        return build_notion_project(
            self.base.chapter,
            self.sources,
            self.literary_projects,
            self.bindings,
            self.base.event,
            self.base.event_annotations,
            self.base.character,
            self.base.character_annotations,
            self.reasoning,
            self.base.reasoning_annotations,
            output,
            ledger_path=ledger,
        )

    def verify(self, output: Path, *, ledger: Path | None = None):
        return verify_notion_project(
            self.base.chapter,
            self.sources,
            self.literary_projects,
            self.bindings,
            self.base.event,
            self.base.event_annotations,
            self.base.character,
            self.base.character_annotations,
            self.reasoning,
            self.base.reasoning_annotations,
            output,
            ledger_path=ledger,
        )

    def make_ledger(self, project: Path, path: Path, *, extra: bool = False) -> Path:
        pages = _read_jsonl(project / "notion-pages.jsonl")
        relations = [NotionRelation(**row) for row in _read_jsonl(project / "notion-relations.jsonl")]
        entries = []
        for index, page in enumerate(pages):
            entries.append(
                {
                    "schema_version": NOTION_LEDGER_SCHEMA_VERSION,
                    "page_key": page["page_key"],
                    "notion_page_id": f"remote-{index:04d}",
                    "content_sha256": page["content_sha256"],
                    "relation_sha256": relation_set_hash(page["page_key"], relations),
                    "archived": False,
                }
            )
        if extra:
            entries.append(
                {
                    "schema_version": NOTION_LEDGER_SCHEMA_VERSION,
                    "page_key": "npg_" + "f" * 32,
                    "notion_page_id": "remote-old-page",
                    "content_sha256": "8" * 64,
                    "relation_sha256": "9" * 64,
                    "archived": False,
                }
            )
        _write_json(path, {"schema_version": NOTION_LEDGER_SCHEMA_VERSION, "entries": entries})
        return path


class PatchedUpstreamVerification(unittest.TestCase):
    def setUp(self) -> None:
        patches = [
            patch("tkr.reasoning_project.verify_chapter_project", return_value=_verified()),
            patch("tkr.reasoning_project.verify_literary_engine", return_value=_verified()),
            patch("tkr.reasoning_project.verify_evidence_project", return_value=_verified()),
            patch("tkr.reasoning_project.verify_event_project", return_value=_verified()),
            patch("tkr.reasoning_project.verify_character_project", return_value=_verified()),
            patch("tkr.notion_project.verify_reasoning_project", return_value=_verified()),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)


class NotionProjectTests(PatchedUpstreamVerification):
    def test_build_and_verify_complete_projection(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            result = fixture.build(output)
            verification = fixture.verify(output)
            self.assertEqual(result.status, "completed")
            self.assertTrue(result.projection_valid)
            self.assertTrue(verification.valid)
            self.assertTrue(verification.projection_valid)
            self.assertGreater(result.database_counts["facts_a"], 0)
            self.assertGreater(result.database_counts["synthesis_b"], 0)
            self.assertGreater(result.database_counts["interpretations_c"], 0)
            self.assertGreater(result.database_counts["counterfactuals_h"], 0)

    def test_only_referenced_evidence_is_projected(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            pages = _read_jsonl(output / "notion-pages.jsonl")
            evidence_ids = {
                row["record_id"]
                for row in pages
                if row["database_key"] == "evidence"
            }
            self.assertEqual(evidence_ids, {E1, E2})
            self.assertNotIn(E3, evidence_ids)

    def test_A_B_C_H_are_in_distinct_databases(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            pages = _read_jsonl(output / "notion-pages.jsonl")
            database_by_layer = {
                "A": "facts_a",
                "B": "synthesis_b",
                "C": "interpretations_c",
                "H": "counterfactuals_h",
            }
            for row in pages:
                layer = row.get("epistemic_layer")
                if layer:
                    self.assertEqual(row["database_key"], database_by_layer[layer])

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
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
                    result.page_count,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
                    result.relation_count,
                )
            finally:
                connection.close()

    def test_repeated_build_is_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            one = fixture.build(first)
            two = fixture.build(second)
            self.assertEqual(one.logical_sha256, two.logical_sha256)
            for name in (
                "notion-workspace-schema.json",
                "notion-pages.jsonl",
                "notion-relations.jsonl",
                "notion-review-items.jsonl",
                "notion-sync-plan.jsonl",
                "notion.sqlite",
            ):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_prior_ledger_yields_idempotent_noops(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first"
            fixture.build(first)
            ledger = fixture.make_ledger(first, Path(directory) / "ledger.json")
            second = Path(directory) / "second"
            result = fixture.build(second, ledger=ledger)
            actions = _read_jsonl(second / "notion-sync-plan.jsonl")
            self.assertTrue(actions)
            self.assertTrue(all(row["action"] == "noop" for row in actions))
            self.assertEqual(result.action_counts["noop"], len(actions))

    def test_title_change_updates_same_stable_page(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first"
            fixture.build(first)
            ledger = fixture.make_ledger(first, Path(directory) / "ledger.json")
            rows = _read_jsonl(fixture.base.character / "characters.jsonl")
            old_id = rows[0]["character_id"]
            rows[0]["canonical_name"] = "甲的新称号"
            _write_jsonl(fixture.base.character / "characters.jsonl", rows)
            second = Path(directory) / "second"
            fixture.build(second, ledger=ledger)
            pages = _read_jsonl(second / "notion-pages.jsonl")
            character_page = next(
                row for row in pages
                if row["database_key"] == "characters" and row["record_id"] == old_id
            )
            actions = _read_jsonl(second / "notion-sync-plan.jsonl")
            action = next(
                row for row in actions
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
            self.assertEqual(
                sum(row["action"] == "archive_candidate" for row in actions),
                1,
            )
            pages = _read_jsonl(second / "notion-pages.jsonl")
            self.assertGreater(
                sum(row["database_key"] == "review_queue" for row in pages),
                0,
            )
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


class NotionCliTests(PatchedUpstreamVerification):
    def _common(self, fixture: Fixture) -> list[str]:
        return [
            str(fixture.base.chapter),
            str(fixture.base.event),
            str(fixture.base.event_annotations),
            str(fixture.base.character),
            str(fixture.base.character_annotations),
            str(fixture.reasoning),
            str(fixture.base.reasoning_annotations),
            "--source-project", str(fixture.base.source),
            "--literary-project", str(fixture.base.literary),
            "--evidence-binding", str(fixture.base.source), str(fixture.base.literary), str(fixture.base.evidence),
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
            code, plan = self._run([
                "plan", str(output), *self._common(fixture),
                "--action", "create", "--target-type", "page",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(plan["decision"], "answered")
            self.assertGreater(plan["action_count"], 0)
            self.assertTrue(all(row["action"] == "create" for row in plan["actions"]))

    def test_plan_filter_by_database(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "notion-project"
            fixture.build(output)
            code, plan = self._run([
                "plan", str(output), *self._common(fixture),
                "--database-key", "counterfactuals_h",
            ])
            self.assertEqual(code, 0)
            self.assertGreater(plan["action_count"], 0)


if __name__ == "__main__":
    unittest.main()
