from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.execution_context import (
    BuildExecutionContextRequest,
    ContextTarget,
    EventCursor,
)

from .contracts import ARCHITECTURE_BASELINE_REF, KnowledgeScopeIdentity, R3E1Error
from .retrieval import KnowledgeRetrievalAdapter, KnowledgeRetrievalResult


@dataclass(frozen=True)
class BoundedSessionHandoff:
    session_ref: str | None
    retrieval_receipt_digest: str
    knowledge_scope_identity: KnowledgeScopeIdentity
    transcript_persisted: bool = False

    def __post_init__(self) -> None:
        if self.session_ref is not None and (not isinstance(self.session_ref, str) or not self.session_ref.strip()):
            raise R3E1Error("R3_E1_SCHEMA_INVALID", "session_ref must be null or non-empty")
        if self.transcript_persisted:
            raise R3E1Error("R3_E1_SCOPE_MISMATCH", "R3.E1 cannot persist a Session transcript as Knowledge")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_ref": self.session_ref,
            "retrieval_receipt_digest": self.retrieval_receipt_digest,
            "knowledge_scope_identity": self.knowledge_scope_identity.to_dict(),
            "transcript_persisted": self.transcript_persisted,
        }


def bounded_session_handoff(result: KnowledgeRetrievalResult, session_ref: str | None = None) -> BoundedSessionHandoff:
    return BoundedSessionHandoff(
        session_ref=session_ref,
        retrieval_receipt_digest=result.result_digest,
        knowledge_scope_identity=result.scope_identity,
    )


def build_context_request(
    result: KnowledgeRetrievalResult,
    *,
    execution_attempt_id: str,
    mission_id: str,
    cursor: EventCursor,
    target: ContextTarget,
    policy_id: str,
    policy_version: int,
) -> BuildExecutionContextRequest:
    knowledge_set, omissions = KnowledgeRetrievalAdapter.to_knowledge_set(result)
    if len(knowledge_set.records) > 24:
        raise R3E1Error("R3_E1_RETRIEVAL_BUDGET_EXCEEDED", "Context Knowledge item count exceeds frozen R1.3A budget")
    handoff = bounded_session_handoff(result, result.retrieval_receipt.get("session_ref"))
    return BuildExecutionContextRequest(
        execution_attempt_id=execution_attempt_id,
        mission_id=mission_id,
        cursor=cursor,
        target=target,
        knowledge_set=knowledge_set,
        policy_id=policy_id,
        policy_version=policy_version,
        knowledge_scope={
            **result.scope_identity.to_dict(),
            "architecture_baseline_ref": ARCHITECTURE_BASELINE_REF,
            "r3_e1_result_digest": result.result_digest,
            "r3_e1_context_omissions": omissions,
            "r2_5_session_ref": handoff.session_ref,
        },
    )
