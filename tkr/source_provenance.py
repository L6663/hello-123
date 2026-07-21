"""Git-backed source provenance for Phase 8 freeze candidates.

The source bundle carries the claimed commit. Verification clones that bundle,
checks the commit object exists, compares every runtime package file in the wheel
with the same path at the claimed commit, rejects unbound installable payloads,
checks package metadata, and binds ``SOURCE_DATE_EPOCH`` to ZIP timestamps.
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
_ALLOWED_DIST_INFO_FILES = {
    "METADATA",
    "WHEEL",
    "entry_points.txt",
    "top_level.txt",
    "RECORD",
}


class SourceProvenanceError(ValueError):
    """Raised when source provenance cannot be established."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_path(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _run_git(*args: str, cwd: Path | None = None) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise SourceProvenanceError(
            "git executable is required for source verification"
        )
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


def _expected_zip_timestamp(
    source_date_epoch: int,
) -> tuple[int, int, int, int, int, int]:
    if (
        not isinstance(source_date_epoch, int)
        or isinstance(source_date_epoch, bool)
        or source_date_epoch < 0
    ):
        raise SourceProvenanceError(
            "source_date_epoch must be a non-negative integer"
        )
    fields = list(time.gmtime(max(source_date_epoch, 315532800))[:6])
    fields[5] -= fields[5] % 2
    return tuple(fields)  # type: ignore[return-value]


def _unsafe_archive_name(name: str) -> bool:
    path = Path(name)
    return (
        not name
        or name.startswith(("/", "\\"))
        or "\\" in name
        or any(part in {"", ".", ".."} for part in path.parts)
    )


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def _entry_point_violations(content: str) -> list[str]:
    violations: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "[")):
            continue
        if "=" not in line:
            violations.append(f"malformed entry point: {line}")
            continue
        target = line.split("=", 1)[1].strip().split("[", 1)[0].strip()
        module = target.split(":", 1)[0].strip()
        if module != "tkr" and not module.startswith("tkr."):
            violations.append(f"entry point targets unbound module: {module}")
    return violations


def _audit_archive(archive: zipfile.ZipFile) -> tuple[str, tuple[str, ...]]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    violations: list[str] = []

    if len(names) != len(set(names)):
        violations.append("wheel contains duplicate archive paths")
    for info in infos:
        if _unsafe_archive_name(info.filename):
            violations.append(f"unsafe wheel path: {info.filename}")
        if _is_symlink(info):
            violations.append(f"wheel symlink is not allowed: {info.filename}")

    metadata_names = [
        name for name in names if name.endswith(".dist-info/METADATA")
    ]
    if len(metadata_names) != 1:
        violations.append("wheel must contain exactly one METADATA file")
        dist_info_prefix = ""
    else:
        dist_info_prefix = metadata_names[0][:-len("METADATA")]

    if dist_info_prefix:
        for name in names:
            if name.endswith("/"):
                continue
            if name.startswith("tkr/"):
                continue
            if not name.startswith(dist_info_prefix):
                violations.append(f"unexpected installable wheel entry: {name}")
                continue
            relative = name[len(dist_info_prefix):]
            if (
                relative not in _ALLOWED_DIST_INFO_FILES
                and not relative.startswith("licenses/")
            ):
                violations.append(f"unexpected dist-info entry: {name}")

        required_metadata = {
            f"{dist_info_prefix}{name}" for name in _ALLOWED_DIST_INFO_FILES
        }
        missing = sorted(required_metadata - set(names))
        violations.extend(f"missing wheel metadata entry: {name}" for name in missing)

        entry_points_name = f"{dist_info_prefix}entry_points.txt"
        if entry_points_name in names:
            try:
                entry_points = archive.read(entry_points_name).decode("utf-8")
            except UnicodeError:
                violations.append("entry_points.txt is not UTF-8")
            else:
                violations.extend(_entry_point_violations(entry_points))

        top_level_name = f"{dist_info_prefix}top_level.txt"
        if top_level_name in names:
            try:
                top_levels = {
                    line.strip()
                    for line in archive.read(top_level_name)
                    .decode("utf-8")
                    .splitlines()
                    if line.strip()
                }
            except UnicodeError:
                violations.append("top_level.txt is not UTF-8")
            else:
                if top_levels != {"tkr"}:
                    violations.append(
                        f"wheel top-level packages must be exactly ['tkr']: "
                        f"{sorted(top_levels)}"
                    )

        wheel_name = f"{dist_info_prefix}WHEEL"
        if wheel_name in names:
            try:
                wheel_metadata = archive.read(wheel_name).decode("utf-8")
            except UnicodeError:
                violations.append("WHEEL metadata is not UTF-8")
            else:
                if not re.search(
                    r"(?mi)^Root-Is-Purelib:\s*true\s*$", wheel_metadata
                ):
                    violations.append("wheel must declare Root-Is-Purelib: true")
                if not re.search(
                    r"(?mi)^Tag:\s*py3-none-any\s*$", wheel_metadata
                ):
                    violations.append("wheel must declare Tag: py3-none-any")

    return dist_info_prefix, tuple(dict.fromkeys(violations))


def audit_wheel_installable_payload(
    wheel_path: str | Path,
) -> tuple[str, ...]:
    """Return policy violations for installable wheel entries and entry points."""

    wheel = Path(wheel_path)
    try:
        with zipfile.ZipFile(wheel) as archive:
            _, violations = _audit_archive(archive)
            return violations
    except (OSError, zipfile.BadZipFile) as exc:
        return (f"invalid wheel archive: {exc}",)


