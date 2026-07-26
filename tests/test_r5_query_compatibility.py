from __future__ import annotations

import unittest

from tkr.hybrid_retrieval import QUERY_PARSER_VERSION, parse_predicate_query
from tkr.literary_query import LITERARY_QUERY_PARSER_VERSION, parse_literary_query


class R5QueryCompatibilityTests(unittest.TestCase):
    def test_natural_count_question_with_classifier(self) -> None:
        intent = parse_predicate_query("方源有几座仙蛊屋？")
        self.assertTrue(intent.supported)
        self.assertEqual(intent.predicate, "count")
        self.assertEqual(intent.subject, "方源")
        self.assertEqual(intent.unit, "座仙蛊屋")

    def test_count_parser_identity_is_r5(self) -> None:
        self.assertEqual(QUERY_PARSER_VERSION, "tkr-predicate-query-v2")

    def test_directional_defeat_object_query(self) -> None:
        intent = parse_literary_query("方源击败了谁？")
        self.assertEqual(intent.intent_type, "directional_defeats_object")
        self.assertEqual(intent.subject, "方源")

    def test_directional_defeat_subject_query_and_identity(self) -> None:
        intent = parse_literary_query("谁击败了凤金煌？")
        self.assertEqual(intent.intent_type, "directional_defeats_subject")
        self.assertEqual(intent.object, "凤金煌")
        self.assertEqual(LITERARY_QUERY_PARSER_VERSION, "tkr-literary-query-parser-v2")


if __name__ == "__main__":
    unittest.main()
