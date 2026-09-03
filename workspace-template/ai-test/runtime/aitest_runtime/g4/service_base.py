from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from aitest_runtime.durable_core import ActorRef, RuntimeError, RuntimeService, canonical_sha256
from aitest_runtime.common import now_iso
from aitest_runtime.execution_resume.contracts import ExecutionAttemptRecord
from aitest_runtime.r2_6 import HumanGateApplicationService
from aitest_runtime.r2_6.contracts import OUTCOMES, policy_digest
from aitest_runtime.r3_e2.contracts import BrowserContextRef

from .contracts import (
    CAPABILITY_STATUSES, COVERAGE_STATES, EXTENSION_ID, GAP_KINDS, GOAL_STATUSES,
    G4State, ITERATION_STATUSES, LEASE_STATES, ORACLE_STATUSES, RECORD_FACT,
    require_percentage, same_browser_context, sanitize_durable_payload,
)
from .executors import CapabilityExecutorRegistry, canonical_capability

G4_SCHEMA = "aitest.g4.real-execution-goal-convergence.v1"


class BrowserLeaseProvider(Protocol):
    def inspect_context(self, browser_context_ref: BrowserContextRef) -> BrowserContextRef: ...
    def inspect_lease(self, browser_context_ref: BrowserContextRef) -> str: ...
    def transfer_lease(self, browser_context_ref: BrowserContextRef, *, from_owner: str, to_owner: str) -> Any: ...


class ResumeConditionVerifier(Protocol):
    def verify_resume_condition(
        self, *, mission_id: str, browser_context_ref: BrowserContextRef,
        resume_condition: Mapping[str, Any], completion_mode: str,
    ) -> Mapping[str, Any]: ...