def _wheel_runtime_records(
    wheel_path: Path,
) -> tuple[dict[str, bytes], str, tuple[int, int, int, int, int, int]]:
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            dist_info_prefix, violations = _audit_archive(archive)
            if violations:
                raise SourceProvenanceError(
                    "wheel installable payload policy failed: "
                    + "; ".join(violations)
                )
            runtime_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("tkr/")
                and not name.endswith("/")
                and "__pycache__" not in name
            )
            if not runtime_names:
                raise SourceProvenanceError(
                    "wheel contains no tkr runtime files"
                )
            runtime = {name: archive.read(name) for name in runtime_names}
            metadata = archive.read(
                f"{dist_info_prefix}METADATA"
            ).decode("utf-8")
            version_match = re.search(
                r"(?m)^Version:\s*(\S+)\s*$", metadata
            )
            if not version_match:
                raise SourceProvenanceError(
                    "wheel METADATA does not contain Version"
                )
            timestamps = {
                info.date_time
                for info in archive.infolist()
                if not info.is_dir()
            }
            if len(timestamps) != 1:
                raise SourceProvenanceError(
                    "wheel entries do not share one build timestamp"
                )
            timestamp = next(iter(timestamps))
    except (OSError, zipfile.BadZipFile, UnicodeError) as exc:
        raise SourceProvenanceError(
            f"invalid wheel: {wheel_path}: {exc}"
        ) from exc
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
        raise SourceProvenanceError(
            f"source root is not a directory: {root}"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise SourceProvenanceError(
            "source_commit must be a lowercase 40-character Git SHA"
        )
    actual_commit = _run_git(
        "rev-parse", "HEAD", cwd=root
    ).decode("ascii").strip()
    if actual_commit != source_commit:
        raise SourceProvenanceError(
            f"source checkout HEAD mismatch: {actual_commit} != {source_commit}"
        )
    tracked_changes = _run_git(
        "status", "--porcelain", "--untracked-files=no", cwd=root
    ).decode("utf-8")
    if tracked_changes.strip():
        raise SourceProvenanceError(
            "source checkout contains tracked modifications"
        )

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
            "wheel timestamp does not match source_date_epoch: "
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
    """Verify the claimed commit and the complete installable wheel payload."""

    bundle = Path(bundle_path).resolve()
    provenance_file = Path(provenance_path).resolve()
    wheel = Path(wheel_path).resolve()
    try:
        payload = json.loads(
            provenance_file.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceProvenanceError(
            f"invalid source provenance: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SourceProvenanceError(
            "source provenance must be a JSON object"
        )
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
        raise SourceProvenanceError(
            "unsupported source provenance schema"
        )
    if payload["source_commit"] != source_commit:
        raise SourceProvenanceError("source provenance commit mismatch")
    if payload["source_date_epoch"] != source_date_epoch:
        raise SourceProvenanceError("source provenance epoch mismatch")
    if payload["source_bundle_sha256"] != _sha256_path(bundle):
        raise SourceProvenanceError("source bundle SHA-256 mismatch")
    if payload["wheel_sha256"] != _sha256_path(wheel):
        raise SourceProvenanceError(
            "source provenance wheel SHA-256 mismatch"
        )

    runtime, wheel_version, wheel_timestamp = _wheel_runtime_records(wheel)
    expected_timestamp = _expected_zip_timestamp(source_date_epoch)
    if wheel_timestamp != expected_timestamp:
        raise SourceProvenanceError(
            "wheel timestamp does not match source_date_epoch"
        )
    if payload["wheel_timestamp_utc"] != list(wheel_timestamp):
        raise SourceProvenanceError(
            "source provenance wheel timestamp mismatch"
        )
    if (
        payload["wheel_version"] != wheel_version
        or wheel_version != release_version
    ):
        raise SourceProvenanceError(
            "wheel version does not match release version"
        )
    if payload["runtime_file_count"] != len(runtime):
        raise SourceProvenanceError(
            "source provenance runtime file count mismatch"
        )
    if payload["runtime_files_sha256"] != _runtime_logical_sha256(runtime):
        raise SourceProvenanceError(
            "source provenance runtime hash mismatch"
        )

    with tempfile.TemporaryDirectory() as temporary:
        repository = Path(temporary) / "source.git"
        _run_git("clone", "--bare", str(bundle), str(repository))
        object_type = _run_git(
            "-C", str(repository), "cat-file", "-t", source_commit
        ).decode("ascii").strip()
        if object_type != "commit":
            raise SourceProvenanceError(
                "claimed source object is not a commit"
            )

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
            "-C",
            str(repository),
            "show",
            f"{source_commit}:pyproject.toml",
        ).decode("utf-8")
        version_match = re.search(
            r'(?m)^version\s*=\s*"([^"]+)"\s*$', pyproject
        )
        if (
            not version_match
            or version_match.group(1) != release_version
        ):
            raise SourceProvenanceError(
                "pyproject version at source commit does not match release version"
            )

    return {
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "source_bundle_sha256": _sha256_path(bundle),
        "runtime_file_count": len(runtime),
        "runtime_files_sha256": _runtime_logical_sha256(runtime),
        "installable_payload_policy_verified": True,
        "source_provenance_verified": True,
    }
