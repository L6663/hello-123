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
    build_source_provenance,
    verify_source_provenance,
)


@unittest.skipUnless(shutil.which("git"), "git executable is required")
class SourceProvenanceTests(unittest.TestCase):
    VERSION = "5.8.0a1"
    EPOCH = 1700000000

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
        with zipfile.ZipFile(self.wheel, "w") as archive:
            runtime_info = zipfile.ZipInfo(
                "tkr/__init__.py", tuple(timestamp)
            )
            archive.writestr(runtime_info, self.runtime_bytes)
            metadata_info = zipfile.ZipInfo(
                "text_knowledge_reader_core-5.8.0a1.dist-info/METADATA",
                tuple(timestamp),
            )
            archive.writestr(
                metadata_info,
                "Metadata-Version: 2.1\n"
                "Name: text-knowledge-reader-core\n"
                f"Version: {self.VERSION}\n",
            )

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
        with zipfile.ZipFile(self.wheel, "a") as archive:
            archive.writestr("tampered.txt", b"tampered")
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


if __name__ == "__main__":
    unittest.main()
