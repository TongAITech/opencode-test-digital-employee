from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError

from .contracts import GAP_KINDS, ITERATION_STATUSES, ORACLE_STATUSES
from .evidence_safety import EvidenceSanitization, sanitize_evidence_ingress
from .service_r2_5 import *  # noqa: F401,F403
from .service_r2_5 import G4RealExecutionService as _R2_5_G4RealExecutionService
from .service_base import _dict, _text


def _taint_metadata(*results: EvidenceSanitization) -> dict[str, Any]:
    return {
        "policy": "TYPED_INGRESS_REDACTION_V1",
        "classifications": sorted({classification for result in results for classification in result.classifications}),
        "redaction_count": sum(result.redaction_count for result in results),
        "raw_sensitive_value_persisted": False,
    }


class G4RealExecutionService(_R2_5_G4RealExecutionService):
    """R2-6: typed sensitive-evidence taint/redaction before every carrying R1 write."""

    def register_capability(
        self,
        mission_id: str,
        capability_id: str,
        status: str,
        *,
        provider_ref: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = sanitize_evidence_ingress(provider_ref, path="capability.provider_ref")
        meta = sanitize_evidence_ingress(dict(metadata or {}), path="capability.provider_metadata")
        safe_metadata = dict(meta.value)
        safe_metadata["sensitive_ingress"] = _taint_metadata(provider, meta)
        return super().register_capability(
            mission_id,
            capability_id,
            status,
            provider_ref=provider.value,
            metadata=safe_metadata,
        )

    def capability_human_gate(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        action = sanitize_evidence_ingress(data.get("required_action"), path="human_gate.required_action")
        executor = sanitize_evidence_ingress(data.get("executor_request") or {}, path="human_gate.executor_request")
        # Validation consumes the sanitized semantic request. Credential material is
        # never authority for deciding whether a HumanGate is required.
        safe = {**data, "required_action": action.value, "executor_request": executor.value}
        return super().capability_human_gate(mission_id, safe)

    def request_human_takeover(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        required_action = sanitize_evidence_ingress(data.get("required_action"), path="takeover.required_action")
        reason = sanitize_evidence_ingress(data.get("reason"), path="takeover.reason")
        current_url = sanitize_evidence_ingress(data.get("current_url"), path="takeover.current_url")
        allowed_scope = sanitize_evidence_ingress(data.get("allowed_scope") or {}, path="takeover.allowed_scope")
        resume_condition = sanitize_evidence_ingress(data.get("resume_condition") or {}, path="takeover.resume_condition")
        safe = {
            **data,
            "required_action": required_action.value,
            "reason": reason.value,
            "current_url": current_url.value,
            "allowed_scope": allowed_scope.value,
            "resume_condition": resume_condition.value,
        }
        return super().request_human_takeover(mission_id, safe)

    def create_batch(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        expected_value = sanitize_evidence_ingress(data.get("expected_value") or {}, path="batch.expected_value")
        target_gaps = sanitize_evidence_ingress(data.get("target_coverage_gaps") or [], path="batch.target_coverage_gaps")
        target_hypotheses = sanitize_evidence_ingress(data.get("target_hypotheses") or [], path="batch.target_hypotheses")
        return super().create_batch(
            mission_id,
            {
                **data,
                "expected_value": expected_value.value,
                "target_coverage_gaps": target_gaps.value,
                "target_hypotheses": target_hypotheses.value,
            },
        )

    def record_blocker_gap(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = _text(data.get("goal_id"), "goal_id")
        self.assert_goal_mutable(mission_id, goal_id, mutation="record_blocker_gap")
        kind = _text(data.get("gap_kind"), "gap_kind").upper()
        if kind not in GAP_KINDS:
            raise RuntimeError("G4_GAP_KIND_INVALID", kind)
        reason = sanitize_evidence_ingress(data.get("reason"), path="blocker.reason")
        source_refs = sanitize_evidence_ingress(data.get("source_refs") or [], path="blocker.source_refs")
        application_id = sanitize_evidence_ingress(data.get("application_id"), path="blocker.application_id")
        file_value = sanitize_evidence_ingress(data.get("file"), path="blocker.file")
        class_value = sanitize_evidence_ingress(data.get("class"), path="blocker.class")
        taint = _taint_metadata(reason, source_refs, application_id, file_value, class_value)
        payload = {
            "gap_id": _text(data.get("gap_id"), "gap_id"),
            "goal_id": goal_id,
            "gap_kind": kind,
            "severity": str(data.get("severity") or "MEDIUM").upper(),
            "status": str(data.get("status") or "OPEN").upper(),
            "application_id": application_id.value,
            "file": file_value.value,
            "class": class_value.value,
            "line": data.get("line"),
            "reason": reason.value,
            "source_refs": list(source_refs.value),
            "sensitive_ingress": taint,
        }
        fact = self._record(
            mission_id,
            "BLOCKER_GAP",
            payload,
            provenance_refs=tuple(str(value) for value in payload["source_refs"]),
        )
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "gap": fact}

    def record_risk_acceptance(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        risk = sanitize_evidence_ingress(data.get("risk"), path="risk_acceptance.risk")
        accepted_by = sanitize_evidence_ingress(data.get("accepted_by"), path="risk_acceptance.accepted_by")
        return super().record_risk_acceptance(
            mission_id,
            {**data, "risk": risk.value, "accepted_by": accepted_by.value},
        )

    def record_iteration(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = _text(data.get("goal_id"), "goal_id")
        self.assert_goal_mutable(mission_id, goal_id, mutation="record_iteration")
        before = data.get("coverage_before") or {}
        after = data.get("coverage_after") or {}
        if not isinstance(before, Mapping) or not isinstance(after, Mapping):
            raise RuntimeError("G4_ITERATION_COVERAGE_INVALID", "coverage_before/after must be objects")
        deltas = {app: float(after.get(app, 0.0)) - float(before.get(app, 0.0)) for app in set(before) | set(after)}
        status = str(data.get("status") or ("PROGRESSING" if any(value > float(data.get("plateau_epsilon", 0.0)) for value in deltas.values()) else "PLATEAU")).upper()
        if status not in ITERATION_STATUSES:
            raise RuntimeError("G4_ITERATION_STATUS_INVALID", status)
        changed_lines = sanitize_evidence_ingress(data.get("new_changed_lines_covered") or [], path="iteration.new_changed_lines_covered")
        remaining = sanitize_evidence_ingress(data.get("remaining_coverage_gaps") or [], path="iteration.remaining_coverage_gaps")
        cases = sanitize_evidence_ingress(data.get("cases_executed") or [], path="iteration.cases_executed")
        failures = sanitize_evidence_ingress(data.get("new_execution_failures") or [], path="iteration.new_execution_failures")
        observations = sanitize_evidence_ingress(data.get("new_observations") or [], path="iteration.new_observations")
        blockers = sanitize_evidence_ingress(data.get("human_blockers") or [], path="iteration.human_blockers")
        strategy = sanitize_evidence_ingress(data.get("strategy_revision_ref"), path="iteration.strategy_revision_ref")
        taint = _taint_metadata(changed_lines, remaining, cases, failures, observations, blockers, strategy)
        payload = {
            "iteration_id": _text(data.get("iteration_id"), "iteration_id"),
            "goal_id": goal_id,
            "coverage_before": dict(before),
            "coverage_after": dict(after),
            "coverage_delta": deltas,
            "new_changed_lines_covered": list(changed_lines.value),
            "remaining_coverage_gaps": list(remaining.value),
            "cases_executed": list(cases.value),
            "new_execution_failures": list(failures.value),
            "new_observations": list(observations.value),
            "human_blockers": list(blockers.value),
            "strategy_revision_ref": strategy.value,
            "status": status,
            "sensitive_ingress": taint,
        }
        fact = self._record(
            mission_id,
            "TEST_LOOP_ITERATION",
            payload,
            provenance_refs=tuple(str(value) for value in payload["cases_executed"] + payload["remaining_coverage_gaps"]),
        )
        return {"status": status, "truth_source": "R1_EVENT_STREAM", "iteration": fact}

    def record_step_result(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        attempt = self._canonical_attempt(
            mission_id,
            _text(data.get("attempt_id"), "attempt_id"),
            _text(data.get("task_id"), "task_id"),
        )
        binding = self._validate_governed_execution(mission_id, data, attempt=attempt)
        batch = self.state(mission_id).by_id(binding.execution_batch_fact_id)
        if batch is None or batch.fact_kind != "EXECUTION_BATCH":
            raise RuntimeError("G4_EXECUTION_BINDING_REQUIRED", binding.execution_batch_fact_id)
        self.assert_goal_mutable(
            mission_id,
            _text(batch.payload.get("goal_id"), "goal_id"),
            mutation="record_step_result",
        )
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

        sensitive_entry_mode = bool(data.get("sensitive_entry_mode"))
        fields = {
            "expected": sanitize_evidence_ingress(data["expected"], path="step.expected"),
            "actual": sanitize_evidence_ingress(data["actual"], path="step.actual", sensitive_entry_mode=sensitive_entry_mode),
            "input_ref": sanitize_evidence_ingress(data.get("input_ref"), path="step.input_ref"),
            "evidence_refs": sanitize_evidence_ingress(evidence, path="step.evidence_refs"),
            "evidence_metadata": sanitize_evidence_ingress(data.get("evidence_metadata") or {}, path="step.evidence_metadata", sensitive_entry_mode=sensitive_entry_mode),
            "source_identity": sanitize_evidence_ingress(str(data["source_identity"]), path="step.source_identity"),
            "auth_context_ref": sanitize_evidence_ingress(data.get("auth_context_ref"), path="step.auth_context_ref"),
            "side_effect_summary": sanitize_evidence_ingress(data.get("side_effect_summary"), path="step.side_effect_summary"),
        }
        classifications = sorted({classification for result in fields.values() for classification in result.classifications})
        redaction_count = sum(result.redaction_count for result in fields.values())
        payload = {
            "step_id": str(data["step_id"]),
            "attempt_id": attempt.attempt_id,
            "root_attempt_id": attempt.root_attempt_id,
            "task_id": attempt.task_id,
            "case_id": binding.case_id,
            "case_version": binding.case_version_id,
            "executor_capability": _text(data.get("executor_capability"), "executor_capability").upper(),
            "input_ref": fields["input_ref"].value,
            "expected": fields["expected"].value,
            "actual": fields["actual"].value,
            "oracle_result": oracle,
            "oracle_reason": str(data["oracle_reason"]),
            "evidence_refs": fields["evidence_refs"].value,
            "evidence_metadata": fields["evidence_metadata"].value,
            "source_identity": fields["source_identity"].value,
            "execution_node": data.get("execution_node"),
            "auth_context_ref": fields["auth_context_ref"].value,
            "side_effect_summary": fields["side_effect_summary"].value,
            "sensitive_entry_mode": sensitive_entry_mode,
            "evidence_taint": {
                "policy": "TYPED_INGRESS_REDACTION_V1",
                "classifications": classifications,
                "redaction_count": redaction_count,
                "raw_sensitive_value_persisted": False,
            },
            "test_fail_is_confirmed_defect": False,
            "governed_execution_binding": binding.to_dict(),
        }
        fact = self._record(
            mission_id,
            "EXECUTION_STEP_RESULT",
            payload,
            provenance_refs=tuple(str(value) for value in fields["evidence_refs"].value)
            + (binding.case_spec_fact_id, binding.case_value_link_fact_id, binding.execution_batch_fact_id),
        )
        if oracle in {"FAIL", "INCONCLUSIVE", "ERROR"}:
            self._record(
                mission_id,
                "UNEXPECTED_OBSERVATION",
                {
                    "step_result_ref": fact["fact_id"],
                    "oracle_result": oracle,
                    "status": "OBSERVATION_ONLY",
                    "g5_defect_truth": "HOLD",
                },
                provenance_refs=(fact["fact_id"],),
            )
        return {"status": oracle, "truth_source": "R1_EVENT_STREAM", "result": fact, "g5_defect_truth": "HOLD"}
