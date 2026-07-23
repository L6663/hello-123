from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tkr.final_acceptance import (
    APPROVAL_SCHEMA_VERSION,
    APPROVAL_STATEMENT_PREFIX,
    BLIND_ATTESTATION_SCHEMA_VERSION,
    ENGINEERING_VALIDATION_SCHEMA_VERSION,
    FinalAcceptanceError,
    PACKAGE_ACCEPTANCE_SCHEMA_VERSION,
    REPRODUCIBLE_BUILD_SCHEMA_VERSION,
    REQUIRED_CONSOLE_SCRIPTS,
    prepare_final_acceptance_candidate,
    seal_final_acceptance,
    verify_final_acceptance_candidate,
    verify_final_acceptance_seal,
)


class FinalAcceptanceTests(unittest.TestCase):
    SOURCE_COMMIT = "a" * 40
    VERSION = "6.0.0rc1"
    SOURCE_DATE_EPOCH = 1700000000
    REPORT_ID = "lbr_" + "b" * 32
    CORPUS_SHA = "c" * 64

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)

        self.wheel = self._write_bytes(
            "text_knowledge_reader_core-6.0.0rc1-py3-none-any.whl",
            b"canonical-wheel",
        )
        self.wheel_sha = self._digest(self.wheel)
        self.reproducible_wheels = [
            self._write_bytes("build-a.whl", self.wheel.read_bytes()),
            self._write_bytes("build-b.whl", self.wheel.read_bytes()),
        ]

        self.cases = self._write_bytes("literary-cases.jsonl", b"{}\n")
        self.observations = self._write_bytes(
            "literary-observations.jsonl", b"{}\n"
        )
        self.report = self._write_json(
            "literary-report.json",
            {
                "policy_profile": "release",
                "passed": True,
                "blockers": [],
                "case_count": 120,
                "report_id": self.REPORT_ID,
                "project_acceptance_performed": False,
                "may_accept_project": False,
                "may_release": False,
                "may_freeze": False,
            },
        )
        self.verification_payload = {
            "schema_version": "tkr-literary-benchmark-verification-v1",
            "status": "verified",
            "valid": True,
            "reason_codes": [],
            "supplied_report_id": self.REPORT_ID,
            "expected_report_id": self.REPORT_ID,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_release": False,
            "may_freeze": False,
        }
        self.literary_verification = self._write_json(
            "literary-verification.json", self.verification_payload
        )
        self.mock_cases = tuple(
            SimpleNamespace(source_sha256s=(self.CORPUS_SHA,))
            for _ in range(120)
        )
        self.mock_verification = SimpleNamespace(
            valid=True,
            reason_codes=(),
            expected_report_id=self.REPORT_ID,
            to_dict=lambda: dict(self.verification_payload),
        )
        self.load_cases_patch = patch(
            "tkr.final_acceptance.load_cases",
            return_value=(self.mock_cases, "d" * 64, "e" * 64),
        )
        self.verify_benchmark_patch = patch(
            "tkr.final_acceptance.verify_benchmark_report",
            return_value=self.mock_verification,
        )
        self.read_report_patch = patch(
            "tkr.final_acceptance.read_report",
            side_effect=lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
        )
        self.source_summary = {
            "source_commit": self.SOURCE_COMMIT,
            "source_date_epoch": self.SOURCE_DATE_EPOCH,
            "source_bundle_sha256": "f" * 64,
            "runtime_file_count": 10,
            "runtime_files_sha256": "1" * 64,
            "source_provenance_verified": True,
        }
        self.source_patch = patch(
            "tkr.final_acceptance.verify_source_provenance",
            return_value=self.source_summary,
        )
        self.load_cases_patch.start()
        self.verify_benchmark_patch.start()
        self.read_report_patch.start()
        self.source_patch.start()

        self.blind = self._write_json(
            "private-blind-attestation.json",
            {
                "schema_version": BLIND_ATTESTATION_SCHEMA_VERSION,
                "protocol_id": "private-blind-001",
                "corpus_sha256s": [self.CORPUS_SHA],
                "cases_file_sha256": self._digest(self.cases),
                "observations_file_sha256": self._digest(self.observations),
                "report_file_sha256": self._digest(self.report),
                "gold_locked_before_run": True,
                "gold_hidden_from_answer_system": True,
                "observations_generated_without_gold_access": True,
                "corpus_not_used_for_v6_development": True,
                "evaluator_id": "evaluator-1",
                "gold_custodian_id": "custodian-1",
                "reviewer_ids": ["reviewer-1", "reviewer-2"],
                "status": "approved",
                "statement": "The private blind protocol was followed.",
                "attested_at_utc": "2026-07-23T09:00:00Z",
                "project_acceptance_performed": False,
                "may_release": False,
                "may_freeze": False,
            },
        )

        self.skill_audit = self._write_json(
            "skill-audit.json",
            {
                "audit_version": "6.0.0-stage8",
                "passed": True,
                "findings": [],
                "finding_count": 0,
                "project_acceptance_performed": False,
                "may_accept_project": False,
                "release_candidate": False,
                "may_freeze": False,
            },
        )
        self.skill_doctor = self._write_json(
            "skill-doctor.json",
            {
                "audit_version": "6.0.0-stage8",
                "passed": True,
                "checks": [{"name": "all", "status": "passed", "detail": "ok"}],
                "project_acceptance_performed": False,
                "may_accept_project": False,
                "release_candidate": False,
                "may_freeze": False,
            },
        )
        self.package_reports: list[Path] = []
        for minor in ("3.10", "3.11", "3.12"):
            self.package_reports.append(
                self._write_json(
                    f"package-{minor}.json",
                    {
                        "schema_version": PACKAGE_ACCEPTANCE_SCHEMA_VERSION,
                        "accepted": True,
                        "failures": [],
                        "python": f"{minor}.9",
                        "version": self.VERSION,
                        "wheel_name": self.wheel.name,
                        "wheel_sha256": self.wheel_sha,
                        "installed_cli": sorted(REQUIRED_CONSOLE_SCRIPTS),
                        "skill_audit_passed": True,
                        "skill_doctor_passed": True,
                    },
                )
            )
        self.reproducible = self._write_json(
            "reproducible-build.json",
            {
                "schema_version": REPRODUCIBLE_BUILD_SCHEMA_VERSION,
                "accepted": True,
                "version": self.VERSION,
                "source_date_epoch": self.SOURCE_DATE_EPOCH,
                "build_count": 2,
                "wheel_name": self.wheel.name,
                "wheel_sha256": self.wheel_sha,
                "build_sha256": [self.wheel_sha, self.wheel_sha],
            },
        )
        self.engineering = self._write_json(
            "engineering-validation.json",
            {
                "schema_version": ENGINEERING_VALIDATION_SCHEMA_VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "workflow_run_id": 123456,
                "conclusion": "success",
                "focused_test_count": 10,
                "full_repository_regression": True,
                "schema_contracts": True,
                "cli_contracts": True,
                "package_matrix": ["3.10", "3.11", "3.12"],
                "wheel_reproducible": True,
                "project_acceptance_performed": False,
                "may_release": False,
                "may_freeze": False,
            },
        )
        self.source_bundle = self._write_bytes("source.bundle", b"bundle")
        self.source_provenance = self._write_json(
            "source-provenance.json", {"schema_version": "test"}
        )
        self.project_status = self._write_bytes(
            "PROJECT_STATUS.yaml", b"status: candidate\n"
        )
        self.skill_contract = self._write_bytes("SKILL.md", b"# Skill\n")
        self.readme = self._write_bytes("README.md", b"# Readme\n")

    def tearDown(self) -> None:
        patch.stopall()
        self.temporary.cleanup()

    def _write_bytes(self, name: str, payload: bytes) -> Path:
        path = self.root / name
        path.write_bytes(payload)
        return path

    def _write_json(self, name: str, payload: object) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _specs(self) -> list[tuple[str, Path]]:
        return [
            ("wheel", self.wheel),
            ("skill_audit", self.skill_audit),
            ("skill_doctor", self.skill_doctor),
            ("literary_cases", self.cases),
            ("literary_observations", self.observations),
            ("literary_report", self.report),
            ("literary_verification", self.literary_verification),
            ("blind_attestation", self.blind),
            ("engineering_validation", self.engineering),
            ("reproducible_build_report", self.reproducible),
            ("source_bundle", self.source_bundle),
            ("source_provenance", self.source_provenance),
            ("project_status", self.project_status),
            ("skill_contract", self.skill_contract),
            ("readme", self.readme),
            *(("package_acceptance", path) for path in self.package_reports),
            *(("reproducible_wheel", path) for path in self.reproducible_wheels),
        ]

    def _prepare(self) -> Path:
        path = self.root / "final-acceptance-candidate.json"
        payload = prepare_final_acceptance_candidate(
            self.root,
            self._specs(),
            release_version=self.VERSION,
            source_commit=self.SOURCE_COMMIT,
            source_date_epoch=self.SOURCE_DATE_EPOCH,
            output_path=path,
        )
        self.assertFalse(payload["project_acceptance_performed"])
        self.assertFalse(payload["may_accept_project"])
        self.assertFalse(payload["release_candidate"])
        self.assertFalse(payload["may_release"])
        self.assertFalse(payload["may_freeze"])
        return path

    def _approval(self, candidate: Path) -> Path:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        return self._write_json(
            "final-acceptance-approval.json",
            {
                "schema_version": APPROVAL_SCHEMA_VERSION,
                "candidate_id": payload["candidate_id"],
                "release_version": payload["release_version"],
                "source_commit": payload["source_commit"],
                "approver": "owner-1",
                "decision": "approve_final_product_acceptance",
                "statement": (
                    APPROVAL_STATEMENT_PREFIX + payload["candidate_id"] + "."
                ),
                "approved_at_utc": "2026-07-23T10:00:00Z",
            },
        )

    def test_prepare_and_verify_candidate(self) -> None:
        candidate = self._prepare()
        result = verify_final_acceptance_candidate(candidate, root=self.root)
        self.assertTrue(result["valid"])
        self.assertFalse(result["project_acceptance_performed"])
        self.assertIn(
            "EXPLICIT_APPROVAL_STILL_REQUIRED", result["reason_codes"]
        )

    def test_tampered_artifact_is_rejected(self) -> None:
        candidate = self._prepare()
        self.wheel.write_bytes(b"tampered")
        with self.assertRaisesRegex(FinalAcceptanceError, "mismatch"):
            verify_final_acceptance_candidate(candidate, root=self.root)

    def test_stage7_report_cannot_self_grant_authority(self) -> None:
        payload = json.loads(self.report.read_text(encoding="utf-8"))
        payload["may_release"] = True
        self.report.write_text(json.dumps(payload), encoding="utf-8")
        self.blind = self._rewrite_attestation_hash("report_file_sha256", self.report)
        with self.assertRaisesRegex(FinalAcceptanceError, "may_release"):
            prepare_final_acceptance_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=self.SOURCE_DATE_EPOCH,
            )

    def _rewrite_attestation_hash(self, key: str, path: Path) -> Path:
        payload = json.loads(self.blind.read_text(encoding="utf-8"))
        payload[key] = self._digest(path)
        self.blind.write_text(json.dumps(payload), encoding="utf-8")
        return self.blind

    def test_private_blind_protocol_flag_is_mandatory(self) -> None:
        payload = json.loads(self.blind.read_text(encoding="utf-8"))
        payload["gold_hidden_from_answer_system"] = False
        self.blind.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FinalAcceptanceError, "must be True"):
            prepare_final_acceptance_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=self.SOURCE_DATE_EPOCH,
            )

    def test_private_blind_roles_must_be_independent(self) -> None:
        payload = json.loads(self.blind.read_text(encoding="utf-8"))
        payload["reviewer_ids"][0] = payload["evaluator_id"]
        self.blind.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FinalAcceptanceError, "independent"):
            prepare_final_acceptance_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=self.SOURCE_DATE_EPOCH,
            )

    def test_forged_literary_verification_is_rejected(self) -> None:
        payload = json.loads(
            self.literary_verification.read_text(encoding="utf-8")
        )
        payload["valid"] = False
        self.literary_verification.write_text(
            json.dumps(payload), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            FinalAcceptanceError, "does not match recomputation"
        ):
            prepare_final_acceptance_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=self.SOURCE_DATE_EPOCH,
            )

    def test_python_package_matrix_is_exact(self) -> None:
        specs = [
            item
            for item in self._specs()
            if item != ("package_acceptance", self.package_reports[-1])
        ]
        with self.assertRaisesRegex(
            FinalAcceptanceError, "exactly three package_acceptance"
        ):
            prepare_final_acceptance_candidate(
                self.root,
                specs,
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=self.SOURCE_DATE_EPOCH,
            )

    def test_engineering_validation_must_bind_source_commit(self) -> None:
        payload = json.loads(self.engineering.read_text(encoding="utf-8"))
        payload["source_commit"] = "0" * 40
        self.engineering.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FinalAcceptanceError, "source_commit mismatch"):
            prepare_final_acceptance_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=self.SOURCE_DATE_EPOCH,
            )

    def test_explicit_approval_creates_acceptance_not_release(self) -> None:
        candidate = self._prepare()
        approval = self._approval(candidate)
        seal = self.root / "final-acceptance-seal.json"
        payload = seal_final_acceptance(
            candidate, approval, seal, root=self.root
        )
        self.assertTrue(payload["project_acceptance_performed"])
        self.assertTrue(payload["may_accept_project"])
        self.assertTrue(payload["release_candidate"])
        self.assertFalse(payload["may_release"])
        self.assertFalse(payload["may_freeze"])
        verification = verify_final_acceptance_seal(
            seal, candidate, approval, root=self.root
        )
        self.assertTrue(verification["valid"])
        self.assertIn(
            "RELEASE_APPROVAL_STILL_REQUIRED",
            verification["reason_codes"],
        )

    def test_approval_must_explicitly_name_candidate(self) -> None:
        candidate = self._prepare()
        approval = self._approval(candidate)
        payload = json.loads(approval.read_text(encoding="utf-8"))
        payload["statement"] = "approve"
        approval.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FinalAcceptanceError, "explicitly name"):
            seal_final_acceptance(
                candidate,
                approval,
                self.root / "seal.json",
                root=self.root,
            )

    def test_verifier_rejects_approval_for_another_candidate(self) -> None:
        candidate = self._prepare()
        approval = self._approval(candidate)
        payload = json.loads(approval.read_text(encoding="utf-8"))
        payload["candidate_id"] = "final_acceptance_candidate_" + "0" * 24
        payload["statement"] = (
            APPROVAL_STATEMENT_PREFIX + payload["candidate_id"] + "."
        )
        approval.write_text(json.dumps(payload), encoding="utf-8")
        fake_seal = self.root / "fake-seal.json"
        fake_seal.write_text(
            json.dumps({
                "schema_version": "tkr-final-acceptance-seal-v1",
                "candidate_id": json.loads(candidate.read_text())["candidate_id"],
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "candidate_sha256": self._digest(candidate),
                "approval_sha256": self._digest(approval),
                "approver": "owner-1",
                "approved_at_utc": "2026-07-23T10:00:00Z",
                "verification_reason_codes": [],
                "project_acceptance_performed": True,
                "may_accept_project": True,
                "release_candidate": True,
                "may_release": False,
                "may_freeze": False,
                "status": "accepted",
                "seal_id": "final_acceptance_seal_" + "0" * 24,
            }),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(FinalAcceptanceError, "approval candidate_id"):
            verify_final_acceptance_seal(
                fake_seal, candidate, approval, root=self.root
            )

    def test_tampered_seal_is_rejected(self) -> None:
        candidate = self._prepare()
        approval = self._approval(candidate)
        seal = self.root / "final-acceptance-seal.json"
        seal_final_acceptance(candidate, approval, seal, root=self.root)
        payload = json.loads(seal.read_text(encoding="utf-8"))
        payload["may_release"] = True
        seal.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FinalAcceptanceError, "may_release"):
            verify_final_acceptance_seal(
                seal, candidate, approval, root=self.root
            )


if __name__ == "__main__":
    unittest.main()
