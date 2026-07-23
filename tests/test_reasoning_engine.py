from __future__ import annotations

import unittest

from tkr.reasoning_engine import (
    REASONING_EDGE_SCHEMA_VERSION,
    REASONING_NODE_SCHEMA_VERSION,
    ReasoningEdge,
    ReasoningEngineError,
    ReasoningNode,
    build_answer_packet,
    build_reasoning_graph,
    reasoning_edge_id,
    reasoning_node_id,
)


A_REC_1 = "las_fact_1"
A_REC_2 = "las_fact_2"
EVIDENCE_1 = "lea_evidence_1"
EVIDENCE_2 = "lea_evidence_2"
CHAPTER_1 = "lch_chapter_1"
CHAPTER_2 = "lch_chapter_2"


def _a(statement: str, record: str, evidence: str, chapter: str, group: str) -> ReasoningNode:
    return ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("A", statement, (record,)),
        "A",
        statement,
        ("fact",),
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


def _b(first: ReasoningNode, second: ReasoningNode) -> ReasoningNode:
    statement = "两个事实共同表明联盟控制开始瓦解"
    return ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("B", statement, (first.node_id, second.node_id)),
        "B",
        statement,
        ("causal_synthesis",),
        (CHAPTER_1, CHAPTER_2),
        (),
        (),
        (),
        (first.node_id, second.node_id),
        (),
        ("group-1", "group-2"),
        0.9,
        "cross_evidence_synthesis",
        ("原文没有使用‘控制瓦解’这一概括性术语",),
        (),
        "",
        "",
        "active",
    )


def _c(support: ReasoningNode) -> ReasoningNode:
    statement = "这一过程可以解释为权力叙事失去合法性"
    return ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("C", statement, (support.node_id,)),
        "C",
        statement,
        ("literary_interpretation",),
        (CHAPTER_1, CHAPTER_2),
        (),
        (),
        (),
        (support.node_id,),
        (),
        (),
        0.72,
        "model_interpretation",
        ("这是模型分析概念，不是原文明确术语",),
        ("也可以解释为单纯的联盟信任崩溃",),
        "",
        "",
        "active",
    )


def _h(first: ReasoningNode, second: ReasoningNode) -> ReasoningNode:
    statement = "若秘密未公开，联盟可能维持更长时间"
    return ReasoningNode(
        REASONING_NODE_SCHEMA_VERSION,
        reasoning_node_id("H", statement, (first.node_id, second.node_id)),
        "H",
        statement,
        ("counterfactual",),
        (CHAPTER_1, CHAPTER_2),
        (),
        (),
        (),
        (first.node_id, second.node_id),
        (),
        (),
        0.55,
        "counterfactual_inference",
        ("其他冲突仍可能导致联盟瓦解",),
        ("联盟也可能因另一事件提前分裂",),
        "秘密没有在该时点公开",
        "沿已验证的‘公开秘密削弱联盟控制’因果路径反向推演",
        "active",
    )


def _edge(source: ReasoningNode, relation: str, target: ReasoningNode) -> ReasoningEdge:
    return ReasoningEdge(
        REASONING_EDGE_SCHEMA_VERSION,
        reasoning_edge_id(source.node_id, relation, target.node_id),
        source.node_id,
        relation,
        target.node_id,
        1.0,
        (),
        "active",
    )


def _valid_graph():
    first = _a("秘密被公开", A_REC_1, EVIDENCE_1, CHAPTER_1, "group-1")
    second = _a("联盟随后失去控制", A_REC_2, EVIDENCE_2, CHAPTER_2, "group-2")
    synthesis = _b(first, second)
    interpretation = _c(synthesis)
    hypothetical = _h(first, second)
    edges = (
        _edge(synthesis, "independent_support", first),
        _edge(synthesis, "independent_support", second),
        _edge(interpretation, "derived_from", synthesis),
        _edge(hypothetical, "counterfactual_premise", first),
        _edge(hypothetical, "counterfactual_inference", second),
    )
    graph = build_reasoning_graph(
        (first, second, synthesis, interpretation, hypothetical),
        edges,
        known_upstream_record_ids=(A_REC_1, A_REC_2),
        known_evidence_anchor_ids=(EVIDENCE_1, EVIDENCE_2),
    )
    return first, second, synthesis, interpretation, hypothetical, graph


