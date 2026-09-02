from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, RuntimeError, canonical_sha256

from .contracts import (
    ARM_RUNTIME_VERIFICATION,
    AUTHORIZE_RESUME,
    AUTH_REQUIRED,
    CLOSE_AUTH_CONTEXT,
    CONTEXT_CLOSED,
    CONTEXT_EXPIRED,
    CONTEXT_REVOKED,
    EXPIRE_AUTH_CONTEXT,
    HUMAN_GATE_LINKED,
    LINK_HUMAN_GATE,
    REQUEST_AUTH_CONTEXT,
    RESUME_AUTHORIZED,
    RUNTIME_VERIFIED,
    SUTAuthContext,
    SUTAuthContextScope,
    R3E2Error,
    R3E2State,
    REVOKE_AUTH_CONTEXT,
    VERIFY_RUNTIME_AUTH,
    VERIFICATION_PENDING,
    validate_transition,
)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _origin(payload: Mapping[str, Any], mission_id: str) -> dict[str, Any]:
    origin = _mapping(payload.get("origin_lineage"), "origin_lineage")
    if origin.get("mission_id") != mission_id:
        raise R3E2Error("R3_E2_SCOPE_MISMATCH", "origin_lineage.mission_id must match command mission_id")
    for key in ("task_id", "root_attempt_id", "attempt_id", "session_id", "case_step_ref"):
        if key in origin and origin[key] is not None:
            _text(origin[key], f"origin_lineage.{key}")
    return origin


def _context(payload: Mapping[str, Any]) -> SUTAuthContext:
    return SUTAuthContext.from_dict(payload.get("context") or {})


def _verify_digest(payload: Mapping[str, Any]) -> None:
    expected = canonical_sha256({key: value for key, value in payload.items() if key != "payload_digest"})
    if payload.get("payload_digest") != expected:
        raise R3E2Error("R3_E2_PROVENANCE_INVALID", "event/command payload digest does not match immutable payload")


def _validate_base(command_or_event: Any, payload: Mapping[str, Any]) -> tuple[SUTAuthContext, dict[str, Any]]:
    context = _context(payload)
    origin = _origin(payload, command_or_event.mission_id)
    _verify_digest(payload)
    if context.lineage_refs.get("origin_mission_id") not in (None, command_or_event.mission_id):
        raise R3E2Error("R3_E2_SCOPE_MISMATCH", "context lineage origin mission differs from command mission")
    return context, origin


def _same_identity(left: SUTAuthContext, right: SUTAuthContext) -> None:
    if left.identity != right.identity:
        raise R3E2Error("R3_E2_CONTEXT_ID_CONFLICT", "SUTAuthContext identity is immutable")
    if left.scope != right.scope:
        raise R3E2Error("R3_E2_SCOPE_MISMATCH", "SUTAuthContext scope is immutable")
    for name in ("auth_profile_ref", "auth_method"):
        if getattr(left, name) != getattr(right, name):
            raise R3E2Error("R3_E2_CONTEXT_ID_CONFLICT", f"immutable context field changed: {name}")


def _existing(state: R3E2State, context: SUTAuthContext) -> SUTAuthContext:
    value = state.context_key(context.identity.key)
    if value is None:
        raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context.identity.key}")
    _same_identity(value, context)
    return value


def _pending(event_type: str, context: SUTAuthContext, command: Any, origin: Mapping[str, Any]) -> list[PendingEvent]:
    payload = {
        "context": context.to_dict(),
        "origin_lineage": dict(origin),
    }
    payload["payload_digest"] = canonical_sha256(payload)
    return [PendingEvent(event_type, "SUT_AUTH_CONTEXT", context.identity.key, payload, session_id=command.session_id)]


def _validate_runtime_context(current: SUTAuthContext, incoming: SUTAuthContext) -> None:
    _same_identity(current, incoming)
    if incoming.status == "INVALID" and incoming.validation_status == "INVALID":
        if not incoming.lineage_refs.get("verification_failure_reason"):
            raise R3E2Error("R3_E2_VERIFICATION_FAILED", "invalid runtime verification requires an explicit failure reason")
        return
    if incoming.status != "AUTHENTICATED" or incoming.validation_status != "VALID":
        raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "runtime verification must produce AUTHENTICATED/VALID or explicit INVALID")
    receipt = incoming.verification_receipt
    if receipt is None or not receipt.real_runtime:
        raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "HumanGate or fake verifier cannot produce VALID")
    if receipt.verifier_kind.upper() in {"MOCK", "FAKE", "NOT_CONFIGURED"}:
        raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "mock/fake/not-configured verifier cannot produce VALID")
    if receipt.scope_digest != incoming.scope.digest or receipt.source_ref.scope != incoming.scope:
        raise R3E2Error("R3_E2_SCOPE_MISMATCH", "runtime verification scope does not match SUTAuthContext scope")
    if incoming.browser_context_ref != receipt.browser_context_ref:
        raise R3E2Error("R3_E2_BROWSER_CONTEXT_MISMATCH", "runtime verification Browser context does not match context binding")
    if receipt.observed_lease_owner != incoming.browser_context_ref.observed_lease_owner:
        raise R3E2Error("R3_E2_BROWSER_LEASE_MISMATCH", "runtime verification lease does not match expected lease")
    if receipt.authenticated_principal_ref != incoming.authenticated_principal_ref:
        raise R3E2Error("R3_E2_PRINCIPAL_MISMATCH", "runtime principal does not match context principal")
    if receipt.source_ref.source_kind != "RUNTIME_VERIFICATION":
        raise R3E2Error("R3_E2_PROVENANCE_INVALID", "VALID requires RUNTIME_VERIFICATION source provenance")


