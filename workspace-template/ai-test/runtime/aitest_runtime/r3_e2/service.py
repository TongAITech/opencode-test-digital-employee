from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandEnvelope, CommandResult, RuntimeService, canonical_sha256

from .contracts import (
    ARM_RUNTIME_VERIFICATION,
    AUTHORIZE_RESUME,
    AUTH_REQUIRED,
    CLOSE_AUTH_CONTEXT,
    EXPIRE_AUTH_CONTEXT,
    HumanGateReference,
    LINK_HUMAN_GATE,
    REQUEST_AUTH_CONTEXT,
    REVOKE_AUTH_CONTEXT,
    R3E2Error,
    R3E2State,
    RuntimeVerificationReceipt,
    SUTAuthContext,
    SUTAuthContextIdentity,
    SUTAuthContextScope,
    VERIFY_RUNTIME_AUTH,
    BrowserContextRef,
    AuthSourceRef,
)
from .ports import BrowserAuthContextPort, ContinuationPort, HumanGatePort, require_real_runtime_verification


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R3E2Error("R3_E2_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _actor(value: ActorRef | Mapping[str, Any]) -> ActorRef:
    if isinstance(value, ActorRef):
        return value
    if not isinstance(value, Mapping):
        raise R3E2Error("R3_E2_SCHEMA_INVALID", "actor must be an object")
    return ActorRef(_text(value.get("type"), "actor.type"), _text(value.get("id"), "actor.id"))


@dataclass(frozen=True)
class R3E2OperationResult:
    command_result: CommandResult
    value: Any = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def error(self) -> Any:
        return self.command_result.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_result": self.command_result.to_dict(),
            "value": self.value.to_dict() if hasattr(self.value, "to_dict") else self.value,
        }


