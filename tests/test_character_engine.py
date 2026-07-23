from __future__ import annotations

import unittest

from tkr.character_engine import (
    CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
    CHARACTER_EVENT_LINK_SCHEMA_VERSION,
    CHARACTER_RELATIONSHIP_SCHEMA_VERSION,
    CHARACTER_SCHEMA_VERSION,
    CHARACTER_STATE_SCHEMA_VERSION,
    CharacterAttribute,
    CharacterEngineError,
    CharacterEventLink,
    CharacterRelationship,
    CharacterState,
    FocusedCharacter,
    build_character_graph,
    character_id,
)

A1 = "las_a1"
A2 = "las_a2"
A3 = "las_a3"
E1 = "lea_e1"
E2 = "lea_e2"
E3 = "lea_e3"
EVENT1 = "cev_event1"
EVENT2 = "cev_event2"


def _character(
    name: str,
    scope: str,
    *,
    first: int = 0,
    last: int = 4,
    evidence: str = E1,
) -> FocusedCharacter:
    return FocusedCharacter(
        CHARACTER_SCHEMA_VERSION,
        character_id(name, f"chapter_{first}"),
        name,
        (name,),
        scope,
        (
            ("main_plot_driver",)
            if scope == "core"
            else ("major_event_cause_or_resolution",)
            if scope == "important"
            else ()
        ),
        f"chapter_{first}",
        f"chapter_{last}",
        first,
        last,
        (evidence,),
        (),
        "active",
    )


def _a_attribute(
    character: FocusedCharacter,
    identifier: str,
    attribute_type: str,
    value: str,
    assertion: str,
    evidence: str,
    *,
    start: int = 0,
    end: int = 4,
) -> CharacterAttribute:
    return CharacterAttribute(
        CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
        identifier,
        character.character_id,
        character.scope,
        attribute_type,
        "A",
        value,
        f"chapter_{start}",
        f"chapter_{end}",
        start,
        end,
        (assertion,),
        (evidence,),
        (),
        1.0,
        (),
        "source_explicit",
        "active",
    )


def _a_state(
    character: FocusedCharacter,
    identifier: str,
    value: str,
    start: int,
    end: int,
    assertion: str,
    evidence: str,
) -> CharacterState:
    return CharacterState(
        CHARACTER_STATE_SCHEMA_VERSION,
        identifier,
        character.character_id,
        "life_status",
        value,
        f"chapter_{start}",
        f"chapter_{end}",
        start,
        end,
        "A",
        (assertion,),
        (evidence,),
        1.0,
        (),
        "source_explicit",
        "active",
    )


class CharacterModelTests(unittest.TestCase):
    def test_active_core_requires_material_impact_reason(self) -> None:
        with self.assertRaises(CharacterEngineError):
            FocusedCharacter(
                CHARACTER_SCHEMA_VERSION,
                "fch_bad",
                "主角",
                ("主角",),
                "core",
                (),
                "chapter_0",
                "chapter_2",
                0,
                2,
                (E1,),
                (),
                "active",
            )

    def test_placeholder_cannot_claim_major_impact_reason(self) -> None:
        with self.assertRaises(CharacterEngineError):
            FocusedCharacter(
                CHARACTER_SCHEMA_VERSION,
                "fch_bad",
                "路人",
                ("路人",),
                "placeholder",
                ("main_plot_driver",),
                "chapter_0",
                "chapter_0",
                0,
                0,
                (E1,),
                (),
                "active",
            )

    def test_placeholder_cannot_receive_ability_or_synthesis(self) -> None:
        placeholder = _character("守卫", "placeholder")
        with self.assertRaises(CharacterEngineError):
            _a_attribute(
                placeholder,
                "cat_bad",
                "ability",
                "剑术",
                A1,
                E1,
            )
        with self.assertRaises(CharacterEngineError):
            CharacterAttribute(
                CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
                "cat_bad_b",
                placeholder.character_id,
                placeholder.scope,
                "role",
                "B",
                "长期政治作用",
                "chapter_0",
                "chapter_4",
                0,
                4,
                (A1, A2),
                (),
                (),
                0.8,
                ("占位人物不应深度归纳",),
                "cross_evidence_synthesis",
                "active",
            )

    def test_character_arc_is_limited_to_core_scope(self) -> None:
        important = _character("军师", "important")
        with self.assertRaises(CharacterEngineError):
            _a_attribute(
                important,
                "cat_arc_bad",
                "arc",
                "完成转变",
                A1,
                E1,
            )

    def test_c_interpretation_requires_limitation_and_model_attribution(self) -> None:
        core = _character("主角", "core")
        support = _a_attribute(core, "cat_a", "choice", "选择留下", A1, E1)
        with self.assertRaises(CharacterEngineError):
            CharacterAttribute(
                CHARACTER_ATTRIBUTE_SCHEMA_VERSION,
                "cat_c_bad",
                core.character_id,
                core.scope,
                "arc",
                "C",
                "象征自由意志",
                "chapter_0",
                "chapter_4",
                0,
                4,
                (),
                (),
                (support.attribute_id,),
                0.7,
                (),
                "model_interpretation",
                "active",
            )


