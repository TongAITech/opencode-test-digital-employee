"""Persisted RC7.2 N1-N10 Autonomous Test Runtime state machine.

This service sits on the canonical R1 repository. It does not infer truth from
Agent chat/session history and it does not replace the inherited RC7.1 state
machine. PASS is gate-controlled; execution failure goes to N8; diagnosis can
create persisted semantic back-edges; upstream changes create persisted
ImpactSets and STALE runtime assets.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .models import ContractError, Gap, GapSeverity
from .rc72_domain import (
    AutonomousMissionNode,
    BackEdge,
    ETUState,
    ExecutionTaskUnit,
    MissionNodeRecord,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
    ObligationStatus,
    ReleaseBatch,
    TestObligation,
)
from .rc72_impact import ImpactSet, ImpactStrategy
from .rc72_impact_truth import append_impact_set
from .rc72_linkage import NodeTransition, NodeTransitionKind
from .rc72_phase2_truth import install_rc72_phase2_truth_overlay
from .rc72_repository import CanonicalRC72Repository
from .truth_overlay import append_entity


install_rc72_phase2_truth_overlay()


class StateMachineContractError(ContractError):
    pass


class FailureClass(str, Enum):
    ENVIRONMENT_GAP = "ENVIRONMENT_GAP"
    REQUIREMENT_GAP = "REQUIREMENT_GAP"
    ANALYSIS_GAP = "ANALYSIS_GAP"
    TEST_DESIGN_GAP = "TEST_DESIGN_GAP"
    TEST_DATA_GAP = "TEST_DATA_GAP"
    EXECUTABLE_GAP = "EXECUTABLE_GAP"
    PRODUCT_DEFECT = "PRODUCT_DEFECT"
    PROVIDER_AUTH = "PROVIDER_AUTH"
    PROVIDER_QUOTA = "PROVIDER_QUOTA"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    VALID_TEST_FAILURE = "VALID_TEST_FAILURE"
    FLAKY = "FLAKY"
    UNKNOWN = "UNKNOWN"


class ReleaseConvergenceResult(str, Enum):
    CONVERGED = "CONVERGED"
    NOT_CONVERGED = "NOT_CONVERGED"
    HUMAN_GATE = "HUMAN_GATE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ReleaseConvergenceFacts:
    requirement_completion: bool
    sst_completion: bool
    obligation_completion: bool
    required_l1_l7_completion: bool
    high_risk_completion: bool
    incremental_coverage_met: bool
    critical_defects_closed: bool
    no_blocked_workitems: bool
    no_unresolved_gaps: bool
    evidence_complete: bool
    runtime_integrity: bool
    human_gate_required: bool = False
    runtime_blocked: bool = False


@dataclass(frozen=True)
class DiagnosisRoute:
    failure_class: FailureClass
    responsible_node: Optional[AutonomousMissionNode]
    action: str
    gap_id: Optional[str] = None
    back_edge_id: Optional[str] = None
    transition_id: Optional[str] = None


_NODE_ROUTE: Dict[FailureClass, AutonomousMissionNode] = {
    FailureClass.ENVIRONMENT_GAP: AutonomousMissionNode.N1_REALITY,
    FailureClass.REQUIREMENT_GAP: AutonomousMissionNode.N2_REQUIREMENT,
    FailureClass.ANALYSIS_GAP: AutonomousMissionNode.N3_CODE_ANALYSIS,
    FailureClass.TEST_DESIGN_GAP: AutonomousMissionNode.N4_TEST_DESIGN,
    FailureClass.TEST_DATA_GAP: AutonomousMissionNode.N5_TEST_DATA,
    FailureClass.EXECUTABLE_GAP: AutonomousMissionNode.N6_EXECUTABLE_READINESS,
    FailureClass.PRODUCT_DEFECT: AutonomousMissionNode.N9_DEFECT,
    FailureClass.VALID_TEST_FAILURE: AutonomousMissionNode.N9_DEFECT,
}

_EXTERNAL_ROUTE: Dict[FailureClass, str] = {
    FailureClass.PROVIDER_AUTH: "RUNTIME_RECOVERY",
    FailureClass.PROVIDER_QUOTA: "RUNTIME_RECOVERY",
    FailureClass.PROVIDER_TIMEOUT: "RUNTIME_RECOVERY",
    FailureClass.CAPABILITY_GAP: "CAPABILITY_BROKER",
    FailureClass.RESOURCE_CONFLICT: "RESOURCE_MANAGER",
    FailureClass.FLAKY: "BOUNDED_RETRY",
    FailureClass.UNKNOWN: "DIAGNOSIS_BLOCKED",
}

_ALLOWED_DIRECT_STATES: Dict[MissionNodeState, Tuple[MissionNodeState, ...]] = {
    MissionNodeState.NOT_STARTED: (MissionNodeState.READY, MissionNodeState.STALE),
    MissionNodeState.READY: (
        MissionNodeState.RUNNING,
        MissionNodeState.BLOCKED,
        MissionNodeState.HUMAN_GATE,
        MissionNodeState.STALE,
    ),
    MissionNodeState.RUNNING: (
        MissionNodeState.REVIEW_PENDING,
        MissionNodeState.NEEDS_REVISION,
        MissionNodeState.BLOCKED,
        MissionNodeState.HUMAN_GATE,
        MissionNodeState.STALE,
    ),
    MissionNodeState.REVIEW_PENDING: (
        MissionNodeState.NEEDS_REVISION,
        MissionNodeState.BLOCKED,
        MissionNodeState.HUMAN_GATE,
        MissionNodeState.STALE,
    ),
    MissionNodeState.PASS: (MissionNodeState.STALE,),
    MissionNodeState.NEEDS_REVISION: (
        MissionNodeState.READY,
        MissionNodeState.RUNNING,
        MissionNodeState.STALE,
    ),
    MissionNodeState.BLOCKED: (
        MissionNodeState.READY,
        MissionNodeState.HUMAN_GATE,
        MissionNodeState.STALE,
    ),
    MissionNodeState.HUMAN_GATE: (
        MissionNodeState.READY,
        MissionNodeState.BLOCKED,
        MissionNodeState.STALE,
    ),
    MissionNodeState.STALE: (MissionNodeState.READY,),
}

_SEQUENTIAL_NODES = (
    AutonomousMissionNode.N1_REALITY,
    AutonomousMissionNode.N2_REQUIREMENT,
    AutonomousMissionNode.N3_CODE_ANALYSIS,
    AutonomousMissionNode.N4_TEST_DESIGN,
    AutonomousMissionNode.N5_TEST_DATA,
    AutonomousMissionNode.N6_EXECUTABLE_READINESS,
    AutonomousMissionNode.N7_EXECUTION,
)


def _now() -> int:
    return int(time.time())


def _uniq(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


class RC72StateMachine:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_phase2_truth_overlay()
        self.truth = truth
        self.release_id = release_id
        self.repository = CanonicalRC72Repository(truth, release_id=release_id)

    # ------------------------------------------------------------------
    # Canonical lookup / bootstrap
    # ------------------------------------------------------------------
    def bootstrap_release_batch(self, batch: ReleaseBatch) -> None:
        existing = self.truth.query("rc72_release_batch", release_batch_id=batch.release_batch_id)
        if not existing:
            self.repository.persist(batch)
        elif len(existing) != 1 or existing[0].get("mission_id") != batch.mission_id:
            raise StateMachineContractError("RELEASE_BATCH_IDENTITY_CONFLICT")

        for index, node_type in enumerate(AutonomousMissionNode.ordered()):
            node_id = self._node_id(batch.mission_id, node_type)
            rows = self.truth.query("rc72_mission_node", mission_node_id=node_id)
            if rows:
                if len(rows) != 1 or rows[0].get("mission_id") != batch.mission_id:
                    raise StateMachineContractError("MISSION_NODE_IDENTITY_CONFLICT")
                continue
            node = MissionNodeRecord(
                mission_node_id=node_id,
                mission_id=batch.mission_id,
                node_type=node_type,
                scope_ref="release-batch://%s" % batch.release_batch_id,
                state=MissionNodeState.READY if index == 0 else MissionNodeState.NOT_STARTED,
                entered_at=_now() if index == 0 else None,
            )
            self.repository.persist(node)

    def node(self, mission_node_id: str) -> dict:
        rows = self.truth.query("rc72_mission_node", mission_node_id=mission_node_id)
        if len(rows) != 1:
            raise StateMachineContractError("MISSION_NODE_NOT_UNIQUE:%s" % mission_node_id)
        return rows[0]

    def node_by_type(self, mission_id: str, node_type: AutonomousMissionNode) -> dict:
        rows = [
            row
            for row in self.truth.query("rc72_mission_node", mission_id=mission_id)
            if row.get("node_type") == node_type.value
        ]
        if len(rows) != 1:
            raise StateMachineContractError("MISSION_NODE_TYPE_NOT_UNIQUE:%s:%s" % (mission_id, node_type.value))
        return rows[0]

    @staticmethod
    def _node_id(mission_id: str, node_type: AutonomousMissionNode) -> str:
        return "MN-%s-%s" % (mission_id, node_type.value)

    # ------------------------------------------------------------------
    # Node lifecycle and Gate-only PASS
    # ------------------------------------------------------------------
    def transition_state(
        self,
        mission_node_id: str,
        target_state: MissionNodeState,
        *,
        reason: str,
    ) -> dict:
        if not isinstance(target_state, MissionNodeState):
            target_state = MissionNodeState(str(target_state))
        if target_state == MissionNodeState.PASS:
            raise StateMachineContractError("PASS_REQUIRES_NODE_GATE")
        current = self.node(mission_node_id)
        current_state = MissionNodeState(current["state"])
        if target_state not in _ALLOWED_DIRECT_STATES[current_state]:
            raise StateMachineContractError(
                "ILLEGAL_NODE_STATE_TRANSITION:%s->%s" % (current_state.value, target_state.value)
            )
        node_type = AutonomousMissionNode(current["node_type"])
        if target_state == MissionNodeState.RUNNING and node_type in _SEQUENTIAL_NODES[1:]:
            self._assert_mandatory_upstream_pass(current["mission_id"], node_type)
        return self._persist_node_state(current, target_state, reason=reason)

    def mark_stale(self, mission_node_id: str, *, reason: str) -> dict:
        current = self.node(mission_node_id)
        if current["state"] == MissionNodeState.STALE.value:
            return current
        return self._persist_node_state(current, MissionNodeState.STALE, reason=reason)

    def submit_delivery(self, delivery: NodeDelivery):
        node = self.node(delivery.mission_node_id)
        if node.get("mission_id") != delivery.mission_id or node.get("node_type") != delivery.node_type.value:
            raise StateMachineContractError("NODE_DELIVERY_IDENTITY_MISMATCH")

        # Detect conflicting delivery identity/version before the lifecycle guard.
        # After the first delivery the node is REVIEW_PENDING; a second producer
        # for the same active version is a conflict, not merely a wrong state.
        same_version = [
            row
            for row in self.truth.query("rc72_node_delivery", mission_node_id=delivery.mission_node_id)
            if row.get("version") == delivery.version
        ]
        for row in same_version:
            if row.get("delivery_id") != delivery.delivery_id:
                raise StateMachineContractError("CONFLICTING_ACTIVE_DELIVERY")
        if node.get("active_delivery_version") == delivery.version:
            refs = node.get("delivery_refs") or []
            if delivery.delivery_id not in refs:
                raise StateMachineContractError("CONFLICTING_ACTIVE_DELIVERY")

        if node.get("state") != MissionNodeState.RUNNING.value:
            raise StateMachineContractError("NODE_DELIVERY_REQUIRES_RUNNING_NODE")
        receipt = self.repository.persist(delivery)
        refs = _uniq(list(node.get("delivery_refs") or []) + [delivery.delivery_id])
        self._persist_node_state(
            node,
            MissionNodeState.REVIEW_PENDING,
            reason="delivery submitted for review",
            active_delivery_version=delivery.version,
            delivery_refs=refs,
        )
        return receipt

    def apply_gate(self, gate: NodeGate):
        node = self.node(gate.mission_node_id)
        if node.get("state") != MissionNodeState.REVIEW_PENDING.value:
            raise StateMachineContractError("NODE_GATE_REQUIRES_REVIEW_PENDING")
        if node.get("mission_id") != gate.mission_id or node.get("node_type") != gate.node_type.value:
            raise StateMachineContractError("NODE_GATE_IDENTITY_MISMATCH")
        delivery_rows = self.truth.query("rc72_node_delivery", delivery_id=gate.delivery_id)
        if len(delivery_rows) != 1:
            raise StateMachineContractError("NODE_GATE_DELIVERY_NOT_UNIQUE")
        delivery = delivery_rows[0]
        if delivery.get("mission_node_id") != gate.mission_node_id:
            raise StateMachineContractError("NODE_GATE_DELIVERY_NODE_MISMATCH")
        if delivery.get("version") != node.get("active_delivery_version"):
            raise StateMachineContractError("NODE_GATE_NOT_FOR_ACTIVE_DELIVERY")
        receipt = self.repository.persist(gate)
        mapping = {
            NodeGateDecision.PASS: MissionNodeState.PASS,
            NodeGateDecision.NEEDS_REVISION: MissionNodeState.NEEDS_REVISION,
            NodeGateDecision.BLOCKED: MissionNodeState.BLOCKED,
            NodeGateDecision.HUMAN_GATE: MissionNodeState.HUMAN_GATE,
        }
        gate_refs = _uniq(list(node.get("gate_refs") or []) + [gate.gate_id])
        self._persist_node_state(
            node,
            mapping[gate.decision],
            reason=gate.reason or "node gate decision %s" % gate.decision.value,
            gate_refs=gate_refs,
            exited_at=_now() if gate.decision == NodeGateDecision.PASS else None,
            bypass_direct_transition=True,
        )
        return receipt

    # ------------------------------------------------------------------
    # Forward flow / failure flow
    # ------------------------------------------------------------------
    def forward(
        self,
        from_node_type: AutonomousMissionNode,
        to_node_type: AutonomousMissionNode,
        *,
        source_gate_id: str,
    ) -> NodeTransition:
        source = self.node_by_type(self._single_mission_id(), from_node_type)
        target = self.node_by_type(source["mission_id"], to_node_type)
        if source.get("state") != MissionNodeState.PASS.value:
            raise StateMachineContractError("FORWARD_SOURCE_NOT_PASS")
        gates = self.truth.query("rc72_node_gate", gate_id=source_gate_id)
        if len(gates) != 1 or gates[0].get("decision") != NodeGateDecision.PASS.value:
            raise StateMachineContractError("FORWARD_REQUIRES_PASS_GATE")
        if gates[0].get("mission_node_id") != source["mission_node_id"]:
            raise StateMachineContractError("FORWARD_GATE_SOURCE_MISMATCH")
        if from_node_type in _SEQUENTIAL_NODES and to_node_type in _SEQUENTIAL_NODES:
            if _SEQUENTIAL_NODES.index(to_node_type) != _SEQUENTIAL_NODES.index(from_node_type) + 1:
                raise StateMachineContractError("FORWARD_EDGE_NOT_SEQUENTIAL")
            self._assert_mandatory_upstream_pass(source["mission_id"], to_node_type)
        if target.get("state") in {
            MissionNodeState.NOT_STARTED.value,
            MissionNodeState.NEEDS_REVISION.value,
            MissionNodeState.STALE.value,
            MissionNodeState.BLOCKED.value,
        }:
            self._persist_node_state(
                target,
                MissionNodeState.READY,
                reason="upstream gate passed",
                bypass_direct_transition=True,
            )
        transition = NodeTransition(
            transition_id=self._new_id("NT"),
            mission_id=source["mission_id"],
            from_mission_node_id=source["mission_node_id"],
            from_node_type=from_node_type,
            to_mission_node_id=target["mission_node_id"],
            to_node_type=to_node_type,
            kind=NodeTransitionKind.FORWARD,
            reason="source node PASS",
            source_gate_id=source_gate_id,
        )
        self.repository.persist(transition)
        return transition

    def route_execution_failure(
        self,
        *,
        failure_evidence_refs: Sequence[str],
        reason: str,
    ) -> NodeTransition:
        mission_id = self._single_mission_id()
        n7 = self.node_by_type(mission_id, AutonomousMissionNode.N7_EXECUTION)
        n8 = self.node_by_type(mission_id, AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
        if n7.get("state") != MissionNodeState.RUNNING.value:
            raise StateMachineContractError("N7_FAILURE_REQUIRES_RUNNING_EXECUTION")
        if not failure_evidence_refs:
            raise StateMachineContractError("N7_FAILURE_REQUIRES_EVIDENCE")
        self._persist_node_state(
            n7,
            MissionNodeState.NEEDS_REVISION,
            reason=reason,
            bypass_direct_transition=True,
        )
        self._persist_node_state(
            n8,
            MissionNodeState.READY,
            reason="failure evidence requires independent diagnosis",
            bypass_direct_transition=True,
        )
        transition = NodeTransition(
            transition_id=self._new_id("NT-DIAG"),
            mission_id=mission_id,
            from_mission_node_id=n7["mission_node_id"],
            from_node_type=AutonomousMissionNode.N7_EXECUTION,
            to_mission_node_id=n8["mission_node_id"],
            to_node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
            kind=NodeTransitionKind.DIAGNOSIS,
            reason=reason,
            evidence_refs=list(failure_evidence_refs),
        )
        self.repository.persist(transition)
        return transition

    def route_diagnosis(
        self,
        failure_class: FailureClass,
        *,
        source_delivery_id: str,
        evidence_refs: Sequence[str],
        affected_refs: Sequence[str],
        rationale: str,
    ) -> DiagnosisRoute:
        if not isinstance(failure_class, FailureClass):
            failure_class = FailureClass(str(failure_class))
        mission_id = self._single_mission_id()
        n8 = self.node_by_type(mission_id, AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
        if n8.get("state") != MissionNodeState.PASS.value:
            raise StateMachineContractError("DIAGNOSIS_ROUTE_REQUIRES_ACCEPTED_N8_GATE")
        source_rows = self.truth.query("rc72_node_delivery", delivery_id=source_delivery_id)
        if len(source_rows) != 1 or source_rows[0].get("mission_node_id") != n8["mission_node_id"]:
            raise StateMachineContractError("DIAGNOSIS_SOURCE_DELIVERY_INVALID")
        if not evidence_refs:
            raise StateMachineContractError("DIAGNOSIS_ROUTE_REQUIRES_EVIDENCE")

        target_type = _NODE_ROUTE.get(failure_class)
        if target_type is None:
            action = _EXTERNAL_ROUTE[failure_class]
            if failure_class == FailureClass.UNKNOWN:
                self._persist_node_state(
                    n8,
                    MissionNodeState.BLOCKED,
                    reason="UNKNOWN diagnosis cannot auto-pass",
                    bypass_direct_transition=True,
                )
            return DiagnosisRoute(failure_class, None, action)

        target = self.node_by_type(mission_id, target_type)
        gap_id = self._new_id("GAP-%s" % failure_class.value)
        gap = Gap(
            gap_id=gap_id,
            mission_id=mission_id,
            source_node=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY.value,
            category=failure_class.value,
            severity=GapSeverity.HIGH,
            target_node=target_type.value,
            description=rationale,
        )
        append_entity(self.truth, gap, release_id=self.release_id)
        edge = BackEdge(
            back_edge_id=self._new_id("BE-%s" % failure_class.value),
            mission_id=mission_id,
            gap_id=gap_id,
            from_node=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
            from_delivery_id=source_delivery_id,
            return_node=target_type,
            reason=failure_class.value,
            invalidated_refs=list(affected_refs),
        )
        self.repository.persist(edge)
        self._persist_node_state(
            target,
            MissionNodeState.NEEDS_REVISION,
            reason="semantic back-edge %s" % failure_class.value,
            bypass_direct_transition=True,
        )
        transition = NodeTransition(
            transition_id=self._new_id("NT-%s" % failure_class.value),
            mission_id=mission_id,
            from_mission_node_id=n8["mission_node_id"],
            from_node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
            to_mission_node_id=target["mission_node_id"],
            to_node_type=target_type,
            kind=NodeTransitionKind.BACK_EDGE,
            reason=failure_class.value,
            back_edge_id=edge.back_edge_id,
            evidence_refs=list(evidence_refs),
        )
        self.repository.persist(transition)
        return DiagnosisRoute(
            failure_class=failure_class,
            responsible_node=target_type,
            action="SEMANTIC_BACK_EDGE",
            gap_id=gap_id,
            back_edge_id=edge.back_edge_id,
            transition_id=transition.transition_id,
        )

    # ------------------------------------------------------------------
    # Impact / stale propagation
    # ------------------------------------------------------------------
    def propagate_stale(
        self,
        *,
        source_delivery_id: str,
        changed_refs: Sequence[str],
        reason: str,
    ) -> ImpactSet:
        if not changed_refs:
            raise StateMachineContractError("STALE_PROPAGATION_REQUIRES_CHANGED_REFS")
        source_rows = self.truth.query("rc72_node_delivery", delivery_id=source_delivery_id)
        if len(source_rows) != 1:
            raise StateMachineContractError("IMPACT_SOURCE_DELIVERY_NOT_UNIQUE")
        source = source_rows[0]
        mission_id = source["mission_id"]
        source_type = AutonomousMissionNode(source["node_type"])
        changed = set(changed_refs)

        stale_node_ids: List[str] = []
        affected_refs: List[str] = []
        for delivery in self.truth.query("rc72_node_delivery", mission_id=mission_id):
            if delivery.get("delivery_id") == source_delivery_id:
                continue
            refs = set(delivery.get("input_refs") or [])
            if refs & changed:
                node = self.node(delivery["mission_node_id"])
                if node["mission_node_id"] not in stale_node_ids:
                    self.mark_stale(node["mission_node_id"], reason=reason)
                    stale_node_ids.append(node["mission_node_id"])
                affected_refs.append(delivery["delivery_id"])

        stale_obligation_ids: List[str] = []
        for obligation in self.truth.query("rc72_test_obligation", mission_id=mission_id):
            refs = set(obligation.get("code_slice_refs") or []) | set(obligation.get("change_refs") or [])
            if refs & changed:
                self._persist_obligation_status(obligation, ObligationStatus.STALE)
                stale_obligation_ids.append(obligation["obligation_id"])
                affected_refs.append(obligation["obligation_id"])

        stale_etu_ids: List[str] = []
        for etu in self.truth.query("rc72_etu", mission_id=mission_id):
            if etu.get("obligation_id") in stale_obligation_ids or etu.get("primary_code_slice") in changed:
                self._persist_etu_state(etu, ETUState.STALE)
                stale_etu_ids.append(etu["etu_id"])
                affected_refs.append(etu["etu_id"])

        strategy = ImpactStrategy.EXPLICIT_DEPENDENCY
        if not (stale_node_ids or stale_obligation_ids or stale_etu_ids):
            strategy = ImpactStrategy.SAFE_FALLBACK
            ordered = list(AutonomousMissionNode.ordered())
            source_index = ordered.index(source_type)
            for node_type in ordered[source_index + 1 :]:
                if node_type in {
                    AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
                    AutonomousMissionNode.N9_DEFECT,
                    AutonomousMissionNode.N10_RELEASE_CONVERGENCE,
                }:
                    continue
                node = self.node_by_type(mission_id, node_type)
                if node.get("state") != MissionNodeState.NOT_STARTED.value:
                    self.mark_stale(node["mission_node_id"], reason="SAFE_FALLBACK: %s" % reason)
                    stale_node_ids.append(node["mission_node_id"])
                    affected_refs.append(node["mission_node_id"])
            for obligation in self.truth.query("rc72_test_obligation", mission_id=mission_id):
                self._persist_obligation_status(obligation, ObligationStatus.STALE)
                stale_obligation_ids.append(obligation["obligation_id"])
                affected_refs.append(obligation["obligation_id"])
            for etu in self.truth.query("rc72_etu", mission_id=mission_id):
                self._persist_etu_state(etu, ETUState.STALE)
                stale_etu_ids.append(etu["etu_id"])
                affected_refs.append(etu["etu_id"])

        impact = ImpactSet(
            impact_set_id=self._new_id("IMPACT"),
            mission_id=mission_id,
            source_mission_node_id=source["mission_node_id"],
            source_node_type=source_type,
            source_delivery_id=source_delivery_id,
            changed_refs=list(changed_refs),
            affected_refs=_uniq(affected_refs),
            stale_mission_node_ids=_uniq(stale_node_ids),
            stale_obligation_ids=_uniq(stale_obligation_ids),
            stale_etu_ids=_uniq(stale_etu_ids),
            strategy=strategy,
            reason=reason,
        )
        append_impact_set(self.truth, impact, release_id=self.release_id)
        return impact

    def assert_n7_dispatchable(self, *, etu_id: Optional[str] = None) -> None:
        mission_id = self._single_mission_id()
        for node_type in _SEQUENTIAL_NODES[:-1]:
            node = self.node_by_type(mission_id, node_type)
            if node.get("state") != MissionNodeState.PASS.value:
                raise StateMachineContractError(
                    "N7_DISPATCH_BLOCKED_BY_UPSTREAM:%s:%s" % (node_type.value, node.get("state"))
                )
        if etu_id:
            rows = self.truth.query("rc72_etu", etu_id=etu_id)
            if len(rows) != 1 or rows[0].get("state") == ETUState.STALE.value:
                raise StateMachineContractError("N7_DISPATCH_BLOCKED_BY_STALE_ETU")

    # ------------------------------------------------------------------
    # Release convergence
    # ------------------------------------------------------------------
    @staticmethod
    def evaluate_convergence(facts: ReleaseConvergenceFacts) -> ReleaseConvergenceResult:
        if facts.runtime_blocked:
            return ReleaseConvergenceResult.BLOCKED
        if facts.human_gate_required:
            return ReleaseConvergenceResult.HUMAN_GATE
        mandatory = (
            facts.requirement_completion,
            facts.sst_completion,
            facts.obligation_completion,
            facts.required_l1_l7_completion,
            facts.high_risk_completion,
            facts.incremental_coverage_met,
            facts.critical_defects_closed,
            facts.no_blocked_workitems,
            facts.no_unresolved_gaps,
            facts.evidence_complete,
            facts.runtime_integrity,
        )
        return (
            ReleaseConvergenceResult.CONVERGED
            if all(mandatory)
            else ReleaseConvergenceResult.NOT_CONVERGED
        )

    # ------------------------------------------------------------------
    # Internal persistence helpers
    # ------------------------------------------------------------------
    def _single_mission_id(self) -> str:
        batches = self.truth.query("rc72_release_batch")
        if len(batches) != 1:
            raise StateMachineContractError("STATE_MACHINE_REQUIRES_SINGLE_RELEASE_BATCH_SCOPE")
        return batches[0]["mission_id"]

    def _assert_mandatory_upstream_pass(
        self,
        mission_id: str,
        node_type: AutonomousMissionNode,
    ) -> None:
        if node_type not in _SEQUENTIAL_NODES:
            return
        index = _SEQUENTIAL_NODES.index(node_type)
        for upstream_type in _SEQUENTIAL_NODES[:index]:
            upstream = self.node_by_type(mission_id, upstream_type)
            if upstream.get("state") != MissionNodeState.PASS.value:
                raise StateMachineContractError(
                    "MANDATORY_UPSTREAM_NOT_PASS:%s:%s" % (
                        upstream_type.value,
                        upstream.get("state"),
                    )
                )

    def _persist_node_state(
        self,
        row: dict,
        state: MissionNodeState,
        *,
        reason: str,
        active_delivery_version: Optional[int] = None,
        delivery_refs: Optional[List[str]] = None,
        gate_refs: Optional[List[str]] = None,
        exited_at: Optional[int] = None,
        bypass_direct_transition: bool = False,
    ) -> dict:
        if not bypass_direct_transition:
            current = MissionNodeState(row["state"])
            if state != current and state not in _ALLOWED_DIRECT_STATES[current]:
                raise StateMachineContractError(
                    "ILLEGAL_NODE_STATE_TRANSITION:%s->%s" % (current.value, state.value)
                )
        node = MissionNodeRecord(
            mission_node_id=row["mission_node_id"],
            mission_id=row["mission_id"],
            node_type=AutonomousMissionNode(row["node_type"]),
            scope_ref=row["scope_ref"],
            state=state,
            active_delivery_version=(
                active_delivery_version
                if active_delivery_version is not None
                else row.get("active_delivery_version")
            ),
            delivery_refs=list(delivery_refs if delivery_refs is not None else row.get("delivery_refs") or []),
            gate_refs=list(gate_refs if gate_refs is not None else row.get("gate_refs") or []),
            open_gap_refs=list(row.get("open_gap_refs") or []),
            entered_at=row.get("entered_at") or (_now() if state == MissionNodeState.RUNNING else None),
            exited_at=exited_at if exited_at is not None else row.get("exited_at"),
            blocked_reason=(
                reason
                if state in {MissionNodeState.BLOCKED, MissionNodeState.HUMAN_GATE, MissionNodeState.STALE}
                else None
            ),
            revision=int(row.get("revision") or 1) + 1,
            created_at=int(row.get("created_at") or _now()),
            updated_at=_now(),
        )
        self.repository.persist(node, artifact_version=int(row.get("artifact_version") or 1) + 1)
        return self.node(node.mission_node_id)

    def _persist_obligation_status(self, row: dict, status: ObligationStatus) -> None:
        obligation = TestObligation(
            obligation_id=row["obligation_id"],
            mission_id=row["mission_id"],
            release_batch_id=row["release_batch_id"],
            requirement_id=row["requirement_id"],
            sst_id=row["sst_id"],
            application_id=row["application_id"],
            business_scenario=row["business_scenario"],
            business_rule=row["business_rule"],
            risk_level=row["risk_level"],
            test_level=row["test_level"],
            code_slice_refs=list(row.get("code_slice_refs") or []),
            change_refs=list(row.get("change_refs") or []),
            oracle_refs=list(row.get("oracle_refs") or []),
            coverage_targets=list(row.get("coverage_targets") or []),
            status=status,
            created_at=int(row.get("created_at") or _now()),
            updated_at=_now(),
        )
        self.repository.persist(obligation, artifact_version=int(row.get("artifact_version") or 1) + 1)

    def _persist_etu_state(self, row: dict, state: ETUState) -> None:
        etu = ExecutionTaskUnit(
            etu_id=row["etu_id"],
            mission_id=row["mission_id"],
            release_batch_id=row["release_batch_id"],
            obligation_id=row["obligation_id"],
            case_ids=list(row.get("case_ids") or []),
            primary_goal=row["primary_goal"],
            primary_code_slice=row["primary_code_slice"],
            test_level=row["test_level"],
            primary_oracle=row["primary_oracle"],
            data_domain=row["data_domain"],
            primary_tool_family=row["primary_tool_family"],
            planning_snapshot_ref=row["planning_snapshot_ref"],
            cohesion_score=float(row["cohesion_score"]),
            cohesion_explanation=row["cohesion_explanation"],
            required_capabilities=list(row.get("required_capabilities") or []),
            estimated_duration_minutes=int(row.get("estimated_duration_minutes") or 15),
            estimated_cost=float(row.get("estimated_cost") or 0.0),
            oversize_justification=row.get("oversize_justification"),
            parent_etu_id=row.get("parent_etu_id"),
            split_reason=row.get("split_reason"),
            child_etu_ids=list(row.get("child_etu_ids") or []),
            state=state,
            created_at=int(row.get("created_at") or _now()),
            updated_at=_now(),
        )
        self.repository.persist(etu, artifact_version=int(row.get("artifact_version") or 1) + 1)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return "%s-%s" % (prefix, uuid.uuid4().hex[:16])
