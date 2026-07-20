from pathlib import Path

hybrid_path = Path("tkr/hybrid_retrieval.py")
hybrid = hybrid_path.read_text(encoding="utf-8")
marker = "def _select_temporal(hits: Sequence[RetrievalHit], scope: str) -> list[RetrievalHit]:\n"
helper = '''def _select_most_precise_compatible_date(\n    hits: Sequence[RetrievalHit],\n) -> list[RetrievalHit]:\n    """Collapse a Phase 4 date-precision refinement to its most precise value."""\n\n    if not hits or any(hit.canonical_status != "compatible_variant" for hit in hits):\n        return list(hits)\n    values = {str(hit.value) for hit in hits}\n    most_precise = max(values, key=lambda value: (value.count("-"), len(value), value))\n    if not all(value == most_precise or most_precise.startswith(value + "-") for value in values):\n        return list(hits)\n    return [hit for hit in hits if str(hit.value) == most_precise]\n\n\n'''
if marker not in hybrid:
    raise SystemExit("temporal-selection marker was not found")
hybrid = hybrid.replace(marker, helper + marker, 1)
old = '''        distinct = {_answer_key(hit, intent) for hit in active}\n        if len(distinct) > 1:\n'''
new = '''        if intent.predicate == "date":\n            active = _select_most_precise_compatible_date(active)\n\n        distinct = {_answer_key(hit, intent) for hit in active}\n        if len(distinct) > 1:\n'''
if old not in hybrid:
    raise SystemExit("answer-distinctness block was not found")
hybrid = hybrid.replace(old, new, 1)
hybrid_path.write_text(hybrid, encoding="utf-8")

test_path = Path("tests/test_hybrid_retrieval.py")
tests = test_path.read_text(encoding="utf-8")
test_marker = "\n    def test_index_contains_structured_tables(self):\n"
test_case = '''\n    def test_date_precision_refinement_returns_most_precise_value(self):\n        with tempfile.TemporaryDirectory() as directory:\n            root = Path(directory)\n            paths = self.build(\n                root,\n                ["工程始于2001-02。工程始于2001-02-03。"],\n                [\n                    {"evidence": "工程始于2001-02。", "claim_type": "date", "subject": "工程", "value": "2001-02"},\n                    {"evidence": "工程始于2001-02-03。", "claim_type": "date", "subject": "工程", "value": "2001-02-03"},\n                ],\n            )\n            result = query_hybrid_index(paths[4], "工程什么时候开始？")\n        self.assertEqual(result.answerability, "answerable")\n        self.assertEqual(result.hits[0].value, "2001-02-03")\n'''
if test_marker not in tests:
    raise SystemExit("test insertion marker was not found")
tests = tests.replace(test_marker, test_case + test_marker, 1)
test_path.write_text(tests, encoding="utf-8")