class R3E2CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        if not isinstance(composed, ComposedRuntimeState):
            raise R3E2Error("EXTENSION_SCHEMA_MISMATCH", "R3.E2 requires composed runtime state")
        if composed.core_state.mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {command.mission_id}")
        payload = _mapping(command.payload, "command.payload")
        context, origin = _validate_base(command, payload)
        state = composed.extension_state("r3_e2_sut_auth_context")
        if not isinstance(state, R3E2State):
            raise R3E2Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.E2 state")
        current = state.context_key(context.identity.key)

        if command.type == REQUEST_AUTH_CONTEXT:
            if context.status != "AUTH_REQUIRED" or context.validation_status != "UNKNOWN":
                raise R3E2Error("R3_E2_STATUS_INVALID", "new context must start AUTH_REQUIRED/UNKNOWN")
            if current is not None:
                raise R3E2Error("R3_E2_CONTEXT_ID_CONFLICT", "context identity already exists")
            return _pending(AUTH_REQUIRED, context, command, origin)

        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context.identity.key}")
        _same_identity(current, context)

        if command.type == LINK_HUMAN_GATE:
            if current.status != "AUTH_REQUIRED" or context.status != "HUMAN_GATE_PENDING":
                raise R3E2Error("R3_E2_STATUS_TRANSITION_INVALID", "HumanGate may only link from AUTH_REQUIRED")
            validate_transition(current.status, context.status)
            if context.human_gate_ref is None or context.human_gate_ref.status != "PENDING":
                raise R3E2Error("R3_E2_GATE_INVALID", "linked HumanGate must be pending")
            return _pending(HUMAN_GATE_LINKED, context, command, origin)

        if command.type == ARM_RUNTIME_VERIFICATION:
            if current.status != "HUMAN_GATE_PENDING" or context.status != "VERIFICATION_PENDING":
                raise R3E2Error("R3_E2_STATUS_TRANSITION_INVALID", "verification may only arm from HumanGate pending")
            validate_transition(current.status, context.status)
            if current.human_gate_ref is None or context.human_gate_ref is None or context.human_gate_ref.gate_id != current.human_gate_ref.gate_id or context.human_gate_ref.status != "APPROVED":
                raise R3E2Error("R3_E2_GATE_NOT_APPROVED", "approved HumanGate decision is required before verification")
            return _pending(VERIFICATION_PENDING, context, command, origin)

        if command.type == VERIFY_RUNTIME_AUTH:
            if current.status != "VERIFICATION_PENDING":
                raise R3E2Error("R3_E2_STATUS_TRANSITION_INVALID", "runtime verification requires VERIFICATION_PENDING")
            if context.status not in {"AUTHENTICATED", "INVALID"}:
                raise R3E2Error("R3_E2_RUNTIME_VERIFICATION_REQUIRED", "verification must produce VALID or explicit INVALID")
            validate_transition(current.status, context.status)
            _validate_runtime_context(current, context)
            return _pending(RUNTIME_VERIFIED, context, command, origin)

        if command.type == AUTHORIZE_RESUME:
            if current.status != "AUTHENTICATED" or current.validation_status != "VALID":
                raise R3E2Error("R3_E2_AUTH_REQUIRED", "resume requires AUTHENTICATED/VALID")
            if context.status != "AUTHENTICATED" or context.validation_status != "VALID" or context.continuation_proof is None:
                raise R3E2Error("R3_E2_CONTINUATION_INVALID", "resume authorization requires valid context and applied continuation proof")
            if current.human_gate_ref is None or context.continuation_proof.gate_id != current.human_gate_ref.gate_id:
                raise R3E2Error("R3_E2_CONTINUATION_INVALID", "continuation gate does not match HumanGate lineage")
            if current.browser_context_ref != context.browser_context_ref:
                raise R3E2Error("R3_E2_BROWSER_CONTEXT_MISMATCH", "resume must reuse the authenticated Browser context")
            if context.last_observed_at is not None and context.expires_at is not None and context.last_observed_at >= context.expires_at:
                raise R3E2Error("R3_E2_CONTEXT_EXPIRED", "cannot authorize resume after expires_at")
            return _pending(RESUME_AUTHORIZED, context, command, origin)

        if command.type == EXPIRE_AUTH_CONTEXT:
            if current.status not in {"HUMAN_GATE_PENDING", "VERIFICATION_PENDING", "AUTHENTICATED"} or context.status != "EXPIRED":
                raise R3E2Error("R3_E2_STATUS_TRANSITION_INVALID", "only active contexts can expire")
            validate_transition(current.status, context.status)
            observed_at = context.last_observed_at or ""
            if current.expires_at is not None and observed_at < current.expires_at:
                raise R3E2Error("R3_E2_NOT_EXPIRED", "context cannot expire before expires_at")
            return _pending(CONTEXT_EXPIRED, context, command, origin)

        if command.type == REVOKE_AUTH_CONTEXT:
            if current.status != "AUTHENTICATED" or context.status != "REVOKED":
                raise R3E2Error("R3_E2_STATUS_TRANSITION_INVALID", "only AUTHENTICATED contexts can be revoked")
            validate_transition(current.status, context.status)
            return _pending(CONTEXT_REVOKED, context, command, origin)

        if command.type == CLOSE_AUTH_CONTEXT:
            if current.status in {"EXPIRED", "INVALID", "REVOKED", "CLOSED"} or context.status != "CLOSED":
                raise R3E2Error("R3_E2_STATUS_TRANSITION_INVALID", "closed/terminal contexts cannot be reopened or closed again")
            validate_transition(current.status, context.status)
            return _pending(CONTEXT_CLOSED, context, command, origin)

        raise R3E2Error("R3_E2_COMMAND_NOT_OWNED", f"unsupported R3.E2 command: {command.type}")
