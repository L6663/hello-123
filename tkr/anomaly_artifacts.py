"""Deterministic Phase 9.4 artifact publication."""
from __future__ import annotations

import csv
from hashlib import sha256
import io
import json
from pathlib import Path
from typing import Final

from .anomaly_detection import AnomalyInspectionReport

ANOMALY_ARTIFACT_SCHEMA_VERSION: Final = "tkr-anomaly-artifact-set-v1"


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _jsonl_bytes(records: list[dict[str, object]]) -> bytes:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    ).encode("utf-8")


def _csv_bytes(records: list[dict[str, object]]) -> bytes:
    fields = [
        "finding_id", "rule_id", "category", "severity", "confidence",
        "recommended_action", "start_char", "end_char", "start_line",
        "end_line", "evidence_sha256", "signals", "evidence_preview",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = dict(record)
        row["signals"] = "|".join(str(item) for item in row.get("signals", ()))
        writer.writerow({field: row.get(field, "") for field in fields})
    return stream.getvalue().encode("utf-8")


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def publish_anomaly_artifacts(
    report: AnomalyInspectionReport,
    outdir: Path,
) -> dict[str, object]:
    """Write the complete deterministic Phase 9.4 artifact set."""

    if outdir.exists() and not outdir.is_dir():
        raise ValueError(f"output path is not a directory: {outdir}")
    outdir.mkdir(parents=True, exist_ok=True)

    findings = [finding.to_dict() for finding in report.findings]
    contamination = [
        record for record in findings if record["category"] == "contamination_candidate"
    ]
    non_body = [
        record for record in findings if record["category"] == "paratext_candidate"
    ]
    structural = [
        record for record in findings if record["category"] == "structural_anomaly"
    ]
    stage_result = {
        "schema_version": "tkr-stage-result-v1",
        "stage": "Phase 9.4",
        "status": report.scan_status,
        "source_id": report.source_id,
        "source_sha256": report.source_sha256,
        "finding_count": report.finding_count,
        "recommended_action": report.recommended_action,
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_freeze": False,
    }

    payloads: dict[str, bytes] = {
        "anomaly-report.json": _json_bytes(report.to_dict()),
        "anomaly-candidates.jsonl": _jsonl_bytes(findings),
        "contamination-candidates.jsonl": _jsonl_bytes(contamination),
        "non-body-content.jsonl": _jsonl_bytes(non_body),
        "structural-anomalies.jsonl": _jsonl_bytes(structural),
        "anomaly-ledger.csv": _csv_bytes(findings),
        "stage-result.json": _json_bytes(stage_result),
    }
    for name, payload in payloads.items():
        _write_atomic(outdir / name, payload)

    manifest_entries = []
    for name in sorted(payloads):
        payload = payloads[name]
        manifest_entries.append(
            {
                "path": name,
                "size_bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "schema_version": ANOMALY_ARTIFACT_SCHEMA_VERSION,
        "source_id": report.source_id,
        "source_sha256": report.source_sha256,
        "detector_version": report.detector_version,
        "artifacts": manifest_entries,
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_freeze": False,
    }
    _write_atomic(outdir / "artifact-manifest.json", _json_bytes(manifest))
    return manifest
