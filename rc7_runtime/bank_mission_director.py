"""Independent Director gate for the BANK N10 product main link.

The Director is an acceptance authority, not a specialist worker. It reviews
the current governed N10 Mission Evaluation and delivery identity, then delegates
the durable ACCEPT write to the existing Wave-F node-adoption authority.
"""
from __future__ import annotations

from typing import Any

from rc6_runtime.truth import TruthRuntime

from .autonomous_n10_node import N10PreparedNode, WaveFNodeAdoptionControl
from .closed_loop_control import ClosedLoopControlPlane


class BankMissionDirectorGateError(RuntimeError):
    pass


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BankMissionDirectorGateError(code)
    return text


class BankMissionDirectorGate:
    """Deterministic, identity-separated Director acceptance gate for N10."""

    DEFAULT_DIRECTOR_REF = "rc7-bank-mission-director-gate"

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        evidence_root: str,
        director_ref: str = DEFAULT_DIRECTOR_REF,
    ) -> None:
        self.truth = truth
        self.release_id = _required(release_id, "DIRECTOR_RELEASE_ID_REQUIRED")
        self.director_ref = _required(director_ref, "DIRECTOR_REF_REQUIRED")
        self.adoption = WaveFNodeAdoptionControl(
            truth,
            release_id=self.release_id,
            evidence_root=evidence_root,
        )

    def review_and_accept(
        self,
        control: ClosedLoopControlPlane,
        prepared: N10PreparedNode,
    ) -> Any:
        if control.truth is not self.truth:
            raise BankMissionDirectorGateError("DIRECTOR_TRUTH_RUNTIME_MISMATCH")
        if control.release_id != self.release_id:
            raise BankMissionDirectorGateError("DIRECTOR_RELEASE_ID_MISMATCH")

        run_id = _required(prepared.run_id, "DIRECTOR_RUN_ID_REQUIRED")
        evaluations = self.truth.query(
            "rc7_evaluation",
            evaluation_id=prepared.evaluation_id,
        )
        if len(evaluations) != 1:
            raise BankMissionDirectorGateError("DIRECTOR_N10_EVALUATION_NOT_UNIQUE")
        evaluation = evaluations[0]
        if evaluation.get("mission_id") != control.mission_id:
            raise BankMissionDirectorGateError("DIRECTOR_N10_MISSION_MISMATCH")
        if evaluation.get("node") != "MISSION_EVALUATION":
            raise BankMissionDirectorGateError("DIRECTOR_N10_EVALUATION_NODE_INVALID")
        if evaluation.get("result") != "PASS":
            raise BankMissionDirectorGateError("DIRECTOR_N10_EVALUATION_PASS_REQUIRED")
        if list(evaluation.get("gap_refs") or []):
            raise BankMissionDirectorGateError("DIRECTOR_N10_OPEN_GAPS_FORBIDDEN")
        if prepared.manifest_artifact_id not in list(evaluation.get("artifact_refs") or []):
            raise BankMissionDirectorGateError("DIRECTOR_N10_MANIFEST_NOT_EVALUATED")

        dimensions = evaluation.get("dimensions")
        if not isinstance(dimensions, dict):
            raise BankMissionDirectorGateError("DIRECTOR_N10_DIMENSIONS_REQUIRED")
        required_dimensions = {
            "sufficiency_state": prepared.sufficiency_state,
            "quality_state": prepared.quality_state,
            "release_recommendation": prepared.release_recommendation,
        }
        for name, expected in required_dimensions.items():
            actual = _required(
                dimensions.get(name),
                "DIRECTOR_N10_%s_REQUIRED" % name.upper(),
            )
            if actual != expected:
                raise BankMissionDirectorGateError(
                    "DIRECTOR_N10_%s_MISMATCH:%s:%s"
                    % (name.upper(), expected, actual)
                )
        if dimensions.get("coverage_state") != "CLOSED":
            raise BankMissionDirectorGateError("DIRECTOR_N10_COVERAGE_CLOSED_REQUIRED")
        if dimensions.get("business_release_decision") != "NOT_DECIDED_BY_TEST_SYSTEM":
            raise BankMissionDirectorGateError(
                "DIRECTOR_N10_BUSINESS_RELEASE_AUTHORITY_VIOLATION"
            )

        current_iteration = self.adoption.node_control.latest_iteration(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
        )
        current_delivery = self.adoption.node_control.latest_delivery(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
        )
        if current_iteration is None or current_delivery is None:
            raise BankMissionDirectorGateError("DIRECTOR_CURRENT_N10_DELIVERY_REQUIRED")
        if current_delivery.iteration_count != current_iteration.iteration_count:
            raise BankMissionDirectorGateError("DIRECTOR_STALE_N10_DELIVERY_FORBIDDEN")
        if current_delivery.iteration_count != prepared.delivery.iteration_count:
            raise BankMissionDirectorGateError("DIRECTOR_PREPARED_N10_ITERATION_STALE")
        if current_delivery.package_artifact_id != prepared.delivery.package_artifact_id:
            raise BankMissionDirectorGateError("DIRECTOR_PREPARED_N10_DELIVERY_STALE")

        decision = self.adoption.director_accept(
            mission_id=control.mission_id,
            run_id=run_id,
            node_id="N10",
            director_ref=self.director_ref,
        )
        if decision.accepted is not True:
            raise BankMissionDirectorGateError("DIRECTOR_N10_ACCEPT_NOT_DURABLE")
        return decision
