"""RC6 Wave 9 governed L1-L7 real execution runtime.

Execution is fail-closed. A PASS is computed by the runtime only after a
PreparedAttempt is matched to the exact frozen Case and TargetIdentity, the
runtime-issued layer execution worker/lease is authorized, all required tools
are admitted for that worker+target, a real action is evidenced by real tool
calls, an actual result exists, and an independent oracle assertion passes.

Execution Closure adds `execute_with_runner`: the product path consumes an
immutable ExecutableTestSpec + SCRIPT_READY validation and invokes a production
RunnerAdapter. The legacy `real_action` callable remains only as a compatibility
surface for frozen Wave9 tests/adapters; it is no longer the only product path.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from .authority import AuthorityError, AuthorityRuntime
from .capability import ToolCapabilityBroker, ToolCapabilityError
from .preparation import PreparedAttempt
from .executable_spec import ExecutableSpecBuilder, ExecutableTestSpec
from .automation import RunnerAdapter, ScriptArtifact, ScriptValidation


class ExecutionContractError(RuntimeError):
    pass


ACTION_STATUSES = {"EXECUTED", "BLOCKED", "SKIPPED", "NOT_RUN"}
FINAL_STATUSES = {"PASS", "FAIL", "BLOCKED", "SKIPPED", "NOT_RUN"}


@dataclass(frozen=True)
class LayerExecutionProfile:
    layer: str
    role: str
    required_tools: Tuple[str, ...]
    action_kind: str


DEFAULT_EXECUTION_PROFILES: Dict[str, LayerExecutionProfile] = {
    "L1": LayerExecutionProfile("L1", "L1_EXECUTE", ("maven", "junit"), "CODE_UNIT"),
    "L2": LayerExecutionProfile("L2", "L2_EXECUTE", ("database",), "DB_COMPONENT"),
    "L3": LayerExecutionProfile("L3", "L3_EXECUTE", ("api-runtime",), "API_SERVICE"),
    "L4": LayerExecutionProfile("L4", "L4_EXECUTE", ("browser-skill",), "UI_BROWSER"),
    "L5": LayerExecutionProfile("L5", "L5_EXECUTE", ("e2e-orchestrator",), "CROSS_SYSTEM_E2E"),
    "L6": LayerExecutionProfile("L6", "L6_EXECUTE", ("k6",), "PERFORMANCE"),
    "L7": LayerExecutionProfile("L7", "L7_EXECUTE", ("zap",), "SECURITY"),
}


@dataclass(frozen=True)
class RealActionResult:
    status: str
    actual_result: Optional[Dict[str, Any]]
    tool_calls: Tuple[Dict[str, str], ...]
    evidence_refs: Tuple[str, ...]
    reason: Optional[str] = None


@dataclass(frozen=True)
class OracleAssertionResult:
    passed: bool
    assertion_ref: str
    evidence_refs: Tuple[str, ...]
    details: Dict[str, Any]


@dataclass(frozen=True)
class ExecutionRecord:
    attempt_id: str
    tc_id: str
    case_version: int
    target_id: str
    layer: str
    worker_id: str
    lease_id: str
    status: str
    integrity_passed: bool
    actual_result: Optional[Dict[str, Any]]
    tool_call_refs: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    assertion_ref: Optional[str]
    assertion_passed: Optional[bool]
    reason: Optional[str]


class ExecutionProfileRegistry:
    def __init__(self, profiles: Optional[Mapping[str, LayerExecutionProfile]] = None):
        source = dict(profiles or DEFAULT_EXECUTION_PROFILES)
        expected = {"L%d" % i for i in range(1, 8)}
        if set(source) != expected:
            raise ExecutionContractError("SEVEN_LAYER_EXECUTION_PROFILES_REQUIRED")
        self._profiles: Dict[str, LayerExecutionProfile] = {}
        roles = set()
        for layer, profile in source.items():
            if profile.layer != layer:
                raise ExecutionContractError("PROFILE_LAYER_MISMATCH")
            if profile.role != "%s_EXECUTE" % layer:
                raise ExecutionContractError("PROFILE_ROLE_MUST_BE_LAYER_EXECUTE")
            if not profile.required_tools or any(not x for x in profile.required_tools):
                raise ExecutionContractError("PROFILE_REQUIRED_TOOLS_REQUIRED")
            if profile.role in roles:
                raise ExecutionContractError("EXECUTION_ROLE_MUST_BE_UNIQUE")
            roles.add(profile.role)
            self._profiles[layer] = profile

    def get(self, layer: str) -> LayerExecutionProfile:
        try:
            return self._profiles[str(layer).upper()]
        except KeyError:
            raise ExecutionContractError("UNKNOWN_EXECUTION_LAYER")

    def all(self) -> Tuple[LayerExecutionProfile, ...]:
        return tuple(self._profiles["L%d" % i] for i in range(1, 8))


class ExecutionIntegrityGate:
    """Computes final execution status; caller/model self-reported PASS is ignored."""

    @staticmethod
    def evaluate(
        *,
        action: RealActionResult,
        assertion: Optional[OracleAssertionResult],
        required_tools: Iterable[str],
        observed_tool_ids: Iterable[str],
    ) -> Tuple[str, bool, Optional[str]]:
        status = str(action.status).upper()
        if status not in ACTION_STATUSES:
            raise ExecutionContractError("INVALID_REAL_ACTION_STATUS")
        if status != "EXECUTED":
            return status, False, action.reason or "ACTION_%s" % status
        if not isinstance(action.actual_result, dict) or not action.actual_result:
            return "FAIL", False, "ACTUAL_RESULT_REQUIRED"
        required = set(required_tools)
        observed = set(observed_tool_ids)
        if not required.issubset(observed):
            missing = sorted(required - observed)
            return "FAIL", False, "REQUIRED_REAL_TOOL_CALL_MISSING:" + ",".join(missing)
        if not action.evidence_refs:
            return "FAIL", False, "CURRENT_EXECUTION_EVIDENCE_REQUIRED"
        if assertion is None:
            return "FAIL", False, "ORACLE_ASSERTION_REQUIRED"
        if not assertion.assertion_ref or not assertion.evidence_refs:
            return "FAIL", False, "ASSERTION_EVIDENCE_REQUIRED"
        if assertion.passed:
            return "PASS", True, None
        return "FAIL", True, "ORACLE_ASSERTION_FAILED"


class ExecutionRuntime:
    """Layer-isolated execution with authority, tool and integrity gates."""

    REQUIRED_ARTIFACTS = ("execution_attempt", "assertion", "evidence")

    def __init__(
        self,
        *,
        authority: AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        oracle_evaluator: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        profiles: Optional[Mapping[str, LayerExecutionProfile]] = None,
    ):
        self.authority = authority
        self.tool_broker = tool_broker
        self.oracle_evaluator = oracle_evaluator
        self.profiles = ExecutionProfileRegistry(profiles)

    @staticmethod
    def _fingerprint(value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_case_and_prepared(case: Dict[str, Any], prepared: PreparedAttempt) -> str:
        if not isinstance(case, dict):
            raise ExecutionContractError("CASE_REQUIRED")
        if str(case.get("status", "")).upper() != "FROZEN":
            raise ExecutionContractError("CASE_MUST_BE_FROZEN_BEFORE_EXECUTION")
        tc_id = case.get("tc_id")
        version = case.get("case_version")
        layer = str(case.get("layer", "")).upper()
        if layer not in {"L%d" % i for i in range(1, 8)}:
            raise ExecutionContractError("SINGLE_VALID_LAYER_REQUIRED")
        if prepared.status != "PREPARED":
            raise ExecutionContractError("PREPARED_ATTEMPT_REQUIRED")
        if prepared.tc_id != tc_id or prepared.case_version != version:
            raise ExecutionContractError("PREPARED_ATTEMPT_CASE_MISMATCH")
        if not prepared.target_id:
            raise ExecutionContractError("TARGET_ID_REQUIRED")
        return layer

    def _authorize(self, *, worker_id: str, lease_id: str, profile: LayerExecutionProfile, scope_ref: str) -> None:
        try:
            identity = self.authority._require_identity(worker_id)
            lease = self.authority._require_lease(lease_id)
        except AuthorityError as exc:
            raise ExecutionContractError(str(exc))
        if identity.role != profile.role:
            raise ExecutionContractError("EXECUTION_WORKER_ROLE_MISMATCH")
        if str(identity.phase).upper() != "EXECUTION":
            raise ExecutionContractError("EXECUTION_PHASE_REQUIRED")
        if str(identity.layer).upper() != profile.layer:
            raise ExecutionContractError("EXECUTION_WORKER_LAYER_MISMATCH")
        if lease.scope_ref != scope_ref:
            raise ExecutionContractError("EXECUTION_LEASE_SCOPE_MISMATCH")
        try:
            for artifact_type in self.REQUIRED_ARTIFACTS:
                self.authority.authorize_artifact(worker_id, lease_id, artifact_type)
            for tool in profile.required_tools:
                self.authority.authorize_tool(worker_id, lease_id, tool)
        except AuthorityError as exc:
            raise ExecutionContractError(str(exc))

    def execute(
        self,
        *,
        case: Dict[str, Any],
        prepared: PreparedAttempt,
        worker_id: str,
        lease_id: str,
        real_action: Callable[[Dict[str, Any], PreparedAttempt, LayerExecutionProfile], Dict[str, Any]],
    ) -> ExecutionRecord:
        """Compatibility execution surface retained for frozen Wave9 adapters/tests."""
        layer = self._validate_case_and_prepared(case, prepared)
        profile = self.profiles.get(layer)
        scope_ref = "case:%s@%s" % (prepared.tc_id, prepared.case_version)
        self._authorize(worker_id=worker_id, lease_id=lease_id, profile=profile, scope_ref=scope_ref)

        admission = self.tool_broker.admit(worker_id, profile.required_tools, prepared.target_id)
        if not admission.ready:
            raise ExecutionContractError("EXECUTION_TOOL_ADMISSION_BLOCKED:%s" % admission.blocked)

        case_before = self._fingerprint(case)
        prepared_before = self._fingerprint(prepared)
        raw = real_action(deepcopy(case), deepcopy(prepared), profile)
        if not isinstance(raw, dict):
            raise ExecutionContractError("REAL_ACTION_RESULT_REQUIRED")
        action_status = str(raw.get("status", "")).upper()
        if action_status not in ACTION_STATUSES:
            raise ExecutionContractError("INVALID_REAL_ACTION_STATUS")
        tool_calls_raw = raw.get("tool_calls", [])
        evidence_raw = raw.get("evidence_refs", [])
        if not isinstance(tool_calls_raw, list) or not isinstance(evidence_raw, list):
            raise ExecutionContractError("REAL_ACTION_EVIDENCE_SHAPE_INVALID")

        observed_tools = []
        call_refs = []
        tool_evidence = []
        for call in tool_calls_raw:
            if not isinstance(call, dict):
                raise ExecutionContractError("STRUCTURED_TOOL_CALL_REQUIRED")
            tool_id = call.get("tool_id")
            call_ref = call.get("call_ref")
            evidence_ref = call.get("evidence_ref")
            if not all(isinstance(x, str) and x.strip() for x in (tool_id, call_ref, evidence_ref)):
                raise ExecutionContractError("TOOL_CALL_EVIDENCE_REQUIRED")
            try:
                self.authority.authorize_tool(worker_id, lease_id, tool_id)
                self.tool_broker.record_tool_call(
                    tool_id,
                    worker_id=worker_id,
                    target_id=prepared.target_id,
                    call_ref=call_ref,
                    evidence_ref=evidence_ref,
                )
            except (AuthorityError, ToolCapabilityError) as exc:
                raise ExecutionContractError(str(exc))
            observed_tools.append(tool_id)
            call_refs.append(call_ref)
            tool_evidence.append(evidence_ref)

        action = RealActionResult(
            status=action_status,
            actual_result=deepcopy(raw.get("actual_result")),
            tool_calls=tuple(deepcopy(tool_calls_raw)),
            evidence_refs=tuple(str(x) for x in evidence_raw if isinstance(x, str) and x.strip()),
            reason=raw.get("reason") if isinstance(raw.get("reason"), str) else None,
        )

        assertion = None
        if action.status == "EXECUTED" and isinstance(action.actual_result, dict) and action.actual_result:
            assertion_raw = self.oracle_evaluator(
                deepcopy(prepared.oracle_snapshot),
                deepcopy(action.actual_result),
                {
                    "attempt_id": prepared.attempt_id,
                    "tc_id": prepared.tc_id,
                    "case_version": prepared.case_version,
                    "target_id": prepared.target_id,
                    "layer": layer,
                },
            )
            if not isinstance(assertion_raw, dict) or not isinstance(assertion_raw.get("passed"), bool):
                raise ExecutionContractError("DETERMINISTIC_ORACLE_RESULT_REQUIRED")
            assertion_ref = assertion_raw.get("assertion_ref")
            assertion_evidence = assertion_raw.get("evidence_refs")
            if not isinstance(assertion_ref, str) or not assertion_ref.strip() or not isinstance(assertion_evidence, list):
                raise ExecutionContractError("ASSERTION_EVIDENCE_REQUIRED")
            assertion = OracleAssertionResult(
                passed=assertion_raw["passed"],
                assertion_ref=assertion_ref,
                evidence_refs=tuple(str(x) for x in assertion_evidence if isinstance(x, str) and x.strip()),
                details=deepcopy(assertion_raw.get("details") or {}),
            )

        final_status, integrity_passed, reason = ExecutionIntegrityGate.evaluate(
            action=action,
            assertion=assertion,
            required_tools=profile.required_tools,
            observed_tool_ids=observed_tools,
        )
        if final_status not in FINAL_STATUSES:
            raise ExecutionContractError("INVALID_FINAL_EXECUTION_STATUS")

        if self._fingerprint(case) != case_before:
            raise ExecutionContractError("FROZEN_CASE_MUTATED_DURING_EXECUTION")
        if self._fingerprint(prepared) != prepared_before:
            raise ExecutionContractError("PREPARED_BINDING_MUTATED_DURING_EXECUTION")

        evidence_refs = tuple(dict.fromkeys(list(action.evidence_refs) + tool_evidence + (list(assertion.evidence_refs) if assertion else [])))
        return ExecutionRecord(
            attempt_id=prepared.attempt_id,
            tc_id=prepared.tc_id,
            case_version=prepared.case_version,
            target_id=prepared.target_id,
            layer=layer,
            worker_id=worker_id,
            lease_id=lease_id,
            status=final_status,
            integrity_passed=integrity_passed,
            actual_result=deepcopy(action.actual_result),
            tool_call_refs=tuple(call_refs),
            evidence_refs=evidence_refs,
            assertion_ref=assertion.assertion_ref if assertion else None,
            assertion_passed=assertion.passed if assertion else None,
            reason=reason,
        )

    def execute_with_runner(
        self,
        *,
        case: Dict[str, Any],
        executable_spec: ExecutableTestSpec,
        script: ScriptArtifact,
        validation: ScriptValidation,
        prepared: PreparedAttempt,
        worker_id: str,
        lease_id: str,
        runner: RunnerAdapter,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> ExecutionRecord:
        """Production path with admission before any real process is launched."""
        layer = self._validate_case_and_prepared(case, prepared)
        if executable_spec.tc_id != prepared.tc_id or executable_spec.case_version != prepared.case_version:
            raise ExecutionContractError("EXECUTABLE_SPEC_CASE_MISMATCH")
        if executable_spec.layer != layer:
            raise ExecutionContractError("EXECUTABLE_SPEC_LAYER_MISMATCH")
        if script.spec_id != executable_spec.spec_id or validation.script_id != script.script_id:
            raise ExecutionContractError("SCRIPT_VALIDATION_SPEC_CHAIN_MISMATCH")
        try:
            ExecutableSpecBuilder.verify_case_binding(executable_spec, case)
            ExecutableSpecBuilder.verify_script_or_repair_binding(
                executable_spec,
                case_fingerprint=script.case_fingerprint,
                oracle_fingerprint=script.oracle_fingerprint,
            )
        except Exception as exc:
            raise ExecutionContractError(str(exc))
        if not validation.ready:
            raise ExecutionContractError("SCRIPT_READY_RUNTIME_GATE_REQUIRED")

        profile = self.profiles.get(layer)
        scope_ref = "case:%s@%s" % (prepared.tc_id, prepared.case_version)
        # Critical ordering: no external process/tool may run before exact
        # worker/lease/target/tool admission is proven.
        self._authorize(worker_id=worker_id, lease_id=lease_id, profile=profile, scope_ref=scope_ref)
        admission = self.tool_broker.admit(worker_id, profile.required_tools, prepared.target_id)
        if not admission.ready:
            raise ExecutionContractError("EXECUTION_TOOL_ADMISSION_BLOCKED:%s" % admission.blocked)

        runner_result = runner.execute(
            spec=executable_spec,
            script=script,
            validation=validation,
            cwd=cwd,
            env=env,
        )
        required = set(profile.required_tools)
        professional_calls = [deepcopy(call) for call in runner_result.tool_calls if call.get("tool_id") in required]

        record = self.execute(
            case=case,
            prepared=prepared,
            worker_id=worker_id,
            lease_id=lease_id,
            real_action=lambda _case, _prepared, _profile: {
                "status": runner_result.status,
                "actual_result": deepcopy(runner_result.actual_result),
                "tool_calls": professional_calls,
                "evidence_refs": list(runner_result.evidence_refs),
                "reason": None if runner_result.status == "EXECUTED" else "RUNNER_NOT_EXECUTED",
            },
        )
        all_call_refs = tuple(dict.fromkeys(list(record.tool_call_refs) + list(runner_result.tool_call_refs)))
        all_evidence = tuple(dict.fromkeys(list(record.evidence_refs) + list(runner_result.evidence_refs)))
        final_status = record.status
        final_integrity = record.integrity_passed
        final_reason = record.reason
        # A runner/process failure is Script/Runner evidence, never a PASS, even
        # if a partial actual result accidentally satisfies the independent oracle.
        if runner_result.exit_code != 0:
            final_status = "FAIL"
            final_integrity = False
            final_reason = "RUNNER_PROCESS_FAILED:%d" % runner_result.exit_code
        return ExecutionRecord(
            attempt_id=record.attempt_id,
            tc_id=record.tc_id,
            case_version=record.case_version,
            target_id=record.target_id,
            layer=record.layer,
            worker_id=record.worker_id,
            lease_id=record.lease_id,
            status=final_status,
            integrity_passed=final_integrity,
            actual_result=deepcopy(record.actual_result),
            tool_call_refs=all_call_refs,
            evidence_refs=all_evidence,
            assertion_ref=record.assertion_ref,
            assertion_passed=record.assertion_passed,
            reason=final_reason,
        )
