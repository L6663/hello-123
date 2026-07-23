from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tkr.literary_benchmark import (
    CASE_SCHEMA_VERSION,
    DOMAINS,
    OBSERVATION_SCHEMA_VERSION,
    LiteraryBenchmarkError,
    evaluate_benchmark,
    verify_benchmark_report,
)


class LiteraryBenchmarkTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        cases: list[dict[str, object]] = []
        observations: list[dict[str, object]] = []
        layer_for_domain = {
            "motive_reasoning": "B",
            "foreshadowing_resolution": "B",
            "theme_interpretation": "C",
            "epistemic_separation": "A",
        }
        refusal_domains = {"cold_detail_recall", "refusal_safety"}
        for index, domain in enumerate(DOMAINS, start=1):
            case_id = f"LBR-{index:03d}"
            mode = "analysis" if domain in {
                "motive_reasoning", "foreshadowing_resolution", "theme_interpretation"
            } else "fact_only"
            if domain in refusal_domains:
                cases.append({
                    "schema_version": CASE_SCHEMA_VERSION,
                    "case_id": case_id,
                    "domain": domain,
                    "question": f"unsupported question for {domain}",
                    "mode": mode,
                    "expected_decision": "refused",
                    "expected_layers": [],
                    "expected_node_ids": [],
                    "required_evidence_anchor_ids": [],
                    "forbidden_node_ids": [f"forbidden-{index}"],
                    "expected_reason_codes": ["NO_SUPPORTED_REASONING_NODE_SELECTED"],
                    "source_sha256s": ["a" * 64],
                    "tags": ["synthetic", "refusal"],
                    "allow_additional_nodes": False,
                    "annotation_status": "draft",
                    "annotator_id": "annotator-1",
                    "reviewer_ids": [],
                    "rationale": "Synthetic smoke refusal case.",
                })
                packet = {
                    "schema_version": "tkr-layered-answer-packet-v1",
                    "mode": mode,
                    "decision": "refused",
                    "reason_codes": ["NO_SUPPORTED_REASONING_NODE_SELECTED"],
                    "facts": [],
                    "synthesis": [],
                    "interpretation": [],
                    "counterfactual": [],
                    "provenance": [],
                    "may_accept_project": False,
                    "may_release": False,
                    "may_freeze": False,
                }
            else:
                layer = layer_for_domain.get(domain, "A")
                node_id = f"node-{index}"
                anchor_id = f"anchor-{index}"
                section = {
                    "A": "facts", "B": "synthesis", "C": "interpretation", "H": "counterfactual"
                }[layer]
                cases.append({
                    "schema_version": CASE_SCHEMA_VERSION,
                    "case_id": case_id,
                    "domain": domain,
                    "question": f"supported question for {domain}",
                    "mode": mode,
                    "expected_decision": "answered",
                    "expected_layers": [layer],
                    "expected_node_ids": [node_id],
                    "required_evidence_anchor_ids": [anchor_id],
                    "forbidden_node_ids": [f"forbidden-{index}"],
                    "expected_reason_codes": [],
                    "source_sha256s": ["b" * 64],
                    "tags": ["synthetic", domain],
                    "allow_additional_nodes": False,
                    "annotation_status": "draft",
                    "annotator_id": "annotator-1",
                    "reviewer_ids": [],
                    "rationale": "Synthetic smoke answer case.",
                })
                packet = {
                    "schema_version": "tkr-layered-answer-packet-v1",
                    "mode": mode,
                    "decision": "answered",
                    "reason_codes": [],
                    "facts": [],
                    "synthesis": [],
                    "interpretation": [],
                    "counterfactual": [],
                    "provenance": [{"node_id": node_id, "evidence_anchor_ids": [anchor_id]}],
                    "may_accept_project": False,
                    "may_release": False,
                    "may_freeze": False,
                }
                packet[section] = [{
                    "node_id": node_id,
                    "layer": layer,
                    "evidence_anchor_ids": [anchor_id],
                }]
            observations.append({
                "schema_version": OBSERVATION_SCHEMA_VERSION,
                "case_id": case_id,
                "packet": packet,
            })
        cases_path = root / "cases.jsonl"
        observations_path = root / "observations.jsonl"
        cases_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in cases),
            encoding="utf-8",
        )
        observations_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observations),
            encoding="utf-8",
        )
        return cases_path, observations_path

    def test_smoke_passes_all_domains_without_granting_authority(self) -> None:
        with TemporaryDirectory() as directory:
            cases, observations = self._fixture(Path(directory))
            report = evaluate_benchmark(cases, observations, profile="smoke")
            self.assertTrue(report.passed)
            self.assertEqual(set(report.domain_results), set(DOMAINS))
            self.assertTrue(all(value["score"] == 10.0 for value in report.domain_results.values()))
            self.assertFalse(report.project_acceptance_performed)
            self.assertFalse(report.may_accept_project)
            self.assertFalse(report.may_release)
            self.assertFalse(report.may_freeze)

    def test_layer_leakage_and_authority_escalation_block(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases, observations = self._fixture(root)
            rows = [json.loads(line) for line in observations.read_text(encoding="utf-8").splitlines()]
            target = next(row for row in rows if row["packet"]["decision"] == "answered")
            node = target["packet"]["facts"][0]
            node["layer"] = "C"
            target["packet"]["may_release"] = True
            observations.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            report = evaluate_benchmark(cases, observations, profile="smoke")
            self.assertFalse(report.passed)
            self.assertIn("EPISTEMIC_LAYER_LEAKAGE_PRESENT", report.blockers)
            self.assertIn("UNAUTHORIZED_BENCHMARK_AUTHORITY_PRESENT", report.blockers)

    def test_report_verification_recomputes_every_field(self) -> None:
        with TemporaryDirectory() as directory:
            cases, observations = self._fixture(Path(directory))
            report = evaluate_benchmark(cases, observations, profile="smoke")
            verification = verify_benchmark_report(cases, observations, report.to_dict())
            self.assertTrue(verification.valid)
            tampered = report.to_dict()
            tampered["metrics"] = {**tampered["metrics"], "wrong_answer_count": 99}
            rejected = verify_benchmark_report(cases, observations, tampered)
            self.assertFalse(rejected.valid)
            self.assertIn("REPORT_RECOMPUTATION_MISMATCH", rejected.reason_codes)

    def test_release_profile_rejects_small_unreviewed_gold(self) -> None:
        with TemporaryDirectory() as directory:
            cases, observations = self._fixture(Path(directory))
            report = evaluate_benchmark(cases, observations, profile="release")
            self.assertFalse(report.passed)
            self.assertIn("CASE_COUNT_BELOW_POLICY_MINIMUM", report.blockers)
            self.assertIn("UNAPPROVED_GOLD_ANNOTATIONS_PRESENT", report.blockers)
            self.assertIn("INDEPENDENT_REVIEWER_FLOOR_NOT_MET", report.blockers)

    def test_duplicate_case_ids_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases, observations = self._fixture(root)
            first = cases.read_text(encoding="utf-8").splitlines()[0]
            cases.write_text(first + "\n" + first + "\n", encoding="utf-8")
            with self.assertRaises(LiteraryBenchmarkError):
                evaluate_benchmark(cases, observations, profile="smoke")


if __name__ == "__main__":
    unittest.main()