class R3E2ApplicationService:
    def __init__(self, runtime_service: RuntimeService) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        runtime_service.extension_registry.manifest("r3_e2_sut_auth_context")
        self._runtime = runtime_service

    @property
    def runtime_service(self) -> RuntimeService:
        return self._runtime

    def get_context(self, mission_id: str, context_id: str, context_epoch: int | None = None) -> SUTAuthContext | None:
        state = self._runtime.replay_composed(mission_id).extension_state("r3_e2_sut_auth_context")
        if not isinstance(state, R3E2State):
            raise R3E2Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.E2 state")
        return state.context(context_id, context_epoch)

    @staticmethod
    def _duplicate(mission_id: str, context: SUTAuthContext, reason: str) -> R3E2OperationResult:
        result = CommandResult(
            "DUPLICATE",
            f"r3.e2:duplicate:{context.identity.key}",
            mission_id,
            duplicate_of=reason,
            state_hash=canonical_sha256(context.to_dict()),
        )
        return R3E2OperationResult(result, context)

    def _run(
        self,
        *,
        command_type: str,
        mission_id: str,
        context: SUTAuthContext,
        origin_lineage: Mapping[str, Any],
        actor: ActorRef | Mapping[str, Any],
        idempotency_key: str | None,
        correlation_id: str | None,
        command_id: str | None,
        session_id: str | None,
    ) -> CommandResult:
        mission_id = _text(mission_id, "mission_id")
        origin = dict(origin_lineage)
        origin["mission_id"] = mission_id
        if session_id is not None:
            origin["session_id"] = session_id
        payload: dict[str, Any] = {"context": context.to_dict(), "origin_lineage": origin}
        payload["payload_digest"] = canonical_sha256(payload)
        stable_key = idempotency_key or context.record_digest or context.identity.key
        command_id = command_id or f"r3.e2:{command_type}:{context.identity.key}:{stable_key}"
        return self._runtime.execute(
            CommandEnvelope(
                command_id=_text(command_id, "command_id"),
                type=command_type,
                mission_id=mission_id,
                session_id=session_id,
                expected_seq=self._runtime.get_head_seq(mission_id),
                actor=_actor(actor),
                payload=payload,
                idempotency_key=idempotency_key or command_id,
                correlation_id=correlation_id or command_id,
                schema_version=1,
            )
        )

    def request_auth_context(
        self,
        *,
        mission_id: str,
        identity: SUTAuthContextIdentity,
        scope: SUTAuthContextScope,
        browser_context_ref: BrowserContextRef,
        lineage_refs: Mapping[str, Any],
        auth_profile_ref: str | None = None,
        source_refs: tuple[AuthSourceRef, ...] | list[AuthSourceRef] = (),
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"},
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E2OperationResult:
        context = SUTAuthContext(
            identity=identity,
            scope=scope,
            auth_profile_ref=auth_profile_ref,
            authenticated_principal_ref=None,
            auth_method="HUMAN_4A",
            status="AUTH_REQUIRED",
            validation_status="UNKNOWN",
            browser_context_ref=browser_context_ref,
            human_gate_ref=None,
            verification_receipt=None,
            lineage_refs={**dict(lineage_refs), "origin_mission_id": mission_id},
            source_refs=tuple(source_refs),
            last_observed_at=browser_context_ref.observed_at,
        )
        existing = self.get_context(mission_id, identity.sut_auth_context_id, identity.context_epoch)
        if existing is not None and existing.to_dict() == context.to_dict():
            return self._duplicate(mission_id, existing, "existing_auth_required_context")
        result = self._run(command_type=REQUEST_AUTH_CONTEXT, mission_id=mission_id, context=context, origin_lineage=context.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=correlation_id, command_id=command_id, session_id=context.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def link_human_gate(
        self,
        *,
        mission_id: str,
        context_id: str,
        context_epoch: int,
        gate_ref: HumanGateReference,
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"},
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        if current.status == "HUMAN_GATE_PENDING" and current.human_gate_ref == gate_ref:
            return self._duplicate(mission_id, current, "human_gate_linked")
        context = replace(current, status="HUMAN_GATE_PENDING", human_gate_ref=gate_ref, last_observed_at=current.last_observed_at, record_digest=None)
        result = self._run(command_type=LINK_HUMAN_GATE, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=correlation_id, command_id=command_id, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def arm_runtime_verification(
        self,
        *,
        mission_id: str,
        context_id: str,
        context_epoch: int,
        gate_ref: HumanGateReference,
        observed_at: str,
        human_gate_port: HumanGatePort | None = None,
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"},
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        decision = human_gate_port.read_decision(gate_ref) if human_gate_port is not None else gate_ref
        if current.status == "VERIFICATION_PENDING" and current.human_gate_ref == decision:
            return self._duplicate(mission_id, current, "verification_armed")
        context = replace(current, status="VERIFICATION_PENDING", human_gate_ref=decision, last_observed_at=_text(observed_at, "observed_at"), record_digest=None)
        result = self._run(command_type=ARM_RUNTIME_VERIFICATION, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=correlation_id, command_id=command_id, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def verify_runtime_auth(
        self,
        *,
        mission_id: str,
        context_id: str,
        context_epoch: int,
        browser_auth_port: BrowserAuthContextPort | None = None,
        receipt: RuntimeVerificationReceipt | None = None,
        policy: Mapping[str, Any] | None = None,
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"},
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        if current.status != "VERIFICATION_PENDING":
            raise R3E2Error("R3_E2_STATUS_TRANSITION_INVALID", "runtime verification requires VERIFICATION_PENDING")
        if current.browser_context_ref is None:
            raise R3E2Error("R3_E2_BROWSER_CONTEXT_MISMATCH", "context has no Browser binding")
        if receipt is None:
            if browser_auth_port is None:
                raise R3E2Error("SUT_AUTH_CONTEXT_RUNTIME_DEPENDENCY_GAP", "no BrowserAuthContext runtime verifier is configured")
            receipt = browser_auth_port.verify_authenticated_runtime(browser_context_ref=current.browser_context_ref, requested_scope=current.scope, policy=policy or {})
        try:
            require_real_runtime_verification(receipt, scope=current.scope, expected_browser_context_ref=current.browser_context_ref)
        except ValueError as exc:
            raise R3E2Error(str(exc).split(":", 1)[0], str(exc).split(":", 1)[-1].strip()) from exc
        if current.status == "AUTHENTICATED" and current.verification_receipt is not None and current.verification_receipt.verification_id == receipt.verification_id:
            return self._duplicate(mission_id, current, "runtime_verified")
        context = replace(
            current,
            status="AUTHENTICATED",
            validation_status="VALID",
            authenticated_principal_ref=receipt.authenticated_principal_ref,
            browser_context_ref=receipt.browser_context_ref,
            verification_receipt=receipt,
            source_refs=tuple(dict((item.source_ref_id, item) for item in (*current.source_refs, receipt.source_ref)).values()),
            verified_at=receipt.verified_at,
            expires_at=receipt.expires_at,
            last_observed_at=receipt.verified_at,
            record_digest=None,
        )
        result = self._run(command_type=VERIFY_RUNTIME_AUTH, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=correlation_id, command_id=command_id, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def record_verification_failure(
        self,
        *,
        mission_id: str,
        context_id: str,
        context_epoch: int,
        reason: str,
        observed_at: str,
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"},
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        context = replace(current, status="INVALID", validation_status="INVALID", last_observed_at=_text(observed_at, "observed_at"), lineage_refs={**current.lineage_refs, "verification_failure_reason": _text(reason, "reason")}, record_digest=None)
        result = self._run(command_type=VERIFY_RUNTIME_AUTH, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=correlation_id, command_id=command_id, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def authorize_resume(
        self,
        *,
        mission_id: str,
        context_id: str,
        context_epoch: int,
        browser_auth_port: BrowserAuthContextPort,
        continuation_port: ContinuationPort,
        observed_at: str,
        actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"},
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        command_id: str | None = None,
    ) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        if current.status == "AUTHENTICATED" and current.validation_status == "VALID" and current.expires_at is not None and observed_at >= current.expires_at:
            self.expire(
                mission_id=mission_id,
                context_id=context_id,
                context_epoch=context_epoch,
                observed_at=observed_at,
                idempotency_key=f"{idempotency_key or context_id}:expiry",
            )
            raise R3E2Error("R3_E2_CONTEXT_EXPIRED", "resume observed an expired AUTHENTICATED/VALID context")
        if current.status != "AUTHENTICATED" or current.validation_status != "VALID" or current.expires_at is None:
            raise R3E2Error("R3_E2_AUTH_REQUIRED", "resume requires an unexpired AUTHENTICATED/VALID context")
        if current.browser_context_ref is None or current.human_gate_ref is None:
            raise R3E2Error("R3_E2_CONTINUATION_INVALID", "resume requires Browser and HumanGate lineage")
        reuse = browser_auth_port.reuse_context(browser_context_ref=current.browser_context_ref, requested_scope=current.scope)
        if not reuse.reused or reuse.browser_context_ref != current.browser_context_ref or reuse.scope_digest != current.scope.digest:
            raise R3E2Error("R3_E2_BROWSER_CONTEXT_MISMATCH", "Browser context reuse receipt does not match authenticated context")
        proof = continuation_port.record_resume(mission_id=mission_id, gate_ref=current.human_gate_ref, auth_context_id=current.identity.sut_auth_context_id, browser_context_ref=current.browser_context_ref)
        if current.continuation_proof is not None and current.continuation_proof.to_dict() == proof.to_dict():
            return self._duplicate(mission_id, current, "resume_authorized")
        context = replace(current, continuation_proof=proof, last_observed_at=_text(observed_at, "observed_at"), record_digest=None)
        result = self._run(command_type=AUTHORIZE_RESUME, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=correlation_id, command_id=command_id, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def expire(self, *, mission_id: str, context_id: str, context_epoch: int, observed_at: str, actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"}, idempotency_key: str | None = None) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        if current.status == "EXPIRED":
            return self._duplicate(mission_id, current, "context_expired")
        context = replace(current, status="EXPIRED", validation_status="INVALID", last_observed_at=_text(observed_at, "observed_at"), record_digest=None)
        result = self._run(command_type=EXPIRE_AUTH_CONTEXT, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=None, command_id=None, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def revoke(self, *, mission_id: str, context_id: str, context_epoch: int, observed_at: str, actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"}, idempotency_key: str | None = None) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        if current.status == "REVOKED":
            return self._duplicate(mission_id, current, "context_revoked")
        context = replace(current, status="REVOKED", validation_status="INVALID", last_observed_at=_text(observed_at, "observed_at"), record_digest=None)
        result = self._run(command_type=REVOKE_AUTH_CONTEXT, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=None, command_id=None, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)

    def close(self, *, mission_id: str, context_id: str, context_epoch: int, observed_at: str, actor: ActorRef | Mapping[str, Any] = {"type": "SYSTEM", "id": "r3.e2"}, idempotency_key: str | None = None) -> R3E2OperationResult:
        current = self.get_context(mission_id, context_id, context_epoch)
        if current is None:
            raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", f"SUTAuthContext not found: {context_id}:{context_epoch}")
        if current.status == "CLOSED":
            return self._duplicate(mission_id, current, "context_closed")
        context = replace(current, status="CLOSED", validation_status="INVALID", last_observed_at=_text(observed_at, "observed_at"), record_digest=None)
        result = self._run(command_type=CLOSE_AUTH_CONTEXT, mission_id=mission_id, context=context, origin_lineage=current.lineage_refs, actor=actor, idempotency_key=idempotency_key, correlation_id=None, command_id=None, session_id=current.lineage_refs.get("session_id"))
        return R3E2OperationResult(result, context if result.ok else None)
