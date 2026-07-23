"""Stage 5 recoverable, cache-aware engineering runtime.

The mutable build state is always stored outside the immutable Stage 4 project.
A cache entry is reusable only after the complete project hash chain verifies and
its source, profile, and system identities match exactly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import socket
import sysconfig
import tempfile
import time
from typing import Mapping
from uuid import uuid4

from .hashing import sha256_file
from .knowledge_models import (
    KNOWLEDGE_SYSTEM_VERSION,
    KnowledgeProjectError,
    KnowledgeProjectPolicy,
)
from .knowledge_project import build_knowledge_project, verify_knowledge_project

ENGINEERING_PROFILE_SCHEMA_VERSION = "tkr-engineering-profile-v1"
ENGINEERING_BUILD_SCHEMA_VERSION = "tkr-engineering-build-result-v1"
ENGINEERING_STATE_SCHEMA_VERSION = "tkr-engineering-build-state-v1"
ENGINEERING_CACHE_SCHEMA_VERSION = "tkr-engineering-cache-v1"
ENGINEERING_VERSION = "6.0.0rc1-r3"
_MAX_PROFILE_BYTES = 64 * 1024
_MAX_STATE_BYTES = 2 * 1024 * 1024
_BUILD_POLICY_KEYS = (
    "index_mode",
    "max_candidates",
    "max_findings",
    "max_model_tasks",
    "max_clause_characters",
    "emit_model_tasks",
)


@dataclass(frozen=True, slots=True)
class EngineeringProfile:
    schema_version: str
    name: str
    description: str
    index_mode: str
    max_candidates: int
    max_findings: int
    max_model_tasks: int
    max_clause_characters: int
    emit_model_tasks: bool
    cache_enabled: bool
    lock_stale_seconds: int
    cleanup_stale_seconds: int

    def __post_init__(self) -> None:
        if self.schema_version != ENGINEERING_PROFILE_SCHEMA_VERSION:
            raise KnowledgeProjectError("engineering profile schema version mismatch")
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise KnowledgeProjectError("engineering profile name is invalid")
        if not self.description.strip():
            raise KnowledgeProjectError("engineering profile description is empty")
        if self.index_mode not in {"review", "canonical"}:
            raise KnowledgeProjectError("engineering profile index_mode is invalid")
        for field in (
            "max_candidates",
            "max_findings",
            "max_model_tasks",
            "max_clause_characters",
            "lock_stale_seconds",
            "cleanup_stale_seconds",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise KnowledgeProjectError(f"engineering profile {field} must be positive")
        if not isinstance(self.emit_model_tasks, bool) or not isinstance(self.cache_enabled, bool):
            raise KnowledgeProjectError("engineering profile boolean fields are invalid")
        if self.cleanup_stale_seconds < self.lock_stale_seconds:
            raise KnowledgeProjectError("cleanup_stale_seconds must not be below lock_stale_seconds")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def project_policy(self, *, reuse: bool = False, replace: bool = False) -> KnowledgeProjectPolicy:
        return KnowledgeProjectPolicy(
            index_mode=self.index_mode,
            max_candidates=self.max_candidates,
            max_findings=self.max_findings,
            max_model_tasks=self.max_model_tasks,
            max_clause_characters=self.max_clause_characters,
            emit_model_tasks=self.emit_model_tasks,
            reuse_verified_project=reuse,
            replace_existing_project=replace,
        )


@dataclass(frozen=True, slots=True)
class EngineeringBuildResult:
    schema_version: str
    engineering_version: str
    status: str
    source_sha256: str
    build_key: str
    profile_name: str
    profile_sha256: str
    project_directory: str
    state_directory: str
    project_id: str
    cache_status: str
    reused_existing_project: bool
    recovered_actions: tuple[str, ...]
    project_report: dict[str, object]
    project_acceptance_performed: bool = False
    may_accept_project: bool = False
    release_candidate: bool = False
    may_freeze: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["recovered_actions"] = list(self.recovered_actions)
        return payload


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_small_object(path: Path, label: str, limit: int) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise KnowledgeProjectError(f"{label} is not a safe regular file: {path}")
    if path.stat().st_size > limit:
        raise KnowledgeProjectError(f"{label} exceeds the size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KnowledgeProjectError(f"{label} must be a JSON object")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(_json_bytes(dict(payload)))
    temporary.replace(path)


def _profile_roots() -> tuple[Path, ...]:
    source_root = Path(__file__).resolve().parents[1] / "profiles"
    installed_root = (
        Path(sysconfig.get_paths()["data"]) / "share" / "text-knowledge-reader" / "profiles"
    )
    return tuple(dict.fromkeys((source_root, installed_root)))


def available_profile_paths() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for root in _profile_roots():
        if not root.is_dir() or root.is_symlink():
            continue
        for path in sorted(root.glob("*.json")):
            if path.is_file() and not path.is_symlink():
                result.setdefault(path.stem, path)
    return result


def load_engineering_profile(value: str | Path = "balanced") -> EngineeringProfile:
    requested = Path(value)
    if requested.exists() or requested.suffix.lower() == ".json" or len(requested.parts) > 1:
        path = requested
    else:
        paths = available_profile_paths()
        path = paths.get(str(value), Path())
        if not path:
            raise KnowledgeProjectError(f"unknown engineering profile: {value}")
    payload = _read_small_object(path, "engineering profile", _MAX_PROFILE_BYTES)
    expected = {
        "schema_version",
        "name",
        "description",
        "index_mode",
        "max_candidates",
        "max_findings",
        "max_model_tasks",
        "max_clause_characters",
        "emit_model_tasks",
        "cache_enabled",
        "lock_stale_seconds",
        "cleanup_stale_seconds",
    }
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        unexpected = sorted(set(payload) - expected)
        raise KnowledgeProjectError(
            f"engineering profile fields mismatch; missing={missing}, unexpected={unexpected}"
        )
    try:
        profile = EngineeringProfile(**payload)  # type: ignore[arg-type]
    except TypeError as exc:
        raise KnowledgeProjectError(f"engineering profile types are invalid: {exc}") from exc
    if path.stem not in {profile.name, "profile"} and requested.exists():
        raise KnowledgeProjectError("profile filename and declared name differ")
    return profile


def profile_sha256(profile: EngineeringProfile) -> str:
    return sha256(_canonical_json(profile.to_dict()).encode("utf-8")).hexdigest()


def build_key(source_sha256: str, profile: EngineeringProfile) -> str:
    payload = {
        "engineering_version": ENGINEERING_VERSION,
        "knowledge_system_version": KNOWLEDGE_SYSTEM_VERSION,
        "profile_sha256": profile_sha256(profile),
        "source_sha256": source_sha256,
    }
    return "bld_" + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:40]


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def _existing_symlink_component(path: Path) -> Path | None:
    absolute = path.absolute()
    candidates = list(reversed(absolute.parents)) + [absolute]
    for candidate in candidates:
        if candidate.exists() and candidate.is_symlink():
            return candidate
    return None


def validate_engineering_paths(
    source: str | Path,
    output: str | Path,
    state_directory: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    source_path = Path(source)
    output_path = Path(output)
    state_path = (
        Path(state_directory)
        if state_directory is not None
        else output_path.parent / f".{output_path.name}.tkr-state"
    )
    if source_path.is_symlink() or not source_path.is_file():
        raise KnowledgeProjectError("source must be a non-symlink regular file")
    if output_path.exists() and (output_path.is_symlink() or not output_path.is_dir()):
        raise KnowledgeProjectError("output must be a non-symlink directory when it exists")
    if state_path.exists() and (state_path.is_symlink() or not state_path.is_dir()):
        raise KnowledgeProjectError("state directory must be a non-symlink directory when it exists")
    for candidate, label in ((output_path.parent, "output parent"), (state_path.parent, "state parent")):
        symlink = _existing_symlink_component(candidate)
        if symlink is not None:
            raise KnowledgeProjectError(f"{label} contains a symlink component: {symlink}")
    source_real = source_path.resolve(strict=True)
    output_real = output_path.absolute()
    state_real = state_path.absolute()
    if source_real == output_real or _is_relative_to(source_real, output_real):
        raise KnowledgeProjectError("output directory must not contain the source file")
    if output_real == state_real or _is_relative_to(output_real, state_real) or _is_relative_to(state_real, output_real):
        raise KnowledgeProjectError("state directory and immutable project directory must not overlap")
    if len(str(output_real)) > 2048 or len(str(state_real)) > 2048:
        raise KnowledgeProjectError("engineering path exceeds the supported length")
    if any(len(part) > 240 for part in (*output_real.parts, *state_real.parts)):
        raise KnowledgeProjectError("engineering path component exceeds the supported length")
    return source_path, output_path, state_path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class _BuildLock:
    def __init__(
        self,
        state: Path,
        *,
        stale_seconds: int,
        recover_stale: bool,
        source_sha256: str,
        output: Path,
    ) -> None:
        self.path = state / "build.lock"
        self.stale_seconds = stale_seconds
        self.recover_stale = recover_stale
        self.source_sha256 = source_sha256
        self.output = output
        self.token = uuid4().hex

    def _recover(self) -> None:
        if not self.path.exists():
            return
        if self.path.is_symlink() or not self.path.is_file():
            raise KnowledgeProjectError("build lock is not a safe regular file")
        age = max(0.0, time.time() - self.path.stat().st_mtime)
        if not self.recover_stale or age < self.stale_seconds:
            raise KnowledgeProjectError("another build lock is active")
        payload = _read_small_object(self.path, "build lock", _MAX_STATE_BYTES)
        hostname = str(payload.get("hostname", ""))
        pid_value = payload.get("pid")
        pid = pid_value if isinstance(pid_value, int) and not isinstance(pid_value, bool) else -1
        if hostname == socket.gethostname() and _pid_alive(pid):
            raise KnowledgeProjectError("stale-lock recovery refused because the recorded process is alive")
        self.path.unlink()

    def __enter__(self) -> "_BuildLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._recover()
        payload = {
            "schema_version": ENGINEERING_STATE_SCHEMA_VERSION,
            "token": self.token,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at_utc": _utc_now(),
            "source_sha256": self.source_sha256,
            "output_directory": str(self.output.absolute()),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            raise KnowledgeProjectError("another build acquired the engineering lock") from exc
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_json_bytes(payload))
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            payload = _read_small_object(self.path, "build lock", _MAX_STATE_BYTES)
            if payload.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except Exception:
            pass


def _journal(
    state: Path,
    *,
    status: str,
    phase: str,
    source_sha256: str,
    key: str,
    profile: EngineeringProfile,
    output: Path,
    attempts: int,
    cache_status: str = "not_checked",
    recovered_actions: tuple[str, ...] = (),
    project_id: str = "",
    error: BaseException | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema_version": ENGINEERING_STATE_SCHEMA_VERSION,
        "engineering_version": ENGINEERING_VERSION,
        "status": status,
        "current_phase": phase,
        "updated_at_utc": _utc_now(),
        "source_sha256": source_sha256,
        "build_key": key,
        "profile_name": profile.name,
        "profile_sha256": profile_sha256(profile),
        "output_directory": str(output.absolute()),
        "attempts": attempts,
        "cache_status": cache_status,
        "recovered_actions": list(recovered_actions),
        "project_id": project_id,
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_freeze": False,
    }
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)[:1000]
    _atomic_json(state / "build-state.json", payload)


def _load_report(project: Path) -> dict[str, object]:
    return _read_small_object(project / "project-report.json", "project report", _MAX_STATE_BYTES)


def _policy_projection(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in _BUILD_POLICY_KEYS}


def _profile_policy_projection(profile: EngineeringProfile) -> dict[str, object]:
    policy = profile.project_policy().to_dict()
    return {key: policy.get(key) for key in _BUILD_POLICY_KEYS}


def _matches_project(project: Path, source_sha: str, profile: EngineeringProfile) -> bool:
    verification = verify_knowledge_project(project)
    if not verification.valid:
        return False
    report = _load_report(project)
    return (
        report.get("raw_source_sha256") == source_sha
        and _policy_projection(report.get("policy")) == _profile_policy_projection(profile)
    )


def _install_copy(source_project: Path, output: Path, replace: bool) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.cache-", dir=output.parent))
    shutil.rmtree(temporary)
    try:
        shutil.copytree(source_project, temporary, symlinks=False)
        verification = verify_knowledge_project(temporary)
        if not verification.valid:
            raise KnowledgeProjectError("cached project copy failed verification")
        if not output.exists():
            temporary.replace(output)
            return
        if not replace:
            raise KnowledgeProjectError("project directory exists and replacement was not requested")
        backup = output.with_name(f".{output.name}.backup")
        if backup.exists():
            if backup.is_symlink():
                raise KnowledgeProjectError("unsafe replacement backup path")
            shutil.rmtree(backup)
        output.replace(backup)
        try:
            temporary.replace(output)
        except Exception:
            if output.exists():
                shutil.rmtree(output, ignore_errors=True)
            backup.replace(output)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _cache_entry(state: Path, key: str) -> Path:
    return state / "cache" / key


def _cache_record(entry: Path) -> dict[str, object]:
    return _read_small_object(entry / "cache-record.json", "cache record", _MAX_STATE_BYTES)


def _cache_matches(entry: Path, source_sha: str, profile: EngineeringProfile, key: str) -> bool:
    try:
        record = _cache_record(entry)
        project = entry / "project"
        return (
            record.get("schema_version") == ENGINEERING_CACHE_SCHEMA_VERSION
            and record.get("engineering_version") == ENGINEERING_VERSION
            and record.get("knowledge_system_version") == KNOWLEDGE_SYSTEM_VERSION
            and record.get("build_key") == key
            and record.get("source_sha256") == source_sha
            and record.get("profile_sha256") == profile_sha256(profile)
            and _matches_project(project, source_sha, profile)
        )
    except Exception:
        return False


def _populate_cache(
    project: Path,
    state: Path,
    source_sha: str,
    profile: EngineeringProfile,
    key: str,
) -> None:
    cache_root = state / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    entry = _cache_entry(state, key)
    if entry.exists() and _cache_matches(entry, source_sha, profile, key):
        return
    if entry.exists():
        if entry.is_symlink():
            raise KnowledgeProjectError("cache entry is an unsafe symlink")
        shutil.rmtree(entry)
    temporary = Path(tempfile.mkdtemp(prefix=f".{key}.tmp-", dir=cache_root))
    try:
        shutil.copytree(project, temporary / "project", symlinks=False)
        if not _matches_project(temporary / "project", source_sha, profile):
            raise KnowledgeProjectError("new cache copy failed verification")
        _atomic_json(
            temporary / "cache-record.json",
            {
                "schema_version": ENGINEERING_CACHE_SCHEMA_VERSION,
                "engineering_version": ENGINEERING_VERSION,
                "knowledge_system_version": KNOWLEDGE_SYSTEM_VERSION,
                "created_at_utc": _utc_now(),
                "build_key": key,
                "source_sha256": source_sha,
                "profile_name": profile.name,
                "profile_sha256": profile_sha256(profile),
                "project_id": _load_report(project).get("project_id", ""),
                "project_acceptance_performed": False,
                "may_accept_project": False,
                "may_freeze": False,
            },
        )
        temporary.replace(entry)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def recover_engineering_workspace(
    output: Path,
    state: Path,
    *,
    stale_seconds: int,
) -> tuple[str, ...]:
    actions: list[str] = []
    backup = output.with_name(f".{output.name}.backup")
    if backup.exists():
        if backup.is_symlink() or not backup.is_dir():
            raise KnowledgeProjectError("replacement backup is unsafe")
        backup_valid = verify_knowledge_project(backup).valid
        if not output.exists():
            if not backup_valid:
                raise KnowledgeProjectError("orphaned replacement backup is invalid")
            backup.replace(output)
            actions.append("restored_orphaned_backup")
        else:
            output_valid = verify_knowledge_project(output).valid
            if output_valid:
                shutil.rmtree(backup)
                actions.append("removed_redundant_backup")
            elif backup_valid:
                if output.is_symlink():
                    raise KnowledgeProjectError("invalid output is an unsafe symlink")
                shutil.rmtree(output)
                backup.replace(output)
                actions.append("rolled_back_invalid_replacement")
            else:
                raise KnowledgeProjectError("both current project and replacement backup are invalid")
    now = time.time()
    for path in sorted(output.parent.glob(f".{output.name}.tmp-*")):
        if path.is_symlink():
            raise KnowledgeProjectError("stale build path is an unsafe symlink")
        if path.is_dir() and now - path.stat().st_mtime >= stale_seconds:
            shutil.rmtree(path)
            actions.append("removed_stale_build_directory")
    cache_root = state / "cache"
    if cache_root.is_dir() and not cache_root.is_symlink():
        for path in sorted(cache_root.glob(".*.tmp-*")):
            if path.is_symlink():
                raise KnowledgeProjectError("stale cache path is an unsafe symlink")
            if path.is_dir() and now - path.stat().st_mtime >= stale_seconds:
                shutil.rmtree(path)
                actions.append("removed_stale_cache_directory")
    return tuple(actions)


def _result(
    *,
    source_sha: str,
    key: str,
    profile: EngineeringProfile,
    output: Path,
    state: Path,
    report: dict[str, object],
    cache_status: str,
    reused: bool,
    recovered: tuple[str, ...],
) -> EngineeringBuildResult:
    return EngineeringBuildResult(
        ENGINEERING_BUILD_SCHEMA_VERSION,
        ENGINEERING_VERSION,
        "completed",
        source_sha,
        key,
        profile.name,
        profile_sha256(profile),
        str(output),
        str(state),
        str(report.get("project_id", "")),
        cache_status,
        reused,
        recovered,
        report,
    )


def build_engineered_project(
    source: str | Path,
    output_directory: str | Path,
    *,
    profile: EngineeringProfile | str | Path = "balanced",
    state_directory: str | Path | None = None,
    reuse_existing: bool = False,
    replace_existing: bool = False,
    use_cache: bool = True,
    resume: bool = True,
    recover_stale_lock: bool = False,
) -> EngineeringBuildResult:
    """Build, resume, cache, and publish one verified immutable project."""
    selected = load_engineering_profile(profile) if not isinstance(profile, EngineeringProfile) else profile
    source_path, output, state = validate_engineering_paths(source, output_directory, state_directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    source_sha = sha256_file(source_path)
    key = build_key(source_sha, selected)
    attempts = 1
    journal_path = state / "build-state.json"
    if journal_path.exists():
        try:
            previous = _read_small_object(journal_path, "build state", _MAX_STATE_BYTES)
            previous_attempts = previous.get("attempts")
            if isinstance(previous_attempts, int) and not isinstance(previous_attempts, bool):
                attempts = previous_attempts + 1
        except KnowledgeProjectError:
            attempts = 1
    recovered: tuple[str, ...] = ()
    with _BuildLock(
        state,
        stale_seconds=selected.lock_stale_seconds,
        recover_stale=recover_stale_lock,
        source_sha256=source_sha,
        output=output,
    ):
        try:
            if resume:
                recovered = recover_engineering_workspace(
                    output,
                    state,
                    stale_seconds=selected.cleanup_stale_seconds,
                )
            _journal(
                state,
                status="running",
                phase="prepared",
                source_sha256=source_sha,
                key=key,
                profile=selected,
                output=output,
                attempts=attempts,
                recovered_actions=recovered,
            )
            if output.exists() and reuse_existing:
                if not _matches_project(output, source_sha, selected):
                    raise KnowledgeProjectError("existing project does not match source and profile")
                report = _load_report(output)
                _journal(
                    state,
                    status="completed",
                    phase="reused_existing",
                    source_sha256=source_sha,
                    key=key,
                    profile=selected,
                    output=output,
                    attempts=attempts,
                    cache_status="not_used",
                    recovered_actions=recovered,
                    project_id=str(report.get("project_id", "")),
                )
                return _result(
                    source_sha=source_sha,
                    key=key,
                    profile=selected,
                    output=output,
                    state=state,
                    report=report,
                    cache_status="not_used",
                    reused=True,
                    recovered=recovered,
                )
            if output.exists() and not replace_existing:
                raise KnowledgeProjectError(
                    "project directory exists; request verified reuse or atomic replacement"
                )

            cache_allowed = use_cache and selected.cache_enabled
            entry = _cache_entry(state, key)
            if cache_allowed and entry.exists():
                if _cache_matches(entry, source_sha, selected, key):
                    _journal(
                        state,
                        status="running",
                        phase="restoring_cache",
                        source_sha256=source_sha,
                        key=key,
                        profile=selected,
                        output=output,
                        attempts=attempts,
                        cache_status="hit",
                        recovered_actions=recovered,
                    )
                    _install_copy(entry / "project", output, replace_existing)
                    report = _load_report(output)
                    _journal(
                        state,
                        status="completed",
                        phase="cache_restored",
                        source_sha256=source_sha,
                        key=key,
                        profile=selected,
                        output=output,
                        attempts=attempts,
                        cache_status="hit",
                        recovered_actions=recovered,
                        project_id=str(report.get("project_id", "")),
                    )
                    return _result(
                        source_sha=source_sha,
                        key=key,
                        profile=selected,
                        output=output,
                        state=state,
                        report=report,
                        cache_status="hit",
                        reused=False,
                        recovered=recovered,
                    )
                if entry.is_symlink():
                    raise KnowledgeProjectError("invalid cache entry is an unsafe symlink")
                shutil.rmtree(entry)
                recovered = tuple((*recovered, "discarded_invalid_cache_entry"))

            _journal(
                state,
                status="running",
                phase="building_project",
                source_sha256=source_sha,
                key=key,
                profile=selected,
                output=output,
                attempts=attempts,
                cache_status="miss" if cache_allowed else "disabled",
                recovered_actions=recovered,
            )
            report_object = build_knowledge_project(
                source_path,
                output,
                policy=selected.project_policy(replace=replace_existing),
            )
            verification = verify_knowledge_project(output)
            if not verification.valid:
                raise KnowledgeProjectError("engineered project failed post-build verification")
            report = report_object.to_dict()
            if cache_allowed:
                _journal(
                    state,
                    status="running",
                    phase="publishing_cache",
                    source_sha256=source_sha,
                    key=key,
                    profile=selected,
                    output=output,
                    attempts=attempts,
                    cache_status="miss",
                    recovered_actions=recovered,
                    project_id=report_object.project_id,
                )
                _populate_cache(output, state, source_sha, selected, key)
            cache_status = "miss" if cache_allowed else "disabled"
            _journal(
                state,
                status="completed",
                phase="completed",
                source_sha256=source_sha,
                key=key,
                profile=selected,
                output=output,
                attempts=attempts,
                cache_status=cache_status,
                recovered_actions=recovered,
                project_id=report_object.project_id,
            )
            return _result(
                source_sha=source_sha,
                key=key,
                profile=selected,
                output=output,
                state=state,
                report=report,
                cache_status=cache_status,
                reused=False,
                recovered=recovered,
            )
        except Exception as exc:
            _journal(
                state,
                status="failed",
                phase="failed",
                source_sha256=source_sha,
                key=key,
                profile=selected,
                output=output,
                attempts=attempts,
                cache_status="unknown",
                recovered_actions=recovered,
                error=exc,
            )
            raise


__all__ = [
    "ENGINEERING_BUILD_SCHEMA_VERSION",
    "ENGINEERING_CACHE_SCHEMA_VERSION",
    "ENGINEERING_PROFILE_SCHEMA_VERSION",
    "ENGINEERING_STATE_SCHEMA_VERSION",
    "ENGINEERING_VERSION",
    "EngineeringBuildResult",
    "EngineeringProfile",
    "available_profile_paths",
    "build_engineered_project",
    "build_key",
    "load_engineering_profile",
    "profile_sha256",
    "recover_engineering_workspace",
    "validate_engineering_paths",
]
