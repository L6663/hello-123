from __future__ import annotations

import json
import unittest

from tkr.evidence_claims import (
    CLAIM_EVIDENCE_EDGE_SCHEMA_VERSION,
    ClaimEvidenceEdge,
    ClaimEvidenceError,
    build_claim_evidence_edges,
    claim_evidence_edge_id,
    edge_from_dict,
    graph_report_from_dict,
    validate_claim_evidence_graph,
)
from tkr.literary_models import ASSERTION_SCHEMA_VERSION, KnowledgeAssertion


def _assertion(
    identifier: str,
    tier: str,
    kind: str,
    evidence: tuple[str, ...],
    supports: tuple[str, ...],
    *,
    attribution: str,
) -> KnowledgeAssertion:
    return KnowledgeAssertion(
        ASSERTION_SCHEMA_VERSION,
        identifier,
        tier,
        kind,
        None,
        identifier,
        "describes",
        None,
        "value",
        None,
        True,
        None,
        None,
        1.0,
        evidence,
        supports,
        ("模型解释" if tier == "C" else "",) if tier == "C" else (),
        attribution,
        "active",
        1,
    )


def _valid_assertions() -> tuple[KnowledgeAssertion, ...]:
    a1 = _assertion(
        "claim_a1",
        "A",
        "fact",
        ("evidence_1",),
        (),
        attribution="source_explicit",
    )
    a2 = _assertion(
        "claim_a2",
        "A",
        "fact",
        ("evidence_2",),
        (),
        attribution="source_direct_event",
    )
    b1 = _assertion(
        "claim_b1",
        "B",
        "synthesis",
        (),
        ("claim_a1", "claim_a2"),
        attribution="cross_evidence_synthesis",
    )
    c1 = _assertion(
        "claim_c1",
        "C",
        "interpretation",
        (),
        ("claim_b1",),
        attribution="model_interpretation",
    )
    return a1, a2, b1, c1


class ClaimEvidenceGraphTests(unittest.TestCase):
    def test_builds_valid_a_b_c_graph(self) -> None:
        assertions = _valid_assertions()
        result = build_claim_evidence_edges(
            assertions,
            {"evidence_1": "clean", "evidence_2": "clean"},
        )
        self.assertTrue(result.report.valid, result.report.findings)
        self.assertEqual(result.report.tier_a_count, 2)
        self.assertEqual(result.report.tier_b_count, 1)
        self.assertEqual(result.report.tier_c_count, 1)
        self.assertEqual(result.report.support_edge_count, 2)
        self.assertEqual(result.report.blocked_support_count, 0)

    def test_contradiction_and_context_do_not_become_positive_support(self) -> None:
        assertions = _valid_assertions()
        result = build_claim_evidence_edges(
            assertions,
            {
                "evidence_1": "clean",
                "evidence_2": "clean",
                "evidence_3": "clean",
                "evidence_4": "clean",
            },
            contradicting_evidence={"claim_a1": ("evidence_3",)},
            contextual_evidence={"claim_a1": ("evidence_4",)},
        )
        self.assertTrue(result.report.valid)
        self.assertEqual(result.report.support_edge_count, 2)
        self.assertEqual(result.report.contradict_edge_count, 1)
        self.assertEqual(result.report.context_edge_count, 1)
        relations = {edge.relation for edge in result.edges if edge.assertion_id == "claim_a1"}
        self.assertEqual(relations, {"support", "contradict", "context"})

    def test_contaminated_evidence_cannot_support_tier_a(self) -> None:
        assertions = (_valid_assertions()[0],)
        result = build_claim_evidence_edges(
            assertions,
            {"evidence_1": "contaminated"},
        )
        self.assertFalse(result.report.valid)
        codes = {item.code for item in result.report.findings}
        self.assertIn("CLAIM_SUPPORT_NON_CLEAN_EVIDENCE", codes)
        self.assertIn("TIER_A_WITHOUT_CLEAN_EVIDENCE", codes)
        self.assertEqual(result.report.blocked_support_count, 1)

    def test_unknown_evidence_reference_is_rejected(self) -> None:
        assertions = (_valid_assertions()[0],)
        result = build_claim_evidence_edges(assertions, {})
        self.assertFalse(result.report.valid)
        self.assertEqual(result.report.unknown_evidence_reference_count, 1)
        self.assertIn(
            "CLAIM_EDGE_UNKNOWN_EVIDENCE",
            {item.code for item in result.report.findings},
        )

    def test_support_edges_must_equal_claim_declaration(self) -> None:
        assertion = _valid_assertions()[0]
        edge = ClaimEvidenceEdge(
            CLAIM_EVIDENCE_EDGE_SCHEMA_VERSION,
            claim_evidence_edge_id(assertion.assertion_id, "evidence_2", "support"),
            assertion.assertion_id,
            "evidence_2",
            "support",
            "clean",
            1,
            1.0,
            "accepted_edge",
        )
        report = validate_claim_evidence_graph(
            (assertion,),
            {"evidence_1": "clean", "evidence_2": "clean"},
            (edge,),
        )
        self.assertFalse(report.valid)
        self.assertIn(
            "CLAIM_SUPPORT_DECLARATION_MISMATCH",
            {item.code for item in report.findings},
        )

    def test_b_synthesis_support_must_be_tier_a(self) -> None:
        assertions = _valid_assertions()
        invalid_b = _assertion(
            "claim_b2",
            "B",
            "synthesis",
            (),
            ("claim_b1", "claim_a1"),
            attribution="cross_evidence_synthesis",
        )
        result = build_claim_evidence_edges(
            (*assertions, invalid_b),
            {"evidence_1": "clean", "evidence_2": "clean"},
        )
        self.assertFalse(result.report.valid)
        self.assertIn(
            "TIER_B_SUPPORT_NOT_TIER_A",
            {item.code for item in result.report.findings},
        )

    def test_optional_edges_cannot_reference_unknown_claim(self) -> None:
        with self.assertRaisesRegex(ClaimEvidenceError, "unknown Claims"):
            build_claim_evidence_edges(
                _valid_assertions(),
                {"evidence_1": "clean", "evidence_2": "clean", "evidence_3": "clean"},
                contradicting_evidence={"missing_claim": ("evidence_3",)},
            )

    def test_edge_and_report_round_trip(self) -> None:
        result = build_claim_evidence_edges(
            _valid_assertions(),
            {"evidence_1": "clean", "evidence_2": "clean"},
        )
        edge_payload = json.loads(json.dumps(result.edges[0].to_dict()))
        report_payload = json.loads(json.dumps(result.report.to_dict()))
        self.assertEqual(edge_from_dict(edge_payload), result.edges[0])
        self.assertEqual(graph_report_from_dict(report_payload), result.report)

    def test_support_edge_identifier_is_relation_sensitive(self) -> None:
        support = claim_evidence_edge_id("claim", "evidence", "support")
        contradict = claim_evidence_edge_id("claim", "evidence", "contradict")
        self.assertNotEqual(support, contradict)


if __name__ == "__main__":
    unittest.main()
