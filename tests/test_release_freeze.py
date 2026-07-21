from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from tkr.release_freeze import (
    FREEZE_APPROVAL_SCHEMA_VERSION,
    FreezeError,
    prepare_freeze_candidate,
    seal_freeze_candidate,
    verify_freeze_candidate,
    verify_freeze_seal,
)


class ReleaseFreezeTests(unittest.TestCase):
    SOURCE_COMMIT = "a" * 40
    VERSION = "5.8.0a1"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wheel = self.root / "text_knowledge_reader_core-5.8.0a1-py3-none-any.whl"
        self.wheel.write_bytes(b"canonical-wheel-bytes")
        self.wheel_sha = sha256(self.wheel.read_bytes()).hexdigest()

        self.release_manifest = self._write_json(
            "release-manifest.json",
            {
                "case_count": 108,
                "governance": {"may_freeze": False},
            },
        )
        self.release_report = self._write_json(
            "release-report.json",
            {
                "passed": True,
                "may_certify_release": True,
                "may_freeze": False,
                "blockers": [],
                "report_id": "bench_release_001",
            },
        )
        self.release_verification = self._write_json(
            "release-verification.json",
            {
                "accepted": True,
                "status": "accepted",
                "expected_report_id": "bench_release_001",
                "supplied_report_id": "bench_release_001",
            },
        )
        self.reproducible = self._write_json(
            "reproducible-build.json",
            {
                "schema_version": "tkr-reproducible-build-v1",
                "accepted": True,
                "build_count": 2,
                "wheel_sha256": self.wheel_sha,
                "build_sha256": [self.wheel_sha, self.wheel_sha],
            },
        )
        self.package_reports = []
        for minor in ("3.10", "3.11", "3.12"):
            self.package_reports.append(
                self._write_json(
                    f"package-{minor}.json",
                    {
                        "accepted": True,
                        "failures": [],
                        "python": f"{minor}.9 (main, test)",
                        "version": self.VERSION,
                        "wheel_sha256": self.wheel_sha,
                        "wheel_name": self.wheel.name,
                    },
                )
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_json(self, name: str, payload: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _specs(self) -> list[tuple[str, Path]]:
        return [
            ("wheel", self.wheel),
            ("release_manifest", self.release_manifest),
            ("release_report", self.release_report),
            ("release_verification", self.release_verification),
            ("reproducible_build_report", self.reproducible),
            *(("package_acceptance", path) for path in self.package_reports),
        ]

    def _prepare(self) -> Path:
        path = self.root / "freeze-candidate.json"
        payload = prepare_freeze_candidate(
            self.root,
            self._specs(),
            release_version=self.VERSION,
            source_commit=self.SOURCE_COMMIT,
            source_date_epoch=1700000000,
            output_path=path,
        )
        self.assertFalse(payload["may_freeze"])
        self.assertTrue(payload["requires_explicit_approval"])
        return path

    def test_prepare_and_verify_candidate(self) -> None:
        candidate = self._prepare()
        result = verify_freeze_candidate(candidate, root=self.root)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["may_freeze"])
        self.assertIn("EXPLICIT_APPROVAL_STILL_REQUIRED", result["reason_codes"])

    def test_tampered_artifact_is_rejected(self) -> None:
        candidate = self._prepare()
        self.wheel.write_bytes(b"tampered")
        with self.assertRaisesRegex(FreezeError, "mismatch"):
            verify_freeze_candidate(candidate, root=self.root)

    def test_missing_required_python_acceptance_is_rejected(self) -> None:
        with self.assertRaisesRegex(FreezeError, "at least 3 package_acceptance"):
            prepare_freeze_candidate(
                self.root,
                self._specs()[:-1],
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_mismatched_package_wheel_hash_is_rejected(self) -> None:
        payload = json.loads(self.package_reports[0].read_text(encoding="utf-8"))
        payload["wheel_sha256"] = "0" * 64
        self.package_reports[0].write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FreezeError, "disagree on wheel SHA-256"):
            prepare_freeze_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_phase7_cannot_self_grant_freeze(self) -> None:
        payload = json.loads(self.release_report.read_text(encoding="utf-8"))
        payload["may_freeze"] = True
        self.release_report.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(FreezeError, "may_freeze must be False"):
            prepare_freeze_candidate(
                self.root,
                self._specs(),
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_explicit_approval_creates_and_verifies_seal(self) -> None:
        candidate = self._prepare()
        candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
        approval = self._write_json(
            "approval.json",
            {
                "schema_version": FREEZE_APPROVAL_SCHEMA_VERSION,
                "candidate_id": candidate_payload["candidate_id"],
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "approver": "release-owner",
                "decision": "approve",
                "statement": "I approve this exact technical candidate for freezing.",
                "approved_at": "2026-07-21T05:00:00Z",
            },
        )
        seal = self.root / "freeze-seal.json"
        payload = seal_freeze_candidate(candidate, approval, seal, root=self.root)
        self.assertTrue(payload["may_freeze"])
        self.assertEqual(
            payload["approval_authentication"],
            "operator_asserted_not_cryptographically_verified",
        )
        verification = verify_freeze_seal(seal, candidate, approval, root=self.root)
        self.assertTrue(verification["accepted"])
        self.assertTrue(verification["may_freeze"])

    def test_approval_for_another_candidate_is_rejected(self) -> None:
        candidate = self._prepare()
        approval = self._write_json(
            "approval.json",
            {
                "schema_version": FREEZE_APPROVAL_SCHEMA_VERSION,
                "candidate_id": "freeze_candidate_wrong",
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "approver": "release-owner",
                "decision": "approve",
                "statement": "approve",
                "approved_at": "2026-07-21T05:00:00Z",
            },
        )
        with self.assertRaisesRegex(FreezeError, "candidate_id does not match"):
            seal_freeze_candidate(
                candidate,
                approval,
                self.root / "freeze-seal.json",
                root=self.root,
            )

    def test_unknown_approval_fields_are_rejected(self) -> None:
        candidate = self._prepare()
        candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
        approval = self._write_json(
            "approval.json",
            {
                "schema_version": FREEZE_APPROVAL_SCHEMA_VERSION,
                "candidate_id": candidate_payload["candidate_id"],
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "approver": "release-owner",
                "decision": "approve",
                "statement": "approve",
                "approved_at": "2026-07-21T05:00:00Z",
                "may_freeze": True,
            },
        )
        with self.assertRaisesRegex(FreezeError, "keys mismatch"):
            seal_freeze_candidate(
                candidate,
                approval,
                self.root / "freeze-seal.json",
                root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
