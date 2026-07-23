from __future__ import annotations

import unittest

from tkr.event_engine import (
    EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
    EVENT_COMPONENT_SCHEMA_VERSION,
    EVENT_RECORD_SCHEMA_VERSION,
    CausalEvent,
    EventCausalEdge,
    EventComponent,
    EventEngineError,
    build_event_graph,
    causal_edge_id,
    component_id,
    event_id,
)


A1 = "las_a1"
A2 = "las_a2"
A3 = "las_a3"
E1 = "lea_e1"
E2 = "lea_e2"
E3 = "lea_e3"


def _event(name: str, chapter: str, position: int, evidence: str) -> CausalEvent:
    identifier = event_id(name, chapter, chapter)
    return CausalEvent(
        EVENT_RECORD_SCHEMA_VERSION,
        identifier,
        name,
        "major_plot_event",
        "major",
        chapter,
        chapter,
        position,
        position,
        (),
        (),
        (evidence,),
        (),
        "active",
    )


def _a_component(event: CausalEvent, kind: str, statement: str, assertion: str, evidence: str) -> EventComponent:
    identifier = component_id(event.event_id, kind, "A", statement, (assertion,), (evidence,))
    return EventComponent(
        EVENT_COMPONENT_SCHEMA_VERSION,
        identifier,
        event.event_id,
        kind,
        "A",
        statement,
        (assertion,),
        (evidence,),
        (),
        1.0,
        (),
        "source_direct_event",
        "active",
    )


def _a_edge(source: CausalEvent, relation: str, target: CausalEvent, assertion: str, evidence: str) -> EventCausalEdge:
    identifier = causal_edge_id(source.event_id, relation, target.event_id, "A", (assertion,), (evidence,))
    return EventCausalEdge(
        EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
        identifier,
        source.event_id,
        relation,
        target.event_id,
        "A",
        (assertion,),
        (evidence,),
        (),
        source.start_position,
        target.start_position,
        "backward_reference" if relation == "recovers" else "forward",
        1.0,
        (),
        "source_direct_event",
        "active",
    )


class EventEngineModelTests(unittest.TestCase):
    def test_active_event_requires_major_significance_and_evidence(self) -> None:
        with self.assertRaises(EventEngineError):
            CausalEvent(
                EVENT_RECORD_SCHEMA_VERSION,
                "cev_bad",
                "路人经过",
                "minor_scene",
                "review_candidate",
                "chapter_1",
                "chapter_1",
                0,
                0,
                (),
                (),
                (E1,),
                (),
                "active",
            )
        with self.assertRaises(EventEngineError):
            CausalEvent(
                EVENT_RECORD_SCHEMA_VERSION,
                "cev_bad2",
                "无证据大事",
                "major_plot_event",
                "major",
                "chapter_1",
                "chapter_1",
                0,
                0,
                (),
                (),
                (),
                (),
                "active",
            )

    def test_tier_b_component_requires_multiple_supports(self) -> None:
        event = _event("事件", "chapter_1", 0, E1)
        with self.assertRaises(EventEngineError):
            EventComponent(
                EVENT_COMPONENT_SCHEMA_VERSION,
                "evc_bad",
                event.event_id,
                "consequence",
                "B",
                "单条事实不足以形成长期归纳",
                (A1,),
                (),
                (),
                0.8,
                ("仅有一条支持",),
                "cross_evidence_synthesis",
                "active",
            )

    def test_tier_c_requires_interpretation_label_and_limitations(self) -> None:
        event = _event("事件", "chapter_1", 0, E1)
        with self.assertRaises(EventEngineError):
            EventComponent(
                EVENT_COMPONENT_SCHEMA_VERSION,
                "evc_bad",
                event.event_id,
                "consequence",
                "C",
                "象征旧秩序崩塌",
                (A1,),
                (),
                (),
                0.7,
                (),
                "model_interpretation",
                "active",
            )

    def test_forward_edge_cannot_point_backward(self) -> None:
        later = _event("后事", "chapter_2", 2, E2)
        earlier = _event("前事", "chapter_1", 1, E1)
        with self.assertRaises(EventEngineError):
            _a_edge(later, "triggers", earlier, A1, E1)

    def test_recovery_edge_may_reference_earlier_foreshadowing(self) -> None:
        clue = _event("伏笔出现", "chapter_1", 1, E1)
        recovery = _event("伏笔回收", "chapter_5", 5, E2)
        edge = _a_edge(recovery, "recovers", clue, A2, E2)
        self.assertEqual(edge.temporal_direction, "backward_reference")


