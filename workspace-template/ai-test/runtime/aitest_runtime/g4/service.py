from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError

from .contracts import ORACLE_STATUSES
from .evidence_safety import sanitize_evidence_ingress
from .service_r2_5 import *  # noqa: F401,F403
from .service_r2_5 import G4RealExecutionService as _R2_5_G4RealExecutionService, _dict, _text


class G4RealExecutionService(_R2_5_G4RealExecutionService):
    """R2-6: typed sensitive-evidence taint/redaction before any durable R1 write."""

    def record_step_result(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        attempt = self._canonical_attempt(
            mission_id,
            _text(data.get("attempt_id"), "attempt_id"),
            _text(data.get("task_id"), "task_id"),
        )
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
