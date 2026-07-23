from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sqlite3
import unittest
from unittest.mock import patch

from tkr.chapter_project import build_chapter_project
from tkr.event_cli import main as event_cli_main
from tkr.event_engine import (
    EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
    EVENT_COMPONENT_SCHEMA_VERSION,
    EVENT_RECORD_SCHEMA_VERSION,
    CausalEvent,
    EventCausalEdge,
    EventComponent,
    causal_edge_id,
    component_id,
    event_id,
)
from tkr.event_project import (
    EVENT_ANNOTATION_SCHEMA_VERSION,
    build_event_project,
    verify_event_project,
)
from tkr.literary_engine import build_literary_engine
from tests.test_chapter_engine import _combined_source, _standalone_volume_source
from tests.test_chapter_project import _materialize
from tests.test_literary_engine import _make_project


def _verified():
    return SimpleNamespace(valid=True, reason_codes=())


def _write_annotation(path: Path, rows: list[tuple[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                {
                    "schema_version": EVENT_ANNOTATION_SCHEMA_VERSION,
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


class EventProjectFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        chapter_source_root = root / "chapter-sources"
        chapter_source_root.mkdir()
        self.source_projects = [
            _materialize(chapter_source_root, _standalone_volume_source()),
            _materialize(chapter_source_root, _combined_source()),
        ]
        self.chapter_project = root / "chapter-project"
        with patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified()):
            build_chapter_project(self.source_projects, self.chapter_project)

        literary_source_root = root / "literary-source"
        literary_source_root.mkdir()
        base_project = _make_project(literary_source_root)
        self.literary_project = root / "literary-project"
        with patch("tkr.literary_engine.verify_secure_knowledge_project", return_value=_verified()):
            build_literary_engine(base_project, self.literary_project)

        self.chapters = [
            json.loads(line)
            for line in (self.chapter_project / "chapters.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertions = [
            json.loads(line)["assertion_id"]
            for line in (self.literary_project / "assertions.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.anchors = [
            json.loads(line)["anchor_id"]
            for line in (self.literary_project / "evidence-anchors.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert len(self.assertions) >= 3
        assert len(self.anchors) >= 3

    def patches(self):
        stack = ExitStack()
        stack.enter_context(
            patch("tkr.chapter_project.verify_secure_knowledge_project", return_value=_verified())
        )
        return stack

    def valid_annotation(self, path: Path) -> tuple[list[CausalEvent], list[EventComponent], list[EventCausalEdge]]:
        chapter0, chapter1, chapter2 = self.chapters[:3]
        clue = CausalEvent(
            EVENT_RECORD_SCHEMA_VERSION,
            event_id("伏笔出现", chapter0["chapter_id"], chapter0["chapter_id"]),
            "伏笔出现",
            "foreshadowing_event",
            "major",
            chapter0["chapter_id"],
            chapter0["chapter_id"],
            chapter0["global_physical_order"],
            chapter0["global_physical_order"],
            (),
            (),
            (self.anchors[0],),
            (),
            "active",
        )
        reveal = CausalEvent(
            EVENT_RECORD_SCHEMA_VERSION,
            event_id("秘密公开", chapter1["chapter_id"], chapter1["chapter_id"]),
            "秘密公开",
            "revelation",
            "core",
            chapter1["chapter_id"],
            chapter1["chapter_id"],
            chapter1["global_physical_order"],
            chapter1["global_physical_order"],
            (),
            (),
            (self.anchors[1],),
            (),
            "active",
        )
        collapse = CausalEvent(
            EVENT_RECORD_SCHEMA_VERSION,
            event_id("联盟瓦解", chapter2["chapter_id"], chapter2["chapter_id"]),
            "联盟瓦解",
            "faction_collapse",
            "core",
            chapter2["chapter_id"],
            chapter2["chapter_id"],
            chapter2["global_physical_order"],
            chapter2["global_physical_order"],
            (),
            (),
            (self.anchors[2],),
            (),
            "active",
        )
        components: list[EventComponent] = []
        for event, kind, statement, assertion, anchor in (
            (clue, "foreshadowing", "线索首次出现", self.assertions[0], self.anchors[0]),
            (reveal, "outcome", "秘密被公开", self.assertions[1], self.anchors[1]),
            (collapse, "outcome", "联盟失去控制", self.assertions[2], self.anchors[2]),
        ):
            components.append(
                EventComponent(
                    EVENT_COMPONENT_SCHEMA_VERSION,
                    component_id(event.event_id, kind, "A", statement, (assertion,), (anchor,)),
                    event.event_id,
                    kind,
                    "A",
                    statement,
                    (assertion,),
                    (anchor,),
                    (),
                    1.0,
                    (),
                    "source_direct_event",
                    "active",
                )
            )
        foreshadow = EventCausalEdge(
            EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
            causal_edge_id(clue.event_id, "foreshadows", reveal.event_id, "A", (self.assertions[0],), (self.anchors[0],)),
            clue.event_id,
            "foreshadows",
            reveal.event_id,
            "A",
            (self.assertions[0],),
            (self.anchors[0],),
            (),
            clue.start_position,
            reveal.start_position,
            "forward",
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        undermines = EventCausalEdge(
            EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
            causal_edge_id(reveal.event_id, "undermines", collapse.event_id, "A", (self.assertions[1],), (self.anchors[1],)),
            reveal.event_id,
            "undermines",
            collapse.event_id,
            "A",
            (self.assertions[1],),
            (self.anchors[1],),
            (),
            reveal.start_position,
            collapse.start_position,
            "forward",
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        events = [clue, reveal, collapse]
        edges = [foreshadow, undermines]
        _write_annotation(
            path,
            [
                *(('event', item) for item in events),
                *(('component', item) for item in components),
                *(('edge', item) for item in edges),
            ],
        )
        return events, components, edges

    def cycle_annotation(self, path: Path) -> None:
        chapter = self.chapters[0]
        first = CausalEvent(
            EVENT_RECORD_SCHEMA_VERSION,
            event_id("同章事件甲", chapter["chapter_id"], chapter["chapter_id"]),
            "同章事件甲",
            "conflict",
            "major",
            chapter["chapter_id"],
            chapter["chapter_id"],
            chapter["global_physical_order"],
            chapter["global_physical_order"],
            (),
            (),
            (self.anchors[0],),
            (),
            "active",
        )
        second = CausalEvent(
            EVENT_RECORD_SCHEMA_VERSION,
            event_id("同章事件乙", chapter["chapter_id"], chapter["chapter_id"]),
            "同章事件乙",
            "conflict",
            "major",
            chapter["chapter_id"],
            chapter["chapter_id"],
            chapter["global_physical_order"],
            chapter["global_physical_order"],
            (),
            (),
            (self.anchors[1],),
            (),
            "active",
        )
        edges = []
        for source, target, assertion, anchor in (
            (first, second, self.assertions[0], self.anchors[0]),
            (second, first, self.assertions[1], self.anchors[1]),
        ):
            edges.append(
                EventCausalEdge(
                    EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
                    causal_edge_id(source.event_id, "enables", target.event_id, "A", (assertion,), (anchor,)),
                    source.event_id,
                    "enables",
                    target.event_id,
                    "A",
                    (assertion,),
                    (anchor,),
                    (),
                    source.start_position,
                    target.start_position,
                    "forward",
                    1.0,
                    (),
                    "source_direct_event",
                    "active",
                )
            )
        _write_annotation(
            path,
            [
                ("event", first),
                ("event", second),
                *(('edge', item) for item in edges),
            ],
        )


class EventProjectTests(unittest.TestCase):
    def test_build_verify_and_sqlite_graph(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EventProjectFixture(root)
            annotation = root / "events.jsonl"
            fixture.valid_annotation(annotation)
            output = root / "event-project"
            with fixture.patches():
                report = build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
                verification = verify_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
            self.assertEqual(report["status"], "completed")
            self.assertTrue(report["graph_valid"])
            self.assertTrue(verification.valid, verification.reason_codes)
            self.assertTrue(verification.graph_valid)
            connection = sqlite3.connect(output / "event.sqlite")
            try:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0], 2)
            finally:
                connection.close()

    def test_repeated_event_projects_are_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EventProjectFixture(root)
            annotation = root / "events.jsonl"
            fixture.valid_annotation(annotation)
            first = root / "first"
            second = root / "second"
            with fixture.patches():
                first_report = build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    first,
                )
                second_report = build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    second,
                )
            self.assertEqual(first_report["logical_sha256"], second_report["logical_sha256"])
            self.assertEqual(first_report["database_sha256"], second_report["database_sha256"])
            for name in (
                "events.jsonl",
                "event-components.jsonl",
                "event-causal-edges.jsonl",
                "event-findings.jsonl",
                "event.sqlite",
            ):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_cycle_project_is_preserved_as_review_required(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EventProjectFixture(root)
            annotation = root / "cycle.jsonl"
            fixture.cycle_annotation(annotation)
            output = root / "event-project"
            with fixture.patches():
                report = build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
                verification = verify_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
            self.assertEqual(report["status"], "review_required")
            self.assertFalse(report["graph_valid"])
            self.assertTrue(verification.valid)
            self.assertFalse(verification.graph_valid)
            findings = [
                json.loads(line)
                for line in (output / "event-findings.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("ACTIVE_CAUSAL_CYCLE", {item["rule_id"] for item in findings})

    def test_tampered_event_artifact_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EventProjectFixture(root)
            annotation = root / "events.jsonl"
            fixture.valid_annotation(annotation)
            output = root / "event-project"
            with fixture.patches():
                build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
            path = output / "events.jsonl"
            path.write_text(path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with fixture.patches():
                verification = verify_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
            self.assertFalse(verification.valid)
            self.assertIn("EVENT_FILE_SIZE_MISMATCH:events.jsonl", verification.reason_codes)


class EventCliTests(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stream = StringIO()
        with redirect_stdout(stream):
            code = event_cli_main(args)
        return code, json.loads(stream.getvalue())

    def _common(self, fixture: EventProjectFixture, annotation: Path, output: Path) -> list[str]:
        return [
            "query",
            str(output),
            str(fixture.chapter_project),
            str(annotation),
            "--source-project",
            str(fixture.source_projects[0]),
            "--source-project",
            str(fixture.source_projects[1]),
            "--literary-project",
            str(fixture.literary_project),
        ]

    def test_profile_path_and_foreshadowing_include_support(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EventProjectFixture(root)
            annotation = root / "events.jsonl"
            events, _, _ = fixture.valid_annotation(annotation)
            output = root / "event-project"
            with fixture.patches():
                build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
                profile_code, profile = self._run(
                    [*self._common(fixture, annotation, output), "--name", "秘密公开"]
                )
                path_code, path = self._run(
                    [
                        *self._common(fixture, annotation, output),
                        "--path",
                        events[0].event_id,
                        events[2].event_id,
                    ]
                )
                clue_code, clue = self._run(
                    [*self._common(fixture, annotation, output), "--foreshadowing"]
                )
            self.assertEqual((profile_code, path_code, clue_code), (0, 0, 0))
            self.assertEqual(profile["event"]["canonical_name"], "秘密公开")
            self.assertTrue(profile["components"][0]["support"]["evidence"])
            self.assertEqual(len(path["path"]), 2)
            self.assertTrue(all(item["support"]["evidence"] for item in path["path"]))
            self.assertEqual(clue["edges"][0]["relation_type"], "foreshadows")

    def test_missing_path_and_review_graph_refuse(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EventProjectFixture(root)
            annotation = root / "events.jsonl"
            events, _, _ = fixture.valid_annotation(annotation)
            output = root / "event-project"
            cycle_annotation = root / "cycle.jsonl"
            fixture.cycle_annotation(cycle_annotation)
            review_output = root / "review-event-project"
            with fixture.patches():
                build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    annotation,
                    output,
                )
                build_event_project(
                    fixture.chapter_project,
                    fixture.source_projects,
                    [fixture.literary_project],
                    cycle_annotation,
                    review_output,
                )
                path_code, path = self._run(
                    [
                        *self._common(fixture, annotation, output),
                        "--path",
                        events[2].event_id,
                        events[0].event_id,
                    ]
                )
                review_code, review = self._run(
                    [
                        *self._common(fixture, cycle_annotation, review_output),
                        "--name",
                        "同章事件甲",
                    ]
                )
            self.assertEqual(path_code, 2)
            self.assertIn("SUPPORTED_CAUSAL_PATH_NOT_FOUND", path["reason_codes"])
            self.assertEqual(review_code, 2)
            self.assertIn("EVENT_GRAPH_REVIEW_REQUIRED", review["reason_codes"])


if __name__ == "__main__":
    unittest.main()
