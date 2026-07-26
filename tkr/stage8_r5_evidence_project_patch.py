"""Bind Stage 8-R5 precise anomaly spans into Evidence Project builds."""
from __future__ import annotations

from . import evidence_project as _project
from . import evidence_engine as _engine

_APPLIED = False
_ORIGINAL_INPUT_RECORDS = _project._input_records
_ORIGINAL_BUILD = _project.build_evidence_project
_ORIGINAL_VERIFY_PROJECT = _project.verify_evidence_project
_ANOMALY_FINDINGS: list[dict[str, object]] | None = None


def _input_records(source_project, literary_project):
    global _ANOMALY_FINDINGS
    values = _ORIGINAL_INPUT_RECORDS(source_project, literary_project)
    anomaly_path = source_project / "stage1-anomaly" / "anomaly-candidates.jsonl"
    _ANOMALY_FINDINGS = (
        _project._load_jsonl(anomaly_path, "anomaly candidates")
        if anomaly_path.is_file() else None
    )
    return (*values, _ANOMALY_FINDINGS)


def _input_records_six(source_project, literary_project):
    return _input_records(source_project, literary_project)[:6]


def _with_legacy_unpack(function, *args, **kwargs):
    current = _project._input_records
    _project._input_records = _input_records_six
    try:
        return function(*args, **kwargs)
    finally:
        _project._input_records = current


def _build(*args, **kwargs):
    return _with_legacy_unpack(_ORIGINAL_BUILD, *args, **kwargs)


def _verify_project(*args, **kwargs):
    return _with_legacy_unpack(_ORIGINAL_VERIFY_PROJECT, *args, **kwargs)


def _extract(source_text, chapters, *, target_chars=900, max_chars=1500):
    return _engine.extract_evidence_units(
        source_text, chapters, target_chars=target_chars, max_chars=max_chars,
        blocked_source_spans=() if _ANOMALY_FINDINGS is None else _ANOMALY_FINDINGS,
    )


def _verify_units(source_text, chapters, units):
    return _engine.verify_evidence_units(
        source_text, chapters, units,
        blocked_source_spans=() if _ANOMALY_FINDINGS is None else _ANOMALY_FINDINGS,
    )


def apply_stage8_r5_evidence_project_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _project._input_records = _input_records
    _project.extract_evidence_units = _extract
    _project.verify_evidence_units = _verify_units
    _project.build_evidence_project = _build
    _project.verify_evidence_project = _verify_project
    _APPLIED = True


__all__ = ["apply_stage8_r5_evidence_project_patch"]
