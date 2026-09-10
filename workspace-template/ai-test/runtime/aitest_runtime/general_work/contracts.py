from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from aitest_runtime.durable_core import RootDefinition, RuntimeError, SubjectRef, canonical_json, canonical_sha256

EXTENSION_ID = "r1_general_work"
EXTENSION_VERSION = "1.0.0"
ROOTS = tuple(RootDefinition(kind, prefix, 1, create, created, kind,
                            frozenset({create, transition}), frozenset({created, changed}))
              for kind, prefix, create, created, transition, changed in (
                  ("GENERAL_WORK", "general-work:v1:", "CREATE_GENERAL_WORK", "general_work.created.v1", "TRANSITION_GENERAL_WORK", "general_work.lifecycle_changed.v1"),
                  ("RUNTIME_DIAGNOSIS", "runtime-diagnosis:v1:", "CREATE_RUNTIME_DIAGNOSIS", "runtime_diagnosis.created.v1", "TRANSITION_RUNTIME_DIAGNOSIS", "runtime_diagnosis.lifecycle_changed.v1")))
TRANSITIONS = {
    "CREATED": frozenset({"ACTIVE", "CANCELLED", "FAILED"}),
    "ACTIVE": frozenset({"PAUSED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"}),
    "PAUSED": frozenset({"ACTIVE", "CANCELLED", "FAILED"}),
    "BLOCKED": frozenset({"ACTIVE", "CANCELLED", "FAILED"}),
    "COMPLETED": frozenset(), "FAILED": frozenset(), "CANCELLED": frozenset(),
}


def text(value, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise RuntimeError("JOB_SCHEMA_INVALID", f"{name} must be nonempty and at most {limit} characters")
    return value


def definition(kind: str) -> RootDefinition:
    found = next((r for r in ROOTS if r.subject_kind == kind), None)
    if found is None:
        raise RuntimeError("JOB_KIND_UNSUPPORTED", "only GeneralWork and RuntimeDiagnosis are handled here")
    return found


def job_subject(kind: str, operation_id: str) -> SubjectRef:
    root = definition(kind)
    return SubjectRef(kind, root.id_prefix + canonical_sha256(text(operation_id, "operation_id")))


def host_reference(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {"schema_version", "host_session_id", "host_message_id", "host_tool_message_id", "parent_message_id", "source_ref", "source_digest", "observed_at", "valid_until"}
    if not isinstance(value, Mapping) or set(value) != fields or value.get("schema_version") != 1 or isinstance(value.get("schema_version"), bool):
        raise RuntimeError("JOB_HOST_REFERENCE_INVALID", "host_turn_ref must use the verified provenance schema")
    out = dict(value)
    for key in fields - {"schema_version", "parent_message_id"}:
        text(out[key], "host_turn_ref." + key, 1024)
    if out["parent_message_id"] is not None:
        text(out["parent_message_id"], "host_turn_ref.parent_message_id")
    if len(out["source_digest"]) != 64 or any(c not in "0123456789abcdef" for c in out["source_digest"]):
        raise RuntimeError("JOB_HOST_REFERENCE_INVALID", "source_digest must be a SHA256 hex digest")
    # Authentication, expiry and actual HostToolContext checking belongs to the
    # admission service; a JSON reference alone is never execution permission.
    return out


@dataclass(frozen=True)
class JobState:
    job_id: str
    subject_kind: str | None = None
    status: str | None = None
    operation_id: str | None = None
    intent: str | None = None
    host_turn_ref: Mapping[str, Any] = field(default_factory=dict)
    summary: str | None = None
    evidence_ref: Mapping[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "subject_kind": self.subject_kind, "status": self.status,
                "operation_id": self.operation_id, "intent": self.intent, "host_turn_ref": dict(self.host_turn_ref),
                "summary": self.summary, "evidence_ref": dict(self.evidence_ref) if self.evidence_ref else None,
                "created_at": self.created_at, "updated_at": self.updated_at}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> JobState:
        return cls(**dict(value))


def validate_create(payload: Mapping[str, Any]) -> None:
    if set(payload) != {"subject", "root_version", "creation_command", "operation_id", "host_turn_ref", "intent"}:
        raise RuntimeError("JOB_SCHEMA_INVALID", "creation fields must match the typed root contract")
    subject = payload["subject"]
    if not isinstance(subject, Mapping) or set(subject) != {"subject_kind", "subject_id"}:
        raise RuntimeError("JOB_SCHEMA_INVALID", "invalid subject reference")
    expected = job_subject(subject["subject_kind"], payload["operation_id"])
    if subject != expected.to_dict():
        raise RuntimeError("ROOT_REFERENCE_MISMATCH", "job id must be runtime-derived from its consumed operation")
    text(payload["intent"], "intent", 4096)
    host_reference(payload["host_turn_ref"])


def validate_transition(payload: Mapping[str, Any], state: JobState) -> None:
    if set(payload) != {"subject", "from_status", "target_status", "summary", "evidence_ref"}:
        raise RuntimeError("JOB_SCHEMA_INVALID", "transition fields must match the typed root contract")
    if payload["from_status"] != state.status or payload["target_status"] not in TRANSITIONS.get(state.status, ()):
        raise RuntimeError("JOB_TRANSITION_FORBIDDEN", "invalid or terminal job lifecycle transition")
    summary = payload["summary"]
    if summary is not None:
        text(summary, "summary", 4096)
    if payload["target_status"] in {"COMPLETED", "FAILED", "BLOCKED"} and summary is None:
        raise RuntimeError("JOB_OUTCOME_REQUIRED", "completion, failure or blockage needs an explicit summary")
    ref = payload["evidence_ref"]
    if ref is not None:
        if not isinstance(ref, Mapping) or set(ref) != {"artifact_ref", "sha256"}:
            raise RuntimeError("JOB_SCHEMA_INVALID", "evidence must be a bounded artifact reference")
        text(ref["artifact_ref"], "artifact_ref", 1024)
        digest = text(ref["sha256"], "sha256", 64)
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RuntimeError("JOB_SCHEMA_INVALID", "artifact sha256 is invalid")
    if len(canonical_json(payload).encode()) > 8192:
        raise RuntimeError("JOB_SCHEMA_INVALID", "transition receipt exceeds the bounded payload")
