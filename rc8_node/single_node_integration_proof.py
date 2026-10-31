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
from .formal_agent import FormalNodeAgent
from .single_node_full_loop_proof import FROZEN_N1_N10_STAGES, SingleNodeFullLoopProof, SingleNodeFullLoopProofRunner
from .single_node_truth import SingleNodeCenterTruthVerifier, SingleNodeTruthProof


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
    production_components_verified: bool
    production_causality_verified: bool
    status: str
    bank_reality_verified: bool = False
    release_status: str = "HOLD"


def assert_production_dispatcher_topology(dispatcher: AutonomousWorkerDispatcher, *, required_stages: Sequence[str] = FROZEN_N1_N10_STAGES) -> None:
    """Reject production-shaped dispatchers that are not one coherent real node topology."""
    expected = tuple(sorted(str(stage).strip() for stage in required_stages))
    actual = tuple(sorted(dispatcher.supported_stages))
    if actual != expected:
        missing = tuple(stage for stage in expected if stage not in actual)
        extra = tuple(stage for stage in actual if stage not in expected)
        raise RuntimeError("FULL_LOOP_PRODUCTION_STAGE_TOPOLOGY_MISMATCH:missing=%s:extra=%s" % (",".join(missing), ",".join(extra)))

    claimant_node_id = str(dispatcher.claimant.node_id or "").strip()
    claimant_center = str(dispatcher.claimant.center_url or "").strip().rstrip("/")
    for stage in expected:
        worker = dispatcher.workers.get(stage)
        expected_identity = _PRODUCTION_WORKER_IDENTITIES.get(stage)
        if expected_identity is None:
            raise RuntimeError("FULL_LOOP_PRODUCTION_WORKER_IDENTITY_UNDEFINED:%s" % stage)
        actual_identity = (str(getattr(type(worker), "__module__", "")), str(getattr(type(worker), "__name__", "")))
        if actual_identity != expected_identity:
            raise RuntimeError("FULL_LOOP_PRODUCTION_WORKER_IDENTITY_MISMATCH:%s:%s.%s" % (stage, actual_identity[0] or "NONE", actual_identity[1] or "NONE"))
        agent = getattr(worker, "agent", None)
        if not isinstance(agent, FormalNodeAgent):
            raise RuntimeError("FULL_LOOP_PRODUCTION_FORMAL_AGENT_REQUIRED:%s" % stage)
        worker_node_id = str(getattr(getattr(agent, "identity", None), "node_id", "") or "").strip()
        if not worker_node_id or worker_node_id != claimant_node_id:
            raise RuntimeError("FULL_LOOP_PRODUCTION_NODE_ID_MISMATCH:%s" % stage)
        worker_center = str(getattr(getattr(agent, "center", None), "base_url", "") or "").strip().rstrip("/")
        if not worker_center or worker_center != claimant_center:
            raise RuntimeError("FULL_LOOP_PRODUCTION_CENTER_AUTHORITY_MISMATCH:%s" % stage)


