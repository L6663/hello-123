"""Typed contracts for Stage 4 end-to-end knowledge projects.

Stage 4 assembles existing deterministic stages into a self-contained project.
It never performs project acceptance, release certification, or freeze approval.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

KNOWLEDGE_PROJECT_SCHEMA_VERSION: Final = "tkr-knowledge-project-v1"
KNOWLEDGE_MANIFEST_SCHEMA_VERSION: Final = "tkr-knowledge-manifest-v1"
KNOWLEDGE_VERIFICATION_SCHEMA_VERSION: Final = "tkr-knowledge-verification-v1"
KNOWLEDGE_ANSWER_SCHEMA_VERSION: Final = "tkr-knowledge-answer-v1"
KNOWLEDGE_ANSWER_VERIFICATION_SCHEMA_VERSION: Final = "tkr-knowledge-answer-verification-v1"
KNOWLEDGE_SYSTEM_VERSION: Final = "5.9.0-final"


class KnowledgeProjectError(ValueError):
    """Raised when a project cannot be built, verified, or queried safely."""


@dataclass(frozen=True, slots=True)
class KnowledgeProjectPolicy:
    index_mode: str = "review"
    max_candidates: int = 200_000
    max_findings: int = 50_000
    max_model_tasks: int = 50_000
    max_clause_characters: int = 600
    emit_model_tasks: bool = True
    reuse_verified_project: bool = False
    replace_existing_project: bool = False

    def __post_init__(self) -> None:
        if self.index_mode not in {"review", "canonical"}:
            raise KnowledgeProjectError("index_mode must be review or canonical")
        for name in (
            "max_candidates",
            "max_findings",
            "max_model_tasks",
            "max_clause_characters",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise KnowledgeProjectError(f"{name} must be a positive integer")
        for name in (
            "emit_model_tasks",
            "reuse_verified_project",
            "replace_existing_project",
        ):
            if not isinstance(getattr(self, name), bool):
                raise KnowledgeProjectError(f"{name} must be boolean")
        if self.reuse_verified_project and self.replace_existing_project:
            raise KnowledgeProjectError(
                "reuse_verified_project and replace_existing_project are mutually exclusive"
            )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class KnowledgeProjectReport:
    schema_version: str
    system_version: str
    project_id: str
    status: str
    index_mode: str
    source_id: str
    source_filename: str
    source_suffix: str
    raw_source_sha256: str
    normalized_source_sha256: str
    selected_encoding: str
    unit_count: int
    semantic_candidate_count: int
    accepted_claim_count: int
    entity_count: int
    fact_count: int
    conflict_count: int
    ambiguity_group_count: int
    anomaly_finding_count: int
    structure_finding_count: int
    semantic_finding_count: int
    index_logical_sha256: str
    database_sha256: str
    recommended_action: str
    warnings: tuple[str, ...]
    policy: dict[str, object]
    may_query_typed: bool
    may_answer_open_queries: bool
    project_acceptance_performed: bool
    may_accept_project: bool
    release_candidate: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True, slots=True)
class ProjectFileRecord:
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class KnowledgeProjectManifest:
    schema_version: str
    system_version: str
    project_id: str
    source_id: str
    raw_source_sha256: str
    normalized_source_sha256: str
    files: tuple[ProjectFileRecord, ...]
    immutable_roots: tuple[str, ...]
    project_acceptance_performed: bool
    may_accept_project: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["files"] = [item.to_dict() for item in self.files]
        payload["immutable_roots"] = list(self.immutable_roots)
        return payload


@dataclass(frozen=True, slots=True)
class KnowledgeProjectVerification:
    schema_version: str
    system_version: str
    project_id: str
    status: str
    valid: bool
    checked_file_count: int
    reason_codes: tuple[str, ...]
    source_id: str
    raw_source_sha256: str
    normalized_source_sha256: str
    index_logical_sha256: str
    may_query_typed: bool
    project_acceptance_performed: bool
    may_accept_project: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True, slots=True)
class KnowledgeAnswerPacket:
    schema_version: str
    system_version: str
    answer_packet_id: str
    project_id: str
    project_manifest_sha256: str
    source_id: str
    raw_source_sha256: str
    normalized_source_sha256: str
    question: str
    qa_packet: dict[str, object]
    may_present: bool
    project_acceptance_performed: bool
    may_accept_project: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class KnowledgeAnswerVerification:
    schema_version: str
    system_version: str
    status: str
    accepted: bool
    reason_codes: tuple[str, ...]
    supplied_answer_packet_id: str
    expected_answer_packet_id: str
    project_id: str
    project_valid: bool
    strict_packet_valid: bool
    project_acceptance_performed: bool
    may_accept_project: bool
    may_freeze: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


__all__ = [
    "KNOWLEDGE_ANSWER_SCHEMA_VERSION",
    "KNOWLEDGE_ANSWER_VERIFICATION_SCHEMA_VERSION",
    "KNOWLEDGE_MANIFEST_SCHEMA_VERSION",
    "KNOWLEDGE_PROJECT_SCHEMA_VERSION",
    "KNOWLEDGE_SYSTEM_VERSION",
    "KNOWLEDGE_VERIFICATION_SCHEMA_VERSION",
    "KnowledgeAnswerPacket",
    "KnowledgeAnswerVerification",
    "KnowledgeProjectError",
    "KnowledgeProjectManifest",
    "KnowledgeProjectPolicy",
    "KnowledgeProjectReport",
    "KnowledgeProjectVerification",
    "ProjectFileRecord",
]
