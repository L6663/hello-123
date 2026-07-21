from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tkr.gold_benchmark import BenchmarkVerification
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
    REPORT_ID = "bench_release_001"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

        self.benchmark_verification = BenchmarkVerification(
            "accepted",
            True,
            ("BENCHMARK_RECOMPUTED_EXACTLY", "IMMUTABLE_POLICY_CONFIRMED"),
            self.REPORT_ID,
            self.REPORT_ID,
        )
        self.verify_patch = patch(
            "tkr.release_freeze.verify_benchmark_report",
            return_value=self.benchmark_verification,
        )
        self.verify_mock = self.verify_patch.start()
        self.source_summary = {
            "source_commit": self.SOURCE_COMMIT,
            "source_date_epoch": 1700000000,
            "source_bundle_sha256": "b" * 64,
            "runtime_file_count": 2,
            "runtime_files_sha256": "c" * 64,
            "source_provenance_verified": True,
        }
        self.source_patch = patch(
            "tkr.release_freeze.verify_source_provenance",
            return_value=self.source_summary,
        )
        self.source_mock = self.source_patch.start()

        self.wheel = (
            self.root
            / "text_knowledge_reader_core-5.8.0a1-py3-none-any.whl"
        )
        self.wheel.write_bytes(b"canonical-wheel-bytes")
        self.wheel_sha = sha256(self.wheel.read_bytes()).hexdigest()

        self.reproducible_wheels = []
        for name in ("build-a.whl", "build-b.whl"):
            path = self.root / name
            path.write_bytes(self.wheel.read_bytes())
            self.reproducible_wheels.append(path)

        self.release_source = self._write_bytes(
            "normalized-text.txt", b"source"
        )
        self.release_units = self._write_bytes(
            "unit-index.csv", b"source_id,unit_id,norm_start,norm_end\n"
        )
        self.release_claims = self._write_bytes(
            "claims.accepted.jsonl", b"{}\n"
        )
        self.release_database = self._write_bytes(
            "knowledge.sqlite3", b"sqlite"
        )
        self.release_index_report = self._write_json(
            "knowledge.report.json", {"index": "report"}
        )
        self.release_gold = self._write_bytes(
            "gold-release.jsonl", b"{}\n"
        )
        self.release_report = self._write_json(
            "release-report.json",
            {
                "policy_profile": "release",
                "case_count": 108,
                "passed": True,
                "may_certify_release": True,
                "may_freeze": False,
                "blockers": [],
                "report_id": self.REPORT_ID,
            },
        )
        self.release_verification = self._write_json(
            "release-verification.json",
            self.benchmark_verification.to_dict(),
        )

        self.release_files = {
            "normalized-text.txt": self.release_source,
            "unit-index.csv": self.release_units,
            "claims.accepted.jsonl": self.release_claims,
            "knowledge.sqlite3": self.release_database,
            "knowledge.report.json": self.release_index_report,
            "gold-release.jsonl": self.release_gold,
            "release-report.json": self.release_report,
            "release-verification.json": self.release_verification,
        }
        self.release_manifest = self._write_json(
            "release-manifest.json",
            {
                "case_count": 108,
                "report_id": self.REPORT_ID,
                "governance": {"may_freeze": False},
                "files": {
                    name: self._digest(path)
                    for name, path in self.release_files.items()
                },
            },
        )

        self.source_bundle = self._write_bytes(
            "source.bundle", b"git-bundle"
        )
        self.source_provenance = self._write_json(
            "source-provenance.json", {"schema_version": "test"}
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
        self.source_patch.stop()
        self.verify_patch.stop()
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

    def _digest(self, path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _rewrite_manifest_hash(self, name: str) -> None:
        payload = json.loads(
            self.release_manifest.read_text(encoding="utf-8")
        )
        payload["files"][name] = self._digest(self.release_files[name])
        self.release_manifest.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _specs(self) -> list[tuple[str, Path]]:
        role_by_name = {
            "normalized-text.txt": "release_source",
            "unit-index.csv": "release_units",
            "claims.accepted.jsonl": "release_claims",
            "knowledge.sqlite3": "release_database",
            "knowledge.report.json": "release_index_report",
            "gold-release.jsonl": "release_gold",
            "release-report.json": "release_report",
            "release-verification.json": "release_verification",
        }
        return [
            ("wheel", self.wheel),
            ("release_manifest", self.release_manifest),
            *(
                (role_by_name[name], path)
                for name, path in self.release_files.items()
            ),
            ("reproducible_build_report", self.reproducible),
            ("source_bundle", self.source_bundle),
            ("source_provenance", self.source_provenance),
            *(
                ("package_acceptance", path)
                for path in self.package_reports
            ),
            *(
                ("reproducible_wheel", path)
                for path in self.reproducible_wheels
            ),
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
        self.assertFalse(payload["technical_gate_passed"])
        self.assertTrue(payload["verification_required"])
        self.assertFalse(payload["may_freeze"])
        self.assertTrue(payload["requires_explicit_approval"])
        self.assertEqual(payload["status"], "prepared")
        self.assertFalse(payload["evidence"]["deep_verification_performed"])
        return path

    def test_prepare_is_lightweight_and_verify_is_strict(self) -> None:
        candidate = self._prepare()
        self.assertEqual(self.verify_mock.call_count, 0)
        self.assertEqual(self.source_mock.call_count, 0)

        result = verify_freeze_candidate(candidate, root=self.root)
        self.assertTrue(result["accepted"])
        self.assertTrue(result["technical_gate_passed"])
        self.assertFalse(result["may_freeze"])
        self.assertIn(
            "PREPARED_MANIFEST_RECOMPUTED",
            result["reason_codes"],
        )
        self.assertIn(
            "RELEASE_BENCHMARK_RECOMPUTED",
            result["reason_codes"],
        )
        self.assertIn(
            "REPRODUCIBLE_WHEELS_REHASHED",
            result["reason_codes"],
        )
        self.assertEqual(self.verify_mock.call_count, 1)
        self.assertEqual(self.source_mock.call_count, 1)

    def test_tampered_artifact_is_rejected(self) -> None:
        candidate = self._prepare()
        self.wheel.write_bytes(b"tampered")
        with self.assertRaisesRegex(FreezeError, "mismatch"):
            verify_freeze_candidate(candidate, root=self.root)

    def test_missing_required_python_acceptance_is_rejected(self) -> None:
        specs = [
            item
            for item in self._specs()
            if not (
                item[0] == "package_acceptance"
                and item[1] == self.package_reports[-1]
            )
        ]
        with self.assertRaisesRegex(
            FreezeError, "at least 3 package_acceptance"
        ):
            prepare_freeze_candidate(
                self.root,
                specs,
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_mismatched_package_wheel_hash_is_rejected(self) -> None:
        payload = json.loads(
            self.package_reports[0].read_text(encoding="utf-8")
        )
        payload["wheel_sha256"] = "0" * 64
        self.package_reports[0].write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        candidate = self._prepare()
        with self.assertRaisesRegex(
            FreezeError, "disagree on wheel SHA-256"
        ):
            verify_freeze_candidate(candidate, root=self.root)

    def test_phase7_cannot_self_grant_freeze(self) -> None:
        payload = json.loads(
            self.release_report.read_text(encoding="utf-8")
        )
        payload["may_freeze"] = True
        self.release_report.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        self._rewrite_manifest_hash("release-report.json")
        candidate = self._prepare()
        with self.assertRaisesRegex(
            FreezeError, "may_freeze must be False"
        ):
            verify_freeze_candidate(candidate, root=self.root)

    def test_forged_release_verification_is_rejected(self) -> None:
        payload = json.loads(
            self.release_verification.read_text(encoding="utf-8")
        )
        payload["accepted"] = False
        self.release_verification.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        self._rewrite_manifest_hash("release-verification.json")
        candidate = self._prepare()
        with self.assertRaisesRegex(
            FreezeError, "independent recomputation"
        ):
            verify_freeze_candidate(candidate, root=self.root)

    def test_manifest_hash_mismatch_is_rejected(self) -> None:
        self.release_gold.write_bytes(b"tampered-gold")
        candidate = self._prepare()
        with self.assertRaisesRegex(
            FreezeError, "release manifest hash mismatch"
        ):
            verify_freeze_candidate(candidate, root=self.root)

    def test_missing_second_reproducible_wheel_is_rejected(self) -> None:
        specs = [
            item
            for item in self._specs()
            if item != (
                "reproducible_wheel",
                self.reproducible_wheels[-1],
            )
        ]
        with self.assertRaisesRegex(
            FreezeError, "at least 2 reproducible_wheel"
        ):
            prepare_freeze_candidate(
                self.root,
                specs,
                release_version=self.VERSION,
                source_commit=self.SOURCE_COMMIT,
                source_date_epoch=1700000000,
            )

    def test_modified_second_reproducible_wheel_is_rejected(self) -> None:
        self.reproducible_wheels[-1].write_bytes(b"different")
        payload = json.loads(
            self.reproducible.read_text(encoding="utf-8")
        )
        payload["build_sha256"][-1] = self._digest(
            self.reproducible_wheels[-1]
        )
        self.reproducible.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        candidate = self._prepare()
        with self.assertRaisesRegex(
            FreezeError, "not byte-identical"
        ):
            verify_freeze_candidate(candidate, root=self.root)

    def test_explicit_approval_creates_and_verifies_seal(self) -> None:
        candidate = self._prepare()
        candidate_payload = json.loads(
            candidate.read_text(encoding="utf-8")
        )
        approval = self._write_json(
            "approval.json",
            {
                "schema_version": FREEZE_APPROVAL_SCHEMA_VERSION,
                "candidate_id": candidate_payload["candidate_id"],
                "release_version": self.VERSION,
                "source_commit": self.SOURCE_COMMIT,
                "approver": "release-owner",
                "decision": "approve",
                "statement":
                    "I approve this exact technical candidate for freezing.",
                "approved_at": "2026-07-21T05:00:00Z",
            },
        )
        seal = self.root / "freeze-seal.json"
        payload = seal_freeze_candidate(
            candidate, approval, seal, root=self.root
        )
        self.assertTrue(payload["may_freeze"])
        verification = verify_freeze_seal(
            seal, candidate, approval, root=self.root
        )
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
        with self.assertRaisesRegex(
            FreezeError, "candidate_id does not match"
        ):
            seal_freeze_candidate(
                candidate,
                approval,
                self.root / "freeze-seal.json",
                root=self.root,
            )

    def test_unknown_approval_fields_are_rejected(self) -> None:
        candidate = self._prepare()
        candidate_payload = json.loads(
            candidate.read_text(encoding="utf-8")
        )
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

    def _rewrite_candidate_id(
        self, payload: dict[str, object]
    ) -> None:
        core = dict(payload)
        core.pop("candidate_id", None)
        canonical = json.dumps(
            core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload["candidate_id"] = (
            "freeze_candidate_"
            + sha256(canonical.encode("utf-8")).hexdigest()[:24]
        )

    def test_verify_rejects_malformed_source_commit(self) -> None:
        candidate = self._prepare()
        payload = json.loads(
            candidate.read_text(encoding="utf-8")
        )
        payload["source_commit"] = "not-a-git-sha"
        self._rewrite_candidate_id(payload)
        candidate.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            FreezeError, "lowercase 40-character Git SHA"
        ):
            verify_freeze_candidate(candidate, root=self.root)

    def test_verify_rejects_negative_source_epoch(self) -> None:
        candidate = self._prepare()
        payload = json.loads(
            candidate.read_text(encoding="utf-8")
        )
        payload["source_date_epoch"] = -1
        self._rewrite_candidate_id(payload)
        candidate.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            FreezeError, "non-negative integer"
        ):
            verify_freeze_candidate(candidate, root=self.root)


if __name__ == "__main__":
    unittest.main()