class CharacterGraphTests(unittest.TestCase):
    def test_valid_focused_graph(self) -> None:
        core = _character("主角", "core", evidence=E1)
        important = _character("盟友", "important", evidence=E2)
        placeholder = _character("守门人", "placeholder", evidence=E3)
        attributes = (
            _a_attribute(core, "cat_core_identity", "identity", "剑修", A1, E1),
            _a_attribute(important, "cat_important_role", "role", "盟军统领", A2, E2),
            _a_attribute(placeholder, "cat_placeholder_role", "role", "守门人", A3, E3),
        )
        graph = build_character_graph(
            (core, important, placeholder),
            attributes,
            (),
            (),
            (),
            known_assertion_ids=(A1, A2, A3),
            known_evidence_anchor_ids=(E1, E2, E3),
            known_event_ids=(EVENT1,),
            event_graph_valid=True,
        )
        self.assertTrue(graph.report.graph_valid)
        self.assertEqual(graph.report.core_count, 1)
        self.assertEqual(graph.report.important_count, 1)
        self.assertEqual(graph.report.placeholder_count, 1)
        self.assertEqual(graph.findings, ())

    def test_alias_collision_is_explicit(self) -> None:
        first = FocusedCharacter(
            CHARACTER_SCHEMA_VERSION,
            character_id("甲", "chapter_0"),
            "甲",
            ("甲", "无名客"),
            "core",
            ("main_plot_driver",),
            "chapter_0",
            "chapter_4",
            0,
            4,
            (E1,),
            (),
            "active",
        )
        second = FocusedCharacter(
            CHARACTER_SCHEMA_VERSION,
            character_id("乙", "chapter_1"),
            "乙",
            ("乙", "无名客"),
            "important",
            ("major_event_cause_or_resolution",),
            "chapter_1",
            "chapter_4",
            1,
            4,
            (E2,),
            (),
            "active",
        )
        graph = build_character_graph(
            (first, second),
            (),
            (),
            (),
            (),
            known_assertion_ids=(),
            known_evidence_anchor_ids=(E1, E2),
            known_event_ids=(),
            event_graph_valid=True,
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn("CHARACTER_ALIAS_COLLISION", {item.rule_id for item in graph.findings})

    def test_unknown_support_is_explicit(self) -> None:
        core = _character("主角", "core")
        attribute = _a_attribute(core, "cat_unknown", "identity", "剑修", A1, E1)
        graph = build_character_graph(
            (core,),
            (attribute,),
            (),
            (),
            (),
            known_assertion_ids=(),
            known_evidence_anchor_ids=(),
            known_event_ids=(),
            event_graph_valid=True,
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn(
            "CHARACTER_RECORD_UNKNOWN_SUPPORT",
            {item.rule_id for item in graph.findings},
        )

    def test_overlapping_contradictory_states_are_findings(self) -> None:
        core = _character("主角", "core")
        alive = _a_state(core, "cst_alive", "alive", 0, 3, A1, E1)
        dead = _a_state(core, "cst_dead", "dead", 2, 4, A2, E2)
        graph = build_character_graph(
            (core,),
            (),
            (alive, dead),
            (),
            (),
            known_assertion_ids=(A1, A2),
            known_evidence_anchor_ids=(E1, E2),
            known_event_ids=(),
            event_graph_valid=True,
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertEqual(graph.report.temporal_conflict_count, 1)
        self.assertIn(
            "OVERLAPPING_CONTRADICTORY_CHARACTER_STATES",
            {item.rule_id for item in graph.findings},
        )

    def test_placeholder_deep_relationship_is_blocked_by_finding(self) -> None:
        core = _character("主角", "core")
        placeholder = _character("路人", "placeholder", evidence=E2)
        relationship = CharacterRelationship(
            CHARACTER_RELATIONSHIP_SCHEMA_VERSION,
            "crl_bad",
            core.character_id,
            placeholder.character_id,
            "spiritual_equal",
            "A",
            "chapter_0",
            "chapter_4",
            0,
            4,
            (),
            (A1,),
            (E1,),
            (),
            1.0,
            (),
            "source_explicit",
            "active",
        )
        graph = build_character_graph(
            (core, placeholder),
            (),
            (),
            (relationship,),
            (),
            known_assertion_ids=(A1,),
            known_evidence_anchor_ids=(E1, E2),
            known_event_ids=(),
            event_graph_valid=True,
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn(
            "PLACEHOLDER_DEEP_RELATIONSHIP",
            {item.rule_id for item in graph.findings},
        )

    def test_review_required_event_graph_blocks_active_character_link(self) -> None:
        core = _character("主角", "core")
        link = CharacterEventLink(
            CHARACTER_EVENT_LINK_SCHEMA_VERSION,
            "cel_bad",
            core.character_id,
            EVENT1,
            "transformed_by",
            "A",
            (A1,),
            (E1,),
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        graph = build_character_graph(
            (core,),
            (),
            (),
            (),
            (link,),
            known_assertion_ids=(A1,),
            known_evidence_anchor_ids=(E1,),
            known_event_ids=(EVENT1,),
            event_graph_valid=False,
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn(
            "ACTIVE_LINK_TO_REVIEW_REQUIRED_EVENT_GRAPH",
            {item.rule_id for item in graph.findings},
        )

    def test_repeated_graph_build_is_deterministic(self) -> None:
        core = _character("主角", "core")
        attribute = _a_attribute(core, "cat_identity", "identity", "剑修", A1, E1)
        kwargs = dict(
            known_assertion_ids=(A1,),
            known_evidence_anchor_ids=(E1,),
            known_event_ids=(),
            event_graph_valid=True,
        )
        first = build_character_graph((core,), (attribute,), (), (), (), **kwargs)
        second = build_character_graph((core,), (attribute,), (), (), (), **kwargs)
        self.assertEqual(
            [item.to_dict() for item in first.characters],
            [item.to_dict() for item in second.characters],
        )
        self.assertEqual(first.report.to_dict(), second.report.to_dict())


if __name__ == "__main__":
    unittest.main()
