"""Project-bound strict QA packets and exact recomputation verification."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from .hashing import sha256_file
from .knowledge_models import (
    KNOWLEDGE_ANSWER_SCHEMA_VERSION,
    KNOWLEDGE_ANSWER_VERIFICATION_SCHEMA_VERSION,
    KNOWLEDGE_SYSTEM_VERSION,
    KnowledgeAnswerPacket,
    KnowledgeAnswerVerification,
    KnowledgeProjectError,
)
from .knowledge_project import verify_knowledge_project
from .strict_qa import answer_strict, verify_strict_packet


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeProjectError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KnowledgeProjectError(f"{label} must be a JSON object")
    return payload


def _answer_id(payload: Mapping[str, object]) -> str:
    return "kap_" + sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:32]


def answer_knowledge_project(
    project_directory: str | Path,
    question: str,
    *,
    source_id: str | None = None,
    retrieval_limit: int = 20,
    max_citations: int = 5,
) -> KnowledgeAnswerPacket:
    """Answer one supported typed question against a fully verified project."""
    root = Path(project_directory)
    verification = verify_knowledge_project(root)
    if not verification.valid:
        raise KnowledgeProjectError(
            "knowledge project failed verification: " + ",".join(verification.reason_codes)
        )
    project_report = _load_object(root / "project-report.json", "project report")
    manifest_hash = sha256_file(root / "project-manifest.json")
    effective_source = source_id or str(project_report.get("source_id", ""))
    if not effective_source:
        raise KnowledgeProjectError("project report lacks source_id")
    qa = answer_strict(
        root / "index" / "knowledge.sqlite",
        question,
        source_id=effective_source,
        retrieval_limit=retrieval_limit,
        max_citations=max_citations,
        verify_database=True,
        report_path=root / "index" / "knowledge.report.json",
    )
    base: dict[str, object] = {
        "schema_version": KNOWLEDGE_ANSWER_SCHEMA_VERSION,
        "system_version": KNOWLEDGE_SYSTEM_VERSION,
        "project_id": verification.project_id,
        "project_manifest_sha256": manifest_hash,
        "source_id": effective_source,
        "raw_source_sha256": verification.raw_source_sha256,
        "normalized_source_sha256": verification.normalized_source_sha256,
        "question": question,
        "qa_packet": qa.to_dict(),
        "may_present": bool(qa.may_present),
        "project_acceptance_performed": False,
        "may_accept_project": False,
        "may_freeze": False,
    }
    identifier = _answer_id(base)
    return KnowledgeAnswerPacket(
        KNOWLEDGE_ANSWER_SCHEMA_VERSION,
        KNOWLEDGE_SYSTEM_VERSION,
        identifier,
        verification.project_id,
        manifest_hash,
        effective_source,
        verification.raw_source_sha256,
        verification.normalized_source_sha256,
        question,
        qa.to_dict(),
        bool(qa.may_present),
        False,
        False,
        False,
    )


def _load_answer(value: Mapping[str, object] | str | Path) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    return _load_object(Path(value), "knowledge answer packet")


def verify_knowledge_answer(
    project_directory: str | Path,
    packet: Mapping[str, object] | str | Path,
) -> KnowledgeAnswerVerification:
    """Recompute a Stage 4 answer and reject any changed project or QA field."""
    root = Path(project_directory)
    reasons: list[str] = []
    supplied_id = expected_id = project_id = ""
    project_valid = strict_valid = False
    try:
        supplied = _load_answer(packet)
        supplied_id = str(supplied.get("answer_packet_id", ""))
        project_id = str(supplied.get("project_id", ""))
        project_check = verify_knowledge_project(root)
        project_valid = project_check.valid
        if not project_valid:
            reasons.append("PROJECT_INTEGRITY_REJECTED")
        qa_payload = supplied.get("qa_packet")
        if not isinstance(qa_payload, dict):
            reasons.append("QA_PACKET_INVALID")
            qa_payload = {}
        else:
            strict_check = verify_strict_packet(
                root / "index" / "knowledge.sqlite",
                qa_payload,
                report_path=root / "index" / "knowledge.report.json",
            )
            strict_valid = strict_check.accepted
            if not strict_valid:
                reasons.extend(("STRICT_QA_PACKET_REJECTED", *strict_check.reason_codes))

        question = supplied.get("question")
        source_id = supplied.get("source_id")
        retrieval_limit = qa_payload.get("retrieval_limit")
        max_citations = qa_payload.get("max_citations")
        if not isinstance(question, str):
            reasons.append("ANSWER_QUESTION_INVALID")
        if not isinstance(source_id, str) or not source_id:
            reasons.append("ANSWER_SOURCE_ID_INVALID")
        if isinstance(retrieval_limit, bool) or not isinstance(retrieval_limit, int):
            reasons.append("ANSWER_RETRIEVAL_LIMIT_INVALID")
        if isinstance(max_citations, bool) or not isinstance(max_citations, int):
            reasons.append("ANSWER_CITATION_LIMIT_INVALID")

        if not reasons:
            expected = answer_knowledge_project(
                root,
                question,
                source_id=source_id,
                retrieval_limit=retrieval_limit,
                max_citations=max_citations,
            )
            expected_payload = expected.to_dict()
            expected_id = expected.answer_packet_id
            if _canonical_json(supplied) != _canonical_json(expected_payload):
                reasons.append("KNOWLEDGE_ANSWER_RECOMPUTATION_MISMATCH")
            if supplied_id != expected_id:
                reasons.append("KNOWLEDGE_ANSWER_ID_MISMATCH")
            if supplied.get("project_manifest_sha256") != sha256_file(root / "project-manifest.json"):
                reasons.append("PROJECT_MANIFEST_BINDING_MISMATCH")
            if supplied.get("project_acceptance_performed") or supplied.get("may_accept_project") or supplied.get("may_freeze"):
                reasons.append("ILLEGAL_ACCEPTANCE_OR_FREEZE_AUTHORITY")
    except Exception as exc:
        reasons.extend(("ANSWER_VERIFICATION_EXCEPTION", type(exc).__name__))

    unique = tuple(dict.fromkeys(reasons))
    accepted = not unique and project_valid and strict_valid
    return KnowledgeAnswerVerification(
        KNOWLEDGE_ANSWER_VERIFICATION_SCHEMA_VERSION,
        KNOWLEDGE_SYSTEM_VERSION,
        "accepted" if accepted else "rejected",
        accepted,
        unique if unique else (
            "PROJECT_HASH_CHAIN_VERIFIED",
            "STRICT_QA_PACKET_RECOMPUTED",
            "KNOWLEDGE_ANSWER_RECOMPUTED_EXACTLY",
        ),
        supplied_id,
        expected_id,
        project_id,
        project_valid,
        strict_valid,
        False,
        False,
        False,
    )


__all__ = ["answer_knowledge_project", "verify_knowledge_answer"]
