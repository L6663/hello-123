"""Deterministic atomic artifact publication for Stage 2 structure results."""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
import csv, io, json
from pathlib import Path
from typing import Iterable
from .structure_detection import StructureInspectionReport, validate_structure_report

ARTIFACT_MANIFEST_SCHEMA_VERSION = "tkr-structure-artifact-manifest-v1"

def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
def _jsonl_bytes(items: Iterable[object]) -> bytes:
    lines=[]
    for item in items:
        payload=item.to_dict() if hasattr(item,"to_dict") else asdict(item)
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",",":")))
    return (("\n".join(lines)+"\n") if lines else "").encode("utf-8")
def _csv_bytes(report: StructureInspectionReport) -> bytes:
    output=io.StringIO(newline="")
    writer=csv.writer(output, lineterminator="\n")
    writer.writerow(["unit_id","unit_type","ordinal","title","parent_unit_id","start_char","end_char","start_line","end_line","content_sha256","review_status"])
    for u in report.units:
        writer.writerow([u.unit_id,u.unit_type,"" if u.ordinal is None else u.ordinal,u.title,u.parent_unit_id or "",u.start_char,u.end_char,u.start_line,u.end_line,u.content_sha256,u.review_status])
    return output.getvalue().encode("utf-8")
def _atomic_write(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(f".{path.name}.tmp"); tmp.write_bytes(data); tmp.replace(path)

def publish_structure_artifacts(report: StructureInspectionReport, outdir: str|Path) -> dict[str,object]:
    validate_structure_report(report)
    root=Path(outdir)
    files={
        "structure-report.json":_json_bytes(report.to_dict()),
        "heading-candidates.jsonl":_jsonl_bytes(report.headings),
        "unit-index.jsonl":_jsonl_bytes(report.units),
        "structure-anomalies.jsonl":_jsonl_bytes(report.findings),
        "unit-ledger.csv":_csv_bytes(report),
        "stage-result.json":_json_bytes({
            "schema_version":"tkr-stage-result-v1","stage":"Stage 2","scan_status":report.scan_status,
            "source_id":report.source_id,"source_sha256":report.source_sha256,"unit_count":report.unit_count,
            "finding_count":report.finding_count,"coverage_ratio":report.coverage_ratio,
            "project_acceptance_performed":False,"may_accept_project":False,"may_freeze":False,
        }),
    }
    manifest_files=[]
    for name in sorted(files):
        data=files[name]; _atomic_write(root/name,data)
        manifest_files.append({"name":name,"size_bytes":len(data),"sha256":sha256(data).hexdigest()})
    manifest={"schema_version":ARTIFACT_MANIFEST_SCHEMA_VERSION,"source_id":report.source_id,"source_sha256":report.source_sha256,
              "files":manifest_files,"project_acceptance_performed":False,"may_accept_project":False,"may_freeze":False}
    _atomic_write(root/"artifact-manifest.json",_json_bytes(manifest))
    return manifest