class BrowserHumanGateSupervisor:
    """Runtime verifier for human-browser resume; caller assertions are never authority."""

    def __init__(self, browser_provider: BrowserLeaseProvider, verifier: ResumeConditionVerifier | None = None) -> None:
        self.browser_provider = browser_provider
        self.verifier = verifier or (browser_provider if callable(getattr(browser_provider, "verify_resume_condition", None)) else None)

    def verify(
        self, *, mission_id: str, browser_context_ref: BrowserContextRef,
        resume_condition: Mapping[str, Any], completion_mode: str,
    ) -> dict[str, Any]:
        observed = self.browser_provider.inspect_context(browser_context_ref)
        if not same_browser_context(browser_context_ref.to_dict(), observed.to_dict()):
            raise RuntimeError("G4_BROWSER_CONTEXT_REPLACED_DURING_HUMAN_CONTROL", mission_id)
        if self.browser_provider.inspect_lease(browser_context_ref).upper() != "HUMAN":
            raise RuntimeError("G4_HUMAN_RESUME_LEASE_INVALID", mission_id)
        if self.verifier is None:
            raise RuntimeError("G4_RESUME_CONDITION_VERIFIER_REQUIRED", "runtime browser/SUT verifier is not configured")
        try:
            raw = self.verifier.verify_resume_condition(
                mission_id=mission_id, browser_context_ref=observed,
                resume_condition=dict(resume_condition), completion_mode=completion_mode,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("G4_HUMAN_RESUME_RUNTIME_VERIFICATION_FAILED", str(exc)) from exc
        value = _dict(raw, "resume_condition_verification")
        checks = {
            "auth_state": str(value.get("auth_state") or "").upper(),
            "page_identity": str(value.get("page_identity") or "").upper(),
            "business_state": str(value.get("business_state") or "").upper(),
        }
        allowed = {"VERIFIED", "AUTHENTICATED", "MATCHED", "RESUME_SAFE", "UNCHANGED", "REPOSITION_ONLY"}
        if value.get("resume_safe") is not True or any(check not in allowed for check in checks.values()):
            raise RuntimeError("G4_HUMAN_RESUME_REVALIDATION_FAILED", canonical_sha256({"condition": dict(resume_condition), "checks": checks})[:16])
        return {
            **checks, "resume_safe": True,
            "source_ref": str(value.get("source_ref") or "runtime:resume-condition-verifier"),
            "evidence_digest": str(value.get("evidence_digest") or canonical_sha256(value)),
            "observed_at": str(value.get("observed_at") or now_iso()),
        }


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError("G4_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("G4_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _attempt_state(runtime: RuntimeService, mission_id: str) -> Any:
    return runtime.replay_composed(mission_id).extension_state("r1_3b_execution_resume")


def _human_state(runtime: RuntimeService, mission_id: str) -> Any:
    return runtime.replay_composed(mission_id).extension_state("r2_6_human_gate")


def _g3_state(runtime: RuntimeService, mission_id: str) -> Any:
    return runtime.replay_composed(mission_id).extension_state("g3_testing_intelligence_product_integration")


def _full_r26_routes(external_route: str = "NONE") -> dict[str, tuple[str, ...]]:
    return {
        outcome: (
            (external_route,) if outcome == "EXTERNAL_ACTION_COMPLETED"
            else (("BLOCK",) if outcome == "REJECTED" else ("NONE",))
        )
        for outcome in OUTCOMES
    }


@dataclass(frozen=True)
class CapabilityDecision:
    capability_id: str
    status: str
    reason: str | None
    normalized_request: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"capability_id": self.capability_id, "status": self.status, "reason": self.reason, "normalized_request": dict(self.normalized_request)}


class G4RealExecutionService:
    def __init__(
        self,
        runtime: RuntimeService,
        *,
        orchestration: Any | None = None,
        browser_provider: BrowserLeaseProvider | None = None,
        capability_executors: Mapping[str, Any] | None = None,
        resume_condition_verifier: ResumeConditionVerifier | None = None,
        actor: ActorRef | None = None,
    ) -> None:
        runtime.extension_registry.manifest(EXTENSION_ID)
        self.runtime = runtime
        self.orchestration = orchestration
        self.browser_provider = browser_provider
        self.resume_condition_verifier = resume_condition_verifier
        self.browser_supervisor = BrowserHumanGateSupervisor(browser_provider, resume_condition_verifier) if browser_provider is not None else None
        self.executor_registry = CapabilityExecutorRegistry(capability_executors)
        self.actor = actor or ActorRef("SYSTEM", "g4-real-execution")
        self.human_gates = HumanGateApplicationService(runtime)

    def state(self, mission_id: str) -> G4State:
        value = self.runtime.replay_composed(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(value, G4State):
            raise RuntimeError("G4_STATE_INVALID", mission_id)
        return value

    def _record(self, mission_id: str, fact_kind: str, payload: Mapping[str, Any], *, provenance_refs: tuple[str, ...] | list[str] = (), fact_id: str | None = None) -> dict[str, Any]:
        clean_payload = sanitize_durable_payload(dict(payload))
        semantic = {"kind": fact_kind, "mission_id": mission_id, "payload": clean_payload, "provenance_refs": list(provenance_refs)}
        fact_id = fact_id or f"g4:{fact_kind.lower()}:{canonical_sha256(semantic)[:24]}"
        existing = self.state(mission_id).by_id(fact_id)
        if existing is not None:
            if existing.payload != clean_payload:
                raise RuntimeError("G4_FACT_ID_CONFLICT", fact_id)
            return existing.to_dict()
        command_id = f"g4:record:{fact_id}"
        result = self.runtime.execute({
            "command_id": command_id, "type": RECORD_FACT, "mission_id": mission_id, "session_id": None,
            "expected_seq": self.runtime.get_head_seq(mission_id), "actor": self.actor.to_dict(),
            "payload": {"fact_id": fact_id, "fact_kind": fact_kind, "payload": clean_payload, "provenance_refs": list(provenance_refs)},
            "idempotency_key": f"g4:fact:{fact_id}", "correlation_id": command_id, "schema_version": 1,
        })
        if not result.ok:
            raise result.error or RuntimeError("G4_DURABLE_WRITE_FAILED", fact_id)
        fact = self.state(mission_id).by_id(fact_id)
        if fact is None:
            raise RuntimeError("G4_FACT_NOT_REPLAYABLE", fact_id)
        return fact.to_dict()

    def status(self, mission_id: str) -> dict[str, Any]:
        state = self.state(mission_id)
        counts: dict[str, int] = {}
        for fact in state.facts:
            counts[fact.fact_kind] = counts.get(fact.fact_kind, 0) + 1
        return {
            "schema_version": G4_SCHEMA, "status": "PASS", "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True, "mission_id": mission_id, "fact_count": len(state.facts),
            "counts": counts, "g5_defect_truth": "HOLD", "g6_closed_loop": "HOLD",
            "legacy_aitest_db_write": "FORBIDDEN",
        }

    def _goal_status_fact(self, mission_id: str, goal_id: str) -> Any | None:
        return self.state(mission_id).latest("TESTING_GOAL_STATUS", lambda f: f.payload.get("goal_id") == goal_id)

    def goal_status(self, mission_id: str, goal_id: str) -> str:
        status_fact = self._goal_status_fact(mission_id, goal_id)
        if status_fact is not None:
            return str(status_fact.payload.get("status") or "").upper()
        base = self.goal(mission_id, goal_id)
        return str(base["payload"].get("status") or "ACTIVE").upper()

    def _set_goal_status(self, mission_id: str, goal_id: str, status: str, *, reason: str, provenance_refs: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
        target = str(status).upper()
        if target not in GOAL_STATUSES:
            raise RuntimeError("G4_GOAL_STATUS_INVALID", target)
        current_fact = self._goal_status_fact(mission_id, goal_id)
        current = str(current_fact.payload.get("status")) if current_fact is not None else str(self.goal(mission_id, goal_id)["payload"].get("status") or "ACTIVE")
        payload = {
            "goal_id": goal_id, "status": target, "from_status": current, "reason": reason,
            "transition_source_seq": self.runtime.get_head_seq(mission_id), "observed_at": now_iso(),
        }
        return self._record(mission_id, "TESTING_GOAL_STATUS", payload, provenance_refs=tuple(provenance_refs))

    def _goal_revision_ref(self, mission_id: str, goal_id: str) -> str:
        goal = self.goal(mission_id, goal_id)
        return f"{goal['fact_id']}:{goal['digest']}"

    def _bind_human_gate(self, mission_id: str, *, gate: Any, goal_id: str | None, batch_id: str | None, mandatory: bool, source_ref: str) -> dict[str, Any] | None:
        if not goal_id:
            return None
        self.goal(mission_id, goal_id)
        payload = {
            "gate_id": gate.gate_id, "goal_id": goal_id, "task_id": gate.task_id,
            "root_attempt_id": gate.root_attempt_id, "batch_id": batch_id,
            "mandatory": bool(mandatory), "source_ref": source_ref,
        }
        fact = self._record(mission_id, "HUMAN_GATE_BINDING", payload, provenance_refs=(f"r2.6:{gate.gate_id}", source_ref))
        if mandatory:
            self._set_goal_status(mission_id, goal_id, "WAITING_HUMAN", reason="MANDATORY_HUMAN_GATE_PENDING", provenance_refs=(fact["fact_id"],))
        return fact

    def _pending_human_gates_for_goal(self, mission_id: str, goal_id: str) -> list[Any]:
        latest: dict[str, Any] = {}
        for fact in self.state(mission_id).by_kind("HUMAN_GATE_BINDING"):
            if fact.payload.get("goal_id") == goal_id:
                latest[str(fact.payload.get("gate_id"))] = fact
        required = {gate_id: fact for gate_id, fact in latest.items() if fact.payload.get("mandatory") is True}
        if not required:
            return []
        human_state = _human_state(self.runtime, mission_id)
        result = []
        for gate in getattr(human_state, "gates", ()):
            binding = required.get(gate.gate_id)
            if binding is None or gate.status != "PENDING" or gate.mission_id != mission_id:
                continue
            if str(binding.payload.get("task_id") or "") != str(gate.task_id) or str(binding.payload.get("root_attempt_id") or "") != str(gate.root_attempt_id):
                continue
            result.append(gate)
        return result

    def _canonical_attempt(self, mission_id: str, attempt_id: str, task_id: str | None = None) -> ExecutionAttemptRecord:
        state = _attempt_state(self.runtime, mission_id)
        attempt = state.attempt(attempt_id) if state is not None and hasattr(state, "attempt") else None
        if attempt is None:
            raise RuntimeError("G4_CANONICAL_EXECUTION_ATTEMPT_REQUIRED", attempt_id)
        if task_id is not None and attempt.task_id != task_id:
            raise RuntimeError("G4_ATTEMPT_TASK_BINDING_MISMATCH", task_id)
        return attempt

    def create_goal(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = _text(data.get("goal_id"), "goal_id")
        affected = [str(x) for x in (data.get("affected_applications") or []) if str(x)]
        if not affected:
            raise RuntimeError("G4_AFFECTED_APPLICATIONS_REQUIRED", goal_id)
        policy = _dict(data.get("coverage_policy") or {}, "coverage_policy")
        target = require_percentage(policy.get("target_pct"))
        source = str(policy.get("source") or "BANK_INCREMENTAL_COVERAGE_PLATFORM")
        if source != "BANK_INCREMENTAL_COVERAGE_PLATFORM":
            raise RuntimeError("G4_ACTUAL_COVERAGE_SOURCE_INVALID", source)
        aggregation = str(policy.get("aggregation_policy") or "PER_AFFECTED_APPLICATION").upper()
        if aggregation != "PER_AFFECTED_APPLICATION" and not bool(policy.get("explicit_override")):
            raise RuntimeError("G4_COVERAGE_AGGREGATION_OVERRIDE_REQUIRED", aggregation)
        payload = {
            "goal_id": goal_id, "mission_id": mission_id, "project_id": _text(data.get("project_id"), "project_id"),
            "release_id": _text(data.get("release_id"), "release_id"),
            "requirement_scope": list(data.get("requirement_scope") or []), "affected_applications": affected,
            "goal_type": str(data.get("goal_type") or "COVERAGE_CONVERGENCE").upper(),
            "coverage_policy": {"source": source, "target_pct": target, "aggregation_policy": aggregation, "critical_gap_policy": str(policy.get("critical_gap_policy") or "ZERO_UNRESOLVED_CRITICAL")},
            "execution_policy": dict(data.get("execution_policy") or {}),
            "defect_discovery_objective": dict(data.get("defect_discovery_objective") or {"enabled": True, "high_value_hypothesis_refs": []}),
            "status": str(data.get("status") or "ACTIVE").upper(),
        }
        if payload["status"] not in GOAL_STATUSES:
            raise RuntimeError("G4_GOAL_STATUS_INVALID", payload["status"])
        fact = self._record(mission_id, "TESTING_GOAL", payload, provenance_refs=("user:testing-goal",), fact_id=f"g4:testing-goal:{goal_id}")
        status_fact = self._set_goal_status(mission_id, goal_id, payload["status"], reason="GOAL_CREATED", provenance_refs=(fact["fact_id"],))
        return {"schema_version": G4_SCHEMA, "status": payload["status"], "truth_source": "R1_EVENT_STREAM", "goal": fact, "goal_status": status_fact}

    def goal(self, mission_id: str, goal_id: str | None = None) -> dict[str, Any]:
        facts = self.state(mission_id).by_kind("TESTING_GOAL")
        fact = next((x for x in reversed(facts) if goal_id is None or x.payload.get("goal_id") == goal_id), None)
        if fact is None:
            raise RuntimeError("G4_TESTING_GOAL_NOT_FOUND", goal_id or mission_id)
        result = fact.to_dict()
        status_fact = self.state(mission_id).latest("TESTING_GOAL_STATUS", lambda f: f.payload.get("goal_id") == fact.payload.get("goal_id"))
        result["effective_status"] = str(status_fact.payload.get("status")) if status_fact is not None else str(fact.payload.get("status") or "ACTIVE")
        result["status_fact_ref"] = status_fact.fact_id if status_fact is not None else None
        return result

    def record_cursor(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        task_id = _text(data.get("task_id"), "task_id")
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), task_id)
        case_id = _text(data.get("case_id"), "case_id")
        case_version = _text(data.get("case_version"), "case_version")
        current_step_index = int(data.get("current_step_index", 0))
        if current_step_index < 0:
            raise RuntimeError("G4_STEP_CURSOR_INVALID", "current_step_index must be non-negative")
        payload = {
            "cursor_id": str(data.get("cursor_id") or f"cursor:{attempt.root_attempt_id}:{case_id}:{case_version}"),
            "case_id": case_id, "case_version": case_version, "task_id": task_id,
            "attempt_id": attempt.attempt_id, "root_attempt_id": attempt.root_attempt_id,
            "current_step_index": current_step_index, "completed_step_ids": list(data.get("completed_step_ids") or []),
            "pending_step_id": data.get("pending_step_id"), "last_safe_checkpoint": data.get("last_safe_checkpoint"),
            "status": str(data.get("status") or "RUNNING").upper(),
        }
        fact_id = f"g4:step-cursor:{canonical_sha256({k: payload[k] for k in ('cursor_id','attempt_id','current_step_index','status','pending_step_id')})[:24]}"
        fact = self._record(mission_id, "STEP_CURSOR", payload, provenance_refs=(f"r1.3b:{attempt.attempt_id}",), fact_id=fact_id)
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "cursor": fact}

    def recover_cursor(self, mission_id: str, *, attempt_id: str | None = None, root_attempt_id: str | None = None, case_id: str | None = None) -> dict[str, Any]:
        if not attempt_id and not root_attempt_id:
            raise RuntimeError("G4_CURSOR_BINDING_REQUIRED", "attempt_id or root_attempt_id is required")
        state = _attempt_state(self.runtime, mission_id)
        target_root = root_attempt_id
        if attempt_id:
            attempt = state.attempt(attempt_id) if state is not None and hasattr(state, "attempt") else None
            if attempt is None:
                raise RuntimeError("G4_CANONICAL_EXECUTION_ATTEMPT_REQUIRED", attempt_id)
            target_root = attempt.root_attempt_id
        candidates = [f for f in self.state(mission_id).by_kind("STEP_CURSOR") if f.payload.get("root_attempt_id") == target_root and (case_id is None or f.payload.get("case_id") == case_id)]
        if not candidates:
            raise RuntimeError("G4_STEP_CURSOR_NOT_FOUND", target_root or "")
        fact = candidates[-1]
        return {"schema_version": G4_SCHEMA, "status": "PASS", "truth_source": "R1_EVENT_STREAM", "cursor": fact.to_dict(), "payload": dict(fact.payload)}

    def register_capability(self, mission_id: str, capability_id: str, status: str, *, provider_ref: str | None = None, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        key = _text(capability_id, "capability_id").upper()
        normalized = _text(status, "status").upper()
        if normalized not in CAPABILITY_STATUSES:
            raise RuntimeError("G4_CAPABILITY_STATUS_INVALID", normalized)
        payload = {"capability_id": key, "capability_status": normalized, "provider_ref": provider_ref, "metadata": dict(metadata or {})}
        fact = self._record(mission_id, "CAPABILITY_STATUS", payload, provenance_refs=((provider_ref,) if provider_ref else ("g4:capability-registry",)))
        return {"status": normalized, "truth_source": "R1_EVENT_STREAM", "capability": fact}

    def validate_executor_request(self, capability_id: str, request: Mapping[str, Any]) -> CapabilityDecision:
        capability = _text(capability_id, "capability_id").upper()
        data = _dict(request, "request")
        if capability in {"BROWSER", "BROWSER_UI", "UI"}:
            if not data.get("browser_context_ref") or not data.get("authorized_scope"):
                return CapabilityDecision(capability, "UNAVAILABLE", "BROWSER_CONTEXT_AND_SCOPE_REQUIRED", data)
            return CapabilityDecision(capability, "AVAILABLE", None, data)
        if capability == "API":
            if not data.get("url") or not data.get("method") or not data.get("authorized_scope"):
                return CapabilityDecision(capability, "UNAVAILABLE", "EXACT_API_URL_METHOD_SCOPE_REQUIRED", data)
            return CapabilityDecision(capability, "AVAILABLE", None, data)
        if capability in {"DB", "DB_DATA", "DATA"}:
            operation = str(data.get("operation") or "READ").upper()
            if not data.get("connection_ref") or not data.get("query"):
                return CapabilityDecision(capability, "UNAVAILABLE", "DB_BINDING_AND_QUERY_REQUIRED", data)
            if operation != "READ" and not (data.get("authorized_scope") and data.get("approval_human_gate_ref")):
                return CapabilityDecision(capability, "APPROVAL_REQUIRED", "DB_WRITE_REQUIRES_AUTHORIZED_SCOPE_AND_HUMAN_GATE", data)
            return CapabilityDecision(capability, "AVAILABLE", None, {**data, "operation": operation})
        if capability in {"CAT", "LOG", "CAT_LOG"}:
            if not data.get("provider_ref"):
                return CapabilityDecision(capability, "UNAVAILABLE", "CAT_LOG_PROVIDER_REQUIRED", data)
            if not data.get("authenticated_context_ref"):
                return CapabilityDecision(capability, "AUTH_REQUIRED", "CAT_LOG_AUTH_REQUIRED", data)
            if str(data.get("operation") or "READ").upper() != "READ":
                return CapabilityDecision(capability, "UNAVAILABLE", "CAT_LOG_READ_ONLY", data)
            return CapabilityDecision(capability, "AVAILABLE", None, data)
        if capability == "MANUAL":
            if not data.get("required_action"):
                return CapabilityDecision(capability, "UNAVAILABLE", "MANUAL_ACTION_REQUIRED", data)
            return CapabilityDecision(capability, "AUTH_REQUIRED", "DURABLE_HUMAN_GATE_REQUIRED", data)
        if capability == "SECURITY":
            required = ("authorized_scope", "target_environment", "rate_limits", "safety_limits", "stop_conditions", "oracle")
            if any(not data.get(name) for name in required) or data.get("destructive") is True:
                return CapabilityDecision(capability, "APPROVAL_REQUIRED", "SECURITY_SCOPE_LIMITS_STOP_ORACLE_REQUIRED", data)
            return CapabilityDecision(capability, "AVAILABLE", None, {**data, "destructive": False})
        if capability == "PERFORMANCE":
            required = ("authorized_scope", "target_environment", "slo", "load_model", "resource_limits", "stop_conditions", "oracle")
            if any(not data.get(name) for name in required):
                return CapabilityDecision(capability, "APPROVAL_REQUIRED", "PERFORMANCE_SLO_LOAD_LIMITS_STOP_ORACLE_REQUIRED", data)
            return CapabilityDecision(capability, "AVAILABLE", None, data)
        return CapabilityDecision(capability, "UNAVAILABLE", "UNKNOWN_PROVIDER_FAIL_CLOSED", data)

    def _governed_test_profile(self, mission_id: str, capability: str, fact_id: str) -> dict[str, Any]:
        g3 = _g3_state(self.runtime, mission_id)
        fact = g3.by_id(fact_id) if g3 is not None and hasattr(g3, "by_id") else None
        if fact is None or fact.fact_kind != "TEST_PROFILE":
            raise RuntimeError("G4_G3_GOVERNED_TEST_PROFILE_REQUIRED", fact_id)
        payload = dict(fact.payload)
        if str(payload.get("profile_type") or "").upper() != capability:
            raise RuntimeError("G4_G3_TEST_PROFILE_TYPE_MISMATCH", f"{fact_id}:{capability}")
        return payload

    def execute_capability(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one governed step through the canonical capability-provider seam.

        Providers are runtime bindings, not truth stores. Only the normalized execution
        observation/evidence is persisted through the G4 R1 extension. Unknown or
        partially bound providers fail closed and never synthesize an execution result.
        """
        data = _dict(request, "request")
        task_id = _text(data.get("task_id"), "task_id")
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), task_id)
        capability = canonical_capability(_text(data.get("capability_id"), "capability_id"))
        executor_request = _dict(data.get("executor_request") or {}, "executor_request")
        profile_ref = data.get("g3_test_profile_fact_id")
        if capability in {"SECURITY", "PERFORMANCE"}:
            if not profile_ref:
                raise RuntimeError("G4_G3_GOVERNED_TEST_PROFILE_REQUIRED", capability)
            profile = self._governed_test_profile(mission_id, capability, str(profile_ref))
            safety = dict(profile.get("safety_contract") or {})
            # Safety/SLO authority comes from G3. Execution-only inputs may be carried
            # alongside it, but cannot override the governed profile.
            governed = dict(executor_request)
            governed.update({
                "authorized_scope": profile.get("authorized_scope"),
                "target_environment": safety.get("target_environment") or profile.get("target_environment"),
                "oracle": profile.get("oracle"),
                "stop_conditions": safety.get("stop_conditions") or profile.get("stop_conditions"),
            })
            if capability == "SECURITY":
                governed.update({
                    "rate_limits": safety.get("rate_limits") or profile.get("rate_limits"),
                    "safety_limits": safety.get("safety_limits") or profile.get("safety_limits"),
                    "destructive": bool(safety.get("destructive", False)),
                })
            else:
                governed.update({
                    "slo": profile.get("slo"),
                    "load_model": profile.get("load_model") or safety.get("load_model"),
                    "resource_limits": safety.get("resource_limits") or profile.get("resource_limits"),
                })
            executor_request = governed
        decision = self.validate_executor_request(capability, executor_request)
        if decision.status != "AVAILABLE":
            return {"status": decision.status, "truth_source": "R1_EVENT_STREAM", "execution": "NOT_RUN", "decision": decision.to_dict()}
        provider = self.executor_registry.get(capability)
        descriptor = self.executor_registry.descriptor(capability)
        if provider is None or descriptor is None:
            return {"status": "UNAVAILABLE", "truth_source": "R1_EVENT_STREAM", "execution": "NOT_RUN", "reason": "EXECUTOR_PROVIDER_NOT_BOUND", "capability_id": capability}
        if descriptor.capability_status != "AVAILABLE":
            return {"status": descriptor.capability_status, "truth_source": "R1_EVENT_STREAM", "execution": "NOT_RUN", "provider": descriptor.to_dict()}
        self.register_capability(mission_id, capability, descriptor.capability_status, provider_ref=str(data.get("provider_ref") or f"provider:{capability.lower()}"), metadata={"evidence_channels": list(descriptor.evidence_channels), "side_effect_classification": descriptor.side_effect_classification})
        step = _dict(data.get("step") or {}, "step")
        runtime_facts = {
            "mission_id": mission_id, "task_id": task_id, "attempt_id": attempt.attempt_id,
            "root_attempt_id": attempt.root_attempt_id, "case_id": data.get("case_id"),
            "case_version": data.get("case_version"), "g3_test_profile_fact_id": profile_ref,
        }
        prepared = provider.prepare(step, runtime_facts)
        result = None
        try:
            result = provider.execute(prepared, {**runtime_facts, "executor_request": decision.normalized_request})
            observation = _dict(provider.observe(result), "provider_observation")
            evidence_refs = [str(x) for x in provider.collect_evidence(result) if str(x)]
            durable = self.record_step_result(mission_id, {
                "task_id": task_id, "attempt_id": attempt.attempt_id,
                "case_id": _text(data.get("case_id"), "case_id"), "case_version": _text(data.get("case_version"), "case_version"),
                "step_id": _text(step.get("step_id"), "step.step_id"), "executor_capability": capability,
                "input_ref": data.get("input_ref") or step.get("input_ref"), "expected": step.get("expected"),
                "actual": observation.get("actual"), "oracle_result": observation.get("oracle_result"),
                "oracle_reason": observation.get("oracle_reason"), "evidence_refs": evidence_refs,
                "source_identity": observation.get("source_identity") or data.get("source_identity"),
                "execution_node": data.get("execution_node"), "auth_context_ref": data.get("auth_context_ref"),
                "side_effect_summary": observation.get("side_effect_summary"),
            })
            return {"status": durable["status"], "truth_source": "R1_EVENT_STREAM", "execution": "COMPLETED", "provider": descriptor.to_dict(), "result": durable["result"], "g5_defect_truth": "HOLD"}
        finally:
            if result is not None:
                provider.cleanup(result)

    def capability_human_gate(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        capability = _text(data.get("capability_id"), "capability_id").upper()
        decision = self.validate_executor_request(capability, _dict(data.get("executor_request") or {}, "executor_request"))
        if decision.status not in {"AUTH_REQUIRED", "APPROVAL_REQUIRED"}:
            raise RuntimeError("G4_CAPABILITY_HUMAN_GATE_NOT_REQUIRED", decision.status)
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), _text(data.get("task_id"), "task_id"))
        gate_id = _text(data.get("gate_id"), "gate_id")
        routes = _full_r26_routes("NONE")
        allowed = ("EXTERNAL_ACTION_COMPLETED",) if decision.status == "AUTH_REQUIRED" else ("APPROVED", "REJECTED")
        policy_id = f"g4-{capability.lower()}-human-policy"
        if decision.status == "APPROVAL_REQUIRED":
            routes = {outcome: (("NONE",) if outcome == "APPROVED" else ("BLOCK",)) for outcome in OUTCOMES}
        gate = self.human_gates.open_gate({
            "mission_id": mission_id, "gate_id": gate_id, "plan_id": attempt.plan_id, "plan_revision_id": attempt.plan_revision_id,
            "task_id": attempt.task_id, "root_attempt_id": attempt.root_attempt_id, "origin_attempt_id": attempt.attempt_id,
            "origin_session_id": attempt.runtime_session_id, "gate_kind": "EXTERNAL_ACTION" if decision.status == "AUTH_REQUIRED" else "APPROVAL",
            "request_payload": {"capability_id": capability, "reason": decision.reason, "required_action": data.get("required_action") or decision.reason},
            "response_schema": {"type": "object"}, "expires_at": None, "expiry_policy": "NONE",
            "decision_policy_id": policy_id, "decision_policy_version": 1,
            "decision_policy_digest": policy_digest(policy_id, 1, allowed, routes),
            "allowed_outcomes": list(allowed), "allowed_routes_by_outcome": {k: list(v) for k, v in routes.items()},
            "request_provenance": {"source_ref": f"g4:{capability}:human-gate", "source_digest": canonical_sha256({"capability": capability, "reason": decision.reason}), "observed_at": str(data.get("observed_at") or now_iso())},
            "actor": {"type": "SYSTEM", "id": "g4-real-execution"},
        })
        binding = None
        if gate.gate is not None:
            binding = self._bind_human_gate(
                mission_id, gate=gate.gate, goal_id=str(data.get("goal_id")) if data.get("goal_id") else None,
                batch_id=str(data.get("batch_id")) if data.get("batch_id") else None,
                mandatory=bool(data.get("mandatory_for_goal", bool(data.get("goal_id")))),
                source_ref=f"g4:{capability}:human-gate",
            )
        return {"status": "WAITING_HUMAN", "truth_source": "R1_EVENT_STREAM", "ai_turn": "YIELD", "capability": decision.to_dict(), "human_gate": gate.gate.to_dict() if gate.gate else None, "human_gate_binding": binding}

    def request_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        if self.browser_provider is None:
            raise RuntimeError("G4_BROWSER_PROVIDER_REQUIRED", "Human takeover requires the governed R3.E3 browser port")
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), _text(data.get("task_id"), "task_id"))
        cursor = self.recover_cursor(mission_id, root_attempt_id=attempt.root_attempt_id, case_id=(str(data.get("case_id")) if data.get("case_id") else None))["payload"]
        raw_ref = _dict(data.get("browser_context_ref"), "browser_context_ref")
        context_ref = BrowserContextRef.from_dict(raw_ref)
        observed = self.browser_provider.inspect_context(context_ref)
        observed_dict = observed.to_dict()
        if not same_browser_context(raw_ref, observed_dict) or self.browser_provider.inspect_lease(context_ref).upper() != "AI":
            raise RuntimeError("G4_BROWSER_CONTEXT_OR_LEASE_MISMATCH", attempt.attempt_id)
        gate_id = _text(data.get("human_gate_id"), "human_gate_id")
        ai_lease = self._record(mission_id, "BROWSER_LEASE", {
            "lease_id": f"lease:{gate_id}:ai-before", "browser_context_ref": observed_dict, "state": "AI_CONTROLLED", "owner": "AI",
            "attempt_id": attempt.attempt_id, "root_attempt_id": attempt.root_attempt_id, "task_id": attempt.task_id,
        }, provenance_refs=(f"r1.3b:{attempt.attempt_id}",))
        requested_lease = self._record(mission_id, "BROWSER_LEASE", {
            "lease_id": f"lease:{gate_id}:takeover-requested", "browser_context_ref": observed_dict, "state": "TAKEOVER_REQUESTED", "owner": "AI",
            "attempt_id": attempt.attempt_id, "root_attempt_id": attempt.root_attempt_id, "task_id": attempt.task_id,
        }, provenance_refs=(ai_lease["fact_id"],))
        takeover_base = {
            "takeover_id": str(data.get("takeover_id") or f"takeover:{gate_id}"), "human_gate_id": gate_id, "mission_id": mission_id,
            "task_id": attempt.task_id, "attempt_id": attempt.attempt_id, "root_attempt_id": attempt.root_attempt_id,
            "step_id": cursor.get("pending_step_id"), "browser_context_ref": observed_dict, "reason": str(data.get("reason") or "HUMAN_BROWSER_ACTION_REQUIRED"),
            "required_action": _text(data.get("required_action"), "required_action"), "current_url": data.get("current_url"),
            "allowed_scope": dict(data.get("allowed_scope") or {}), "resume_mode": str(data.get("resume_mode") or "AUTO_OR_EXPLICIT").upper(),
            "resume_condition": dict(data.get("resume_condition") or {}), "status": "TAKEOVER_REQUESTED",
            "goal_id": data.get("goal_id"), "batch_id": data.get("batch_id"), "mandatory_for_goal": bool(data.get("mandatory_for_goal", bool(data.get("goal_id")))),
            "sensitive_evidence_suppressed": True,
        }
        takeover_intent = self._record(mission_id, "HUMAN_TAKEOVER_REQUEST", takeover_base, provenance_refs=(requested_lease["fact_id"],))
        routes = _full_r26_routes("NONE"); allowed = ("EXTERNAL_ACTION_COMPLETED",); policy_id = "g4-human-browser-takeover-v1"
        gate_result = self.human_gates.open_gate({
            "mission_id": mission_id, "gate_id": gate_id, "plan_id": attempt.plan_id, "plan_revision_id": attempt.plan_revision_id,
            "task_id": attempt.task_id, "root_attempt_id": attempt.root_attempt_id, "origin_attempt_id": attempt.attempt_id,
            "origin_session_id": attempt.runtime_session_id, "gate_kind": "EXTERNAL_ACTION",
            "request_payload": {"action": takeover_base["required_action"], "reason": takeover_base["reason"], "browser_context_id": raw_ref["browser_context_id_or_epoch"]},
            "response_schema": {"type": "object"}, "expires_at": None, "expiry_policy": "NONE",
            "decision_policy_id": policy_id, "decision_policy_version": 1,
            "decision_policy_digest": policy_digest(policy_id, 1, allowed, routes), "allowed_outcomes": list(allowed),
            "allowed_routes_by_outcome": {k: list(v) for k, v in routes.items()},
            "request_provenance": {"source_ref": f"g4:human-takeover:{gate_id}", "source_digest": canonical_sha256({"gate_id": gate_id, "attempt": attempt.attempt_id, "context": raw_ref}), "observed_at": str(data.get("observed_at") or now_iso())},
            "actor": {"type": "SYSTEM", "id": "g4-browser-human-takeover"},
        })
        gate = gate_result.gate
        if gate is None:
            raise RuntimeError("G4_HUMAN_GATE_OPEN_FAILED", gate_id)
        binding = self._bind_human_gate(
            mission_id, gate=gate, goal_id=str(data.get("goal_id")) if data.get("goal_id") else None,
            batch_id=str(data.get("batch_id")) if data.get("batch_id") else None,
            mandatory=bool(data.get("mandatory_for_goal", bool(data.get("goal_id")))), source_ref=takeover_intent["fact_id"],
        )
        intent_reconciliation = self._record(mission_id, "BROWSER_TAKEOVER_RECONCILIATION", {
            "gate_id": gate_id, "takeover_ref": takeover_intent["fact_id"], "status": "GATE_OPENED_TRANSFER_PENDING",
            "recoverable": True, "expected_from_owner": "AI", "expected_to_owner": "HUMAN", "observed_at": now_iso(),
        }, provenance_refs=(takeover_intent["fact_id"], f"r2.6:{gate_id}"))
        try:
            transfer = self.browser_provider.transfer_lease(context_ref, from_owner="AI", to_owner="HUMAN")
            human_ref = BrowserContextRef(raw_ref["browser_session_id"], raw_ref["browser_context_id_or_epoch"], raw_ref["context_binding_digest"], "HUMAN", raw_ref["observed_at"])
            after = self.browser_provider.inspect_context(human_ref)
            if not same_browser_context(raw_ref, after.to_dict()) or self.browser_provider.inspect_lease(human_ref).upper() != "HUMAN":
                raise RuntimeError("G4_BROWSER_CONTEXT_REPLACED_DURING_TAKEOVER", gate_id)
        except Exception as exc:
            failure_code = getattr(exc, "code", type(exc).__name__)
            observed_owner = "UNKNOWN"; current = observed_dict; compensated = False
            try:
                current_ref = self.browser_provider.inspect_context(context_ref); current = current_ref.to_dict()
                observed_owner = str(self.browser_provider.inspect_lease(current_ref)).upper()
                if observed_owner == "HUMAN":
                    self.browser_provider.transfer_lease(current_ref, from_owner="HUMAN", to_owner="AI")
                    observed_owner = "AI"; compensated = True
            except Exception:
                pass
            blocked_lease = self._record(mission_id, "BROWSER_LEASE", {
                "lease_id": f"lease:{gate_id}:takeover-blocked:{self.runtime.get_head_seq(mission_id)}", "browser_context_ref": current,
                "state": "BLOCKED", "owner": observed_owner, "attempt_id": attempt.attempt_id, "root_attempt_id": attempt.root_attempt_id, "task_id": attempt.task_id,
                "failure_code": str(failure_code), "recoverable": True,
            }, provenance_refs=(requested_lease["fact_id"], intent_reconciliation["fact_id"]))
            blocked = self._record(mission_id, "HUMAN_TAKEOVER_REQUEST", {
                **takeover_base, "status": "BLOCKED", "browser_context_ref": current, "failure_code": str(failure_code), "recoverable": True,
            }, provenance_refs=(takeover_intent["fact_id"], blocked_lease["fact_id"], f"r2.6:{gate_id}"))
            recon = self._record(mission_id, "BROWSER_TAKEOVER_RECONCILIATION", {
                "gate_id": gate_id, "takeover_ref": blocked["fact_id"], "status": "BLOCKED", "recoverable": True,
                "failure_code": str(failure_code), "external_lease_owner": observed_owner, "compensated_to_ai": compensated, "observed_at": now_iso(),
            }, provenance_refs=(intent_reconciliation["fact_id"], blocked["fact_id"]))
            return {"schema_version": G4_SCHEMA, "status": "BLOCKED", "truth_source": "R1_EVENT_STREAM", "ai_turn": "YIELD", "blocking_tool_call": False, "human_gate": gate.to_dict(), "browser_lease": blocked_lease, "takeover": blocked, "reconciliation": recon}
        lease = self._record(mission_id, "BROWSER_LEASE", {
            "lease_id": f"lease:{gate_id}:human", "browser_context_ref": after.to_dict(), "state": "HUMAN_CONTROLLED", "owner": "HUMAN",
            "attempt_id": attempt.attempt_id, "root_attempt_id": attempt.root_attempt_id, "task_id": attempt.task_id,
        }, provenance_refs=(requested_lease["fact_id"], f"r2.6:{gate_id}", "r3.e3:lease-transfer"))
        takeover = self._record(mission_id, "HUMAN_TAKEOVER_REQUEST", {
            **takeover_base, "browser_context_ref": after.to_dict(), "status": "HUMAN_CONTROLLED",
        }, provenance_refs=(takeover_intent["fact_id"], gate.gate_id, lease["fact_id"]))
        recon = self._record(mission_id, "BROWSER_TAKEOVER_RECONCILIATION", {
            "gate_id": gate_id, "takeover_ref": takeover["fact_id"], "status": "HUMAN_CONTROLLED", "recoverable": True,
            "external_lease_owner": "HUMAN", "observed_at": now_iso(),
        }, provenance_refs=(intent_reconciliation["fact_id"], lease["fact_id"]))
        return {"schema_version": G4_SCHEMA, "status": "WAITING_HUMAN", "truth_source": "R1_EVENT_STREAM", "ai_turn": "YIELD", "blocking_tool_call": False, "human_gate": gate.to_dict(), "human_gate_binding": binding, "browser_lease_requested": requested_lease, "browser_lease": lease, "takeover": takeover, "reconciliation": recon, "transfer": getattr(transfer, "to_dict", lambda: transfer)() if transfer is not None else None}

    def reconcile_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        if self.browser_provider is None:
            raise RuntimeError("G4_BROWSER_PROVIDER_REQUIRED", "takeover reconciliation requires browser provider")
        gate_id = _text(data.get("human_gate_id"), "human_gate_id")
        r26 = _human_state(self.runtime, mission_id); gate = r26.gate(gate_id) if r26 is not None and hasattr(r26, "gate") else None
        if gate is None or gate.status != "PENDING":
            raise RuntimeError("G4_HUMAN_GATE_NOT_PENDING", gate_id)
        takeover = self.state(mission_id).latest("HUMAN_TAKEOVER_REQUEST", lambda f: f.payload.get("human_gate_id") == gate_id)
        if takeover is None:
            raise RuntimeError("G4_HUMAN_TAKEOVER_NOT_FOUND", gate_id)
        original = dict(takeover.payload["browser_context_ref"])
        ref = BrowserContextRef.from_dict(original)
        try:
            observed = self.browser_provider.inspect_context(ref); owner = str(self.browser_provider.inspect_lease(observed)).upper()
            if owner == "AI":
                self.browser_provider.transfer_lease(observed, from_owner="AI", to_owner="HUMAN")
            elif owner != "HUMAN":
                raise RuntimeError("G4_BROWSER_LEASE_OWNER_UNRECOVERABLE", owner)
            human_ref = BrowserContextRef(original["browser_session_id"], original["browser_context_id_or_epoch"], original["context_binding_digest"], "HUMAN", original["observed_at"])
            after = self.browser_provider.inspect_context(human_ref)
            if not same_browser_context(original, after.to_dict()) or self.browser_provider.inspect_lease(human_ref).upper() != "HUMAN":
                raise RuntimeError("G4_BROWSER_CONTEXT_REPLACED_DURING_TAKEOVER", gate_id)
        except Exception as exc:
            code = str(getattr(exc, "code", type(exc).__name__))
            recon = self._record(mission_id, "BROWSER_TAKEOVER_RECONCILIATION", {"gate_id": gate_id, "takeover_ref": takeover.fact_id, "status": "BLOCKED", "recoverable": True, "failure_code": code, "observed_at": now_iso()}, provenance_refs=(takeover.fact_id,))
            return {"status": "BLOCKED", "truth_source": "R1_EVENT_STREAM", "human_gate": gate.to_dict(), "reconciliation": recon}
        lease = self._record(mission_id, "BROWSER_LEASE", {"lease_id": f"lease:{gate_id}:human-reconciled:{self.runtime.get_head_seq(mission_id)}", "browser_context_ref": after.to_dict(), "state": "HUMAN_CONTROLLED", "owner": "HUMAN", "attempt_id": gate.origin_attempt_id, "root_attempt_id": gate.root_attempt_id, "task_id": gate.task_id}, provenance_refs=(takeover.fact_id, f"r2.6:{gate_id}"))
        recovered = self._record(mission_id, "HUMAN_TAKEOVER_REQUEST", {**dict(takeover.payload), "browser_context_ref": after.to_dict(), "status": "HUMAN_CONTROLLED", "recoverable": True}, provenance_refs=(takeover.fact_id, lease["fact_id"]))
        recon = self._record(mission_id, "BROWSER_TAKEOVER_RECONCILIATION", {"gate_id": gate_id, "takeover_ref": recovered["fact_id"], "status": "RECOVERED", "recoverable": True, "external_lease_owner": "HUMAN", "observed_at": now_iso()}, provenance_refs=(lease["fact_id"], recovered["fact_id"]))
        return {"status": "WAITING_HUMAN", "truth_source": "R1_EVENT_STREAM", "ai_turn": "YIELD", "blocking_tool_call": False, "human_gate": gate.to_dict(), "browser_lease": lease, "takeover": recovered, "reconciliation": recon}

    def complete_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        if self.browser_provider is None or self.browser_supervisor is None:
            raise RuntimeError("G4_BROWSER_PROVIDER_REQUIRED", "Human takeover completion requires governed browser and resume verifier")
        gate_id = data.get("human_gate_id"); r26 = _human_state(self.runtime, mission_id); pending = [g for g in getattr(r26, "gates", ()) if g.status == "PENDING"]
        if not gate_id:
            compatible = []
            for candidate in pending:
                takeover = self.state(mission_id).latest("HUMAN_TAKEOVER_REQUEST", lambda f: f.payload.get("human_gate_id") == candidate.gate_id)
                if candidate.gate_kind == "EXTERNAL_ACTION" and takeover is not None:
                    compatible.append(candidate)
            if len(compatible) != 1:
                raise RuntimeError("G4_HUMAN_GATE_SELECTION_REQUIRED", f"compatible_open_gates={len(compatible)}")
            gate_id = compatible[0].gate_id
        gate = r26.gate(str(gate_id)) if r26 is not None and hasattr(r26, "gate") else None
        if gate is None or gate.status != "PENDING":
            raise RuntimeError("G4_HUMAN_GATE_NOT_PENDING", str(gate_id))
        takeover_fact = self.state(mission_id).latest("HUMAN_TAKEOVER_REQUEST", lambda f: f.payload.get("human_gate_id") == gate.gate_id)
        if takeover_fact is None or takeover_fact.payload.get("status") not in {"HUMAN_CONTROLLED", "BLOCKED", "TAKEOVER_REQUESTED"}:
            raise RuntimeError("G4_HUMAN_TAKEOVER_NOT_FOUND", gate.gate_id)
        if takeover_fact.payload.get("status") != "HUMAN_CONTROLLED":
            reconciled = self.reconcile_human_takeover(mission_id, {"human_gate_id": gate.gate_id})
            if reconciled["status"] != "WAITING_HUMAN":
                return reconciled
            takeover_fact = self.state(mission_id).latest("HUMAN_TAKEOVER_REQUEST", lambda f: f.payload.get("human_gate_id") == gate.gate_id)
        mode = str(data.get("completion_mode") or "EXPLICIT").upper()
        if mode not in {"EXPLICIT", "AUTO"}:
            raise RuntimeError("G4_HUMAN_COMPLETION_MODE_INVALID", mode)
        resume_mode = str(takeover_fact.payload.get("resume_mode") or "AUTO_OR_EXPLICIT").upper()
        if resume_mode == "AUTO" and mode != "AUTO":
            raise RuntimeError("G4_HUMAN_COMPLETION_MODE_INVALID", "EXPLICIT_NOT_ALLOWED")
        if resume_mode == "EXPLICIT" and mode != "EXPLICIT":
            raise RuntimeError("G4_HUMAN_COMPLETION_MODE_INVALID", "AUTO_NOT_ALLOWED")
        original = dict(takeover_fact.payload["browser_context_ref"])
        human_ref = BrowserContextRef(original["browser_session_id"], original["browser_context_id_or_epoch"], original["context_binding_digest"], "HUMAN", original["observed_at"])
        verification = self.browser_supervisor.verify(
            mission_id=mission_id, browser_context_ref=human_ref,
            resume_condition=dict(takeover_fact.payload.get("resume_condition") or {}), completion_mode=mode,
        )
        pending_verify = self._record(mission_id, "BROWSER_LEASE", {
            "lease_id": f"lease:{gate.gate_id}:human-completed-pending-verify", "browser_context_ref": self.browser_provider.inspect_context(human_ref).to_dict(),
            "state": "HUMAN_COMPLETED_PENDING_VERIFY", "owner": "HUMAN", "attempt_id": gate.origin_attempt_id,
            "root_attempt_id": gate.root_attempt_id, "task_id": gate.task_id, "runtime_verification": verification,
        }, provenance_refs=(takeover_fact.fact_id, f"r2.6:{gate.gate_id}"))
        reclaiming = self._record(mission_id, "BROWSER_LEASE", {
            "lease_id": f"lease:{gate.gate_id}:reclaiming", "browser_context_ref": self.browser_provider.inspect_context(human_ref).to_dict(), "state": "AI_RECLAIMING", "owner": "HUMAN",
            "attempt_id": gate.origin_attempt_id, "root_attempt_id": gate.root_attempt_id, "task_id": gate.task_id,
        }, provenance_refs=(pending_verify["fact_id"], f"r2.6:{gate.gate_id}"))
        try:
            self.browser_provider.transfer_lease(human_ref, from_owner="HUMAN", to_owner="AI")
            ai_ref = BrowserContextRef(original["browser_session_id"], original["browser_context_id_or_epoch"], original["context_binding_digest"], "AI", original["observed_at"])
            observed_ai = self.browser_provider.inspect_context(ai_ref)
            if not same_browser_context(original, observed_ai.to_dict()) or self.browser_provider.inspect_lease(ai_ref).upper() != "AI":
                raise RuntimeError("G4_BROWSER_RECLAIM_VERIFICATION_FAILED", gate.gate_id)
            decision = self.human_gates.record_decision({
                "mission_id": mission_id, "gate_id": gate.gate_id, "decision_id": str(data.get("decision_id") or f"g4-complete:{gate.gate_id}"),
                "outcome": "EXTERNAL_ACTION_COMPLETED", "route": "NONE", "decision_payload": {"completion_mode": mode, "runtime_verification": verification, "caller_verification_authoritative": False},
                "decision_provenance": {"source_ref": verification["source_ref"], "source_digest": verification["evidence_digest"], "observed_at": verification["observed_at"]},
                "actor": {"type": "USER" if mode == "EXPLICIT" else "SYSTEM", "id": str(data.get("actor_id") or ("human-user" if mode == "EXPLICIT" else "g4-browser-supervisor"))},
            })
        except Exception as exc:
            code = str(getattr(exc, "code", type(exc).__name__)); compensated = False
            try:
                ai_ref = BrowserContextRef(original["browser_session_id"], original["browser_context_id_or_epoch"], original["context_binding_digest"], "AI", original["observed_at"])
                if self.browser_provider.inspect_lease(ai_ref).upper() == "AI":
                    self.browser_provider.transfer_lease(ai_ref, from_owner="AI", to_owner="HUMAN"); compensated = True
            except Exception:
                pass
            recon = self._record(mission_id, "BROWSER_TAKEOVER_RECONCILIATION", {"gate_id": gate.gate_id, "takeover_ref": takeover_fact.fact_id, "status": "RESUME_BLOCKED", "recoverable": True, "failure_code": code, "compensated_to_human": compensated, "observed_at": now_iso()}, provenance_refs=(pending_verify["fact_id"], reclaiming["fact_id"]))
            return {"status": "BLOCKED", "truth_source": "R1_EVENT_STREAM", "human_gate": gate.to_dict(), "reconciliation": recon}
        lease = self._record(mission_id, "BROWSER_LEASE", {
            "lease_id": f"lease:{gate.gate_id}:ai", "browser_context_ref": observed_ai.to_dict(), "state": "AI_CONTROLLED", "owner": "AI",
            "attempt_id": gate.origin_attempt_id, "root_attempt_id": gate.root_attempt_id, "task_id": gate.task_id,
        }, provenance_refs=(reclaiming["fact_id"],))
        completed = self._record(mission_id, "HUMAN_TAKEOVER_REQUEST", {
            **dict(takeover_fact.payload), "browser_context_ref": observed_ai.to_dict(), "status": "RESUME_SAFE", "completion_mode": mode,
            "verification": verification, "caller_verification_authoritative": False, "sensitive_evidence_suppressed": True,
        }, provenance_refs=(takeover_fact.fact_id, lease["fact_id"], f"r2.6:{gate.gate_id}"))
        recon = self._record(mission_id, "BROWSER_TAKEOVER_RECONCILIATION", {"gate_id": gate.gate_id, "takeover_ref": completed["fact_id"], "status": "RESUME_COMPLETED", "recoverable": False, "external_lease_owner": "AI", "observed_at": now_iso()}, provenance_refs=(lease["fact_id"], completed["fact_id"]))
        binding = self.state(mission_id).latest("HUMAN_GATE_BINDING", lambda f: f.payload.get("gate_id") == gate.gate_id)
        if binding is not None and binding.payload.get("mandatory") is True:
            self._set_goal_status(mission_id, str(binding.payload.get("goal_id")), "EXECUTING", reason="MANDATORY_HUMAN_GATE_COMPLETED", provenance_refs=(completed["fact_id"],))
        cursor = self.recover_cursor(mission_id, root_attempt_id=gate.root_attempt_id)
        return {"schema_version": G4_SCHEMA, "status": "RESUME_SAFE", "truth_source": "R1_EVENT_STREAM", "human_gate": decision.gate.to_dict() if decision.gate else None, "browser_lease_pending_verify": pending_verify, "browser_lease": lease, "takeover": completed, "reconciliation": recon, "cursor": cursor, "resume_attempt_id": cursor["payload"]["attempt_id"], "root_attempt_id": gate.root_attempt_id}

    def record_step_result(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), _text(data.get("task_id"), "task_id"))
        oracle = str(data.get("oracle_result") or "").upper()
        if oracle not in ORACLE_STATUSES:
            raise RuntimeError("G4_ORACLE_STATUS_INVALID", oracle)
        if data.get("confirmed_defect") or str(data.get("defect_status") or "").upper() == "CONFIRMED_DEFECT":
            raise RuntimeError("G4_G5_DEFECT_TRUTH_BOUNDARY", "G4 cannot confirm defects")
        evidence = data.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence:
            raise RuntimeError("G4_EVIDENCE_REQUIRED", "every executed step requires evidence_refs")
        for name in ("step_id", "expected", "actual", "oracle_reason", "source_identity"):
            if data.get(name) in (None, ""):
                raise RuntimeError("G4_STEP_RESULT_INCOMPLETE", name)
        payload = {
            "step_id": str(data["step_id"]), "attempt_id": attempt.attempt_id, "root_attempt_id": attempt.root_attempt_id,
            "task_id": attempt.task_id, "case_id": _text(data.get("case_id"), "case_id"), "case_version": _text(data.get("case_version"), "case_version"),
            "executor_capability": _text(data.get("executor_capability"), "executor_capability").upper(), "input_ref": data.get("input_ref"),
            "expected": data["expected"], "actual": data["actual"], "oracle_result": oracle, "oracle_reason": str(data["oracle_reason"]),
            "evidence_refs": list(evidence), "source_identity": str(data["source_identity"]), "execution_node": data.get("execution_node"),
            "auth_context_ref": data.get("auth_context_ref"), "side_effect_summary": data.get("side_effect_summary"),
            "test_fail_is_confirmed_defect": False,
        }
        fact = self._record(mission_id, "EXECUTION_STEP_RESULT", payload, provenance_refs=tuple(str(x) for x in evidence))
        if oracle in {"FAIL", "INCONCLUSIVE", "ERROR"}:
            self._record(mission_id, "UNEXPECTED_OBSERVATION", {"step_result_ref": fact["fact_id"], "oracle_result": oracle, "status": "OBSERVATION_ONLY", "g5_defect_truth": "HOLD"}, provenance_refs=(fact["fact_id"],))
        return {"status": oracle, "truth_source": "R1_EVENT_STREAM", "result": fact, "g5_defect_truth": "HOLD"}

    def create_batch(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        case_refs = [str(x) for x in (data.get("case_refs") or []) if str(x)]
        if not case_refs:
            raise RuntimeError("G4_EXECUTION_BATCH_CASES_REQUIRED", "case_refs")
        strategy_version_id = _text(data.get("strategy_version_id"), "strategy_version_id")
        g3 = _g3_state(self.runtime, mission_id)
        validated: list[str] = []
        for ref in case_refs:
            fact = g3.by_id(ref) if g3 is not None and hasattr(g3, "by_id") else None
            if fact is None or fact.fact_kind != "CASE_SPECIFICATION":
                raise RuntimeError("G4_G3_GOVERNED_CASE_REQUIRED", ref)
            case = fact.payload.get("r3_3_case") or {}
            if str(case.get("strategy_version_id") or "") != strategy_version_id:
                raise RuntimeError("G4_CASE_STRATEGY_BINDING_MISMATCH", ref)
            links = [x for x in g3.by_kind("CASE_VALUE_LINK") if x.payload.get("case_version_id") == case.get("case_version_id")]
            if not links:
                raise RuntimeError("G4_CASE_VALUE_LINK_REQUIRED", ref)
            validated.append(ref)
        payload = {
            "batch_id": _text(data.get("batch_id"), "batch_id"), "goal_id": _text(data.get("goal_id"), "goal_id"),
            "case_refs": validated, "strategy_version_id": strategy_version_id, "target_application": _text(data.get("target_application"), "target_application"),
            "target_coverage_gaps": list(data.get("target_coverage_gaps") or []), "target_hypotheses": list(data.get("target_hypotheses") or []),
            "expected_value": dict(data.get("expected_value") or {}), "status": str(data.get("status") or "READY").upper(),
        }
        fact = self._record(mission_id, "EXECUTION_BATCH", payload, provenance_refs=tuple(validated), fact_id=f"g4:execution-batch:{payload['batch_id']}:{payload['status'].lower()}")
        if payload["status"] in {"READY", "RUNNING"}:
            self._set_goal_status(mission_id, payload["goal_id"], "EXECUTING", reason=f"EXECUTION_BATCH_{payload['status']}", provenance_refs=(fact["fact_id"],))
        elif payload["status"] == "COMPLETED":
            self._set_goal_status(mission_id, payload["goal_id"], "MEASURING", reason="EXECUTION_BATCH_COMPLETED", provenance_refs=(fact["fact_id"],))
        return {"status": payload["status"], "truth_source": "R1_EVENT_STREAM", "batch": fact}

    def record_coverage_from_g3(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        state = str(data.get("state") or "AVAILABLE").upper()
        if state not in COVERAGE_STATES:
            raise RuntimeError("G4_COVERAGE_STATE_INVALID", state)
        snapshot_ref = data.get("g3_snapshot_fact_id")
        payload: dict[str, Any] = {
            "measurement_id": _text(data.get("measurement_id"), "measurement_id"), "goal_id": _text(data.get("goal_id"), "goal_id"),
            "batch_id": data.get("batch_id"), "state": state, "source": "BANK_INCREMENTAL_COVERAGE_PLATFORM",
        }
        provenance: list[str] = []
        if state == "AVAILABLE":
            if not snapshot_ref:
                raise RuntimeError("G4_BANK_COVERAGE_SNAPSHOT_REQUIRED", state)
            g3 = _g3_state(self.runtime, mission_id)
            snap = g3.by_id(str(snapshot_ref)) if g3 is not None and hasattr(g3, "by_id") else None
            if snap is None or snap.fact_kind != "INCREMENTAL_COVERAGE_SNAPSHOT":
                raise RuntimeError("G4_G3_BANK_COVERAGE_FACT_REQUIRED", str(snapshot_ref))
            sp = dict(snap.payload)
            if sp.get("coverage_semantics") != "BANK_EFFECTIVE_INCREMENTAL":
                raise RuntimeError("G4_ACTUAL_COVERAGE_SEMANTICS_INVALID", str(sp.get("coverage_semantics")))
            payload.update({
                "g3_snapshot_fact_id": snap.fact_id, "application_id": sp.get("application_id"), "target_version": sp.get("target_version"),
                "baseline_identity_status": sp.get("baseline_identity_status"), "baseline_label": sp.get("baseline_label"),
                "source_identity": sp.get("source_identity"), "observed_at": sp.get("observed_at"),
                "effective_incremental_coverage_pct": sp.get("effective_incremental_coverage_pct"), "details": list(sp.get("details") or []),
            })
            provenance.append(snap.fact_id)
        else:
            payload.update({"application_id": data.get("application_id"), "source_identity": data.get("source_identity"), "reason": data.get("reason"), "observed_at": str(data.get("observed_at") or now_iso())})
        fact = self._record(mission_id, "COVERAGE_MEASUREMENT", payload, provenance_refs=provenance or ("bank-coverage-provider",))
        if state in {"WAITING_REFRESH", "STALE", "SOURCE_IDENTITY_MISMATCH", "SOURCE_UNAVAILABLE", "AUTH_REQUIRED"}:
            self._set_goal_status(mission_id, payload["goal_id"], "WAITING_COVERAGE_REFRESH", reason=f"COVERAGE_{state}", provenance_refs=(fact["fact_id"],))
        else:
            self._set_goal_status(mission_id, payload["goal_id"], "MEASURING", reason=f"COVERAGE_{state}", provenance_refs=(fact["fact_id"],))
        return {"status": state, "truth_source": "R1_EVENT_STREAM", "measurement": fact, "actual_coverage": payload.get("effective_incremental_coverage_pct") if state == "AVAILABLE" else None}

    def record_blocker_gap(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        kind = _text(data.get("gap_kind"), "gap_kind").upper()
        if kind not in GAP_KINDS:
            raise RuntimeError("G4_GAP_KIND_INVALID", kind)
        payload = {
            "gap_id": _text(data.get("gap_id"), "gap_id"), "goal_id": _text(data.get("goal_id"), "goal_id"), "gap_kind": kind,
            "severity": str(data.get("severity") or "MEDIUM").upper(), "status": str(data.get("status") or "OPEN").upper(),
            "application_id": data.get("application_id"), "file": data.get("file"), "class": data.get("class"), "line": data.get("line"),
            "reason": data.get("reason"), "source_refs": list(data.get("source_refs") or []),
        }
        fact = self._record(mission_id, "BLOCKER_GAP", payload, provenance_refs=tuple(str(x) for x in payload["source_refs"]))
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "gap": fact}

    def _latest_gap_by_id(self, mission_id: str, goal_id: str) -> dict[str, Any]:
        latest: dict[str, Any] = {}
        for fact in self.state(mission_id).by_kind("BLOCKER_GAP"):
            if fact.payload.get("goal_id") == goal_id:
                latest[str(fact.payload.get("gap_id"))] = fact
        return latest

    def _open_gap_refs(self, mission_id: str, goal_id: str) -> list[str]:
        return sorted(
            fact.fact_id for fact in self._latest_gap_by_id(mission_id, goal_id).values()
            if str(fact.payload.get("status") or "OPEN").upper() not in {"RESOLVED", "CLOSED"}
        )

    def record_risk_acceptance(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        if data.get("human_authorized") is not True or not data.get("accepted_by"):
            raise RuntimeError("G4_HUMAN_RISK_ACCEPTANCE_REQUIRED", "human_authorized and accepted_by are required")
        goal_id = _text(data.get("goal_id"), "goal_id"); goal_record = self.goal(mission_id, goal_id); goal = goal_record["payload"]
        target = float(goal["coverage_policy"]["target_pct"])
        if data.get("target_pct") is not None and require_percentage(data.get("target_pct"), "target_pct") != target:
            raise RuntimeError("G4_RISK_ACCEPTANCE_GOAL_TARGET_MISMATCH", goal_id)
        measurements = self._latest_measurement_by_app(mission_id, goal_id)
        affected = [str(x) for x in goal["affected_applications"]]
        current = [measurements.get(app) for app in affected]
        if any(fact is None or fact.payload.get("state") != "AVAILABLE" for fact in current):
            raise RuntimeError("G4_RISK_ACCEPTANCE_CURRENT_MEASUREMENT_REQUIRED", goal_id)
        current_refs = sorted(fact.fact_id for fact in current if fact is not None)
        provided_refs = sorted(str(x) for x in (data.get("measurement_refs") or []))
        if provided_refs != current_refs:
            raise RuntimeError("G4_RISK_ACCEPTANCE_MEASUREMENT_BINDING_MISMATCH", goal_id)
        current_gap_refs = self._open_gap_refs(mission_id, goal_id)
        provided_gap_refs = sorted(str(x) for x in (data.get("residual_gap_refs") or data.get("residual_gaps") or []))
        if provided_gap_refs != current_gap_refs:
            raise RuntimeError("G4_RISK_ACCEPTANCE_RESIDUAL_GAP_BINDING_MISMATCH", goal_id)
        per_app = {str(f.payload["application_id"]): float(f.payload["effective_incremental_coverage_pct"]) for f in current if f is not None}
        supplied = data.get("actual_by_application")
        if supplied is not None:
            if not isinstance(supplied, Mapping) or {str(k): float(v) for k, v in supplied.items()} != per_app:
                raise RuntimeError("G4_RISK_ACCEPTANCE_ACTUAL_MISMATCH", goal_id)
        elif len(per_app) == 1 and data.get("actual_pct") is not None:
            actual = require_percentage(data.get("actual_pct"), "actual_pct")
            if actual != next(iter(per_app.values())):
                raise RuntimeError("G4_RISK_ACCEPTANCE_ACTUAL_MISMATCH", goal_id)
        bindings = [{
            "application_id": str(f.payload.get("application_id")), "measurement_ref": f.fact_id,
            "source_identity": f.payload.get("source_identity"), "baseline_identity_status": f.payload.get("baseline_identity_status"),
            "baseline_label": f.payload.get("baseline_label"), "target_version": f.payload.get("target_version"),
            "observed_at": f.payload.get("observed_at"),
        } for f in current if f is not None]
        if any(not item["source_identity"] or item["baseline_identity_status"] not in {"COMMIT_PINNED", "MASTER_ALIAS_ONLY"} for item in bindings):
            raise RuntimeError("G4_RISK_ACCEPTANCE_SOURCE_IDENTITY_REQUIRED", goal_id)
        goal_revision_ref = self._goal_revision_ref(mission_id, goal_id)
        payload = {
            "acceptance_id": _text(data.get("acceptance_id"), "acceptance_id"), "goal_id": goal_id,
            "goal_revision_ref": goal_revision_ref, "target_pct": target, "actual_by_application": per_app,
            "measurement_refs": current_refs, "measurement_binding_digest": canonical_sha256(bindings), "source_identity_bindings": bindings,
            "residual_gap_refs": current_gap_refs, "residual_gap_digest": canonical_sha256(current_gap_refs), "risk": _text(data.get("risk"), "risk"),
            "human_authorized": True, "accepted_by": str(data["accepted_by"]), "accepted_at": _text(data.get("accepted_at"), "accepted_at"),
        }
        fact = self._record(mission_id, "RISK_ACCEPTANCE", payload, provenance_refs=tuple([f"human:{payload['accepted_by']}"] + current_refs + current_gap_refs))
        return {"status": "ACCEPTED", "truth_source": "R1_EVENT_STREAM", "risk_acceptance": fact}

    def _latest_measurement_by_app(self, mission_id: str, goal_id: str) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for fact in self.state(mission_id).by_kind("COVERAGE_MEASUREMENT"):
            if fact.payload.get("goal_id") != goal_id:
                continue
            app = fact.payload.get("application_id")
            if app:
                values[str(app)] = fact
        return values

    def _risk_acceptance_is_current(self, mission_id: str, goal_id: str, acceptance: Any | None, measurements: Mapping[str, Any], open_gap_refs: list[str]) -> bool:
        if acceptance is None:
            return False
        goal = self.goal(mission_id, goal_id)["payload"]
        affected = [str(x) for x in goal["affected_applications"]]
        facts = [measurements.get(app) for app in affected]
        if any(f is None or f.payload.get("state") != "AVAILABLE" for f in facts):
            return False
        current_refs = sorted(f.fact_id for f in facts if f is not None)
        return (
            str(acceptance.payload.get("goal_revision_ref") or "") == self._goal_revision_ref(mission_id, goal_id)
            and sorted(str(x) for x in acceptance.payload.get("measurement_refs") or []) == current_refs
            and sorted(str(x) for x in acceptance.payload.get("residual_gap_refs") or []) == sorted(open_gap_refs)
        )

    def evaluate_goal(self, mission_id: str, goal_id: str) -> dict[str, Any]:
        goal = self.goal(mission_id, goal_id)["payload"]
        target = float(goal["coverage_policy"]["target_pct"]); affected = [str(x) for x in goal["affected_applications"]]
        measurements = self._latest_measurement_by_app(mission_id, goal_id); measurement_summary: dict[str, Any] = {}; pending_measurement = False; all_target = True
        for app in affected:
            fact = measurements.get(app)
            if fact is None or fact.payload.get("state") != "AVAILABLE":
                pending_measurement = True; all_target = False
                measurement_summary[app] = {"state": fact.payload.get("state") if fact else "MISSING", "pct": None, "measurement_ref": fact.fact_id if fact else None}
            else:
                pct = float(fact.payload.get("effective_incremental_coverage_pct") or 0.0)
                measurement_summary[app] = {"state": "AVAILABLE", "pct": pct, "measurement_ref": fact.fact_id, "source_identity": fact.payload.get("source_identity"), "baseline_identity_status": fact.payload.get("baseline_identity_status")}
                if pct < target: all_target = False
        latest_gaps = self._latest_gap_by_id(mission_id, goal_id)
        open_gaps = [f for f in latest_gaps.values() if str(f.payload.get("status") or "OPEN").upper() not in {"RESOLVED", "CLOSED"}]
        open_gap_refs = sorted(f.fact_id for f in open_gaps)
        critical = [f for f in open_gaps if f.payload.get("severity") == "CRITICAL"]
        batches = [f for f in self.state(mission_id).by_kind("EXECUTION_BATCH") if f.payload.get("goal_id") == goal_id]; latest_batch: dict[str, Any] = {}
        for f in batches: latest_batch[str(f.payload.get("batch_id"))] = f
        required_execution_pending = any(f.payload.get("status") in {"READY", "RUNNING"} for f in latest_batch.values())
        human_pending = self._pending_human_gates_for_goal(mission_id, goal_id)
        acceptance = self.state(mission_id).latest("RISK_ACCEPTANCE", lambda f: f.payload.get("goal_id") == goal_id)
        acceptance_current = self._risk_acceptance_is_current(mission_id, goal_id, acceptance, measurements, open_gap_refs)
        if pending_measurement:
            status = "WAITING_MEASUREMENT"
        elif all_target and not critical and not required_execution_pending and not human_pending:
            status = "SATISFIED"
        elif acceptance_current and not required_execution_pending and not human_pending:
            status = "COMPLETED_WITH_ACCEPTED_GAP"
        else:
            status = "REPLAN_REQUIRED"
        payload = {
            "evaluation_id": f"evaluation:{goal_id}:{self.runtime.get_head_seq(mission_id)}", "goal_id": goal_id, "status": status,
            "target_pct": target, "aggregation_policy": goal["coverage_policy"]["aggregation_policy"], "per_application": measurement_summary,
            "unresolved_critical_gap_refs": [f.fact_id for f in critical], "unresolved_gap_refs": open_gap_refs,
            "required_execution_pending": required_execution_pending, "required_measurement_pending": pending_measurement,
            "mandatory_human_gate_refs": [g.gate_id for g in human_pending],
            "risk_acceptance_ref": acceptance.fact_id if acceptance_current else None, "stale_risk_acceptance_ref": acceptance.fact_id if acceptance is not None and not acceptance_current else None,
        }
        fact = self._record(mission_id, "GOAL_EVALUATION", payload, provenance_refs=tuple([x.get("measurement_ref") for x in measurement_summary.values() if x.get("measurement_ref")] + open_gap_refs + [g.gate_id for g in human_pending]))
        goal_status = "WAITING_COVERAGE_REFRESH" if status == "WAITING_MEASUREMENT" else status if status in {"SATISFIED", "COMPLETED_WITH_ACCEPTED_GAP"} else ("WAITING_HUMAN" if human_pending else ("EXECUTING" if required_execution_pending else "REPLANNING"))
        status_fact = self._set_goal_status(mission_id, goal_id, goal_status, reason=f"GOAL_EVALUATION_{status}", provenance_refs=(fact["fact_id"],))
        return {"status": status, "truth_source": "R1_EVENT_STREAM", "evaluation": fact, "goal_status": status_fact}

    def record_iteration(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        before = data.get("coverage_before") or {}
        after = data.get("coverage_after") or {}
        if not isinstance(before, Mapping) or not isinstance(after, Mapping):
            raise RuntimeError("G4_ITERATION_COVERAGE_INVALID", "coverage_before/after must be objects")
        deltas = {app: float(after.get(app, 0.0)) - float(before.get(app, 0.0)) for app in set(before) | set(after)}
        status = str(data.get("status") or ("PROGRESSING" if any(value > float(data.get("plateau_epsilon", 0.0)) for value in deltas.values()) else "PLATEAU")).upper()
        if status not in ITERATION_STATUSES:
            raise RuntimeError("G4_ITERATION_STATUS_INVALID", status)
        payload = {
            "iteration_id": _text(data.get("iteration_id"), "iteration_id"), "goal_id": _text(data.get("goal_id"), "goal_id"),
            "coverage_before": dict(before), "coverage_after": dict(after), "coverage_delta": deltas,
            "new_changed_lines_covered": list(data.get("new_changed_lines_covered") or []), "remaining_coverage_gaps": list(data.get("remaining_coverage_gaps") or []),
            "cases_executed": list(data.get("cases_executed") or []), "new_execution_failures": list(data.get("new_execution_failures") or []),
            "new_observations": list(data.get("new_observations") or []), "human_blockers": list(data.get("human_blockers") or []),
            "strategy_revision_ref": data.get("strategy_revision_ref"), "status": status,
        }
        fact = self._record(mission_id, "TEST_LOOP_ITERATION", payload, provenance_refs=tuple(str(x) for x in payload["cases_executed"] + payload["remaining_coverage_gaps"]))
        return {"status": status, "truth_source": "R1_EVENT_STREAM", "iteration": fact}

    def request_g3_replan(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = _text(data.get("goal_id"), "goal_id")
        evaluation = self.evaluate_goal(mission_id, goal_id)
        if evaluation["status"] in {"SATISFIED", "COMPLETED_WITH_ACCEPTED_GAP"}:
            raise RuntimeError("G4_REPLAN_NOT_REQUIRED", evaluation["status"])
        payload = {
            "replan_request_id": str(data.get("replan_request_id") or f"replan:{goal_id}:{self.runtime.get_head_seq(mission_id)}"),
            "goal_id": goal_id, "strategy_revision_ref": data.get("strategy_revision_ref"),
            "actual_coverage_snapshot_refs": list(data.get("actual_coverage_snapshot_refs") or []),
            "remaining_coverage_gap_refs": list(data.get("remaining_coverage_gap_refs") or []),
            "execution_result_refs": list(data.get("execution_result_refs") or []), "unresolved_observation_refs": list(data.get("unresolved_observation_refs") or []),
            "blocker_refs": list(data.get("blocker_refs") or []), "budget_safety_status": dict(data.get("budget_safety_status") or {}),
            "status": "REQUESTED", "authority": "G3", "g4_case_authoring": "FORBIDDEN",
        }
        fact = self._record(mission_id, "REPLAN_REQUEST", payload, provenance_refs=tuple(str(x) for x in payload["actual_coverage_snapshot_refs"] + payload["remaining_coverage_gap_refs"] + payload["execution_result_refs"]))
        return {"status": "G3_REPLAN_REQUIRED", "truth_source": "R1_EVENT_STREAM", "replan_request": fact, "next_authority": "G3"}


class TestObjectiveController:
    """Non-LLM convergence controller over R1 facts. It never authors test cases."""

    def __init__(self, service: G4RealExecutionService) -> None:
        self.service = service

    def tick(self, mission_id: str, goal_id: str, *, replan_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        evaluation = self.service.evaluate_goal(mission_id, goal_id)
        status = evaluation["status"]
        if status == "SATISFIED":
            return {"status": "SATISFIED", "truth_source": "R1_EVENT_STREAM", "evaluation": evaluation["evaluation"], "next_action": "NONE"}
        if status == "COMPLETED_WITH_ACCEPTED_GAP":
            return {"status": status, "truth_source": "R1_EVENT_STREAM", "evaluation": evaluation["evaluation"], "next_action": "NONE"}
        if status == "WAITING_MEASUREMENT":
            return {"status": "WAITING_MEASUREMENT", "truth_source": "R1_EVENT_STREAM", "evaluation": evaluation["evaluation"], "next_action": "WAIT_COVERAGE_REFRESH"}
        context = dict(replan_context or {})
        context["goal_id"] = goal_id
        replan = self.service.request_g3_replan(mission_id, context)
        return {"status": "REPLANNING", "truth_source": "R1_EVENT_STREAM", "evaluation": evaluation["evaluation"], "replan": replan["replan_request"], "next_action": "G3_REPLAN"}