class SingleNodeDurableIntegrationProofRunner:
    """Run dispatcher traversal, then verify the exact traversal in durable truth.

    Production component identity is intentionally distinct from production causality.
    A production traversal starts with a durable-attempt preflight and, after the
    traversal, binds the complete durable Attempt identity set to the Center-issued
    lease identities actually observed by the dispatcher. These are necessary
    causality conditions, not sufficient authority to promote the proof.
    """

    def __init__(self, *, dispatcher: Any, truth_reader: Any, required_stages: Sequence[str] = FROZEN_N1_N10_STAGES, require_production_components: bool = True) -> None:
        expected_node_id = None
        if require_production_components:
            if not isinstance(dispatcher, AutonomousWorkerDispatcher):
                raise RuntimeError("FULL_LOOP_PRODUCTION_DISPATCHER_REQUIRED")
            if not isinstance(getattr(dispatcher, "claimant", None), AutonomousClaimClient):
                raise RuntimeError("FULL_LOOP_PRODUCTION_CLAIM_CLIENT_REQUIRED")
            assert_production_dispatcher_topology(dispatcher, required_stages=required_stages)
            if not isinstance(truth_reader, ProductionCenterR1TruthReader):
                raise RuntimeError("FULL_LOOP_PRODUCTION_TRUTH_READER_REQUIRED")
            expected_node_id = str(dispatcher.claimant.node_id or "").strip()
            if not expected_node_id:
                raise RuntimeError("FULL_LOOP_PRODUCTION_NODE_ID_REQUIRED")
        self.production_components_verified = bool(require_production_components)
        self.expected_node_id = expected_node_id
        self.truth_reader = truth_reader
        self.observer = SingleNodeFullLoopProofRunner(
            dispatcher=dispatcher,
            required_stages=required_stages,
            require_center_claim_provenance=bool(require_production_components),
        )
        self.verifier = SingleNodeCenterTruthVerifier(truth_reader=truth_reader, expected_node_id=expected_node_id)

    def run(self, *, test_run_id: str) -> SingleNodeDurableIntegrationProof:
        if self.production_components_verified:
            # This must happen immediately before the first production claim. A
            # pre-existing Attempt proves the run is not a fresh causality fixture.
            self.truth_reader.assert_no_attempts_for_test_run(test_run_id)
        observed = self.observer.run(test_run_id=test_run_id)
        if self.production_components_verified:
            # The post-traversal durable Attempt set must be exactly the set of
            # Center-issued leases observed in this traversal. Extra/stale/missing
            # Attempts therefore fail before durable evidence can be promoted.
            self.truth_reader.assert_attempt_ids_match_observed_leases(
                test_run_id=test_run_id,
                observed_lease_ids=observed.lease_ids,
            )
        durable = self.verifier.verify(observed)
        if durable.verified_work_items != observed.work_item_ids:
            raise RuntimeError("FULL_LOOP_DURABLE_WORK_ITEM_IDENTITY_MISMATCH")
        if durable.verified_attempts != observed.attempt_ids:
            raise RuntimeError("FULL_LOOP_DURABLE_ATTEMPT_IDENTITY_MISMATCH")
        if self.production_components_verified:
            # The composed proof must retain the production node authority and both
            # halves of the worker-produced R1 chain.  Losing either after the
            # truth verifier would make a later promotion unable to prove that the
            # Center-issued leases and durable events came from the same node/run.
            if durable.verified_production_node_id != self.expected_node_id:
                raise RuntimeError("FULL_LOOP_DURABLE_PRODUCTION_NODE_IDENTITY_MISMATCH")
            if len(durable.verified_r1_start_events) != len(observed.attempt_ids):
                raise RuntimeError("FULL_LOOP_DURABLE_START_EVENT_CARDINALITY_MISMATCH")
            if len(durable.verified_r1_events) != len(observed.attempt_ids):
                raise RuntimeError("FULL_LOOP_DURABLE_COMPLETION_EVENT_CARDINALITY_MISMATCH")
        if durable.bank_reality_verified:
            raise RuntimeError("CLOUD_INTEGRATION_MUST_NOT_ASSERT_BANK_REALITY")
        if durable.release_status != "HOLD":
            raise RuntimeError("INTEGRATION_PROOF_MUST_NOT_AUTHORIZE_RELEASE")
        status = (
            "PRODUCTION_COMPONENTS_DURABLE_TRUTH_MATCHED_CAUSALITY_NOT_PROVEN"
            if self.production_components_verified
            else "BOUNDARY_DOUBLE_VERIFIED_NOT_PRODUCTION_PROOF"
        )
        return SingleNodeDurableIntegrationProof(
            observed=observed,
            durable_truth=durable,
            production_components_verified=self.production_components_verified,
            production_causality_verified=False,
            status=status,
        )
