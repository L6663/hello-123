from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile

from tkr.source_provenance import (
    SourceProvenanceError,
    audit_wheel_installable_payload,
    build_source_provenance,
    verify_source_provenance,
)


@unittest.skipUnless(shutil.which("git"), "git executable is required")
class SourceProvenanceTests(unittest.TestCase):
    VERSION = "5.8.0a1"
    EPOCH = 1700000000
    DIST_INFO = "text_knowledge_reader_core-5.8.0a1.dist-info/"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init")
        self._git("config", "user.name", "TKR Test")
        self._git("config", "user.email", "tkr@example.invalid")

        (self.repository / "tkr").mkdir()
        self.runtime_bytes = b'__version__ = "5.8.0-alpha1"\n'
        (self.repository / "tkr" / "__init__.py").write_bytes(
            self.runtime_bytes
        )
        (self.repository / "pyproject.toml").write_text(
            '[project]\nname = "text-knowledge-reader-core"\n'
            f'version = "{self.VERSION}"\n',
            encoding="utf-8",
        )
        self._git("add", "tkr/__init__.py", "pyproject.toml")
        self._git("commit", "-m", "source snapshot")
        self.commit = self._git("rev-parse", "HEAD").strip()

        self.wheel = self.root / (
            "text_knowledge_reader_core-5.8.0a1-py3-none-any.whl"
        )
        timestamp = list(time.gmtime(self.EPOCH)[:6])
        timestamp[5] -= timestamp[5] % 2
        self.timestamp = tuple(timestamp)
        self._write_wheel()

        self.bundle = self.root / "source.bundle"
        self.provenance = self.root / "source-provenance.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            [str(shutil.which("git")), *args],
            cwd=self.repository,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout

    def _write_entry(
        self,
        archive: zipfile.ZipFile,
        name: str,
        content: str | bytes,
    ) -> None:
        info = zipfile.ZipInfo(name, self.timestamp)
        archive.writestr(info, content)

    def _write_wheel(
        self,
        *,
        entry_point_target: str = "tkr:main",
        extra_entries: dict[str, bytes] | None = None,
    ) -> None:
        with zipfile.ZipFile(self.wheel, "w") as archive:
            self._write_entry(
                archive, "tkr/__init__.py", self.runtime_bytes
            )
            self._write_entry(
                archive,
                f"{self.DIST_INFO}METADATA",
                "Metadata-Version: 2.1\n"
                "Name: text-knowledge-reader-core\n"
                f"Version: {self.VERSION}\n",
            )
            self._write_entry(
                archive,
                f"{self.DIST_INFO}WHEEL",
                "Wheel-Version: 1.0\n"
                "Generator: test\n"
                "Root-Is-Purelib: true\n"
                "Tag: py3-none-any\n",
            )
            self._write_entry(
                archive,
                f"{self.DIST_INFO}entry_points.txt",
                "[console_scripts]\n"
                f"tkr-test = {entry_point_target}\n",
            )
            self._write_entry(
                archive,
                f"{self.DIST_INFO}top_level.txt",
                "tkr\n",
            )
            self._write_entry(
                archive,
                f"{self.DIST_INFO}RECORD",
                "",
            )
            for name, payload in (extra_entries or {}).items():
                self._write_entry(archive, name, payload)

    def _build(self) -> None:
        build_source_provenance(
            self.repository,
            self.bundle,
            self.provenance,
            source_commit=self.commit,
            source_date_epoch=self.EPOCH,
            wheel_path=self.wheel,
        )

    def test_build_and_verify_source_provenance(self) -> None:
        self._build()
        result = verify_source_provenance(
            self.bundle,
            self.provenance,
            self.wheel,
            source_commit=self.commit,
            source_date_epoch=self.EPOCH,
            release_version=self.VERSION,
        )
        self.assertTrue(result["source_provenance_verified"])
        self.assertTrue(result["installable_payload_policy_verified"])
        self.assertEqual(result["source_commit"], self.commit)
        self.assertEqual(result["runtime_file_count"], 1)

    def test_different_claimed_commit_is_rejected(self) -> None:
        self._build()
        with self.assertRaisesRegex(
            SourceProvenanceError, "commit mismatch"
        ):
            verify_source_provenance(
                self.bundle,
                self.provenance,
                self.wheel,
                source_commit="b" * 40,
                source_date_epoch=self.EPOCH,
                release_version=self.VERSION,
            )

    def test_modified_wheel_is_rejected(self) -> None:
        self._build()
        self._write_wheel(extra_entries={"tampered.txt": b"tampered"})
        with self.assertRaisesRegex(
            SourceProvenanceError, "wheel SHA-256 mismatch"
        ):
            verify_source_provenance(
                self.bundle,
                self.provenance,
                self.wheel,
                source_commit=self.commit,
                source_date_epoch=self.EPOCH,
                release_version=self.VERSION,
            )

    def test_wrong_epoch_is_rejected(self) -> None:
        self._build()
        with self.assertRaisesRegex(
            SourceProvenanceError, "epoch mismatch"
        ):
            verify_source_provenance(
                self.bundle,
                self.provenance,
                self.wheel,
                source_commit=self.commit,
                source_date_epoch=self.EPOCH + 2,
                release_version=self.VERSION,
            )

    def test_top_level_sitecustomize_is_rejected(self) -> None:
        self._write_wheel(
            extra_entries={"sitecustomize.py": b"raise SystemExit\n"}
        )
        violations = audit_wheel_installable_payload(self.wheel)
        self.assertTrue(
            any("unexpected installable wheel entry" in item for item in violations)
        )
        with self.assertRaisesRegex(
            SourceProvenanceError, "unexpected installable wheel entry"
        ):
            self._build()

    def test_top_level_pth_is_rejected(self) -> None:
        self._write_wheel(extra_entries={"execute.pth": b"import evil\n"})
        violations = audit_wheel_installable_payload(self.wheel)
        self.assertTrue(any("execute.pth" in item for item in violations))

    def test_entry_point_outside_tkr_is_rejected(self) -> None:
        self._write_wheel(entry_point_target="evil_module:main")
        violations = audit_wheel_installable_payload(self.wheel)
        self.assertTrue(
            any("unbound module" in item for item in violations)
        )
        with self.assertRaisesRegex(
            SourceProvenanceError, "unbound module"
        ):
            self._build()


if __name__ == "__main__":
    unittest.main()
