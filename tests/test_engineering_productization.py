from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import time
import unittest

from tkr.engineering import (
    ENGINEERING_PROFILE_SCHEMA_VERSION,
    build_engineered_project,
    build_key,
    load_engineering_profile,
    profile_sha256,
    validate_engineering_paths,
)
from tkr.knowledge_models import KnowledgeProjectError
from tkr.project_cli import main as project_main
from tkr.project_security import (
    answer_secure_knowledge_project,
    build_secure_engineered_project,
    verify_secure_knowledge_answer,
    verify_secure_knowledge_project,
)
from tkr.skill_audit import audit_skill_layout, doctor_environment, profile_catalog
from tkr.skill_cli import main as skill_main

CORPUS = (
    "玄霄又称青帝。\n"
    "陆川击败韩岳。\n"
    "听雪楼位于北境。\n"
    "守门人允许陆川进入内殿。\n"
    "剑阵共有十二柄飞剑。\n"
    "大战发生于2026年7月22日。\n"
)
ROOT = Path(__file__).resolve().parents[1]


class ProfileAndLayoutTests(unittest.TestCase):
    def test_balanced_profile_loads(self):
        profile = load_engineering_profile("balanced")
        self.assertEqual(profile.schema_version, ENGINEERING_PROFILE_SCHEMA_VERSION)
        self.assertEqual(profile.index_mode, "review")
        self.assertTrue(profile.cache_enabled)

    def test_builtin_profiles_have_distinct_hashes(self):
        rows = [load_engineering_profile(name) for name in ("balanced", "strict", "high-recall")]
        self.assertEqual(len({profile_sha256(item) for item in rows}), 3)

    def test_build_key_is_deterministic_and_profile_sensitive(self):
        source_hash = "a" * 64
        balanced = load_engineering_profile("balanced")
        strict = load_engineering_profile("strict")
        self.assertEqual(build_key(source_hash, balanced), build_key(source_hash, balanced))
        self.assertNotEqual(build_key(source_hash, balanced), build_key(source_hash, strict))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(KnowledgeProjectError):
            load_engineering_profile("profile-that-does-not-exist")

    def test_profile_unknown_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            payload = load_engineering_profile("balanced").to_dict()
            payload["unexpected"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(KnowledgeProjectError):
                load_engineering_profile(path)

    def test_profile_filename_name_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wrong.json"
            path.write_text(
                json.dumps(load_engineering_profile("balanced").to_dict()),
                encoding="utf-8",
            )
            with self.assertRaises(KnowledgeProjectError):
                load_engineering_profile(path)

    def test_profile_catalog_contains_all_builtins(self):
        names = {str(item["name"]) for item in profile_catalog()}
        self.assertTrue({"balanced", "strict", "high-recall"}.issubset(names))

    def test_source_checkout_skill_audit_passes(self):
        report = audit_skill_layout(ROOT)
        self.assertTrue(report.passed, [item.to_dict() for item in report.findings])
        self.assertGreaterEqual(report.profile_count, 3)
        self.assertGreaterEqual(report.schema_count, 20)

    def test_empty_skill_root_fails_audit(self):
        with tempfile.TemporaryDirectory() as td:
            report = audit_skill_layout(td)
            self.assertFalse(report.passed)
            self.assertGreater(report.finding_count, 0)

    def test_environment_doctor_passes_source_checkout(self):
        report = doctor_environment(ROOT)
        self.assertTrue(report.passed, [item.to_dict() for item in report.checks])

    def test_skill_cli_profiles_and_audit(self):
        with tempfile.TemporaryDirectory() as td:
            profile_out = Path(td) / "profiles.json"
            audit_out = Path(td) / "audit.json"
            self.assertEqual(skill_main(["profiles", "--output", str(profile_out)]), 0)
            self.assertEqual(skill_main(["audit", "--root", str(ROOT), "--output", str(audit_out)]), 0)
            self.assertIn("balanced", profile_out.read_text(encoding="utf-8"))
            self.assertTrue(json.loads(audit_out.read_text(encoding="utf-8"))["passed"])


class EngineeringPathTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        path = root / "corpus.txt"
        path.write_text(CORPUS, encoding="utf-8")
        return path

    def test_output_must_not_contain_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source(root)
            with self.assertRaises(KnowledgeProjectError):
                validate_engineering_paths(source, root, root.parent / "state")

    def test_output_and_state_must_not_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source(root)
            output = root / "project"
            with self.assertRaises(KnowledgeProjectError):
                validate_engineering_paths(source, output, output / "state")

    def test_symbolic_link_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source(root)
            link = root / "source-link.txt"
            try:
                link.symlink_to(source)
            except OSError:
                self.skipTest("symbolic links unavailable")
            with self.assertRaises(KnowledgeProjectError):
                validate_engineering_paths(link, root / "project", root / "state")

    def test_symbolic_link_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source(root)
            target = root / "target"
            target.mkdir()
            link = root / "project"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("symbolic links unavailable")
            with self.assertRaises(KnowledgeProjectError):
                validate_engineering_paths(source, link, root / "state")


class EngineeringBuildTests(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "corpus.txt"
        source.write_text(CORPUS, encoding="utf-8")
        return source, root / "project", root / "state"

    def _build(self, root: Path, **kwargs):
        source, output, state = self._paths(root)
        result = build_secure_engineered_project(
            source,
            output,
            state_directory=state,
            **kwargs,
        )
        return source, output, state, result

    def test_first_build_is_cache_miss_and_writes_completed_journal(self):
        with tempfile.TemporaryDirectory() as td:
            source, output, state, result = self._build(Path(td))
            self.assertEqual(result.cache_status, "miss")
            self.assertTrue(verify_secure_knowledge_project(output).valid)
            journal = json.loads((state / "build-state.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "completed")
            self.assertFalse(journal["may_accept_project"])
            self.assertFalse(journal["may_freeze"])

    def test_second_build_restores_verified_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            shutil.rmtree(output)
            second = build_secure_engineered_project(source, output, state_directory=state)
            self.assertEqual(second.cache_status, "hit")
            self.assertEqual(first.project_id, second.project_id)
            self.assertTrue(verify_secure_knowledge_project(output).valid)

    def test_tampered_cache_is_discarded_and_rebuilt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            shutil.rmtree(output)
            cached = next((state / "cache").glob("*/project/source/normalized-source.txt"))
            cached.write_text("tampered", encoding="utf-8")
            second = build_secure_engineered_project(source, output, state_directory=state)
            self.assertEqual(second.cache_status, "miss")
            self.assertIn("discarded_invalid_cache_entry", second.recovered_actions)
            self.assertTrue(verify_secure_knowledge_project(output).valid)

    def test_exact_existing_project_can_be_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            second = build_secure_engineered_project(
                source,
                output,
                state_directory=state,
                reuse_existing=True,
            )
            self.assertTrue(second.reused_existing_project)
            self.assertEqual(first.project_id, second.project_id)

    def test_existing_project_without_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            with self.assertRaises(KnowledgeProjectError):
                build_secure_engineered_project(source, output, state_directory=state)

    def test_changed_source_cannot_reuse_existing_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            source.write_text(CORPUS + "新增正文。\n", encoding="utf-8")
            with self.assertRaises(KnowledgeProjectError):
                build_secure_engineered_project(
                    source,
                    output,
                    state_directory=state,
                    reuse_existing=True,
                )

    def test_force_replacement_changes_project_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            source.write_text(CORPUS.replace("韩岳", "韩山"), encoding="utf-8")
            second = build_secure_engineered_project(
                source,
                output,
                state_directory=state,
                replace_existing=True,
            )
            self.assertNotEqual(first.project_id, second.project_id)
            self.assertTrue(verify_secure_knowledge_project(output).valid)

    def test_cache_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state = self._paths(root)
            result = build_secure_engineered_project(
                source,
                output,
                state_directory=state,
                use_cache=False,
            )
            self.assertEqual(result.cache_status, "disabled")
            self.assertFalse((state / "cache").exists())

    def test_active_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state = self._paths(root)
            state.mkdir()
            (state / "build.lock").write_text("{}", encoding="utf-8")
            with self.assertRaises(KnowledgeProjectError):
                build_engineered_project(source, output, state_directory=state)

    def test_expired_dead_lock_can_be_recovered_explicitly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state = self._paths(root)
            state.mkdir()
            lock = state / "build.lock"
            lock.write_text(
                json.dumps({"hostname": socket.gethostname(), "pid": 99999999}),
                encoding="utf-8",
            )
            old = time.time() - 30000
            os.utime(lock, (old, old))
            result = build_secure_engineered_project(
                source,
                output,
                state_directory=state,
                recover_stale_lock=True,
            )
            self.assertTrue(result.project_id)
            self.assertFalse(lock.exists())

    def test_orphaned_backup_is_restored_before_verified_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            backup = output.with_name(f".{output.name}.backup")
            output.replace(backup)
            second = build_secure_engineered_project(
                source,
                output,
                state_directory=state,
                reuse_existing=True,
            )
            self.assertIn("restored_orphaned_backup", second.recovered_actions)
            self.assertTrue(second.reused_existing_project)

    def test_old_temporary_build_directory_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, first = self._build(root)
            stale = output.parent / f".{output.name}.tmp-stale"
            stale.mkdir()
            old = time.time() - 100000
            os.utime(stale, (old, old))
            second = build_secure_engineered_project(
                source,
                output,
                state_directory=state,
                reuse_existing=True,
            )
            self.assertIn("removed_stale_build_directory", second.recovered_actions)
            self.assertFalse(stale.exists())

    def test_state_directory_remains_outside_immutable_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state, result = self._build(root)
            self.assertFalse((output / "build-state.json").exists())
            self.assertTrue((state / "build-state.json").exists())
            self.assertTrue(verify_secure_knowledge_project(output).valid)

    def test_clean_corpus_builds_with_strict_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output, state = self._paths(root)
            result = build_secure_engineered_project(
                source,
                output,
                state_directory=state,
                profile="strict",
            )
            self.assertEqual(result.project_report["index_mode"], "canonical")

    def test_corpus_without_typed_claims_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "corpus.txt"
            source.write_text("这里只有普通叙述，没有受支持的类型化关系。", encoding="utf-8")
            with self.assertRaises(KnowledgeProjectError):
                build_secure_engineered_project(source, root / "project", state_directory=root / "state")
            journal = json.loads((root / "state" / "build-state.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "failed")


class SecureProjectAndQueryTests(unittest.TestCase):
    def _build(self, root: Path):
        source = root / "corpus.txt"
        source.write_text(CORPUS, encoding="utf-8")
        output = root / "project"
        build_secure_engineered_project(source, output, state_directory=root / "state")
        return output

    def test_unexpected_project_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._build(Path(td))
            (project / "unexpected.txt").write_text("x", encoding="utf-8")
            result = verify_secure_knowledge_project(project)
            self.assertFalse(result.valid)
            self.assertIn("UNEXPECTED_PROJECT_FILE", result.reason_codes)

    def test_project_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._build(Path(td))
            link = project / "unsafe-link"
            try:
                link.symlink_to(project / "project-report.json")
            except OSError:
                self.skipTest("symbolic links unavailable")
            result = verify_secure_knowledge_project(project)
            self.assertFalse(result.valid)
            self.assertIn("SYMLINK_IN_PROJECT", result.reason_codes)

    def test_manifest_parent_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._build(Path(td))
            path = project / "project-manifest.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["files"][0]["path"] = "../escape"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_secure_knowledge_project(project)
            self.assertFalse(result.valid)
            self.assertIn("MANIFEST_PATH_INVALID_OR_DUPLICATE", result.reason_codes)

    def test_supported_query_returns_citations(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._build(Path(td))
            packet = answer_secure_knowledge_project(project, "陆川击败了谁？")
            self.assertEqual(packet.qa_packet["decision"], "answered")
            self.assertGreater(len(packet.qa_packet["citations"]), 0)

    def test_unsupported_query_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._build(Path(td))
            packet = answer_secure_knowledge_project(project, "陆川为什么要击败韩岳？")
            self.assertEqual(packet.qa_packet["decision"], "refused_unsupported")

    def test_answer_packet_recomputes_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._build(Path(td))
            packet = answer_secure_knowledge_project(project, "听雪楼位于哪里？")
            result = verify_secure_knowledge_answer(project, packet.to_dict())
            self.assertTrue(result.accepted)

    def test_changed_answer_packet_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._build(Path(td))
            packet = answer_secure_knowledge_project(project, "听雪楼位于哪里？").to_dict()
            packet["qa_packet"]["answer_text"] = "伪造答案"
            result = verify_secure_knowledge_answer(project, packet)
            self.assertFalse(result.accepted)

    def test_unified_cli_build_verify_query_and_verify_answer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "corpus.txt"
            source.write_text(CORPUS, encoding="utf-8")
            project = root / "project"
            state = root / "state"
            answer = root / "answer.json"
            verification = root / "verification.json"
            self.assertEqual(
                project_main([
                    "build", str(source), "--outdir", str(project), "--state-dir", str(state),
                    "--profile", "balanced", "--no-cache",
                ]),
                0,
            )
            self.assertEqual(project_main(["verify", str(project), "--output", str(verification)]), 0)
            self.assertEqual(
                project_main(["query", str(project), "陆川击败了谁？", "--output", str(answer)]),
                0,
            )
            self.assertEqual(project_main(["verify-answer", str(project), str(answer)]), 0)
            self.assertTrue(json.loads(verification.read_text(encoding="utf-8"))["valid"])


if __name__ == "__main__":
    unittest.main()
