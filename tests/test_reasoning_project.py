from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tkr.reasoning_cli import main as reasoning_main
from tkr.reasoning_engine import (
    REASONING_EDGE_SCHEMA_VERSION,
    REASONING_NODE_SCHEMA_VERSION,
    ReasoningEdge,
    ReasoningNode,
    reasoning_edge_id,
    reasoning_node_id,
)
from tkr.reasoning_project import (
    REASONING_ANNOTATION_SCHEMA_VERSION,
    ReasoningProjectError,
    build_reasoning_project,
    verify_reasoning_project,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64
SRC = "src-1"
CH1 = "lch-1"
CH2 = "lch-2"
A1 = "las-1"
A2 = "las-2"
E1 = "lea-1"
E2 = "lea-2"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _verified(graph_valid: bool = True):
    return SimpleNamespace(valid=True, reason_codes=(), graph_valid=graph_valid)


def _a(statement: str, record: str, evidence: str, chapter: str) -> ReasoningNode:
    group = f"{SRC}:{chapter}"
    return ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("A", statement, (record,)),
        "A",
        statement,
        ("all", "fact"),
        (chapter,),
        (),
        (),
        (record,),
        (),
        (evidence,),
        (group,),
        1.0,
        "source_fact",
        (),
        (),
        "",
        "",
        "active",
    )


def _records(cycle: bool = False):
    first = _a("秘密被公开", A1, E1, CH1)
    second = _a("联盟随后失去控制", A2, E2, CH2)
    synthesis = ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("B", "联盟控制开始瓦解", (first.node_id, second.node_id)),
        "B",
        "联盟控制开始瓦解",
        ("all", "mainline_cause"),
        (CH1, CH2),
        (),
        (),
        (),
        (first.node_id, second.node_id),
        (),
        (f"{SRC}:{CH1}", f"{SRC}:{CH2}"),
        0.91,
        "cross_evidence_synthesis",
        ("原文没有使用这一概括性术语",),
        (),
        "",
        "",
        "active",
    )
    interpretation = ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("C", "可以解释为权力叙事失效", (synthesis.node_id,)),
        "C",
        "可以解释为权力叙事失效",
        ("all", "theme"),
        (CH1, CH2),
        (),
        (),
        (),
        (synthesis.node_id,),
        (),
        (),
        0.72,
        "model_interpretation",
        ("‘权力叙事’是分析概念，不是原文术语",),
        ("也可解释为联盟成员信任崩溃",),
        "",
        "",
        "active",
    )
    hypothetical = ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("H", "若秘密未公开，联盟可能维持更久", (first.node_id, second.node_id)),
        "H",
        "若秘密未公开，联盟可能维持更久",
        ("all", "counterfactual"),
        (CH1, CH2),
        (),
        (),
        (),
        (first.node_id, second.node_id),
        (),
        (),
        0.54,
        "counterfactual_inference",
        ("其他冲突仍可能瓦解联盟",),
        ("另一事件也可能导致更早分裂",),
        "秘密没有在该时点公开",
        "沿已验证因果路径反向推演",
        "active",
    )
    edges = [
        ReasoningEdge(
            REASONING_EDGE_SCHEMA_VERSION,
            reasoning_edge_id(synthesis.node_id, "independent_support", first.node_id),
            synthesis.node_id,
            "independent_support",
            first.node_id,
            1.0,
            (),
            "active",
        ),
        ReasoningEdge(
            REASONING_EDGE_SCHEMA_VERSION,
            reasoning_edge_id(synthesis.node_id, "independent_support", second.node_id),
            synthesis.node_id,
            "independent_support",
            second.node_id,
            1.0,
            (),
            "active",
        ),
        ReasoningEdge(
            REASONING_EDGE_SCHEMA_VERSION,
            reasoning_edge_id(interpretation.node_id, "derived_from", synthesis.node_id),
            interpretation.node_id,
            "derived_from",
            synthesis.node_id,
            0.9,
            (),
            "active",
        ),
        ReasoningEdge(
            REASONING_EDGE_SCHEMA_VERSION,
            reasoning_edge_id(hypothetical.node_id, "counterfactual_premise", first.node_id),
            hypothetical.node_id,
            "counterfactual_premise",
            first.node_id,
            1.0,
            (),
            "active",
        ),
        ReasoningEdge(
            REASONING_EDGE_SCHEMA_VERSION,
            reasoning_edge_id(hypothetical.node_id, "counterfactual_inference", second.node_id),
            hypothetical.node_id,
            "counterfactual_inference",
            second.node_id,
            0.7,
            (),
            "active",
        ),
    ]
    if cycle:
        edges.append(ReasoningEdge(
            REASONING_EDGE_SCHEMA_VERSION,
            reasoning_edge_id(synthesis.node_id, "derived_from", interpretation.node_id),
            synthesis.node_id,
            "derived_from",
            interpretation.node_id,
            0.5,
            ("故意构造循环用于审核",),
            "active",
        ))
        synthesis = ReasoningNode(
            **{
                **synthesis.to_dict(),
                "intent_tags": synthesis.intent_tags,
                "chapter_ids": synthesis.chapter_ids,
                "entity_ids": synthesis.entity_ids,
                "event_ids": synthesis.event_ids,
                "upstream_record_ids": synthesis.upstream_record_ids,
                "support_node_ids": (*synthesis.support_node_ids, interpretation.node_id),
                "evidence_anchor_ids": synthesis.evidence_anchor_ids,
                "independence_groups": synthesis.independence_groups,
                "limitations": synthesis.limitations,
                "alternatives": synthesis.alternatives,
            }
        )
    return (first, second, synthesis, interpretation, hypothetical), tuple(edges)


