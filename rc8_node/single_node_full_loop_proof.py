"""Fail-closed verifier for one-mission RC8 SINGLE_NODE N1-N10 traversal.

The runner drives the production AutonomousWorkerDispatcher one claim at a time.
It does not complete stages, invent evidence, or grant PASS authority. A proof is
accepted only when the frozen 15-stage denominator is observed in order and each
real worker result carries a distinct WorkItem, lease, Stage instance, Attempt and
canonical artifact Evidence reference. Center/Director remain the only MissionNode/
convergence/release authorities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple


FROZEN_N1_N10_STAGES: Tuple[str, ...] = (
    "SCOPE_INTAKE", "REQUIREMENT_ANALYSIS", "REQUIREMENT_SUFFICIENCY",
    "CODE_ANALYSIS", "CODE_SUFFICIENCY", "RISK_TEST_MODEL", "TEST_DESIGN",
    "DESIGN_SUFFICIENCY", "PRECONDITION_DATA_PREP", "EXECUTABLE_SPEC",
    "APPLICABLE_LAYER_EXECUTION", "FAILURE_COVERAGE_EVALUATION",
    "DEFECT_CLOSURE_OBSERVATION", "MISSION_SUFFICIENCY", "REPORT_RELEASE",
)


class SingleNodeFullLoopProofError(RuntimeError):
    pass


@dataclass(frozen=True)
class SingleNodeFullLoopProof:
    test_run_id: str
    stages: Tuple[str, ...]
    work_item_ids: Tuple[str, ...]
    lease_ids: Tuple[str, ...]
    stage_instance_ids: Tuple[str, ...]
    attempt_ids: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    status: str = "OBSERVED_NOT_AUTHORIZED"
    bank_reality_verified: bool = False
    release_status: str = "HOLD"


class SingleNodeFullLoopProofRunner:
    """Observe a real dispatcher traversal without becoming a PASS authority."""

    def __init__(self, *, dispatcher: Any, required_stages: Sequence[str] = FROZEN_N1_N10_STAGES) -> None:
        stages = tuple(str(v or "").strip() for v in required_stages)
        if not stages or any(not v for v in stages) or len(set(stages)) != len(stages):
            raise SingleNodeFullLoopProofError("FULL_LOOP_STAGE_DENOMINATOR_INVALID")
        supported = set(getattr(dispatcher, "supported_stages", ()) or ())
        missing = tuple(stage for stage in stages if stage not in supported)
        if missing:
            raise SingleNodeFullLoopProofError("FULL_LOOP_WORKER_DENOMINATOR_MISSING:%s" % ",".join(missing))
        self.dispatcher = dispatcher
        self.required_stages = stages

    def run(self, *, test_run_id: str) -> SingleNodeFullLoopProof:
        run_id = str(test_run_id or "").strip()
        if not run_id:
            raise SingleNodeFullLoopProofError("FULL_LOOP_TEST_RUN_ID_REQUIRED")
        observed: List[str] = []
        work_items: List[str] = []
        leases: List[str] = []
        stage_instances: List[str] = []
        attempts: List[str] = []
        evidence: List[str] = []
        for expected in self.required_stages:
            outcome = self.dispatcher.run_once(test_run_id=run_id)
            if getattr(outcome, "status", None) != "EXECUTED":
                raise SingleNodeFullLoopProofError("FULL_LOOP_STAGE_NOT_EXECUTED:%s" % expected)
            actual = str(getattr(outcome, "stage", None) or "").strip()
            if actual != expected:
                raise SingleNodeFullLoopProofError("FULL_LOOP_STAGE_ORDER_MISMATCH:%s:%s" % (expected, actual or "NONE"))
            work_item_id = str(getattr(outcome, "work_item_id", None) or "").strip()
            if not work_item_id:
                raise SingleNodeFullLoopProofError("FULL_LOOP_WORK_ITEM_ID_MISSING:%s" % expected)
            lease_id = str(getattr(outcome, "lease_id", None) or "").strip()
            if not lease_id:
                raise SingleNodeFullLoopProofError("FULL_LOOP_LEASE_ID_MISSING:%s" % expected)
            stage_instance_id = str(getattr(outcome, "stage_instance_id", None) or "").strip()
            if not stage_instance_id:
                raise SingleNodeFullLoopProofError("FULL_LOOP_STAGE_INSTANCE_ID_MISSING:%s" % expected)
            result = getattr(outcome, "result", None)
            if not isinstance(result, dict) or str(result.get("status") or "") != "COMPLETED":
                raise SingleNodeFullLoopProofError("FULL_LOOP_WORKER_NOT_COMPLETED:%s" % expected)
            attempt_id = str(result.get("attempt_id") or "").strip()
            artifact_ref = str(result.get("artifact_ref") or "").strip()
            if not attempt_id:
                raise SingleNodeFullLoopProofError("FULL_LOOP_ATTEMPT_EVIDENCE_MISSING:%s" % expected)
            # Production Center defines the active lease as the immutable Attempt
            # identity. Every canonical Stage worker follows attempt_id=lease_id.
            # Reject a worker result that splices evidence from another Attempt
            # even when both identities are individually unique and durable.
            if attempt_id != lease_id:
                raise SingleNodeFullLoopProofError("FULL_LOOP_ATTEMPT_LEASE_IDENTITY_MISMATCH:%s" % expected)
            if not artifact_ref.startswith("artifact:"):
                raise SingleNodeFullLoopProofError("FULL_LOOP_ARTIFACT_EVIDENCE_MISSING:%s" % expected)
            observed.append(actual)
            work_items.append(work_item_id)
            leases.append(lease_id)
            stage_instances.append(stage_instance_id)
            attempts.append(attempt_id)
            evidence.append(artifact_ref)
        if len(set(work_items)) != len(work_items):
            raise SingleNodeFullLoopProofError("FULL_LOOP_WORK_ITEM_ID_REUSED")
        if len(set(leases)) != len(leases):
            raise SingleNodeFullLoopProofError("FULL_LOOP_LEASE_ID_REUSED")
        if len(set(stage_instances)) != len(stage_instances):
            raise SingleNodeFullLoopProofError("FULL_LOOP_STAGE_INSTANCE_ID_REUSED")
        if len(set(attempts)) != len(attempts):
            raise SingleNodeFullLoopProofError("FULL_LOOP_ATTEMPT_ID_REUSED")
        if len(set(evidence)) != len(evidence):
            raise SingleNodeFullLoopProofError("FULL_LOOP_EVIDENCE_REF_REUSED")
        return SingleNodeFullLoopProof(
            test_run_id=run_id,
            stages=tuple(observed),
            work_item_ids=tuple(work_items),
            lease_ids=tuple(leases),
            stage_instance_ids=tuple(stage_instances),
            attempt_ids=tuple(attempts),
            evidence_refs=tuple(evidence),
        )
