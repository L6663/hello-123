"""Atomic deterministic publication for Stage 3 semantic artifacts."""
from __future__ import annotations

import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import shutil
import tempfile

from .semantic_extraction import validate_semantic_report
from .semantic_models import SemanticExtractionReport

ARTIFACT_SET_SCHEMA_VERSION = "tkr-semantic-artifact-set-v1"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _jsonl_bytes(rows) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")


def _csv_bytes(report: SemanticExtractionReport) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        [
            "candidate_id",
            "claim_type",
            "subject",
            "object",
            "value",
            "unit",
            "polarity",
            "discourse_status",
            "factual_status",
            "attributor",
            "unit_id",
            "evidence_start",
            "evidence_end",
            "validation_status",
            "may_index",
            "requires_review",
        ]
    )
    for item in report.candidates:
        writer.writerow(
            [
                item.candidate_id,
                item.claim_type,
                item.subject,
                item.object,
                item.value,
                item.unit,
                str(item.polarity).lower(),
                item.discourse_status,
                item.factual_status,
                item.attributor,
                item.unit_id,
                item.evidence_start,
                item.evidence_end,
                item.validation_status,
                str(item.may_index).lower(),
                str(item.requires_review).lower(),
            ]
        )
    return stream.getvalue().encode("utf-8")


def _normalization_rows(report: SemanticExtractionReport, key: str) -> list[dict[str, object]]:
    rows = report.normalization.get(key, [])
    return list(rows) if isinstance(rows, list) else []


def publish_semantic_artifacts(report: SemanticExtractionReport, output_directory: Path) -> dict[str, object]:
    validate_semantic_report(report)
    output_directory = Path(output_directory)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}.tmp-", dir=output_directory.parent)
    )
    try:
        payloads: dict[str, bytes] = {
            "semantic-report.json": _json_bytes(report.to_dict()),
            "claim-candidates.jsonl": _jsonl_bytes(item.to_dict() for item in report.candidates),
            "accepted-claims.jsonl": _jsonl_bytes(report.accepted_records),
            "nonassertive-claims.jsonl": _jsonl_bytes(
                item.to_dict() for item in report.candidates if item.discourse_status != "assertion"
            ),
            "semantic-findings.jsonl": _jsonl_bytes(item.to_dict() for item in report.findings),
            "model-extraction-tasks.jsonl": _jsonl_bytes(item.to_dict() for item in report.model_tasks),
            "entities.jsonl": _jsonl_bytes(_normalization_rows(report, "entities")),
            "facts.jsonl": _jsonl_bytes(_normalization_rows(report, "facts")),
            "timeline.jsonl": _jsonl_bytes(_normalization_rows(report, "timeline")),
            "conflicts.jsonl": _jsonl_bytes(_normalization_rows(report, "conflicts")),
            "ambiguity-groups.jsonl": _jsonl_bytes(_normalization_rows(report, "ambiguity_groups")),
            "normalization-report.json": _json_bytes(report.normalization.get("report", {})),
            "semantic-ledger.csv": _csv_bytes(report),
            "stage-result.json": _json_bytes(
                {
                    "schema_version": ARTIFACT_SET_SCHEMA_VERSION,
                    "stage": "Stage 3",
                    "scan_status": report.scan_status,
                    "source_id": report.source_id,
                    "source_sha256": report.source_sha256,
                    "candidate_count": report.candidate_count,
                    "accepted_candidate_count": report.accepted_candidate_count,
                    "nonassertive_candidate_count": report.nonassertive_candidate_count,
                    "model_task_count": report.model_task_count,
                    "finding_count": report.finding_count,
                    "recommended_action": report.recommended_action,
                    "project_acceptance_performed": False,
                    "may_accept_project": False,
                    "may_freeze": False,
                }
            ),
        }
        files = []
        for name in sorted(payloads):
            data = payloads[name]
            (temporary / name).write_bytes(data)
            files.append({"name": name, "size_bytes": len(data), "sha256": sha256(data).hexdigest()})
        manifest = {
            "schema_version": ARTIFACT_SET_SCHEMA_VERSION,
            "source_id": report.source_id,
            "source_sha256": report.source_sha256,
            "files": files,
            "project_acceptance_performed": False,
            "may_accept_project": False,
            "may_freeze": False,
        }
        manifest_bytes = _json_bytes(manifest)
        (temporary / "artifact-manifest.json").write_bytes(manifest_bytes)
        if output_directory.exists():
            shutil.rmtree(output_directory)
        temporary.replace(output_directory)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