def _annotations(path: Path, *, cycle: bool = False) -> tuple[ReasoningNode, ...]:
    nodes, edges = _records(cycle=cycle)
    rows = [
        {
            "schema_version": REASONING_ANNOTATION_SCHEMA_VERSION,
            "record_type": "node",
            "record": item.to_dict(),
        }
        for item in nodes
    ] + [
        {
            "schema_version": REASONING_ANNOTATION_SCHEMA_VERSION,
            "record_type": "edge",
            "record": item.to_dict(),
        }
        for item in edges
    ]
    _write_jsonl(path, rows)
    return nodes


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "source-project"
        self.chapter = root / "chapter-project"
        self.literary = root / "literary-project"
        self.evidence = root / "evidence-project"
        self.event = root / "event-project"
        self.character = root / "character-project"
        self.event_annotations = root / "events.jsonl"
        self.character_annotations = root / "characters.jsonl"
        self.reasoning_annotations = root / "reasoning.jsonl"
        for directory in (
            self.source, self.chapter, self.literary, self.evidence, self.event, self.character
        ):
            directory.mkdir(parents=True)
        self.event_annotations.write_text("", encoding="utf-8")
        self.character_annotations.write_text("", encoding="utf-8")
        _write_json(self.chapter / "chapter-project-report.json", {"logical_sha256": HEX_A})
        _write_json(
            self.literary / "literary-report.json",
            {"project_id": "lit-project-1", "logical_sha256": HEX_B},
        )
        assertions = [
            {"assertion_id": A1, "tier": "A", "evidence_anchor_ids": [E1]},
            {"assertion_id": A2, "tier": "A", "evidence_anchor_ids": [E2]},
        ]
        anchors = [
            {
                "anchor_id": E1,
                "source_id": SRC,
                "chapter_id": CH1,
                "evidence_start": 0,
                "evidence_end": 5,
                "evidence_text": "秘密公开",
            },
            {
                "anchor_id": E2,
                "source_id": SRC,
                "chapter_id": CH2,
                "evidence_start": 10,
                "evidence_end": 16,
                "evidence_text": "联盟失控",
            },
        ]
        _write_jsonl(self.literary / "assertions.jsonl", assertions)
        _write_jsonl(self.literary / "evidence-anchors.jsonl", anchors)
        _write_json(self.evidence / "evidence-project-report.json", {"logical_sha256": HEX_C})
        _write_jsonl(self.evidence / "claim-evidence-anchors.jsonl", anchors)
        _write_json(
            self.event / "event-project-report.json",
            {"logical_sha256": HEX_D, "graph_valid": True},
        )
        _write_jsonl(self.event / "events.jsonl", [
            {"event_id": "evt-1", "canonical_name": "秘密公开", "evidence_anchor_ids": [E1]},
        ])
        _write_jsonl(self.event / "event-components.jsonl", [
            {"component_id": "evc-1", "component_type": "cause", "evidence_anchor_ids": [E1]},
        ])
        _write_jsonl(self.event / "event-causal-edges.jsonl", [
            {"edge_id": "eve-1", "relation": "triggers", "evidence_anchor_ids": [E1, E2]},
        ])
        _write_json(
            self.character / "character-project-report.json",
            {"logical_sha256": HEX_E, "graph_valid": True},
        )
        _write_jsonl(self.character / "characters.jsonl", [
            {"character_id": "chr-1", "canonical_name": "甲", "evidence_anchor_ids": []},
        ])
        _write_jsonl(self.character / "character-attributes.jsonl", [
            {"attribute_id": "cha-1", "attribute_type": "choice", "evidence_anchor_ids": [E1]},
        ])
        _write_jsonl(self.character / "character-states.jsonl", [
            {"state_id": "chs-1", "state_type": "political", "evidence_anchor_ids": [E2]},
        ])
        _write_jsonl(self.character / "character-relationships.jsonl", [
            {"relationship_id": "chr-rel-1", "relation_type": "alliance", "evidence_anchor_ids": [E2]},
        ])
        _write_jsonl(self.character / "character-event-links.jsonl", [
            {"link_id": "chl-1", "link_type": "consequence", "evidence_anchor_ids": [E2]},
        ])
        self.nodes = _annotations(self.reasoning_annotations)

    @property
    def sources(self):
        return (self.source,)

    @property
    def literary_projects(self):
        return (self.literary,)

    @property
    def bindings(self):
        return ((self.source, self.literary, self.evidence),)

    def build(self, output: Path, *, annotations: Path | None = None):
        return build_reasoning_project(
            self.chapter,
            self.sources,
            self.literary_projects,
            self.bindings,
            self.event,
            self.event_annotations,
            self.character,
            self.character_annotations,
            annotations or self.reasoning_annotations,
            output,
        )

    def verify(self, output: Path, *, annotations: Path | None = None):
        return verify_reasoning_project(
            self.chapter,
            self.sources,
            self.literary_projects,
            self.bindings,
            self.event,
            self.event_annotations,
            self.character,
            self.character_annotations,
            annotations or self.reasoning_annotations,
            output,
        )


class PatchedVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.patches = [
            patch("tkr.reasoning_project.verify_chapter_project", return_value=_verified()),
            patch("tkr.reasoning_project.verify_literary_engine", return_value=_verified()),
            patch("tkr.reasoning_project.verify_evidence_project", return_value=_verified()),
            patch("tkr.reasoning_project.verify_event_project", return_value=_verified()),
            patch("tkr.reasoning_project.verify_character_project", return_value=_verified()),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)


class ReasoningProjectTests(PatchedVerification):
    def test_build_and_verify_completed_project(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "reasoning-project"
            result = fixture.build(output)
            verification = fixture.verify(output)
            self.assertEqual(result.status, "completed")
            self.assertTrue(result.graph_valid)
            self.assertEqual(result.node_count, 5)
            self.assertEqual(result.layer_counts, {"A": 2, "B": 1, "C": 1, "H": 1})
            self.assertTrue(verification.valid)
            self.assertTrue(verification.graph_valid)

    def test_sqlite_foreign_keys_and_metadata(self) -> None:
        import sqlite3

        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "reasoning-project"
            result = fixture.build(output)
            connection = sqlite3.connect(output / "reasoning.sqlite")
            try:
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                metadata = dict(connection.execute("SELECT key,value FROM metadata"))
                self.assertEqual(metadata["logical_sha256"], result.logical_sha256)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0], 5)
            finally:
                connection.close()

    def test_repeated_builds_are_byte_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            one = fixture.build(first)
            two = fixture.build(second)
            self.assertEqual(one.logical_sha256, two.logical_sha256)
            for name in (
                "reasoning-nodes.jsonl",
                "reasoning-edges.jsonl",
                "reasoning-findings.jsonl",
                "reasoning.sqlite",
            ):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_tampered_artifact_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "reasoning-project"
            fixture.build(output)
            with (output / "reasoning-nodes.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            verification = fixture.verify(output)
            self.assertFalse(verification.valid)
            self.assertIn("REASONING_FILE_SIZE_MISMATCH", verification.reason_codes)

    def test_unregistered_file_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "reasoning-project"
            fixture.build(output)
            (output / "extra.txt").write_text("unexpected", encoding="utf-8")
            verification = fixture.verify(output)
            self.assertFalse(verification.valid)
            self.assertIn("REASONING_PROJECT_FILE_SET_MISMATCH", verification.reason_codes)

    def test_A_evidence_must_belong_to_upstream_record(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            rows = _load_rows(fixture.reasoning_annotations)
            first_node = next(row for row in rows if row["record_type"] == "node" and row["record"]["layer"] == "A")
            first_node["record"]["evidence_anchor_ids"] = [E2]
            first_node["record"]["independence_groups"] = [f"{SRC}:{CH2}"]
            bad = Path(directory) / "bad.jsonl"
            _write_jsonl(bad, rows)
            with self.assertRaises(ReasoningProjectError):
                fixture.build(Path(directory) / "bad-project", annotations=bad)

    def test_B_independence_groups_must_match_A_lineage(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            rows = _load_rows(fixture.reasoning_annotations)
            b_node = next(row for row in rows if row["record_type"] == "node" and row["record"]["layer"] == "B")
            b_node["record"]["independence_groups"] = [f"{SRC}:{CH1}", "invented:group"]
            bad = Path(directory) / "bad.jsonl"
            _write_jsonl(bad, rows)
            with self.assertRaises(ReasoningProjectError):
                fixture.build(Path(directory) / "bad-project", annotations=bad)

    def test_declared_support_must_equal_active_support_edges(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            rows = _load_rows(fixture.reasoning_annotations)
            rows = [
                row for row in rows
                if not (
                    row["record_type"] == "edge"
                    and row["record"]["relation"] == "independent_support"
                    and row["record"]["target_node_id"] == fixture.nodes[1].node_id
                )
            ]
            bad = Path(directory) / "bad.jsonl"
            _write_jsonl(bad, rows)
            with self.assertRaises(ReasoningProjectError):
                fixture.build(Path(directory) / "bad-project", annotations=bad)

    def test_review_required_cycle_project_verifies_but_blocks_presentation(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            cycle = Path(directory) / "cycle.jsonl"
            _annotations(cycle, cycle=True)
            output = Path(directory) / "cycle-project"
            result = fixture.build(output, annotations=cycle)
            verification = fixture.verify(output, annotations=cycle)
            self.assertEqual(result.status, "review_required")
            self.assertFalse(result.graph_valid)
            self.assertTrue(verification.valid)
            self.assertFalse(verification.graph_valid)


def _load_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class ReasoningCliTests(PatchedVerification):
    def _common(self, fixture: Fixture) -> list[str]:
        return [
            str(fixture.chapter),
            str(fixture.event),
            str(fixture.event_annotations),
            str(fixture.character),
            str(fixture.character_annotations),
            str(fixture.reasoning_annotations),
            "--source-project", str(fixture.source),
            "--literary-project", str(fixture.literary),
            "--evidence-binding", str(fixture.source), str(fixture.literary), str(fixture.evidence),
        ]

    def _run(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stream = StringIO()
        with redirect_stdout(stream):
            code = reasoning_main(args)
        return code, json.loads(stream.getvalue())

    def test_build_verify_and_analysis_query_expand_provenance(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "reasoning-project"
            code, built = self._run(["build", *self._common(fixture), "--outdir", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(built["status"], "completed")
            code, verified = self._run(["verify", str(output), *self._common(fixture)])
            self.assertEqual(code, 0)
            self.assertTrue(verified["valid"])
            code, packet = self._run([
                "query", str(output), *self._common(fixture),
                "--mode", "analysis", "--intent-tag", "all",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(packet["decision"], "partial")
            self.assertEqual(len(packet["facts"]), 2)
            self.assertEqual(len(packet["synthesis"]), 1)
            self.assertEqual(len(packet["interpretation"]), 1)
            self.assertEqual(packet["counterfactual"], [])
            fact_provenance = next(
                item for item in packet["resolved_provenance"] if item["layer"] == "A"
            )
            self.assertTrue(fact_provenance["upstream_records"])
            self.assertTrue(fact_provenance["evidence_anchors"])

    def test_fact_only_query_does_not_leak_higher_layers(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "reasoning-project"
            fixture.build(output)
            code, packet = self._run([
                "query", str(output), *self._common(fixture),
                "--mode", "fact_only", "--all",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(len(packet["facts"]), 2)
            self.assertEqual(packet["synthesis"], [])
            self.assertEqual(packet["interpretation"], [])
            self.assertEqual(packet["counterfactual"], [])

    def test_missing_intent_refuses_without_guessing(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            output = Path(directory) / "reasoning-project"
            fixture.build(output)
            code, packet = self._run([
                "query", str(output), *self._common(fixture),
                "--mode", "analysis", "--intent-tag", "not-present",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(packet["decision"], "refused")
            self.assertIn("NO_SUPPORTED_REASONING_NODE_SELECTED", packet["reason_codes"])


if __name__ == "__main__":
    unittest.main()
