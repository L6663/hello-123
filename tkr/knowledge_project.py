"""Atomic Stage 4 orchestration from raw source to a verified typed QA index."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Mapping, Sequence

from .anomaly_artifacts import publish_anomaly_artifacts
from .anomaly_detection import inspect_source_anomalies
from .encoding_inspection import inspect_source_encoding
from .entity_normalization import NORMALIZER_VERSION
from .hashing import sha256_file
from .hybrid_retrieval import build_hybrid_index, query_hybrid_index
from .knowledge_models import (
    KNOWLEDGE_MANIFEST_SCHEMA_VERSION,
    KNOWLEDGE_PROJECT_SCHEMA_VERSION,
    KNOWLEDGE_SYSTEM_VERSION,
    KNOWLEDGE_VERIFICATION_SCHEMA_VERSION,
    KnowledgeProjectError,
    KnowledgeProjectManifest,
    KnowledgeProjectPolicy,
    KnowledgeProjectReport,
    KnowledgeProjectVerification,
    ProjectFileRecord,
)
from .semantic_artifacts import publish_semantic_artifacts
from .semantic_extraction import inspect_source_semantics, validate_semantic_report
from .semantic_models import SemanticPolicy
from .structure_artifacts import publish_structure_artifacts
from .structure_detection import inspect_source_structure, validate_structure_report

_IMMUTABLE_ROOTS = ("source", "stage1-anomaly", "stage2-structure", "stage3-semantics", "bridge", "index")
_BOM_BYTES = {
    "utf-8": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
}
_ENTITY_DATASETS = {
    "mentions.jsonl": "mentions",
    "entities.jsonl": "entities",
    "facts.jsonl": "facts",
    "timeline.jsonl": "timeline",
    "conflicts.jsonl": "conflicts",
    "ambiguity-groups.jsonl": "ambiguity_groups",
}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonl_bytes(rows: Sequence[object]) -> bytes:
    output: list[str] = []
    for row in rows:
        payload = row.to_dict() if hasattr(row, "to_dict") else row
        output.append(_canonical_json(payload))
    return (("\n".join(output) + "\n") if output else "").encode("utf-8")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KnowledgeProjectError(f"{label} must be a JSON object")
    return payload


def _decode_source(source: Path, encoding_report) -> tuple[bytes, str]:
    raw = source.read_bytes()
    encoding = encoding_report.selected_encoding
    if not encoding_report.strict_decode_passed or encoding is None:
        raise KnowledgeProjectError("source is not strictly decodable")
    prefix = _BOM_BYTES.get(encoding_report.bom, b"")
    if prefix:
        if not raw.startswith(prefix):
            raise KnowledgeProjectError("source BOM changed after encoding inspection")
        raw_for_decode = raw[len(prefix):]
    else:
        raw_for_decode = raw
    try:
        text = raw_for_decode.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError) as exc:
        raise KnowledgeProjectError(f"source decoding failed after inspection: {exc}") from exc
    if text.startswith("\ufeff"):
        raise KnowledgeProjectError("decoded source retained an unexpected external BOM")
    if encoding_report.decoded_character_count != len(text):
        raise KnowledgeProjectError("decoded character count differs from encoding inspection")
    return raw, text


def _publish_bridge(root: Path, source_text: str, structure, semantic) -> tuple[Path, Path, Path]:
    bridge = root / "bridge"
    entity_dir = bridge / "entity"
    entity_dir.mkdir(parents=True, exist_ok=True)
    source_path = bridge / "normalized-source.txt"
    units_path = bridge / "units.jsonl"
    accepted_path = bridge / "accepted-claims.jsonl"
    _write_atomic(source_path, source_text.encode("utf-8"))

    unit_rows = [
        {
            "unit_id": unit.unit_id,
            "source_id": unit.source_id,
            "norm_start": unit.start_char,
            "norm_end": unit.end_char,
        }
        for unit in structure.units
    ]
    _write_atomic(units_path, _jsonl_bytes(unit_rows))
    _write_atomic(accepted_path, _jsonl_bytes(list(semantic.accepted_records)))

    normalization = semantic.normalization
    report = normalization.get("report")
    if not isinstance(report, dict):
        raise KnowledgeProjectError("Stage 3 did not produce an entity-normalization report")
    artifact_hashes: dict[str, str] = {}
    for filename, key in _ENTITY_DATASETS.items():
        rows = normalization.get(key, [])
        if not isinstance(rows, list):
            raise KnowledgeProjectError(f"Stage 3 normalization dataset {key!r} is malformed")
        data = _jsonl_bytes(rows)
        _write_atomic(entity_dir / filename, data)
        artifact_hashes[filename] = sha256(data).hexdigest()

    bound_report = dict(report)
    bound_report.update(
        {
            "accepted_claims_sha256": sha256_file(accepted_path),
            "unit_index_sha256": sha256_file(units_path),
            "identity_links_sha256": None,
            "artifact_sha256": dict(sorted(artifact_hashes.items())),
        }
    )
    if bound_report.get("normalizer_version") != NORMALIZER_VERSION:
        raise KnowledgeProjectError("Stage 3 normalizer version is incompatible with the index")
    _write_atomic(entity_dir / "entity-normalization-report.json", _json_bytes(bound_report))
    return source_path, units_path, accepted_path


def _canonical_gate(anomaly, structure, semantic) -> None:
    unsafe = [
        item for item in anomaly.findings
        if item.category in {"contamination_candidate", "paratext_candidate"}
        or (item.category == "text_anomaly" and item.severity == "high")
    ]
    if unsafe:
        raise KnowledgeProjectError("canonical index blocked by unresolved Stage 1 findings")
    if structure.findings or any(unit.review_status != "accepted_candidate" for unit in structure.units):
        raise KnowledgeProjectError("canonical index blocked by unresolved Stage 2 findings")
    high_semantic = [item for item in semantic.findings if item.severity in {"high", "blocker"}]
    if high_semantic:
        raise KnowledgeProjectError("canonical index blocked by unresolved Stage 3 findings")
    normalization_report = semantic.normalization.get("report", {})
    if not isinstance(normalization_report, dict) or not normalization_report.get("may_publish_canonical"):
        raise KnowledgeProjectError("entity normalization does not permit canonical publication")


def _project_id(raw_sha: str, normalized_sha: str, index_hash: str, mode: str) -> str:
    payload = "\0".join((KNOWLEDGE_SYSTEM_VERSION, raw_sha, normalized_sha, index_hash, mode))
    return "kpr_" + sha256(payload.encode("utf-8")).hexdigest()[:32]


def _manifest_files(root: Path) -> tuple[ProjectFileRecord, ...]:
    records: list[ProjectFileRecord] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "project-manifest.json":
            continue
        records.append(ProjectFileRecord(relative, path.stat().st_size, sha256_file(path)))
    return tuple(records)


def _install_directory(temporary: Path, destination: Path, replace: bool) -> None:
    if not destination.exists():
        temporary.replace(destination)
        return
    if not replace:
        raise KnowledgeProjectError(f"project directory already exists: {destination}")
    backup = destination.with_name(f".{destination.name}.backup")
    if backup.exists():
        shutil.rmtree(backup)
    destination.replace(backup)
    try:
        temporary.replace(destination)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        backup.replace(destination)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def _report_from_dict(payload: Mapping[str, object]) -> KnowledgeProjectReport:
    data = dict(payload)
    data["warnings"] = tuple(str(item) for item in data.get("warnings", []))
    return KnowledgeProjectReport(**data)  # type: ignore[arg-type]


def build_knowledge_project(
    source: str | Path,
    output_directory: str | Path,
    *,
    policy: KnowledgeProjectPolicy | None = None,
) -> KnowledgeProjectReport:
    """Build one self-contained immutable typed-knowledge project atomically."""
    active = policy or KnowledgeProjectPolicy()
    source_path = Path(source)
    output = Path(output_directory)
    if not source_path.is_file():
        raise KnowledgeProjectError(f"source is not a regular file: {source_path}")

    if output.exists() and active.reuse_verified_project:
        verification = verify_knowledge_project(output)
        if not verification.valid:
            raise KnowledgeProjectError("existing project failed integrity verification")
        current_raw = sha256_file(source_path)
        report = _load_object(output / "project-report.json", "project report")
        if report.get("raw_source_sha256") != current_raw:
            raise KnowledgeProjectError("existing project belongs to a different source revision")
        return _report_from_dict(report)
    if output.exists() and not active.replace_existing_project:
        raise KnowledgeProjectError(
            "project directory exists; use reuse_verified_project or replace_existing_project"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        encoding_report = inspect_source_encoding(source_path)
        raw_bytes, source_text = _decode_source(source_path, encoding_report)
        raw_sha = sha256(raw_bytes).hexdigest()
        normalized_bytes = source_text.encode("utf-8")
        normalized_sha = sha256(normalized_bytes).hexdigest()

        source_root = temporary / "source"
        source_root.mkdir(parents=True, exist_ok=True)
        _write_atomic(source_root / "original-source.bin", raw_bytes)
        _write_atomic(source_root / "normalized-source.txt", normalized_bytes)
        _write_atomic(
            source_root / "source-metadata.json",
            _json_bytes(
                {
                    "schema_version": "tkr-project-source-metadata-v1",
                    "source_id": encoding_report.source_id,
                    "original_filename": source_path.name,
                    "original_suffix": source_path.suffix.lower(),
                    "raw_source_sha256": raw_sha,
                    "normalized_source_sha256": normalized_sha,
                    "selected_encoding": encoding_report.selected_encoding,
                    "external_bom": encoding_report.bom,
                    "decoded_character_count": len(source_text),
                }
            ),
        )

        anomaly = inspect_source_anomalies(source_path)
        publish_anomaly_artifacts(anomaly, temporary / "stage1-anomaly")
        structure = inspect_source_structure(source_path)
        validate_structure_report(structure)
        publish_structure_artifacts(structure, temporary / "stage2-structure")
        semantic = inspect_source_semantics(
            source_path,
            policy=SemanticPolicy(
                max_candidates=active.max_candidates,
                max_findings=active.max_findings,
                max_model_tasks=active.max_model_tasks,
                max_clause_characters=active.max_clause_characters,
                emit_model_tasks=active.emit_model_tasks,
                run_entity_normalization=True,
            ),
        )
        validate_semantic_report(semantic)
        publish_semantic_artifacts(semantic, temporary / "stage3-semantics")
        if not semantic.accepted_records:
            raise KnowledgeProjectError("no accepted typed Claims are available for indexing")
        if active.index_mode == "canonical":
            _canonical_gate(anomaly, structure, semantic)

        bridge_source, bridge_units, bridge_accepted = _publish_bridge(
            temporary, source_text, structure, semantic
        )
        index_dir = temporary / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        database = index_dir / "knowledge.sqlite"
        index_report_path = index_dir / "knowledge.report.json"
        index_report = build_hybrid_index(
            bridge_source,
            bridge_units,
            bridge_accepted,
            temporary / "bridge" / "entity",
            database,
            index_mode=active.index_mode,
            source_id=structure.source_id,
            report_path=index_report_path,
        )
        index_hash = str(index_report["index_logical_sha256"])
        project_identifier = _project_id(raw_sha, normalized_sha, index_hash, active.index_mode)
        normalization_report = semantic.normalization.get("report", {})
        if not isinstance(normalization_report, dict):
            normalization_report = {}
        warnings = tuple(
            dict.fromkeys(
                (
                    *encoding_report.warnings,
                    *anomaly.warnings,
                    *structure.warnings,
                    *semantic.warnings,
                )
            )
        )
        report = KnowledgeProjectReport(
            KNOWLEDGE_PROJECT_SCHEMA_VERSION,
            KNOWLEDGE_SYSTEM_VERSION,
            project_identifier,
            "completed",
            active.index_mode,
            structure.source_id,
            source_path.name,
            source_path.suffix.lower(),
            raw_sha,
            normalized_sha,
            str(encoding_report.selected_encoding),
            structure.unit_count,
            semantic.candidate_count,
            semantic.accepted_candidate_count,
            int(normalization_report.get("entity_count", 0)),
            int(normalization_report.get("fact_count", 0)),
            int(normalization_report.get("conflict_count", 0)),
            int(normalization_report.get("ambiguity_group_count", 0)),
            anomaly.finding_count,
            structure.finding_count,
            semantic.finding_count,
            index_hash,
            str(index_report["database_sha256"]),
            "typed_knowledge_project_ready",
            warnings,
            active.to_dict(),
            True,
            False,
            False,
            False,
            False,
            False,
        )
        _write_atomic(temporary / "project-report.json", _json_bytes(report.to_dict()))
        manifest = KnowledgeProjectManifest(
            KNOWLEDGE_MANIFEST_SCHEMA_VERSION,
            KNOWLEDGE_SYSTEM_VERSION,
            project_identifier,
            structure.source_id,
            raw_sha,
            normalized_sha,
            _manifest_files(temporary),
            _IMMUTABLE_ROOTS,
            False,
            False,
            False,
        )
        _write_atomic(temporary / "project-manifest.json", _json_bytes(manifest.to_dict()))
        verification = verify_knowledge_project(temporary)
        if not verification.valid:
            raise KnowledgeProjectError(
                "new project failed post-build verification: " + ",".join(verification.reason_codes)
            )
        _install_directory(temporary, output, active.replace_existing_project)
        return report
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _safe_manifest_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or value != pure.as_posix():
        return None
    return value


def verify_knowledge_project(project_directory: str | Path) -> KnowledgeProjectVerification:
    """Verify project files, provenance, index report, and SQLite logical identity."""
    root = Path(project_directory)
    reasons: list[str] = []
    checked = 0
    project_id = source_id = raw_sha = normalized_sha = index_hash = ""
    try:
        manifest = _load_object(root / "project-manifest.json", "project manifest")
        report = _load_object(root / "project-report.json", "project report")
        project_id = str(manifest.get("project_id", ""))
        source_id = str(manifest.get("source_id", ""))
        raw_sha = str(manifest.get("raw_source_sha256", ""))
        normalized_sha = str(manifest.get("normalized_source_sha256", ""))
        index_hash = str(report.get("index_logical_sha256", ""))
        if manifest.get("schema_version") != KNOWLEDGE_MANIFEST_SCHEMA_VERSION:
            reasons.append("MANIFEST_SCHEMA_VERSION_MISMATCH")
        if report.get("schema_version") != KNOWLEDGE_PROJECT_SCHEMA_VERSION:
            reasons.append("PROJECT_REPORT_SCHEMA_VERSION_MISMATCH")
        if manifest.get("system_version") != KNOWLEDGE_SYSTEM_VERSION or report.get("system_version") != KNOWLEDGE_SYSTEM_VERSION:
            reasons.append("KNOWLEDGE_SYSTEM_VERSION_MISMATCH")
        if manifest.get("project_id") != report.get("project_id"):
            reasons.append("PROJECT_ID_MISMATCH")
        for payload in (manifest, report):
            if payload.get("project_acceptance_performed") or payload.get("may_accept_project") or payload.get("may_freeze"):
                reasons.append("ILLEGAL_ACCEPTANCE_OR_FREEZE_AUTHORITY")
        if report.get("release_candidate"):
            reasons.append("ILLEGAL_RELEASE_CANDIDATE_STATE")

        entries = manifest.get("files")
        if not isinstance(entries, list):
            reasons.append("MANIFEST_FILES_INVALID")
            entries = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                reasons.append("MANIFEST_FILE_RECORD_INVALID")
                continue
            relative = _safe_manifest_path(entry.get("path"))
            if relative is None or relative in seen:
                reasons.append("MANIFEST_PATH_INVALID_OR_DUPLICATE")
                continue
            seen.add(relative)
            path = root / relative
            if not path.is_file():
                reasons.append("MANIFEST_FILE_MISSING")
                continue
            checked += 1
            if entry.get("size_bytes") != path.stat().st_size:
                reasons.append("MANIFEST_FILE_SIZE_MISMATCH")
            if entry.get("sha256") != sha256_file(path):
                reasons.append("MANIFEST_FILE_HASH_MISMATCH")

        metadata = _load_object(root / "source" / "source-metadata.json", "source metadata")
        if metadata.get("raw_source_sha256") != raw_sha:
            reasons.append("RAW_SOURCE_METADATA_MISMATCH")
        if metadata.get("normalized_source_sha256") != normalized_sha:
            reasons.append("NORMALIZED_SOURCE_METADATA_MISMATCH")
        if sha256_file(root / "source" / "original-source.bin") != raw_sha:
            reasons.append("RAW_SOURCE_HASH_MISMATCH")
        if sha256_file(root / "source" / "normalized-source.txt") != normalized_sha:
            reasons.append("NORMALIZED_SOURCE_HASH_MISMATCH")

        index_report = _load_object(root / "index" / "knowledge.report.json", "index report")
        if index_report.get("index_logical_sha256") != index_hash:
            reasons.append("INDEX_LOGICAL_HASH_MISMATCH")
        if index_report.get("database_sha256") != sha256_file(root / "index" / "knowledge.sqlite"):
            reasons.append("DATABASE_HASH_MISMATCH")
        probe = query_hybrid_index(
            root / "index" / "knowledge.sqlite",
            "__tkr_integrity_probe__",
            limit=1,
            verify_database=True,
            report_path=root / "index" / "knowledge.report.json",
        )
        if probe.index_logical_sha256 != index_hash:
            reasons.append("INDEX_METADATA_RECOMPUTATION_MISMATCH")
    except Exception as exc:
        reasons.extend(("PROJECT_VERIFICATION_EXCEPTION", type(exc).__name__))

    unique = tuple(dict.fromkeys(reasons))
    valid = not unique
    return KnowledgeProjectVerification(
        KNOWLEDGE_VERIFICATION_SCHEMA_VERSION,
        KNOWLEDGE_SYSTEM_VERSION,
        project_id,
        "verified" if valid else "rejected",
        valid,
        checked,
        unique if unique else ("PROJECT_HASH_CHAIN_VERIFIED", "INDEX_INTEGRITY_VERIFIED"),
        source_id,
        raw_sha,
        normalized_sha,
        index_hash,
        valid,
        False,
        False,
        False,
    )


__all__ = ["build_knowledge_project", "verify_knowledge_project"]
