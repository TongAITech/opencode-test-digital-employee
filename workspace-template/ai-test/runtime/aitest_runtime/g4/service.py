from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.execution_resume.contracts import ExecutionAttemptRecord

# Wave 2 keeps the already-reviewed G4 implementation byte-for-byte as the base
# and applies only the authorized governed-execution hardening in this module.
from .service_base import *  # noqa: F401,F403
from .service_base import (
    G4RealExecutionService as _BaseG4RealExecutionService,
    _dict,
    _g3_state,
    _text,
)


@dataclass(frozen=True)
class GovernedExecutionBinding:
    case_spec_fact_id: str
    case_id: str
    case_version_id: str
    case_value_link_fact_id: str
    strategy_version_id: str
    strategy_fingerprint: str
    execution_batch_fact_id: str
    batch_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_spec_fact_id": self.case_spec_fact_id,
            "case_id": self.case_id,
            "case_version_id": self.case_version_id,
            "case_value_link_fact_id": self.case_value_link_fact_id,
            "strategy_version_id": self.strategy_version_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "binding_kind": "EXECUTION_BATCH",
            "binding_ref": self.execution_batch_fact_id,
            "batch_id": self.batch_id,
        }


class G4RealExecutionService(_BaseG4RealExecutionService):
    """Wave-2 hardened G4 service.

    R2-2 invariant: no cursor, provider execution or durable step result may be
    created for caller-only case identity.  Every execution must resolve exact
    governed G3 Case/CaseValueLink/Strategy truth and one active ExecutionBatch.
    """

    def _resolve_governed_case(
        self, mission_id: str, case_id: str, case_version_id: str,
    ) -> tuple[Any, Any, str, str]:
        g3 = _g3_state(self.runtime, mission_id)
        if g3 is None or not hasattr(g3, "by_kind"):
            raise RuntimeError("G4_G3_GOVERNED_CASE_REQUIRED", case_version_id)
        matches: list[tuple[Any, dict[str, Any]]] = []
        for fact in g3.by_kind("CASE_SPECIFICATION"):
            case = dict(fact.payload.get("r3_3_case") or {})
            if str(case.get("tc_id") or "") == case_id and str(case.get("case_version_id") or "") == case_version_id:
                matches.append((fact, case))
        if len(matches) != 1:
            raise RuntimeError("G4_G3_GOVERNED_CASE_REQUIRED", f"{case_id}:{case_version_id}")
        case_fact, case = matches[0]
        links = [
            fact for fact in g3.by_kind("CASE_VALUE_LINK")
            if str(fact.payload.get("case_version_id") or "") == case_version_id
            and case_fact.fact_id in tuple(fact.provenance_refs)
        ]
        if len(links) != 1:
            raise RuntimeError("G4_CASE_VALUE_LINK_REQUIRED", case_fact.fact_id)
        strategy_version_id = _text(case.get("strategy_version_id"), "strategy_version_id")
        portfolios = [
            fact for fact in g3.by_kind("TEST_STRATEGY_PORTFOLIO")
            if str((fact.payload.get("r3_3_strategy") or {}).get("strategy_version_id") or "") == strategy_version_id
        ]
        if not portfolios:
            raise RuntimeError("G4_G3_STRATEGY_IDENTITY_REQUIRED", strategy_version_id)
        strategy = dict(portfolios[-1].payload.get("r3_3_strategy") or {})
        fingerprint = _text(strategy.get("strategy_fingerprint"), "strategy_fingerprint")
        return case_fact, links[0], strategy_version_id, fingerprint

    def _validate_governed_execution(
        self,
        mission_id: str,
        request: Mapping[str, Any],
        *,
        attempt: ExecutionAttemptRecord | None = None,
    ) -> GovernedExecutionBinding:
        data = _dict(request, "request")
        case_id = _text(data.get("case_id"), "case_id")
        case_version_id = _text(data.get("case_version") or data.get("case_version_id"), "case_version")
        case_fact, link_fact, strategy_version_id, fingerprint = self._resolve_governed_case(
            mission_id, case_id, case_version_id,
        )
        if data.get("case_spec_fact_id") and str(data["case_spec_fact_id"]) != case_fact.fact_id:
            raise RuntimeError("G4_CASE_SPEC_BINDING_MISMATCH", str(data["case_spec_fact_id"]))
        if data.get("strategy_version_id") and str(data["strategy_version_id"]) != strategy_version_id:
            raise RuntimeError("G4_CASE_STRATEGY_BINDING_MISMATCH", case_fact.fact_id)

        latest: dict[str, Any] = {}
        for fact in self.state(mission_id).by_kind("EXECUTION_BATCH"):
            batch_id = str(fact.payload.get("batch_id") or "")
            if batch_id:
                latest[batch_id] = fact
        requested_batch_id = str(data.get("execution_batch_id") or "")
        candidates = []
        for batch_id, fact in latest.items():
            payload = fact.payload
            if requested_batch_id and batch_id != requested_batch_id:
                continue
            if str(payload.get("status") or "").upper() not in {"READY", "RUNNING"}:
                continue
            if case_fact.fact_id not in tuple(payload.get("case_refs") or ()):
                continue
            if str(payload.get("strategy_version_id") or "") != strategy_version_id:
                continue
            candidates.append(fact)
        if len(candidates) != 1:
            raise RuntimeError("G4_EXECUTION_BINDING_REQUIRED", f"{case_fact.fact_id}:matches={len(candidates)}")
        batch = candidates[0]
        return GovernedExecutionBinding(
            case_fact.fact_id,
            case_id,
            case_version_id,
            link_fact.fact_id,
            strategy_version_id,
            fingerprint,
            batch.fact_id,
            str(batch.payload.get("batch_id")),
        )

    def create_batch(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        case_refs = [str(value) for value in (data.get("case_refs") or []) if str(value)]
        if not case_refs:
            raise RuntimeError("G4_EXECUTION_BATCH_CASES_REQUIRED", "case_refs")
        expected_strategy = _text(data.get("strategy_version_id"), "strategy_version_id")
        g3 = _g3_state(self.runtime, mission_id)
        for case_ref in case_refs:
            case_fact = g3.by_id(case_ref) if g3 is not None and hasattr(g3, "by_id") else None
            if case_fact is None or case_fact.fact_kind != "CASE_SPECIFICATION":
                raise RuntimeError("G4_G3_GOVERNED_CASE_REQUIRED", case_ref)
            case = dict(case_fact.payload.get("r3_3_case") or {})
            case_id = _text(case.get("tc_id"), "case_id")
            case_version = _text(case.get("case_version_id"), "case_version_id")
            resolved_fact, _, strategy_version_id, _ = self._resolve_governed_case(mission_id, case_id, case_version)
            if resolved_fact.fact_id != case_ref or strategy_version_id != expected_strategy:
                raise RuntimeError("G4_CASE_STRATEGY_BINDING_MISMATCH", case_ref)
        return super().create_batch(mission_id, data)

    def create_focused_execution_binding(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        """Focused execution is a one-case governed ExecutionBatch, not a second truth model."""
        data = _dict(request, "request")
        case_id = _text(data.get("case_id"), "case_id")
        case_version = _text(data.get("case_version") or data.get("case_version_id"), "case_version")
        case_fact, _, strategy_version_id, _ = self._resolve_governed_case(mission_id, case_id, case_version)
        binding_id = _text(data.get("binding_id"), "binding_id")
        batch = self.create_batch(mission_id, {
            "batch_id": f"focused:{binding_id}",
            "goal_id": _text(data.get("goal_id"), "goal_id"),
            "case_refs": [case_fact.fact_id],
            "strategy_version_id": strategy_version_id,
            "target_application": _text(data.get("target_application"), "target_application"),
            "target_coverage_gaps": list(data.get("target_coverage_gaps") or []),
            "target_hypotheses": list(data.get("target_hypotheses") or []),
            "expected_value": {"focused_execution_binding_id": binding_id},
            "status": "RUNNING",
        })
        return {
            "status": "ACTIVE",
            "truth_source": "R1_EVENT_STREAM",
            "binding_kind": "EXECUTION_BATCH",
            "binding_id": binding_id,
            "execution_batch_id": batch["batch"]["payload"]["batch_id"],
            "batch": batch["batch"],
        }

    def record_cursor(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        task_id = _text(data.get("task_id"), "task_id")
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), task_id)
        case_id = _text(data.get("case_id"), "case_id")
        case_version = _text(data.get("case_version"), "case_version")
        binding = self._validate_governed_execution(mission_id, data, attempt=attempt)
        current_step_index = int(data.get("current_step_index", 0))
        if current_step_index < 0:
            raise RuntimeError("G4_STEP_CURSOR_INVALID", "current_step_index must be non-negative")
        payload = {
            "cursor_id": str(data.get("cursor_id") or f"cursor:{attempt.root_attempt_id}:{case_id}:{case_version}"),
            "case_id": case_id,
            "case_version": case_version,
            "task_id": task_id,
            "attempt_id": attempt.attempt_id,
            "root_attempt_id": attempt.root_attempt_id,
            "current_step_index": current_step_index,
            "completed_step_ids": list(data.get("completed_step_ids") or []),
            "pending_step_id": data.get("pending_step_id"),
            "last_safe_checkpoint": data.get("last_safe_checkpoint"),
            "status": str(data.get("status") or "RUNNING").upper(),
            "governed_execution_binding": binding.to_dict(),
        }
        fact_id = f"g4:step-cursor:{canonical_sha256({key: payload[key] for key in ('cursor_id','attempt_id','current_step_index','status','pending_step_id')})[:24]}"
        fact = self._record(
            mission_id,
            "STEP_CURSOR",
            payload,
            provenance_refs=(f"r1.3b:{attempt.attempt_id}", binding.case_spec_fact_id, binding.case_value_link_fact_id, binding.execution_batch_fact_id),
            fact_id=fact_id,
        )
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "cursor": fact}

    def execute_capability(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        task_id = _text(data.get("task_id"), "task_id")
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), task_id)
        # Validate before provider lookup/prepare/execute so fake caller cases cannot create side effects.
        self._validate_governed_execution(mission_id, data, attempt=attempt)
        return super().execute_capability(mission_id, data)

    def record_step_result(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        attempt = self._canonical_attempt(mission_id, _text(data.get("attempt_id"), "attempt_id"), _text(data.get("task_id"), "task_id"))
        binding = self._validate_governed_execution(mission_id, data, attempt=attempt)
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
            "step_id": str(data["step_id"]),
            "attempt_id": attempt.attempt_id,
            "root_attempt_id": attempt.root_attempt_id,
            "task_id": attempt.task_id,
            "case_id": binding.case_id,
            "case_version": binding.case_version_id,
            "executor_capability": _text(data.get("executor_capability"), "executor_capability").upper(),
            "input_ref": data.get("input_ref"),
            "expected": data["expected"],
            "actual": data["actual"],
            "oracle_result": oracle,
            "oracle_reason": str(data["oracle_reason"]),
            "evidence_refs": list(evidence),
            "source_identity": str(data["source_identity"]),
            "execution_node": data.get("execution_node"),
            "auth_context_ref": data.get("auth_context_ref"),
            "side_effect_summary": data.get("side_effect_summary"),
            "test_fail_is_confirmed_defect": False,
            "governed_execution_binding": binding.to_dict(),
        }
        fact = self._record(
            mission_id,
            "EXECUTION_STEP_RESULT",
            payload,
            provenance_refs=tuple(str(value) for value in evidence)
            + (binding.case_spec_fact_id, binding.case_value_link_fact_id, binding.execution_batch_fact_id),
        )
        if oracle in {"FAIL", "INCONCLUSIVE", "ERROR"}:
            self._record(
                mission_id,
                "UNEXPECTED_OBSERVATION",
                {"step_result_ref": fact["fact_id"], "oracle_result": oracle, "status": "OBSERVATION_ONLY", "g5_defect_truth": "HOLD"},
                provenance_refs=(fact["fact_id"],),
            )
        return {"status": oracle, "truth_source": "R1_EVENT_STREAM", "result": fact, "g5_defect_truth": "HOLD"}