class ReasoningNodeContractTests(unittest.TestCase):
    def test_layer_A_requires_exact_evidence(self) -> None:
        with self.assertRaises(ReasoningEngineError):
            ReasoningNode(
                REASONING_NODE_SCHEMA_VERSION,
                "rrn_bad",
                "A",
                "无证据事实",
                ("fact",),
                (CHAPTER_1,),
                (),
                (),
                (A_REC_1,),
                (),
                (),
                ("group-1",),
                1.0,
                "source_fact",
                (),
                (),
                "",
                "",
                "active",
            )

    def test_layer_A_requires_one_independence_group(self) -> None:
        with self.assertRaises(ReasoningEngineError):
            _a("事实", A_REC_1, EVIDENCE_1, CHAPTER_1, "")

    def test_layer_B_requires_two_supports(self) -> None:
        first = _a("事实一", A_REC_1, EVIDENCE_1, CHAPTER_1, "group-1")
        with self.assertRaises(ReasoningEngineError):
            ReasoningNode(
                REASONING_NODE_SCHEMA_VERSION,
                "rrn_bad_b",
                "B",
                "不充分归纳",
                ("synthesis",),
                (CHAPTER_1,),
                (),
                (),
                (),
                (first.node_id,),
                (),
                ("group-1", "group-2"),
                0.8,
                "cross_evidence_synthesis",
                ("证据不足",),
                (),
                "",
                "",
                "active",
            )

    def test_layer_C_requires_attribution_limit_and_alternative(self) -> None:
        first = _a("事实一", A_REC_1, EVIDENCE_1, CHAPTER_1, "group-1")
        with self.assertRaises(ReasoningEngineError):
            ReasoningNode(
                REASONING_NODE_SCHEMA_VERSION,
                "rrn_bad_c",
                "C",
                "确定的作者意图",
                ("interpretation",),
                (CHAPTER_1,),
                (),
                (),
                (),
                (first.node_id,),
                (),
                (),
                0.7,
                "model_interpretation",
                (),
                (),
                "",
                "",
                "active",
            )

    def test_layer_H_requires_changed_premise_and_inference_rule(self) -> None:
        first = _a("事实一", A_REC_1, EVIDENCE_1, CHAPTER_1, "group-1")
        with self.assertRaises(ReasoningEngineError):
            ReasoningNode(
                REASONING_NODE_SCHEMA_VERSION,
                "rrn_bad_h",
                "H",
                "可能发生另一结果",
                ("counterfactual",),
                (CHAPTER_1,),
                (),
                (),
                (),
                (first.node_id,),
                (),
                (),
                0.5,
                "counterfactual_inference",
                ("不确定",),
                ("其他结果",),
                "",
                "",
                "active",
            )


