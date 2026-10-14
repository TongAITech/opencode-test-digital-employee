"""Verified execution-closure recovery adapters.

These are runtime adapters, not Agents.  FAILURE_DIAGNOSTIC owns classification
and recovery selection; a selected action is carried out by a narrowly scoped
adapter that must execute a side effect (or a bounded retry policy) and verify
its result before RecoveryActionExecutor may create a successor Attempt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .automation import ScriptArtifact, ScriptValidator
from .capability import ToolCapabilityBroker
from .diagnosis import DiagnosisResult, FailureContext, RecoveryDecision
from .executable_spec import ExecutableSpecBuilder, ExecutableTestSpec
from .preparation import PreparedAttempt


class RecoveryAdapterError(RuntimeError):
    pass


class VerifiedRecoveryAdapter(ABC):
    action: str

    @abstractmethod
    def execute(self, context: FailureContext, diagnosis: DiagnosisResult, decision: RecoveryDecision) -> Dict[str, Any]:
        raise NotImplementedError

    def __call__(self, context: FailureContext, diagnosis: DiagnosisResult, decision: RecoveryDecision) -> Dict[str, Any]:
        return self.execute(context, diagnosis, decision)


@dataclass
class ScriptRepairAdapter(VerifiedRecoveryAdapter):
    spec: ExecutableTestSpec
    current_script: ScriptArtifact
    repairer: Callable[[ExecutableTestSpec, ScriptArtifact, DiagnosisResult], ScriptArtifact]
    validator: ScriptValidator
    cwd: str
    env: Optional[Mapping[str, str]] = None
    action: str = "REPAIR_SCRIPT"

    def execute(self, context, diagnosis, decision):
        repaired = self.repairer(self.spec, self.current_script, diagnosis)
        if not isinstance(repaired, ScriptArtifact):
            raise RecoveryAdapterError("SCRIPT_REPAIR_MUST_RETURN_SCRIPT_ARTIFACT")
        if repaired.revision <= self.current_script.revision:
            raise RecoveryAdapterError("SCRIPT_REPAIR_REVISION_MUST_ADVANCE")
        ExecutableSpecBuilder.verify_script_or_repair_binding(
            self.spec,
            case_fingerprint=repaired.case_fingerprint,
            oracle_fingerprint=repaired.oracle_fingerprint,
        )
        validation = self.validator.validate(
            spec=self.spec,
            script=repaired,
            cwd=self.cwd,
            env=self.env,
            execute_target=True,
        )
        if not validation.ready:
            raise RecoveryAdapterError("REPAIRED_SCRIPT_NOT_READY")
        evidence = list(repaired.builder_evidence_refs) + list(validation.evidence_refs)
        return {
            "verified": True,
            "evidence_refs": list(dict.fromkeys(evidence)),
            "output_refs": ["script://%s" % repaired.script_id, "validation://%s" % validation.validation_id],
        }


@dataclass
class ExecutableSpecRepairAdapter(VerifiedRecoveryAdapter):
    current_spec: ExecutableTestSpec
    rebuilder: Callable[[ExecutableTestSpec, DiagnosisResult], ExecutableTestSpec]
    verifier: Callable[[ExecutableTestSpec], Tuple[bool, str]]
    action: str = "REOPEN_EXECUTABLE_SPEC"

    def execute(self, context, diagnosis, decision):
        rebuilt = self.rebuilder(self.current_spec, diagnosis)
        if not isinstance(rebuilt, ExecutableTestSpec):
            raise RecoveryAdapterError("SPEC_REBUILD_MUST_RETURN_EXECUTABLE_SPEC")
        # SPEC repair can change execution mapping/preconditions/actions, but an
        # Oracle change is a separate design-review path and is never silent.
        if rebuilt.oracle_fingerprint != self.current_spec.oracle_fingerprint:
            raise RecoveryAdapterError("SPEC_REPAIR_CANNOT_CHANGE_ORACLE")
        ok, evidence_ref = self.verifier(rebuilt)
        if ok is not True or not isinstance(evidence_ref, str) or not evidence_ref:
            raise RecoveryAdapterError("REBUILT_SPEC_VERIFICATION_REQUIRED")
        return {
            "verified": True,
            "evidence_refs": [evidence_ref],
            "output_refs": ["executable-spec://%s" % rebuilt.spec_id, "validation://spec/%s" % rebuilt.spec_id],
        }


@dataclass
class PreparationRecoveryAdapter(VerifiedRecoveryAdapter):
    action: str
    rebuild: Callable[[FailureContext, DiagnosisResult], PreparedAttempt]
    verifier: Callable[[PreparedAttempt], Tuple[bool, str]]

    def __post_init__(self):
        if self.action not in {"RESEARCH_OR_REBUILD_DATA", "RECONSTRUCT_PRECONDITION"}:
            raise RecoveryAdapterError("INVALID_PREPARATION_RECOVERY_ACTION")

    def execute(self, context, diagnosis, decision):
        prepared = self.rebuild(context, diagnosis)
        if not isinstance(prepared, PreparedAttempt) or prepared.status != "PREPARED":
            raise RecoveryAdapterError("PREPARED_ATTEMPT_REBUILD_REQUIRED")
        if prepared.tc_id != context.tc_id or prepared.case_version != context.case_version:
            raise RecoveryAdapterError("PREPARED_ATTEMPT_CASE_DRIFT")
        ok, evidence_ref = self.verifier(prepared)
        if ok is not True or not evidence_ref:
            raise RecoveryAdapterError("PREPARED_ATTEMPT_VERIFICATION_REQUIRED")
        return {
            "verified": True,
            "evidence_refs": [evidence_ref] + list(prepared.precondition_evidence) + list(prepared.binding_evidence),
            "output_refs": ["prepared-attempt://%s" % prepared.attempt_id],
        }


@dataclass
class AuthRecoveryAdapter(VerifiedRecoveryAdapter):
    authenticate: Callable[[FailureContext, DiagnosisResult], Dict[str, Any]]
    verify: Callable[[Dict[str, Any]], bool]
    action: str = "REAUTH"

    def execute(self, context, diagnosis, decision):
        result = self.authenticate(context, diagnosis)
        if not isinstance(result, dict):
            raise RecoveryAdapterError("AUTH_ADAPTER_RESULT_REQUIRED")
        # Never persist cookies/passwords/tokens in recovery output.
        forbidden = {"password", "passwd", "secret", "token", "cookie", "credential", "authorization"}
        lowered = {str(key).lower() for key in result}
        if forbidden.intersection(lowered):
            raise RecoveryAdapterError("AUTH_SECRET_MUST_NOT_ENTER_RECOVERY_ARTIFACT")
        evidence_ref = result.get("evidence_ref")
        session_ref = result.get("session_ref")
        if not isinstance(evidence_ref, str) or not evidence_ref or not isinstance(session_ref, str) or not session_ref:
            raise RecoveryAdapterError("AUTH_EVIDENCE_AND_SESSION_REF_REQUIRED")
        if self.verify(result) is not True:
            raise RecoveryAdapterError("AUTH_REFRESH_NOT_VERIFIED")
        return {"verified": True, "evidence_refs": [evidence_ref], "output_refs": ["auth-evidence://%s" % session_ref]}


@dataclass
class RouteRecoveryAdapter(VerifiedRecoveryAdapter):
    reconcile: Callable[[FailureContext, DiagnosisResult], Dict[str, Any]]
    verify: Callable[[Dict[str, Any]], bool]
    action: str = "RECONCILE_ROUTE_BINDING"

    def execute(self, context, diagnosis, decision):
        result = self.reconcile(context, diagnosis)
        if not isinstance(result, dict):
            raise RecoveryAdapterError("ROUTE_RECONCILE_RESULT_REQUIRED")
        binding_ref = result.get("binding_ref")
        evidence_ref = result.get("evidence_ref")
        if not isinstance(binding_ref, str) or not binding_ref or not isinstance(evidence_ref, str) or not evidence_ref:
            raise RecoveryAdapterError("ROUTE_BINDING_EVIDENCE_REQUIRED")
        if self.verify(result) is not True:
            raise RecoveryAdapterError("ROUTE_RECONCILIATION_NOT_VERIFIED")
        return {"verified": True, "evidence_refs": [evidence_ref], "output_refs": ["route-binding://%s" % binding_ref]}


@dataclass
class ToolRecoveryAdapter(VerifiedRecoveryAdapter):
    broker: ToolCapabilityBroker
    worker_id: str
    target_id: str
    required_tools: Tuple[str, ...]
    repair: Callable[[FailureContext, DiagnosisResult], Sequence[str]]
    action: str = "REPAIR_TOOL_BINDING"

    def execute(self, context, diagnosis, decision):
        evidence = tuple(self.repair(context, diagnosis))
        if not evidence or any(not isinstance(ref, str) or not ref for ref in evidence):
            raise RecoveryAdapterError("TOOL_REPAIR_EVIDENCE_REQUIRED")
        admission = self.broker.admit(self.worker_id, self.required_tools, self.target_id)
        if not admission.ready:
            raise RecoveryAdapterError("TOOL_REPAIR_ADMISSION_STILL_BLOCKED:%s" % admission.blocked)
        joined = ",".join(sorted(self.required_tools))
        return {"verified": True, "evidence_refs": list(evidence), "output_refs": ["tool-binding://%s" % joined]}


@dataclass
class EnvironmentRecoveryAdapter(VerifiedRecoveryAdapter):
    requalify: Callable[[FailureContext, DiagnosisResult], Dict[str, Any]]
    verify: Callable[[Dict[str, Any]], bool]
    action: str = "REQUALIFY_TARGET"

    def execute(self, context, diagnosis, decision):
        result = self.requalify(context, diagnosis)
        if not isinstance(result, dict):
            raise RecoveryAdapterError("TARGET_REQUALIFICATION_RESULT_REQUIRED")
        target_ref = result.get("target_ref")
        evidence_ref = result.get("evidence_ref")
        if not target_ref or not evidence_ref or self.verify(result) is not True:
            raise RecoveryAdapterError("TARGET_REQUALIFICATION_NOT_VERIFIED")
        return {"verified": True, "evidence_refs": [evidence_ref], "output_refs": ["target://%s" % target_ref]}


@dataclass
class DependencyRecoveryAdapter(VerifiedRecoveryAdapter):
    repair: Callable[[FailureContext, DiagnosisResult], Dict[str, Any]]
    verify: Callable[[Dict[str, Any]], bool]
    action: str = "REPAIR_DEPENDENCY_BINDING"

    def execute(self, context, diagnosis, decision):
        result = self.repair(context, diagnosis)
        if not isinstance(result, dict) or self.verify(result) is not True:
            raise RecoveryAdapterError("DEPENDENCY_REPAIR_NOT_VERIFIED")
        ref = result.get("dependency_ref")
        evidence = result.get("evidence_ref")
        if not ref or not evidence:
            raise RecoveryAdapterError("DEPENDENCY_REPAIR_EVIDENCE_REQUIRED")
        return {"verified": True, "evidence_refs": [evidence], "output_refs": ["dependency://%s" % ref]}


@dataclass
class BoundedRetryAdapter(VerifiedRecoveryAdapter):
    evidence_factory: Callable[[FailureContext, DiagnosisResult], str]
    action: str = "RETRY_SAME_STEP"

    def execute(self, context, diagnosis, decision):
        evidence = self.evidence_factory(context, diagnosis)
        if not isinstance(evidence, str) or not evidence:
            raise RecoveryAdapterError("TRANSIENT_RETRY_EVIDENCE_REQUIRED")
        return {"verified": True, "evidence_refs": [evidence], "output_refs": ["retry-policy://bounded"]}


@dataclass
class FlakyRepeatAdapter(VerifiedRecoveryAdapter):
    stability_probe: Callable[[FailureContext, DiagnosisResult], Dict[str, Any]]
    action: str = "CONTROLLED_REPEAT"

    def execute(self, context, diagnosis, decision):
        result = self.stability_probe(context, diagnosis)
        if not isinstance(result, dict):
            raise RecoveryAdapterError("FLAKY_STABILITY_RESULT_REQUIRED")
        evidence = result.get("evidence_ref")
        classification = result.get("classification")
        if not evidence or classification not in {"FLAKY", "STABLE_FAILURE", "STABLE_PASS"}:
            raise RecoveryAdapterError("FLAKY_STABILITY_CLASSIFICATION_REQUIRED")
        return {"verified": True, "evidence_refs": [evidence], "output_refs": ["stability-plan://%s" % classification.lower()]}


class RecoveryAdapterRegistry:
    def __init__(self, adapters: Optional[Mapping[str, VerifiedRecoveryAdapter]] = None):
        self._adapters: Dict[str, VerifiedRecoveryAdapter] = {}
        for adapter in (adapters or {}).values():
            self.register(adapter)

    def register(self, adapter: VerifiedRecoveryAdapter) -> None:
        if not isinstance(adapter, VerifiedRecoveryAdapter):
            raise RecoveryAdapterError("VERIFIED_RECOVERY_ADAPTER_REQUIRED")
        self._adapters[adapter.action] = adapter

    def require(self, action: str) -> VerifiedRecoveryAdapter:
        try:
            return self._adapters[action]
        except KeyError:
            raise RecoveryAdapterError("RECOVERY_ADAPTER_NOT_CONFIGURED:%s" % action)

    def as_executor_mapping(self) -> Dict[str, VerifiedRecoveryAdapter]:
        return dict(self._adapters)
