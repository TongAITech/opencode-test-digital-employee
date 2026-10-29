"""Composition gate for RC8 SINGLE_NODE full-loop integration proof.

This module deliberately owns no PASS/release authority. It composes the production
AutonomousWorkerDispatcher traversal proof with the durable Center/R1 truth verifier
so an observed worker result cannot be promoted unless the same TestRun/WorkItem/
Attempt/Artifact identities exist in durable truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader

from .autonomous_claim_client import AutonomousClaimClient
from .autonomous_dispatcher import AutonomousWorkerDispatcher
from .single_node_full_loop_proof import (
    FROZEN_N1_N10_STAGES,
    SingleNodeFullLoopProof,
    SingleNodeFullLoopProofRunner,
)
from .single_node_truth import SingleNodeCenterTruthVerifier, SingleNodeTruthProof


# Exact worker identities wired by rc8_node.__main__._build_dispatcher.  A dispatcher
# with all 15 stage labels but generic/double workers is still not a production
# topology and must not enter the production-driven SINGLE_NODE proof.
_PRODUCTION_WORKER_IDENTITIES = {
    "SCOPE_INTAKE": ("rc8_node.scope_intake_worker", "ScopeIntakeWorker"),
    "REQUIREMENT_ANALYSIS": ("rc8_node.requirement_analysis_worker", "RequirementAnalysisWorker"),
    "REQUIREMENT_SUFFICIENCY": ("rc8_node.requirement_sufficiency_worker", "RequirementSufficiencyWorker"),
    "CODE_ANALYSIS": ("rc8_node.code_analysis_worker", "CodeAnalysisWorker"),
    "CODE_SUFFICIENCY": ("rc8_node.code_sufficiency_worker", "CodeSufficiencyWorker"),
    "RISK_TEST_MODEL": ("rc8_node.risk_test_model_worker", "RiskTestModelWorker"),
    "TEST_DESIGN": ("rc8_node.test_design_worker", "TestDesignWorker"),
    "DESIGN_SUFFICIENCY": ("rc8_node.design_sufficiency_worker", "DesignSufficiencyWorker"),
    "PRECONDITION_DATA_PREP": ("rc8_node.precondition_data_prep_worker", "PreconditionDataPrepWorker"),
    "EXECUTABLE_SPEC": ("rc8_node.executable_spec_worker", "ExecutableSpecWorker"),
    "APPLICABLE_LAYER_EXECUTION": ("rc8_node.n7_execution_worker", "N7ExecutionDispatchWorker"),
    "FAILURE_COVERAGE_EVALUATION": ("rc8_node.failure_coverage_evaluation_worker", "FailureCoverageEvaluationWorker"),
    "DEFECT_CLOSURE_OBSERVATION": ("rc8_node.defect_closure_observation_worker", "DefectClosureObservationWorker"),
    "MISSION_SUFFICIENCY": ("rc8_node.mission_sufficiency_observation_worker", "MissionSufficiencyObservationWorker"),
    "REPORT_RELEASE": ("rc8_node.report_release_observation_worker", "ReportReleaseObservationWorker"),
}


@dataclass(frozen=True)
class SingleNodeDurableIntegrationProof:
    observed: SingleNodeFullLoopProof
    durable_truth: SingleNodeTruthProof
    status: str = "DURABLE_INTEGRATION_VERIFIED_NOT_AUTHORIZED"
    bank_reality_verified: bool = False
    release_status: str = "HOLD"


def assert_production_dispatcher_topology(
    dispatcher: AutonomousWorkerDispatcher,
    *,
    required_stages: Sequence[str] = FROZEN_N1_N10_STAGES,
) -> None:
    """Reject production-shaped dispatchers that are not the real 15-worker topology."""
    expected = tuple(sorted(str(stage).strip() for stage in required_stages))
    actual = tuple(sorted(dispatcher.supported_stages))
    if actual != expected:
        missing = tuple(stage for stage in expected if stage not in actual)
        extra = tuple(stage for stage in actual if stage not in expected)
        raise RuntimeError(
            "FULL_LOOP_PRODUCTION_STAGE_TOPOLOGY_MISMATCH:missing=%s:extra=%s"
            % (",".join(missing), ",".join(extra))
        )
    for stage in expected:
        worker = dispatcher.workers.get(stage)
        expected_identity = _PRODUCTION_WORKER_IDENTITIES.get(stage)
        if expected_identity is None:
            raise RuntimeError("FULL_LOOP_PRODUCTION_WORKER_IDENTITY_UNDEFINED:%s" % stage)
        actual_identity = (
            str(getattr(type(worker), "__module__", "")),
            str(getattr(type(worker), "__name__", "")),
        )
        if actual_identity != expected_identity:
            raise RuntimeError(
                "FULL_LOOP_PRODUCTION_WORKER_IDENTITY_MISMATCH:%s:%s.%s"
                % (stage, actual_identity[0] or "NONE", actual_identity[1] or "NONE")
            )


class SingleNodeDurableIntegrationProofRunner:
    """Run dispatcher traversal, then verify the exact traversal in durable truth.

    Production-driven proof is the default. Boundary-double tests must opt out
    explicitly; they can exercise verifier contracts but can never be promoted as
    the SINGLE_NODE production full-loop checkpoint.
    """

    def __init__(
        self,
        *,
        dispatcher: Any,
        truth_reader: Any,
        required_stages: Sequence[str] = FROZEN_N1_N10_STAGES,
        require_production_components: bool = True,
    ) -> None:
        if require_production_components:
            if not isinstance(dispatcher, AutonomousWorkerDispatcher):
                raise RuntimeError("FULL_LOOP_PRODUCTION_DISPATCHER_REQUIRED")
            if not isinstance(getattr(dispatcher, "claimant", None), AutonomousClaimClient):
                raise RuntimeError("FULL_LOOP_PRODUCTION_CLAIM_CLIENT_REQUIRED")
            assert_production_dispatcher_topology(dispatcher, required_stages=required_stages)
            if not isinstance(truth_reader, ProductionCenterR1TruthReader):
                raise RuntimeError("FULL_LOOP_PRODUCTION_TRUTH_READER_REQUIRED")
        self.production_components_verified = bool(require_production_components)
        self.observer = SingleNodeFullLoopProofRunner(
            dispatcher=dispatcher,
            required_stages=required_stages,
        )
        self.verifier = SingleNodeCenterTruthVerifier(truth_reader=truth_reader)

    def run(self, *, test_run_id: str) -> SingleNodeDurableIntegrationProof:
        observed = self.observer.run(test_run_id=test_run_id)
        durable = self.verifier.verify(observed)
        if durable.verified_work_items != observed.work_item_ids:
            raise RuntimeError("FULL_LOOP_DURABLE_WORK_ITEM_IDENTITY_MISMATCH")
        if durable.verified_attempts != observed.attempt_ids:
            raise RuntimeError("FULL_LOOP_DURABLE_ATTEMPT_IDENTITY_MISMATCH")
        if durable.bank_reality_verified:
            raise RuntimeError("CLOUD_INTEGRATION_MUST_NOT_ASSERT_BANK_REALITY")
        if durable.release_status != "HOLD":
            raise RuntimeError("INTEGRATION_PROOF_MUST_NOT_AUTHORIZE_RELEASE")
        return SingleNodeDurableIntegrationProof(observed=observed, durable_truth=durable)