class ReasoningGraphTests(unittest.TestCase):
    def test_valid_A_B_C_H_graph(self) -> None:
        *_, graph = _valid_graph()
        self.assertTrue(graph.report.graph_valid)
        self.assertEqual(graph.report.layer_counts, {"A": 2, "B": 1, "C": 1, "H": 1})
        self.assertEqual(graph.findings, ())

    def test_duplicate_restatement_is_not_independent_support(self) -> None:
        first = _a("事实一", A_REC_1, EVIDENCE_1, CHAPTER_1, "same-group")
        second = _a("事实一的改写", A_REC_2, EVIDENCE_2, CHAPTER_2, "same-group")
        synthesis = _b(first, second)
        graph = build_reasoning_graph(
            (first, second, synthesis),
            (
                _edge(synthesis, "independent_support", first),
                _edge(synthesis, "independent_support", second),
            ),
            known_upstream_record_ids=(A_REC_1, A_REC_2),
            known_evidence_anchor_ids=(EVIDENCE_1, EVIDENCE_2),
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn("B_SUPPORT_NOT_INDEPENDENT", {item.rule_id for item in graph.findings})

    def test_B_cannot_use_C_as_direct_support(self) -> None:
        first, second, synthesis, interpretation, _, _ = _valid_graph()
        invalid = ReasoningNode(
            REASONING_NODE_SCHEMA_VERSION,
            "rrn_invalid_b",
            "B",
            "错误地用解释支撑归纳",
            ("synthesis",),
            (CHAPTER_1, CHAPTER_2),
            (),
            (),
            (),
            (first.node_id, interpretation.node_id),
            (),
            ("group-1", "group-2"),
            0.8,
            "cross_evidence_synthesis",
            ("存在层级错误",),
            (),
            "",
            "",
            "active",
        )
        graph = build_reasoning_graph(
            (first, second, synthesis, interpretation, invalid),
            (),
            known_upstream_record_ids=(A_REC_1, A_REC_2),
            known_evidence_anchor_ids=(EVIDENCE_1, EVIDENCE_2),
        )
        self.assertIn("B_SUPPORT_NOT_DIRECT_A", {item.rule_id for item in graph.findings})

    def test_unknown_upstream_support_blocks_graph(self) -> None:
        first = _a("事实一", A_REC_1, EVIDENCE_1, CHAPTER_1, "group-1")
        graph = build_reasoning_graph(
            (first,),
            (),
            known_upstream_record_ids=(),
            known_evidence_anchor_ids=(),
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn(
            "REASONING_NODE_UNKNOWN_UPSTREAM_SUPPORT",
            {item.rule_id for item in graph.findings},
        )

    def test_derivation_cycle_is_explicit(self) -> None:
        first, second, synthesis, interpretation, _, _ = _valid_graph()
        graph = build_reasoning_graph(
            (first, second, synthesis, interpretation),
            (
                _edge(synthesis, "derived_from", interpretation),
                _edge(interpretation, "derived_from", synthesis),
            ),
            known_upstream_record_ids=(A_REC_1, A_REC_2),
            known_evidence_anchor_ids=(EVIDENCE_1, EVIDENCE_2),
        )
        self.assertFalse(graph.report.graph_valid)
        self.assertIn("REASONING_DERIVATION_CYCLE", {item.rule_id for item in graph.findings})

    def test_repeated_build_is_deterministic(self) -> None:
        first, second, synthesis, interpretation, hypothetical, _ = _valid_graph()
        args = (
            (first, second, synthesis, interpretation, hypothetical),
            (
                _edge(synthesis, "independent_support", first),
                _edge(synthesis, "independent_support", second),
                _edge(interpretation, "derived_from", synthesis),
            ),
        )
        kwargs = {
            "known_upstream_record_ids": (A_REC_1, A_REC_2),
            "known_evidence_anchor_ids": (EVIDENCE_1, EVIDENCE_2),
        }
        first_graph = build_reasoning_graph(*args, **kwargs)
        second_graph = build_reasoning_graph(*args, **kwargs)
        self.assertEqual(
            [item.to_dict() for item in first_graph.nodes],
            [item.to_dict() for item in second_graph.nodes],
        )
        self.assertEqual(
            [item.to_dict() for item in first_graph.findings],
            [item.to_dict() for item in second_graph.findings],
        )


class AnswerPacketTests(unittest.TestCase):
    def test_fact_only_never_leaks_B_C_or_H(self) -> None:
        first, _, synthesis, interpretation, hypothetical, graph = _valid_graph()
        packet = build_answer_packet(
            graph,
            (first.node_id, synthesis.node_id, interpretation.node_id, hypothetical.node_id),
            mode="fact_only",
        )
        self.assertEqual(packet["decision"], "partial")
        self.assertEqual(len(packet["facts"]), 1)
        self.assertEqual(packet["synthesis"], [])
        self.assertEqual(packet["interpretation"], [])
        self.assertEqual(packet["counterfactual"], [])
        self.assertEqual(len(packet["reason_codes"]), 3)

    def test_analysis_keeps_A_B_C_in_separate_sections(self) -> None:
        first, _, synthesis, interpretation, _, graph = _valid_graph()
        packet = build_answer_packet(
            graph,
            (first.node_id, synthesis.node_id, interpretation.node_id),
            mode="analysis",
        )
        self.assertEqual(packet["decision"], "answered")
        self.assertEqual([item["layer"] for item in packet["facts"]], ["A"])
        self.assertEqual([item["layer"] for item in packet["synthesis"]], ["B"])
        self.assertEqual([item["layer"] for item in packet["interpretation"]], ["C"])
        self.assertEqual(packet["counterfactual"], [])

    def test_counterfactual_packet_marks_noncanon_premise(self) -> None:
        first, _, _, _, hypothetical, graph = _valid_graph()
        packet = build_answer_packet(
            graph,
            (first.node_id, hypothetical.node_id),
            mode="counterfactual",
        )
        self.assertEqual(packet["decision"], "answered")
        item = packet["counterfactual"][0]
        self.assertTrue(item["counterfactual_premise"])
        self.assertTrue(item["inference_rule"])
        self.assertEqual(item["attribution"], "counterfactual_inference")

    def test_review_required_graph_refuses_normal_answer_but_allows_provenance(self) -> None:
        first = _a("事实一", A_REC_1, EVIDENCE_1, CHAPTER_1, "group-1")
        graph = build_reasoning_graph(
            (first,),
            (),
            known_upstream_record_ids=(),
            known_evidence_anchor_ids=(),
        )
        refused = build_answer_packet(graph, (first.node_id,), mode="fact_only")
        provenance = build_answer_packet(graph, (first.node_id,), mode="provenance")
        self.assertEqual(refused["decision"], "refused")
        self.assertIn("REASONING_GRAPH_REVIEW_REQUIRED", refused["reason_codes"])
        self.assertEqual(provenance["decision"], "answered")
        self.assertEqual(len(provenance["provenance"]), 1)

    def test_missing_node_refuses_without_guessing(self) -> None:
        *_, graph = _valid_graph()
        packet = build_answer_packet(graph, ("rrn_missing",), mode="analysis")
        self.assertEqual(packet["decision"], "refused")
        self.assertIn("REASONING_NODE_NOT_FOUND:rrn_missing", packet["reason_codes"])


if __name__ == "__main__":
    unittest.main()
