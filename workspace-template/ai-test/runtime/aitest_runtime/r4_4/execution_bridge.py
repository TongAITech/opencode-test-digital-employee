from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, canonical_sha256

from .contracts import *
from .errors import EXECUTION_BLOCKED, RESULT_CONFLICT, SUFFICIENCY_HANDOFF_FAILED, R44Error


def _ref(value: Any, kind: str, object_id: str) -> ExactReference:
    return value if isinstance(value, ExactReference) else ExactReference.from_dict(value) if value is not None else make_reference(kind, object_id)


@dataclass(frozen=True)
class BridgeResult:
    outcome: str
    intent: ValidationExecutionIntent | None = None
    linkage: Any | None = None
    upstream_result: Any | None = None
    error_code: str | None = None
    details: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", dict(self.details or {}))

    @property
    def ok(self) -> bool:
        return self.outcome in {"APPLIED", "DUPLICATE", "RECONCILED"}

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "intent": self.intent.to_dict() if self.intent else None, "linkage": self.linkage.to_dict() if hasattr(self.linkage, "to_dict") else self.linkage, "upstream_result": self.upstream_result.to_dict() if hasattr(self.upstream_result, "to_dict") else self.upstream_result, "error_code": self.error_code, "details": dict(self.details)}


class R44ExecutionBridge:
    """Caller-owned additive bridge; it owns no EventStore, scheduler, or truth ledger."""

    def __init__(self, r44_service: Any | None = None, *, r2_service: Any | None = None, r1_service: Any | None = None, r34_service: Any | None = None, r37_service: Any | None = None, actor: ActorRef | None = None) -> None:
        self.r44_service = r44_service
        self.r2_service = r2_service
        self.r1_service = r1_service
        self.r34_service = r34_service
        self.r37_service = r37_service
        self.actor = actor or ActorRef("SYSTEM", "r4.4.bridge")

    @staticmethod
    def deterministic_task_id(intent_seed: Mapping[str, Any]) -> str:
        return f"r4.4:task:{canonical_sha256(dict(intent_seed))}"

    @staticmethod
    def deterministic_dispatch_id(intent_seed: Mapping[str, Any]) -> str:
        return f"r4.4:dispatch:{canonical_sha256(dict(intent_seed))}"

    @staticmethod
    def deterministic_intent_id(intent_seed: Mapping[str, Any]) -> str:
        return f"r4.4:execution-intent:{canonical_sha256(dict(intent_seed))}"

    def build_intent(self, *, cycle_ref: ExactReference | Mapping[str, Any], case_ref: ExactReference | Mapping[str, Any], oracle_ref: ExactReference | Mapping[str, Any], binding: ExecutableCaseBinding | Mapping[str, Any], target_scope: Mapping[str, Any], mission_ref: ExactReference | Mapping[str, Any], plan_ref: ExactReference | Mapping[str, Any], plan_revision_ref: ExactReference | Mapping[str, Any], task_id: str | None = None, dispatch_id: str | None = None, correlation_id: str | None = None, idempotency_key: str | None = None) -> ValidationExecutionIntent:
        binding_value = binding if isinstance(binding, ExecutableCaseBinding) else ExecutableCaseBinding.from_dict(binding)
        cycle = ExactReference.from_dict(cycle_ref)
        case = ExactReference.from_dict(case_ref)
        oracle = ExactReference.from_dict(oracle_ref)
        mission = ExactReference.from_dict(mission_ref)
        plan = ExactReference.from_dict(plan_ref)
        revision = ExactReference.from_dict(plan_revision_ref)
        seed = {"cycle_ref": cycle.to_dict(), "case_ref": case.to_dict(), "oracle_ref": oracle.to_dict(), "binding_digest": binding_value.binding_digest, "target_scope": dict(target_scope), "mission_ref": mission.to_dict(), "plan_ref": plan.to_dict(), "plan_revision_ref": revision.to_dict()}
        return ValidationExecutionIntent(
            execution_intent_id=self.deterministic_intent_id(seed), cycle_ref=cycle, case_ref=case, oracle_ref=oracle,
            binding_ref=make_reference("EXECUTABLE_CASE_BINDING", binding_value.binding_id, binding_value.binding_digest), target_scope=dict(target_scope),
            mission_ref=mission, plan_ref=plan, plan_revision_ref=revision, task_id=task_id or self.deterministic_task_id(seed),
            dispatch_id=dispatch_id or self.deterministic_dispatch_id(seed), correlation_id=correlation_id or f"r4.4:corr:{canonical_sha256(seed)}",
            idempotency_key=idempotency_key or f"r4.4:idempotency:{canonical_sha256(seed)}", binding_digest=binding_value.binding_digest,
        )

    @staticmethod
    def _require_reconcile_api(service: Any) -> Any:
        method = getattr(service, "reconcile", None)
        if not callable(method):
            raise R44Error(EXECUTION_BLOCKED, "ToolExecutionApplicationService.reconcile is required before retry")
        return method

    def reconcile_tool_execution(self, request: Any) -> BridgeResult:
        if self.r1_service is None:
            return BridgeResult("BLOCKED", error_code=EXECUTION_BLOCKED, details={"reason": "R1 service not injected"})
        try:
            result = self._require_reconcile_api(self.r1_service)(request)
            return BridgeResult("RECONCILED", upstream_result=result)
        except Exception as exc:
            code = getattr(exc, "code", None) or getattr(getattr(exc, "error", None), "code", None)
            if code in {"TOOL_EXECUTION_NOT_FOUND", "NOT_FOUND"}:
                return BridgeResult("DISPATCH_REQUIRED", error_code=code, details={"reconcile": "not_found", "blind_repeat": False})
            return BridgeResult("BLOCKED", error_code=code or EXECUTION_BLOCKED, details={"reconcile": "failed", "blind_repeat": False})

    def execute_or_reconcile(self, intent: ValidationExecutionIntent, *, reconcile_request: Any, execute_request: Any | None = None, allow_dispatch: bool = False) -> BridgeResult:
        if not isinstance(intent, ValidationExecutionIntent):
            raise R44Error("R4_4_SCHEMA_INVALID", "intent must be ValidationExecutionIntent")
        reconciled = self.reconcile_tool_execution(reconcile_request)
        if reconciled.outcome == "RECONCILED":
            return BridgeResult("RECONCILED", intent=intent, upstream_result=reconciled.upstream_result)
        if not allow_dispatch or execute_request is None:
            return BridgeResult("BLOCKED", intent=intent, error_code=EXECUTION_BLOCKED, details={"reason": "reconciliation did not prove absence or safe dispatch", "blind_repeat": False})
        if self.r1_service is None or not callable(getattr(self.r1_service, "execute", None)):
            return BridgeResult("BLOCKED", intent=intent, error_code=EXECUTION_BLOCKED, details={"reason": "R1 execute API is unavailable"})
        try:
            result = self.r1_service.execute(execute_request)
            return BridgeResult("APPLIED", intent=intent, upstream_result=result)
        except Exception as exc:
            return BridgeResult("BLOCKED", intent=intent, error_code=getattr(exc, "code", None) or EXECUTION_BLOCKED, details={"blind_repeat": False})

    def record_execution_linkage(self, linkage: ExecutionLinkage | Mapping[str, Any], *, mission_id: str) -> BridgeResult:
        if self.r44_service is None or not callable(getattr(self.r44_service, "record_execution_linkage", None)):
            return BridgeResult("BLOCKED", error_code=EXECUTION_BLOCKED)
        result = self.r44_service.record_execution_linkage(linkage, mission_id=mission_id)
        return BridgeResult(result.outcome, linkage=result.entity, upstream_result=result)

    def write_r34_lineage(self, *, attempt_request: Mapping[str, Any], oracle_request: Mapping[str, Any], result_request: Mapping[str, Any]) -> BridgeResult:
        if self.r34_service is None:
            return BridgeResult("BLOCKED", error_code=RESULT_CONFLICT, details={"reason": "R3.4 service not injected"})
        for name in ("register_case_execution_attempt", "evaluate_oracle", "record_test_result"):
            if not callable(getattr(self.r34_service, name, None)):
                return BridgeResult("BLOCKED", error_code=RESULT_CONFLICT, details={"missing_api": name})
        try:
            attempt = self.r34_service.register_case_execution_attempt(attempt_request)
            evaluation = self.r34_service.evaluate_oracle(oracle_request)
            result = self.r34_service.record_test_result(result_request)
            return BridgeResult("APPLIED", upstream_result={"attempt": attempt, "oracle_evaluation": evaluation, "test_result": result})
        except Exception as exc:
            return BridgeResult("BLOCKED", error_code=getattr(exc, "code", None) or RESULT_CONFLICT)

    def request_sufficiency(self, evaluation_input: Any, *, idempotency_key: str, correlation_id: str | None = None) -> BridgeResult:
        if self.r37_service is None or not callable(getattr(self.r37_service, "evaluate_test_sufficiency", None)):
            return BridgeResult("BLOCKED", error_code=SUFFICIENCY_HANDOFF_FAILED)
        try:
            request = evaluation_input.to_dict() if hasattr(evaluation_input, "to_dict") else dict(evaluation_input)
            result = self.r37_service.evaluate_test_sufficiency({"mission_id": request["mission_id"], "idempotency_key": idempotency_key, "correlation_id": correlation_id or f"corr:{idempotency_key}", "evaluation": request})
            return BridgeResult(result.outcome, upstream_result=result)
        except Exception as exc:
            return BridgeResult("BLOCKED", error_code=getattr(exc, "code", None) or SUFFICIENCY_HANDOFF_FAILED)

    def reconcile_sufficiency(self, evaluation_input: Any, *, idempotency_key: str, correlation_id: str | None = None) -> BridgeResult:
        return self.request_sufficiency(evaluation_input, idempotency_key=idempotency_key, correlation_id=correlation_id)


__all__ = ["BridgeResult", "R44ExecutionBridge"]
