from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from tkr.character_cli import main as character_cli_main
from tkr.character_engine import (
    CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
    CHARACTER_EVENT_LINK_SCHEMA_VERSION,
    CHARACTER_RELATIONSHIP_SCHEMA_VERSION,
    CHARACTER_SCHEMA_VERSION,
    CHARACTER_STATE_SCHEMA_VERSION,
    CharacterAttribute,
    CharacterEventLink,
    CharacterRelationship,
    CharacterState,
    FocusedCharacter,
    character_id,
)
from tkr.character_project import (
    CHARACTER_ANNOTATION_SCHEMA_VERSION,
    build_character_project,
    verify_character_project,
)
from tkr.event_project import build_event_project
from tests.test_event_project import EventProjectFixture


def _write_annotation(path: Path, rows: list[tuple[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                {
                    "schema_version": CHARACTER_ANNOTATION_SCHEMA_VERSION,
                    "record_type": record_type,
                    "record": record.to_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for record_type, record in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


class CharacterProjectFixture:
    def __init__(self, root: Path, *, review_event_graph: bool = False) -> None:
        self.root = root
        self.event_fixture = EventProjectFixture(root)
        self.source_projects = self.event_fixture.source_projects
        self.chapter_project = self.event_fixture.chapter_project
        self.literary_project = self.event_fixture.literary_project
        self.chapters = self.event_fixture.chapters
        self.assertions = self.event_fixture.assertions
        self.anchors = self.event_fixture.anchors
        self.event_annotations = root / ("cycle-events.jsonl" if review_event_graph else "events.jsonl")
        if review_event_graph:
            self.event_fixture.cycle_annotation(self.event_annotations)
        else:
            self.events, _, _ = self.event_fixture.valid_annotation(self.event_annotations)
        self.event_project = root / ("review-event-project" if review_event_graph else "event-project")
        with self.patches():
            build_event_project(
                self.chapter_project,
                self.source_projects,
                [self.literary_project],
                self.event_annotations,
                self.event_project,
            )
        if review_event_graph:
            self.events = [
                type("EventRef", (), row)
                for row in [
                    json.loads(line)
                    for line in (self.event_project / "events.jsonl").read_text(encoding="utf-8").splitlines()
                ]
            ]
        self.character_annotations = root / "characters.jsonl"
        self.characters = self._write_valid_characters(self.character_annotations)

    def patches(self):
        return self.event_fixture.patches()

    def _write_valid_characters(self, path: Path) -> list[FocusedCharacter]:
        chapter0, chapter1, chapter2 = self.chapters[:3]
        core = FocusedCharacter(
            CHARACTER_SCHEMA_VERSION,
            character_id("林舟", chapter0["chapter_id"]),
            "林舟",
            ("林舟", "舟客"),
            "core",
            ("main_plot_driver",),
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            (self.anchors[0],),
            (),
            "active",
        )
        important = FocusedCharacter(
            CHARACTER_SCHEMA_VERSION,
            character_id("赵衡", chapter0["chapter_id"]),
            "赵衡",
            ("赵衡",),
            "important",
            ("major_event_cause_or_resolution",),
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            (self.anchors[1],),
            (),
            "active",
        )
        placeholder = FocusedCharacter(
            CHARACTER_SCHEMA_VERSION,
            character_id("守门人", chapter1["chapter_id"]),
            "守门人",
            ("守门人",),
            "placeholder",
            (),
            chapter1["chapter_id"],
            chapter1["chapter_id"],
            chapter1["global_physical_order"],
            chapter1["global_physical_order"],
            (self.anchors[2],),
            (),
            "active",
        )
        identity = CharacterAttribute(
            CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
            "cat_core_identity",
            core.character_id,
            core.scope,
            "identity",
            "A",
            "剑修",
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            (self.assertions[0],),
            (self.anchors[0],),
            (),
            1.0,
            (),
            "source_explicit",
            "active",
        )
        choice1 = CharacterAttribute(
            CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
            "cat_choice_1",
            core.character_id,
            core.scope,
            "choice",
            "A",
            "公开秘密",
            chapter0["chapter_id"],
            chapter0["chapter_id"],
            chapter0["global_physical_order"],
            chapter0["global_physical_order"],
            (self.assertions[0],),
            (self.anchors[0],),
            (),
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        choice2 = CharacterAttribute(
            CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
            "cat_choice_2",
            core.character_id,
            core.scope,
            "choice",
            "A",
            "承担后果",
            chapter1["chapter_id"],
            chapter1["chapter_id"],
            chapter1["global_physical_order"],
            chapter1["global_physical_order"],
            (self.assertions[1],),
            (self.anchors[1],),
            (),
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        arc_b = CharacterAttribute(
            CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
            "cat_arc_b",
            core.character_id,
            core.scope,
            "arc",
            "B",
            "从隐瞒转向承担公开责任",
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            (),
            (),
            (choice1.attribute_id, choice2.attribute_id),
            0.9,
            ("跨两次明确选择形成的归纳",),
            "cross_evidence_synthesis",
            "active",
        )
        arc_c = CharacterAttribute(
            CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
            "cat_arc_c",
            core.character_id,
            core.scope,
            "arc",
            "C",
            "可解释为从自我保护转向公共责任",
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            (),
            (),
            (arc_b.attribute_id,),
            0.7,
            ("属于模型文学解释，不代表作者明确结论",),
            "model_interpretation",
            "active",
        )
        important_role = CharacterAttribute(
            CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
            "cat_important_role",
            important.character_id,
            important.scope,
            "role",
            "A",
            "联盟关键成员",
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            (self.assertions[1],),
            (self.anchors[1],),
            (),
            1.0,
            (),
            "source_explicit",
            "active",
        )
        placeholder_role = CharacterAttribute(
            CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
            "cat_placeholder_role",
            placeholder.character_id,
            placeholder.scope,
            "role",
            "A",
            "守门人",
            chapter1["chapter_id"],
            chapter1["chapter_id"],
            chapter1["global_physical_order"],
            chapter1["global_physical_order"],
            (self.assertions[2],),
            (self.anchors[2],),
            (),
            1.0,
            (),
            "source_explicit",
            "active",
        )
        alive = CharacterState(
            CHARACTER_STATE_SCHEMA_VERSION,
            "cst_core_alive",
            core.character_id,
            "life_status",
            "alive",
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            "A",
            (self.assertions[0],),
            (self.anchors[0],),
            1.0,
            (),
            "source_explicit",
            "active",
        )
        relationship = CharacterRelationship(
            CHARACTER_RELATIONSHIP_SCHEMA_VERSION,
            "crl_core_important",
            core.character_id,
            important.character_id,
            "opponents_then_allies",
            "A",
            chapter0["chapter_id"],
            chapter2["chapter_id"],
            chapter0["global_physical_order"],
            chapter2["global_physical_order"],
            (self.events[1].event_id,),
            (self.assertions[1],),
            (self.anchors[1],),
            (),
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        core_link = CharacterEventLink(
            CHARACTER_EVENT_LINK_SCHEMA_VERSION,
            "cel_core_event",
            core.character_id,
            self.events[1].event_id,
            "causes",
            "A",
            (self.assertions[1],),
            (self.anchors[1],),
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        important_link = CharacterEventLink(
            CHARACTER_EVENT_LINK_SCHEMA_VERSION,
            "cel_important_event",
            important.character_id,
            self.events[2].event_id,
            "participant",
            "A",
            (self.assertions[2],),
            (self.anchors[2],),
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        placeholder_link = CharacterEventLink(
            CHARACTER_EVENT_LINK_SCHEMA_VERSION,
            "cel_placeholder_event",
            placeholder.character_id,
            self.events[1].event_id,
            "participant",
            "A",
            (self.assertions[2],),
            (self.anchors[2],),
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        rows: list[tuple[str, object]] = [
            ("character", core),
            ("character", important),
            ("character", placeholder),
            ("attribute", identity),
            ("attribute", choice1),
            ("attribute", choice2),
            ("attribute", arc_b),
            ("attribute", arc_c),
            ("attribute", important_role),
            ("attribute", placeholder_role),
            ("state", alive),
            ("relationship", relationship),
            ("event_link", core_link),
            ("event_link", important_link),
            ("event_link", placeholder_link),
        ]
        _write_annotation(path, rows)
        return [core, important, placeholder]


class CharacterProjectTests(unittest.TestCase):
    def test_build_verify_and_sqlite_scope_counts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = CharacterProjectFixture(root)
            output = root / "character-project"
            with fixture.patches():
                report = build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
                verification = verify_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
            self.assertEqual(report["status"], "completed")
            self.assertTrue(report["graph_valid"])
            self.assertTrue(verification.valid, verification.reason_codes)
            connection = sqlite3.connect(output / "character.sqlite")
            try:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                counts = dict(connection.execute("SELECT scope,COUNT(*) FROM characters GROUP BY scope"))
                self.assertEqual(counts, {"core": 1, "important": 1, "placeholder": 1})
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM attributes").fetchone()[0], 7)
            finally:
                connection.close()

    def test_repeated_character_projects_are_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = CharacterProjectFixture(root)
            first = root / "first"
            second = root / "second"
            with fixture.patches():
                first_report = build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    first,
                )
                second_report = build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    second,
                )
            self.assertEqual(first_report["logical_sha256"], second_report["logical_sha256"])
            self.assertEqual(first_report["database_sha256"], second_report["database_sha256"])
            for name in (
                "characters.jsonl",
                "character-attributes.jsonl",
                "character-states.jsonl",
                "character-relationships.jsonl",
                "character-event-links.jsonl",
                "character-findings.jsonl",
                "character.sqlite",
            ):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_review_event_graph_produces_review_required_character_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = CharacterProjectFixture(root, review_event_graph=True)
            output = root / "character-project"
            with fixture.patches():
                report = build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
                verification = verify_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
            self.assertEqual(report["status"], "review_required")
            self.assertFalse(report["graph_valid"])
            self.assertTrue(verification.valid)
            self.assertFalse(verification.graph_valid)
            rules = {
                json.loads(line)["rule_id"]
                for line in (output / "character-findings.jsonl").read_text(encoding="utf-8").splitlines()
            }
            self.assertIn("ACTIVE_LINK_TO_REVIEW_REQUIRED_EVENT_GRAPH", rules)

    def test_tampered_character_artifact_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = CharacterProjectFixture(root)
            output = root / "character-project"
            with fixture.patches():
                build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
            path = output / "characters.jsonl"
            path.write_text(path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with fixture.patches():
                verification = verify_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
            self.assertFalse(verification.valid)
            self.assertIn("CHARACTER_FILE_SIZE_MISMATCH:characters.jsonl", verification.reason_codes)


class CharacterCliTests(unittest.TestCase):
    def _common(self, fixture: CharacterProjectFixture, output: Path) -> list[str]:
        return [
            "query",
            str(output),
            str(fixture.chapter_project),
            str(fixture.event_project),
            str(fixture.event_annotations),
            str(fixture.character_annotations),
            "--source-project",
            str(fixture.source_projects[0]),
            "--source-project",
            str(fixture.source_projects[1]),
            "--literary-project",
            str(fixture.literary_project),
        ]

    def _run(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stream = StringIO()
        with redirect_stdout(stream):
            code = character_cli_main(args)
        return code, json.loads(stream.getvalue())

    def test_profile_state_relationship_events_and_arc_are_evidence_linked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = CharacterProjectFixture(root)
            output = root / "character-project"
            with fixture.patches():
                build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
                common = self._common(fixture, output)
                profile_code, profile = self._run([*common, "--name", "林舟"])
                state_code, state = self._run([*common, "--state-at", "林舟", "1"])
                relationship_code, relationship = self._run(
                    [*common, "--relationship-at", "林舟", "赵衡", "1"]
                )
                event_code, events = self._run([*common, "--events", "林舟"])
                arc_code, arc = self._run([*common, "--arc", "林舟"])
            self.assertEqual(
                (profile_code, state_code, relationship_code, event_code, arc_code),
                (0, 0, 0, 0, 0),
            )
            self.assertEqual(profile["character"]["scope"], "core")
            self.assertTrue(profile["attributes"][0]["support"]["evidence"])
            self.assertEqual(state["states"][0]["state_value"], "alive")
            self.assertTrue(relationship["relationships"][0]["support"]["evidence"])
            self.assertEqual(events["event_links"][0]["event"]["canonical_name"], "秘密公开")
            self.assertEqual({item["tier"] for item in arc["arc"]}, {"B", "C"})

    def test_placeholder_is_minimal_and_deep_arc_refuses(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = CharacterProjectFixture(root)
            output = root / "character-project"
            with fixture.patches():
                build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
                common = self._common(fixture, output)
                profile_code, profile = self._run([*common, "--name", "守门人"])
                arc_code, arc = self._run([*common, "--arc", "守门人"])
                relationship_code, relationship = self._run(
                    [*common, "--relationship-at", "守门人", "林舟", "1"]
                )
            self.assertEqual(profile_code, 0)
            self.assertEqual(profile["character"]["scope"], "placeholder")
            self.assertEqual({item["attribute_type"] for item in profile["attributes"]}, {"role"})
            self.assertEqual(arc_code, 2)
            self.assertIn("CHARACTER_ARC_RESERVED_FOR_CORE_SCOPE", arc["reason_codes"])
            self.assertEqual(relationship_code, 2)
            self.assertIn(
                "PLACEHOLDER_DEEP_RELATIONSHIP_NOT_MODELED",
                relationship["reason_codes"],
            )

    def test_review_required_character_graph_refuses_query(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = CharacterProjectFixture(root, review_event_graph=True)
            output = root / "character-project"
            with fixture.patches():
                build_character_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    fixture.event_project,
                    fixture.event_annotations,
                    fixture.character_annotations,
                    output,
                )
                code, payload = self._run(
                    [*self._common(fixture, output), "--name", "林舟"]
                )
            self.assertEqual(code, 2)
            self.assertIn("CHARACTER_GRAPH_REVIEW_REQUIRED", payload["reason_codes"])


if __name__ == "__main__":
    unittest.main()