class EventGraphTests(unittest.TestCase):
    def test_valid_graph_preserves_components_edges_and_tiers(self) -> None:
        cause = _event("秘密公开", "chapter_1", 1, E1)
        outcome = _event("联盟瓦解", "chapter_2", 2, E2)
        cause_component = _a_component(cause, "outcome", "秘密被公开", A1, E1)
        outcome_component = _a_component(outcome, "outcome", "联盟成员退出", A2, E2)
        edge = _a_edge(cause, "undermines", outcome, A3, E3)
        graph = build_event_graph(
            (cause, outcome),
            (cause_component, outcome_component),
            (edge,),
            known_assertion_ids=(A1, A2, A3),
            known_evidence_anchor_ids=(E1, E2, E3),
        )
        self.assertTrue(graph.report.graph_valid)
        self.assertEqual(graph.report.event_count, 2)
        self.assertEqual(graph.report.edge_count, 1)
        self.assertEqual(graph.report.tier_a_component_count, 2)
        self.assertEqual(graph.findings, ())

    def test_unknown_support_is_explicit_and_invalidates_graph(self) -> None:
        event = _event("事件", "chapter_1", 1, E1)
        component = _a_component(event, "outcome", "发生结果", A1, E1)
        graph = build_event_graph(
            (event,),
            (component,),
            (),
            known_assertion_ids=(),
            known_evidence_anchor_ids=(),
        )
        self.assertFalse(graph.report.graph_valid)
        rules = {item.rule_id for item in graph.findings}
        self.assertIn("EVENT_UNKNOWN_EVIDENCE", rules)
        self.assertIn("COMPONENT_UNKNOWN_SUPPORT", rules)

    def test_position_binding_mismatch_is_rejected_by_finding(self) -> None:
        first = _event("事件一", "chapter_1", 1, E1)
        second = _event("事件二", "chapter_2", 2, E2)
        edge = EventCausalEdge(
            EVENT_CAUSAL_EDGE_SCHEMA_VERSION,
            causal_edge_id(first.event_id, "triggers", second.event_id, "A", (A1,), (E1,)),
            first.event_id,
            "triggers",
            second.event_id,
            "A",
            (A1,),
            (E1,),
            (),
            0,
            2,
            "forward",
            1.0,
            (),
            "source_direct_event",
            "active",
        )
        graph = build_event_graph(
            (first, second),
            (),
            (edge,),
            known_assertion_ids=(A1,),
            known_evidence_anchor_ids=(E1, E2),
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn(
            "EDGE_POSITION_BINDING_MISMATCH",
            {item.rule_id for item in graph.findings},
        )

    def test_same_position_causal_cycle_is_retained_as_finding(self) -> None:
        first = _event("同章事件一", "chapter_1", 1, E1)
        second = _event("同章事件二", "chapter_1", 1, E2)
        forward = _a_edge(first, "enables", second, A1, E1)
        backward = _a_edge(second, "enables", first, A2, E2)
        graph = build_event_graph(
            (first, second),
            (),
            (forward, backward),
            known_assertion_ids=(A1, A2),
            known_evidence_anchor_ids=(E1, E2),
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertEqual(graph.report.cycle_count, 1)
        self.assertIn("ACTIVE_CAUSAL_CYCLE", {item.rule_id for item in graph.findings})

    def test_repeated_graph_build_is_deterministic(self) -> None:
        first = _event("事件一", "chapter_1", 1, E1)
        second = _event("事件二", "chapter_2", 2, E2)
        edge = _a_edge(first, "triggers", second, A1, E1)
        args = (
            (first, second),
            (),
            (edge,),
        )
        first_graph = build_event_graph(
            *args,
            known_assertion_ids=(A1,),
            known_evidence_anchor_ids=(E1, E2),
        )
        second_graph = build_event_graph(
            *args,
            known_assertion_ids=(A1,),
            known_evidence_anchor_ids=(E1, E2),
        )
        self.assertEqual(
            [item.to_dict() for item in first_graph.events],
            [item.to_dict() for item in second_graph.events],
        )
        self.assertEqual(
            [item.to_dict() for item in first_graph.edges],
            [item.to_dict() for item in second_graph.edges],
        )
        self.assertEqual(first_graph.report.to_dict(), second_graph.report.to_dict())


if __name__ == "__main__":
    unittest.main()
