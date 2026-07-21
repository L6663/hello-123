"""Git-backed source provenance for Phase 8 freeze candidates.

The source bundle carries the claimed commit. Verification clones that bundle,
checks the commit object exists, compares every runtime package file in the wheel
with the same path at the claimed commit, checks package version metadata, and
binds ``SOURCE_DATE_EPOCH`` to wheel ZIP timestamps.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Mapping
import zipfile

SOURCE_PROVENANCE_SCHEMA_VERSION = "tkr-source-provenance-v1"


class SourceProvenanceError(ValueError):
    """Raised when source provenance cannot be established."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_path(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _run_git(*args: str, cwd: Path | None = None) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise SourceProvenanceError("git executable is required for source verification")
    try:
        completed = subprocess.run(
            [executable, *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise SourceProvenanceError(f"git command failed: {detail}") from exc
    return completed.stdout


def _expected_zip_timestamp(source_date_epoch: int) -> tuple[int, int, int, int, int, int]:
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise SourceProvenanceError("source_date_epoch must be a non-negative integer")
    # ZIP cannot represent dates before 1980 and stores seconds in two-second units.
    fields = list(time.gmtime(max(source_date_epoch, 315532800))[:6])
    fields[5] -= fields[5] % 2
    return tuple(fields)  # type: ignore[return-value]


def _wheel_runtime_records(
    wheel_path: Path,
) -> tuple[dict[str, bytes], str, tuple[int, int, int, int, int, int]]:
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            runtime_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("tkr/")
                and not name.endswith("/")
                and "__pycache__" not in name
            )
            if not runtime_names:
                raise SourceProvenanceError("wheel contains no tkr runtime files")
            runtime = {name: archive.read(name) for name in runtime_names}
            metadata_names = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise SourceProvenanceError("wheel must contain exactly one METADATA file")
            metadata = archive.read(metadata_names[0]).decode("utf-8")
            version_match = re.search(r"(?m)^Version:\s*(\S+)\s*$", metadata)
            if not version_match:
                raise SourceProvenanceError("wheel METADATA does not contain Version")
            timestamps = {
                info.date_time
                for info in archive.infolist()
                if not info.is_dir()
            }
            if len(timestamps) != 1:
                raise SourceProvenanceError("wheel entries do not share one build timestamp")
            timestamp = next(iter(timestamps))
    except (OSError, zipfile.BadZipFile, UnicodeError) as exc:
        raise SourceProvenanceError(f"invalid wheel: {wheel_path}: {exc}") from exc
    return runtime, version_match.group(1), timestamp


def _runtime_logical_sha256(runtime: Mapping[str, bytes]) -> str:
    records = [
        {"path": path, "sha256": sha256(content).hexdigest()}
        for path, content in sorted(runtime.items())
    ]
    return sha256(_canonical_json(records).encode("utf-8")).hexdigest()


def build_source_provenance(
    source_root: str | Path,
    bundle_path: str | Path,
    provenance_path: str | Path,
    *,
    source_commit: str,
    source_date_epoch: int,
    wheel_path: str | Path,
) -> dict[str, object]:
    """Create a Git bundle and provenance record for an exact clean checkout."""

    root = Path(source_root).resolve()
    bundle = Path(bundle_path).resolve()
    provenance = Path(provenance_path).resolve()
    wheel = Path(wheel_path).resolve()
    if not root.is_dir():
        raise SourceProvenanceError(f"source root is not a directory: {root}")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise SourceProvenanceError("source_commit must be a lowercase 40-character Git SHA")
    actual_commit = _run_git("rev-parse", "HEAD", cwd=root).decode("ascii").strip()
    if actual_commit != source_commit:
        raise SourceProvenanceError(
            f"source checkout HEAD mismatch: {actual_commit} != {source_commit}"
        )
    tracked_changes = _run_git(
        "status", "--porcelain", "--untracked-files=no", cwd=root
    ).decode("utf-8")
    if tracked_changes.strip():
        raise SourceProvenanceError("source checkout contains tracked modifications")

    bundle.parent.mkdir(parents=True, exist_ok=True)
    if bundle.exists():
        bundle.unlink()
    _run_git("bundle", "create", str(bundle), "HEAD", cwd=root)
    if not bundle.is_file():
        raise SourceProvenanceError("git bundle was not created")

    runtime, wheel_version, wheel_timestamp = _wheel_runtime_records(wheel)
    expected_timestamp = _expected_zip_timestamp(source_date_epoch)
    if wheel_timestamp != expected_timestamp:
        raise SourceProvenanceError(
            f"wheel timestamp does not match source_date_epoch: "
            f"{wheel_timestamp} != {expected_timestamp}"
        )

    payload = {
        "schema_version": SOURCE_PROVENANCE_SCHEMA_VERSION,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "source_bundle_sha256": _sha256_path(bundle),
        "wheel_sha256": _sha256_path(wheel),
        "wheel_version": wheel_version,
        "wheel_timestamp_utc": list(wheel_timestamp),
        "runtime_file_count": len(runtime),
        "runtime_files_sha256": _runtime_logical_sha256(runtime),
    }
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def verify_source_provenance(
    bundle_path: str | Path,
    provenance_path: str | Path,
    wheel_path: str | Path,
    *,
    source_commit: str,
    source_date_epoch: int,
    release_version: str,
) -> dict[str, object]:
    """Verify the claimed commit, wheel runtime files, version, and build epoch."""

    bundle = Path(bundle_path).resolve()
    provenance_file = Path(provenance_path).resolve()
    wheel = Path(wheel_path).resolve()
    try:
        payload = json.loads(provenance_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceProvenanceError(f"invalid source provenance: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceProvenanceError("source provenance must be a JSON object")
    expected_keys = {
        "schema_version",
        "source_commit",
        "source_date_epoch",
        "source_bundle_sha256",
        "wheel_sha256",
        "wheel_version",
        "wheel_timestamp_utc",
        "runtime_file_count",
        "runtime_files_sha256",
    }
    if set(payload) != expected_keys:
        raise SourceProvenanceError("source provenance keys mismatch")
    if payload["schema_version"] != SOURCE_PROVENANCE_SCHEMA_VERSION:
        raise SourceProvenanceError("unsupported source provenance schema")
    if payload["source_commit"] != source_commit:
        raise SourceProvenanceError("source provenance commit mismatch")
    if payload["source_date_epoch"] != source_date_epoch:
        raise SourceProvenanceError("source provenance epoch mismatch")
    if payload["source_bundle_sha256"] != _sha256_path(bundle):
        raise SourceProvenanceError("source bundle SHA-256 mismatch")
    if payload["wheel_sha256"] != _sha256_path(wheel):
        raise SourceProvenanceError("source provenance wheel SHA-256 mismatch")

    runtime, wheel_version, wheel_timestamp = _wheel_runtime_records(wheel)
    expected_timestamp = _expected_zip_timestamp(source_date_epoch)
    if wheel_timestamp != expected_timestamp:
        raise SourceProvenanceError("wheel timestamp does not match source_date_epoch")
    if payload["wheel_timestamp_utc"] != list(wheel_timestamp):
        raise SourceProvenanceError("source provenance wheel timestamp mismatch")
    if payload["wheel_version"] != wheel_version or wheel_version != release_version:
        raise SourceProvenanceError("wheel version does not match release version")
    if payload["runtime_file_count"] != len(runtime):
        raise SourceProvenanceError("source provenance runtime file count mismatch")
    if payload["runtime_files_sha256"] != _runtime_logical_sha256(runtime):
        raise SourceProvenanceError("source provenance runtime hash mismatch")

    with tempfile.TemporaryDirectory() as temporary:
        repository = Path(temporary) / "source.git"
        _run_git("clone", "--bare", str(bundle), str(repository))
        object_type = _run_git(
            "-C", str(repository), "cat-file", "-t", source_commit
        ).decode("ascii").strip()
        if object_type != "commit":
            raise SourceProvenanceError("claimed source object is not a commit")

        tracked_names = _run_git(
            "-C",
            str(repository),
            "ls-tree",
            "-r",
            "--name-only",
            source_commit,
            "--",
            "tkr",
        ).decode("utf-8").splitlines()
        tracked_runtime = sorted(
            name
            for name in tracked_names
            if name.startswith("tkr/") and "__pycache__" not in name
        )
        if tracked_runtime != sorted(runtime):
            raise SourceProvenanceError(
                "wheel runtime file set does not match claimed source commit"
            )
        for name in tracked_runtime:
            source_bytes = _run_git(
                "-C", str(repository), "show", f"{source_commit}:{name}"
            )
            if source_bytes != runtime[name]:
                raise SourceProvenanceError(
                    f"wheel runtime file differs from source commit: {name}"
                )

        pyproject = _run_git(
            "-C", str(repository), "show", f"{source_commit}:pyproject.toml"
        ).decode("utf-8")
        version_match = re.search(
            r'(?m)^version\s*=\s*"([^"]+)"\s*$', pyproject
        )
        if not version_match or version_match.group(1) != release_version:
            raise SourceProvenanceError(
                "pyproject version at source commit does not match release version"
            )

    return {
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "source_bundle_sha256": _sha256_path(bundle),
        "runtime_file_count": len(runtime),
        "runtime_files_sha256": _runtime_logical_sha256(runtime),
        "source_provenance_verified": True,
    }
