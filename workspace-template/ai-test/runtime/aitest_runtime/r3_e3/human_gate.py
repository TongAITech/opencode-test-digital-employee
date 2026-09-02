from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.common import now_iso
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.r2_6.contracts import APPLIED, EXTERNAL_ACTION_COMPLETED, REFERENCE, RESUME_EXECUTION
from aitest_runtime.r3_e2.contracts import BrowserContextRef, ContinuationProof, HumanGateReference

from .contracts import R3E3Error


class R26HumanGateBridge:
    """Adapter over the canonical R2.6 HumanGate/continuation services."""

    def __init__(self, service: Any | None = None, *, fallback_port: Any | None = None) -> None:
        self.service = service
        self.fallback_port = fallback_port
        self._missions: dict[str, str] = {}
        self._lineage: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _reference(gate: Any) -> HumanGateReference:
        approved = gate.status == "RESOLVED" and gate.decision_outcome == EXTERNAL_ACTION_COMPLETED
        if gate.status == "RESOLVED" and gate.decision_outcome not in {EXTERNAL_ACTION_COMPLETED, "REJECTED"}:
            approved = False
        return HumanGateReference(
            gate.gate_id,
            gate.gate_kind,
            "SUT_AUTHENTICATION_4A",
            "APPROVED" if approved else ("REJECTED" if gate.decision_outcome == "REJECTED" else "PENDING"),
            gate.decision_id if approved else None,
            gate.decision_digest if approved else None,
        )

    def open_external_action(self, *, mission_id: str, lineage_refs: Mapping[str, Any], browser_context_ref: BrowserContextRef) -> HumanGateReference:
        if self.fallback_port is not None and self.service is None:
            result = self.fallback_port.open_external_action(mission_id=mission_id, lineage_refs=lineage_refs, browser_context_ref=browser_context_ref)
            self._missions[result.gate_id] = mission_id
            self._lineage[result.gate_id] = dict(lineage_refs)
            return result
        if self.service is None:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "canonical R2.6 HumanGate service is not configured")
        lineage = dict(lineage_refs)
        required = ("plan_id", "plan_revision_id", "task_id", "root_attempt_id", "origin_attempt_id", "origin_session_id")
        missing = [name for name in required if not lineage.get(name)]
        if missing:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", f"R2.6 lineage is incomplete: {','.join(missing)}")
        gate_id = str(lineage.get("gate_id") or f"r3.e3:{mission_id}:{lineage['root_attempt_id']}:AUTH")
        request_payload = {
            "purpose": "SUT_AUTHENTICATION_4A",
            "browser_session_id": browser_context_ref.browser_session_id,
            "browser_context_id_or_epoch": browser_context_ref.browser_context_id_or_epoch,
            "context_binding_digest": browser_context_ref.context_binding_digest,
        }
        source_digest = canonical_sha256({"mission_id": mission_id, "gate_id": gate_id, "lineage": lineage, "context": browser_context_ref.to_dict()})
        result = self.service.open_gate(
            mission_id=mission_id,
            gate_id=gate_id,
            plan_id=str(lineage["plan_id"]),
            plan_revision_id=str(lineage["plan_revision_id"]),
            task_id=str(lineage["task_id"]),
            root_attempt_id=str(lineage["root_attempt_id"]),
            origin_attempt_id=str(lineage["origin_attempt_id"]),
            origin_session_id=str(lineage["origin_session_id"]),
            gate_kind="EXTERNAL_ACTION",
            request_payload_mode=REFERENCE,
            request_payload=request_payload,
            response_schema={"action": "SUT_AUTHENTICATION_4A", "browser_context": "opaque"},
            decision_policy_id="r3.e3.sut_authentication_4a",
            decision_policy_version=1,
            decision_policy_digest=canonical_sha256({"gate_kind": "EXTERNAL_ACTION", "action": "SUT_AUTHENTICATION_4A"}),
            allowed_outcomes=[EXTERNAL_ACTION_COMPLETED, "REJECTED"],
            allowed_routes_by_outcome={EXTERNAL_ACTION_COMPLETED: [RESUME_EXECUTION], "REJECTED": ["BLOCK"]},
            request_provenance={"source_ref": "r3.e3", "source_digest": source_digest, "observed_at": now_iso()},
        )
        gate = result.gate
        if gate is None:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "R2.6 did not return the opened gate")
        self._missions[gate_id] = mission_id
        self._lineage[gate_id] = lineage
        return self._reference(gate)

    def read_decision(self, gate_ref: HumanGateReference) -> HumanGateReference:
        if self.fallback_port is not None and self.service is None:
            return self.fallback_port.read_decision(gate_ref)
        if self.service is None or gate_ref.gate_id not in self._missions:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "HumanGate reference is not bound to canonical R2.6 service")
        mission_id = self._missions[gate_ref.gate_id]
        gate = self.service.state(mission_id).gate(gate_ref.gate_id)
        if gate is None:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "canonical R2.6 gate is missing")
        return self._reference(gate)

    def record_resume(self, *, mission_id: str, gate_ref: HumanGateReference, auth_context_id: str, browser_context_ref: BrowserContextRef) -> ContinuationProof:
        if self.fallback_port is not None and self.service is None:
            return self.fallback_port.record_resume(
                mission_id=mission_id,
                gate_ref=gate_ref,
                auth_context_id=auth_context_id,
                browser_context_ref=browser_context_ref,
            )
        if self.service is None:
            raise R3E3Error("R3_E3_HUMAN_GATE_BOUNDARY_UNAVAILABLE", "canonical R2.6 continuation service is not configured")
        lineage = self._lineage.get(gate_ref.gate_id) or {}
        canonical_reference = lineage.get("canonical_reference")
        if not isinstance(canonical_reference, Mapping):
            raise R3E3Error("R3_E3_CONTINUATION_SOURCE_CONFLICT", "canonical R2.6 RESUME_EXECUTION reference is unavailable")
        result = self.service.record_continuation(
            mission_id=mission_id,
            gate_id=gate_ref.gate_id,
            route=RESUME_EXECUTION,
            canonical_reference=dict(canonical_reference),
            continuation_provenance={
                "source_ref": "r3.e3",
                "source_digest": canonical_sha256({"auth_context_id": auth_context_id, "browser_context_ref": browser_context_ref.to_dict()}),
                "observed_at": now_iso(),
            },
        )
        gate = result.gate
        if gate is None or gate.continuation_state != APPLIED or not gate.continuation_reference:
            raise R3E3Error("R3_E3_CONTINUATION_SOURCE_CONFLICT", "R2.6 continuation did not reach APPLIED")
        reference = dict(gate.continuation_reference)
        return ContinuationProof(
            gate_ref.gate_id,
            RESUME_EXECUTION,
            reference.get("canonical_reference") or dict(canonical_reference),
            int(reference.get("source_seq") or gate.created_seq),
            str(reference.get("source_digest") or ""),
            str(reference.get("continuation_operation_id") or gate_ref.gate_id),
            {"source_ref": "r3.e3", "source_digest": str(reference.get("source_digest") or ""), "observed_at": now_iso()},
            True,
        )
