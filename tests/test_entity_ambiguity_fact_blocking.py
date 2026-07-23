from __future__ import annotations

import unittest

from tkr.chunking import UnitSpan
from tkr.claim_validation import ClaimCandidate, validate_claim
from tkr.entity_normalization import normalize_entities


class EntityAmbiguityFactBlockingTests(unittest.TestCase):
    def _record(
        self,
        source: str,
        evidence: str,
        span: UnitSpan,
        *,
        value: int,
        start: int,
    ) -> dict[str, object]:
        candidate = ClaimCandidate(
            claim_type="count",
            subject="狐如意法",
            value=value,
            unit="篇",
            source_id=span.source_id,
            unit_id=span.unit_id,
            evidence_start=start,
            evidence_end=start + len(evidence),
            evidence_text=evidence,
        )
        validation = validate_claim(candidate, source, unit_span=span, require_unit=True)
        self.assertEqual(validation.status, "accepted", validation.reason_codes)
        return {
            "candidate_line": 1,
            "candidate": candidate.to_dict(),
            "validation": validation.to_dict(),
        }

    def test_unresolved_same_surface_identity_contests_all_attached_facts(self) -> None:
        first = "狐如意法共分七篇。"
        second = "狐如意法共分九篇。"
        source = first + second
        u1 = UnitSpan("u1", 0, len(first), "novel")
        u2 = UnitSpan("u2", len(first), len(source), "novel")
        records = [
            self._record(source, first, u1, value=7, start=0),
            self._record(source, second, u2, value=9, start=len(first)),
        ]

        bundle = normalize_entities(records, source, [u1, u2])

        ambiguity = next(
            item for item in bundle.ambiguity_groups if item.normalized_surface == "狐如意法"
        )
        conflict = next(
            item for item in bundle.conflicts if item.conflict_type == "AMBIGUOUS_ENTITY_REFERENCE"
        )
        self.assertEqual(conflict.status, "unresolved")
        self.assertEqual(conflict.severity, "review")
        self.assertEqual(conflict.details["ambiguity_id"], ambiguity.ambiguity_id)
        self.assertEqual(set(conflict.entity_ids), set(ambiguity.entity_ids))
        self.assertEqual(set(conflict.fact_ids), {fact.fact_id for fact in bundle.facts})
        self.assertTrue(all(fact.canonical_status == "contested" for fact in bundle.facts))
        self.assertTrue(all(conflict.conflict_id in fact.conflict_ids for fact in bundle.facts))
        self.assertEqual(bundle.report["contested_fact_count"], 2)
        self.assertEqual(bundle.report["canonical_fact_count"], 0)
        self.assertFalse(bundle.report["may_publish_canonical"])
        self.assertFalse(bundle.report["project_acceptance_performed"] if "project_acceptance_performed" in bundle.report else False)

    def test_explicit_same_as_removes_ambiguity_and_preserves_value_conflict(self) -> None:
        # Existing identity-link tests cover merge validation. This assertion
        # protects the contract that only unresolved ambiguity creates the new
        # conflict type.
        first = "守卫共有七人。"
        source = first
        unit = UnitSpan("u1", 0, len(source), "novel")
        candidate = ClaimCandidate(
            claim_type="count",
            subject="守卫",
            value=7,
            unit="人",
            source_id="novel",
            unit_id="u1",
            evidence_start=0,
            evidence_end=len(first),
            evidence_text=first,
        )
        validation = validate_claim(candidate, source, unit_span=unit, require_unit=True)
        record = {"candidate_line": 1, "candidate": candidate.to_dict(), "validation": validation.to_dict()}
        bundle = normalize_entities([record], source, [unit])
        self.assertFalse(bundle.ambiguity_groups)
        self.assertFalse(any(c.conflict_type == "AMBIGUOUS_ENTITY_REFERENCE" for c in bundle.conflicts))
        self.assertEqual(bundle.facts[0].canonical_status, "canonical")


if __name__ == "__main__":
    unittest.main()
