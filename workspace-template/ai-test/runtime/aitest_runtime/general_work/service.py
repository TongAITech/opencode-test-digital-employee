from __future__ import annotations

from typing import Any, Mapping
from aitest_runtime.durable_core import ActorRef, CommandEnvelope, RuntimeError, SubjectRef, SubjectState, canonical_sha256
from .contracts import EXTENSION_ID, definition, host_reference, job_subject, text


class GeneralWorkService:
    """Trusted internal lifecycle port, not a model-facing authorization bypass.

    Admission must verify actual HostToolContext before calling this port. Job
    creation grants no file/network/tool permission and makes no test verdict.
    """
    def __init__(self, runtime):
        self.runtime = runtime
        runtime.extension_registry.manifest(EXTENSION_ID)

    def create(self, *, subject_kind: str, operation_id: str, host_turn_ref: Mapping[str, Any], intent: str, actor: ActorRef) -> SubjectState:
        root = definition(subject_kind)
        subject = job_subject(subject_kind, operation_id)
        command_id = "r1:job:create:" + canonical_sha256(text(operation_id, "operation_id"))
        payload = {"subject": subject.to_dict(), "root_version": root.version, "creation_command": root.creation_command,
                   "operation_id": operation_id, "host_turn_ref": host_reference(host_turn_ref), "intent": text(intent, "intent", 4096)}
        result = self.runtime.execute(CommandEnvelope(command_id, root.creation_command, subject.subject_id, 0, actor, payload,
                                                      idempotency_key=command_id, correlation_id=operation_id))
        if not result.ok:
            raise result.error or RuntimeError("JOB_CREATE_FAILED", "job creation rejected")
        return self.runtime.get_subject_state(subject)

    def transition(self, subject: SubjectRef, *, expected_seq: int, request_id: str, target_status: str,
                   actor: ActorRef, summary: str | None = None, evidence_ref: Mapping[str, Any] | None = None) -> SubjectState:
        root = definition(subject.subject_kind)
        state = self.runtime.get_subject_state(subject)
        cursor = self.runtime.replay_composed(subject.subject_id, through_seq=expected_seq)
        if cursor.seq != expected_seq or cursor.subject != subject:
            raise RuntimeError("EXPECTED_SEQ_MISMATCH", "transition needs an existing exact subject cursor")
        prior = cursor.extension_state(EXTENSION_ID)
        command_id = "r1:job:transition:" + canonical_sha256(text(request_id, "request_id"))
        command_type = next(c for c in root.command_types if c != root.creation_command)
        payload = {"subject": subject.to_dict(), "from_status": prior.status, "target_status": target_status,
                   "summary": summary, "evidence_ref": dict(evidence_ref) if evidence_ref is not None else None}
        result = self.runtime.execute(CommandEnvelope(command_id, command_type, subject.subject_id, expected_seq, actor, payload,
                                                      idempotency_key=command_id, correlation_id=request_id))
        if not result.ok:
            raise result.error or RuntimeError("JOB_TRANSITION_FAILED", "job transition rejected")
        return self.runtime.get_subject_state(subject)
