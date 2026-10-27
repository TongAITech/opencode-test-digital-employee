"""Center-owned MissionNode review and final gate authority.

This service is the only supported RC8 N1-N10 transition from domain delivery to
MissionNode PASS. Director may review but cannot execute domain work or grant
final PASS. Center evaluates current-attempt evidence, denominator, blocking
gaps and prerequisites deterministically. When a MissionNode repository is
configured, every accepted Center transition is durably persisted.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional, Sequence, Tuple

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.mission_nodes import (
    DirectorReviewDecision,
    DirectorReviewReceipt,
    MissionNodeGateDecision,
    MissionNodeGateResult,
    MissionNodeInstance,
    MissionNodeState,
    NodeDeliveryPackage,
)

from .control_plane import CenterControlError
from .distributed_orchestration import ActorRole

if TYPE_CHECKING:
    from .mission_node_repository import MissionNodeRepository


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CenterControlError("%s_MUST_BE_LIST" % name.upper())
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise CenterControlError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        result.append(value.strip())
    return tuple(result)


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CenterControlError("%s_REQUIRED" % name.upper())
    return value.strip()


@dataclass(frozen=True)
class MissionNodeDeliverySubmission:
    package: NodeDeliveryPackage
    transport_role: ActorRole
    evidence_producer_role: ActorRole

    def __post_init__(self) -> None:
        if not isinstance(self.package, NodeDeliveryPackage):
            raise RC8ContractError("NODE_DELIVERY_PACKAGE_REQUIRED")
        if not isinstance(self.transport_role, ActorRole):
            raise RC8ContractError("NODE_DELIVERY_TRANSPORT_ROLE_INVALID")
        if not isinstance(self.evidence_producer_role, ActorRole):
            raise RC8ContractError("NODE_DELIVERY_EVIDENCE_ROLE_INVALID")


class CenterMissionNodeReviewGate:
    """Deterministic Center authority for N1-N10 review and PASS."""

    def __init__(self, repository: Optional[MissionNodeRepository] = None) -> None:
        self.repository = repository

    def begin(self, node: MissionNodeInstance) -> MissionNodeInstance:
        self._require_node(node)
        if node.state not in {MissionNodeState.PENDING, MissionNodeState.READY}:
            raise CenterControlError("MISSION_NODE_BEGIN_STATE_INVALID:%s" % node.state.value)
        return self._persist(replace(node, state=MissionNodeState.IN_PROGRESS))

    def submit_delivery(
        self,
        node: MissionNodeInstance,
        submission: MissionNodeDeliverySubmission,
    ) -> MissionNodeInstance:
        self._require_node(node)
        if not isinstance(submission, MissionNodeDeliverySubmission):
            raise CenterControlError("MISSION_NODE_DELIVERY_SUBMISSION_REQUIRED")
        package = submission.package
        self._require_package_link(node, package)
        if node.state != MissionNodeState.IN_PROGRESS:
            raise CenterControlError("MISSION_NODE_DELIVERY_REQUIRES_IN_PROGRESS")

        if submission.transport_role not in {ActorRole.DSH_NODE, ActorRole.TEAM_WORKER}:
            raise CenterControlError(
                "MISSION_NODE_DELIVERY_TRANSPORT_FORBIDDEN:%s" % submission.transport_role.value
            )
        if submission.evidence_producer_role != ActorRole.TEAM_WORKER:
            if submission.evidence_producer_role == ActorRole.DIRECTOR:
                raise CenterControlError("DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN")
            raise CenterControlError(
                "MISSION_NODE_DOMAIN_EVIDENCE_PRODUCER_FORBIDDEN:%s"
                % submission.evidence_producer_role.value
            )

        refs = tuple(dict.fromkeys(node.output_refs + package.output_refs + package.evidence_refs))
        return self._persist(
            replace(node, state=MissionNodeState.READY_FOR_DIRECTOR_REVIEW, output_refs=refs)
        )

    def record_director_review(
        self,
        node: MissionNodeInstance,
        review: DirectorReviewReceipt,
    ) -> MissionNodeInstance:
        self._require_node(node)
        if not isinstance(review, DirectorReviewReceipt):
            raise CenterControlError("DIRECTOR_REVIEW_RECEIPT_REQUIRED")
        if node.state != MissionNodeState.READY_FOR_DIRECTOR_REVIEW:
            raise CenterControlError("DIRECTOR_REVIEW_REQUIRES_READY_DELIVERY")
        self._require_same_subject(
            node, review.test_run_id, review.mission_node_id, "DIRECTOR_REVIEW"
        )
        refs = tuple(
            dict.fromkeys(
                node.output_refs
                + review.evidence_refs
                + ("director-review:%s" % review.receipt_id,)
            )
        )
        if review.decision == DirectorReviewDecision.ACCEPTED:
            return self._persist(
                replace(node, state=MissionNodeState.REVIEW_ACCEPTED, output_refs=refs)
            )
        return self._persist(
            replace(node, state=MissionNodeState.INSUFFICIENT, output_refs=refs)
        )

    def evaluate_center_gate(
        self,
        node: MissionNodeInstance,
        *,
        delivery: NodeDeliveryPackage,
        review: DirectorReviewReceipt,
        decision: MissionNodeGateDecision,
        current_attempt_ref: str,
        blocking_gap_ids: Sequence[str] = (),
        evidence_complete: bool,
        denominator_satisfied: bool,
        prerequisites_satisfied: bool,
    ) -> MissionNodeInstance:
        self._require_node(node)
        if not isinstance(delivery, NodeDeliveryPackage):
            raise CenterControlError("NODE_DELIVERY_PACKAGE_REQUIRED")
        if not isinstance(review, DirectorReviewReceipt):
            raise CenterControlError("DIRECTOR_REVIEW_RECEIPT_REQUIRED")
        if not isinstance(decision, MissionNodeGateDecision):
            raise CenterControlError("MISSION_NODE_GATE_DECISION_REQUIRED")
        current_attempt_ref = _required(current_attempt_ref, "current_attempt_ref")
        blocking_gap_ids = _refs(blocking_gap_ids, "blocking_gap_ids")

        self._require_package_link(node, delivery)
        self._require_same_subject(
            node, review.test_run_id, review.mission_node_id, "DIRECTOR_REVIEW"
        )
        self._require_same_subject(
            node, decision.test_run_id, decision.mission_node_id, "CENTER_GATE"
        )

        if node.state != MissionNodeState.REVIEW_ACCEPTED:
            raise CenterControlError("MISSION_NODE_GATE_REQUIRES_DIRECTOR_ACCEPTANCE")
        if review.decision != DirectorReviewDecision.ACCEPTED:
            raise CenterControlError("MISSION_NODE_GATE_REQUIRES_ACCEPTED_REVIEW")
        if decision.authority != "CENTER":
            raise CenterControlError("MISSION_NODE_GATE_REQUIRES_CENTER_AUTHORITY")

        refs = tuple(
            dict.fromkeys(
                node.output_refs
                + delivery.evidence_refs
                + review.evidence_refs
                + decision.evidence_refs
                + ("center-gate:%s" % decision.decision_id,)
            )
        )

        if decision.result == MissionNodeGateResult.INSUFFICIENT:
            return self._persist(
                replace(node, state=MissionNodeState.INSUFFICIENT, output_refs=refs)
            )
        if decision.result == MissionNodeGateResult.BLOCKED:
            return self._persist(
                replace(node, state=MissionNodeState.BLOCKED, output_refs=refs)
            )

        if delivery.attempt_ref != current_attempt_ref:
            raise CenterControlError("STALE_ATTEMPT_EVIDENCE_FORBIDDEN")
        if blocking_gap_ids:
            raise CenterControlError(
                "MISSION_NODE_BLOCKING_GAP_PRESENT:%s" % ",".join(blocking_gap_ids)
            )
        if not evidence_complete:
            raise CenterControlError("MISSION_NODE_EVIDENCE_INCOMPLETE")
        if not denominator_satisfied:
            raise CenterControlError("MISSION_NODE_DENOMINATOR_UNSATISFIED")
        if not prerequisites_satisfied:
            raise CenterControlError("MISSION_NODE_PREREQUISITES_UNSATISFIED")

        return self._persist(
            replace(node, state=MissionNodeState.PASS, output_refs=refs)
        )

    def _persist(self, node: MissionNodeInstance) -> MissionNodeInstance:
        if self.repository is not None:
            self.repository.save(node)
        return node

    @staticmethod
    def _require_node(node: MissionNodeInstance) -> None:
        if not isinstance(node, MissionNodeInstance):
            raise CenterControlError("MISSION_NODE_INSTANCE_REQUIRED")

    @staticmethod
    def _require_package_link(
        node: MissionNodeInstance, package: NodeDeliveryPackage
    ) -> None:
        if package.test_run_id != node.test_run_id:
            raise CenterControlError("NODE_DELIVERY_TEST_RUN_MISMATCH")
        if package.mission_node_id != node.mission_node_id:
            raise CenterControlError("NODE_DELIVERY_MISSION_NODE_MISMATCH")

    @staticmethod
    def _require_same_subject(
        node: MissionNodeInstance,
        test_run_id: str,
        mission_node_id: str,
        prefix: str,
    ) -> None:
        if test_run_id != node.test_run_id:
            raise CenterControlError("%s_TEST_RUN_MISMATCH" % prefix)
        if mission_node_id != node.mission_node_id:
            raise CenterControlError("%s_MISSION_NODE_MISMATCH" % prefix)
