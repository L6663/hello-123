"""Constrained model-candidate task contracts for Stage 3.

The task interface can request candidate proposals, but model output can never
accept, index, certify, or freeze a Claim. Returned proposals must remain inside
the bound evidence span and pass the deterministic Phase 3 validator.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Mapping

from .semantic_models import (
    CLAIM_TYPES,
    MODEL_EXTRACTION_TASK_SCHEMA_VERSION,
    SEMANTIC_CANDIDATE_SCHEMA_VERSION,
    ModelExtractionTask,
    SemanticExtractionError,
    stable_id,
)

MODEL_INSTRUCTION_VERSION = "tkr-model-candidate-instruction-v1"


def make_model_task(
    *,
    source_id: str,
    source_sha256: str,
    unit_id: str,
    evidence_start: int,
    evidence_end: int,
    evidence_text: str,
) -> ModelExtractionTask:
    digest = sha256(evidence_text.encode("utf-8")).hexdigest()
    task_id = stable_id(
        "smt_",
        MODEL_EXTRACTION_TASK_SCHEMA_VERSION,
        source_sha256,
        unit_id,
        evidence_start,
        evidence_end,
        digest,
    )
    return ModelExtractionTask(
        MODEL_EXTRACTION_TASK_SCHEMA_VERSION,
        task_id,
        source_id,
        source_sha256,
        unit_id,
        evidence_start,
        evidence_end,
        digest,
        evidence_text,
        tuple(sorted(CLAIM_TYPES)),
        MODEL_INSTRUCTION_VERSION,
        SEMANTIC_CANDIDATE_SCHEMA_VERSION,
        False,
        True,
    )


def validate_model_proposal(task: ModelExtractionTask, payload: Mapping[str, object]) -> dict[str, object]:
    """Validate only the task envelope, never semantic truth or acceptance."""

    forbidden = {
        "accepted",
        "may_index",
        "may_freeze",
        "may_accept_project",
        "validation_status",
        "validation_result_id",
    }
    present = sorted(forbidden.intersection(payload))
    if present:
        raise SemanticExtractionError(
            "model proposal contains authority fields: " + ",".join(present)
        )
    claim_type = payload.get("claim_type")
    if claim_type not in task.allowed_claim_types:
        raise SemanticExtractionError("model proposal claim_type is not allowed by the task")
    start = payload.get("evidence_start")
    end = payload.get("evidence_end")
    if isinstance(start, bool) or not isinstance(start, int):
        raise SemanticExtractionError("model proposal evidence_start must be an integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise SemanticExtractionError("model proposal evidence_end must be an integer")
    if not task.evidence_start <= start < end <= task.evidence_end:
        raise SemanticExtractionError("model proposal evidence span escapes the bound task evidence")
    evidence_text = payload.get("evidence_text")
    if not isinstance(evidence_text, str):
        raise SemanticExtractionError("model proposal evidence_text must be a string")
    local_start = start - task.evidence_start
    local_end = end - task.evidence_start
    if task.evidence_text[local_start:local_end] != evidence_text:
        raise SemanticExtractionError("model proposal evidence_text does not match the task source span")
    normalized = dict(payload)
    normalized["source_id"] = task.source_id
    normalized["unit_id"] = task.unit_id
    normalized["proposal_task_id"] = task.task_id
    normalized["requires_deterministic_validation"] = True
    normalized["may_accept_directly"] = False
    return normalized
