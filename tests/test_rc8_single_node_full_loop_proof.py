from __future__ import annotations

import pytest

from rc8_node.autonomous_dispatcher import DispatchOutcome
from rc8_node.single_node_full_loop_proof import (
    FROZEN_N1_N10_STAGES,
    SingleNodeFullLoopProofError,
    SingleNodeFullLoopProofRunner,
)


class SequencedProductionDispatcherDouble:
    """Dispatcher boundary double; proof runner itself consumes production DispatchOutcome."""
    def __init__(self, stages=FROZEN_N1_N10_STAGES, mutate=None):
        self.supported_stages = tuple(stages)
        self._stages = list(stages)
        self._index = 0
        self._mutate = mutate
        self.test_run_ids = []

    def run_once(self, *, test_run_id=None):
        self.test_run_ids.append(test_run_id)
        stage = self._stages[self._index]
        result = {
            "status": "COMPLETED",
            "attempt_id": "attempt-%02d" % self._index,
            "artifact_ref": "artifact:evidence-%02d" % self._index,
        }
        outcome = DispatchOutcome(
            status="EXECUTED",
            stage=stage,
            work_item_id="wi-%02d" % self._index,
            lease_id="lease-%02d" % self._index,
            stage_instance_id="stage-instance-%02d" % self._index,
            result=result,
        )
        if self._mutate is not None:
            outcome = self._mutate(self._index, outcome)
        self._index += 1
        return outcome


def test_full_loop_runner_freezes_denominator_and_never_grants_pass_or_release() -> None:
    dispatcher = SequencedProductionDispatcherDouble()
    proof = SingleNodeFullLoopProofRunner(dispatcher=dispatcher).run(test_run_id="TR-SINGLE-N1-N10")
    assert proof.stages == FROZEN_N1_N10_STAGES
    assert len(proof.work_item_ids) == 15
    assert len(proof.lease_ids) == 15
    assert len(proof.stage_instance_ids) == 15
    assert len(proof.attempt_ids) == 15
    assert len(proof.evidence_refs) == 15
    assert proof.status == "OBSERVED_NOT_AUTHORIZED"
    assert proof.bank_reality_verified is False
    assert proof.release_status == "HOLD"
    assert dispatcher.test_run_ids == ["TR-SINGLE-N1-N10"] * 15


def test_full_loop_runner_rejects_missing_real_worker_denominator() -> None:
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_WORKER_DENOMINATOR_MISSING:REPORT_RELEASE"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(FROZEN_N1_N10_STAGES[:-1]))


def test_full_loop_runner_fails_closed_on_idle_or_out_of_order_stage() -> None:
    def idle_first(index, outcome):
        return DispatchOutcome(status="IDLE") if index == 0 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_STAGE_NOT_EXECUTED:SCOPE_INTAKE"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=idle_first)).run(test_run_id="TR")

    def wrong_second(index, outcome):
        return DispatchOutcome(status="EXECUTED", stage="CODE_ANALYSIS", work_item_id=outcome.work_item_id, lease_id=outcome.lease_id, stage_instance_id=outcome.stage_instance_id, result=outcome.result) if index == 1 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_STAGE_ORDER_MISMATCH:REQUIREMENT_ANALYSIS:CODE_ANALYSIS"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=wrong_second)).run(test_run_id="TR")


def test_full_loop_runner_requires_distinct_claim_identity() -> None:
    def no_work_item(index, outcome):
        return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id="", lease_id=outcome.lease_id, stage_instance_id=outcome.stage_instance_id, result=outcome.result) if index == 2 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_WORK_ITEM_ID_MISSING:REQUIREMENT_SUFFICIENCY"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=no_work_item)).run(test_run_id="TR")

    def no_lease(index, outcome):
        return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id=outcome.work_item_id, lease_id="", stage_instance_id=outcome.stage_instance_id, result=outcome.result) if index == 3 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_LEASE_ID_MISSING:CODE_ANALYSIS"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=no_lease)).run(test_run_id="TR")

    def no_stage_instance(index, outcome):
        return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id=outcome.work_item_id, lease_id=outcome.lease_id, stage_instance_id="", result=outcome.result) if index == 5 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_STAGE_INSTANCE_ID_MISSING:RISK_TEST_MODEL"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=no_stage_instance)).run(test_run_id="TR")

    def reused_work_item(index, outcome):
        return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id="wi-00", lease_id=outcome.lease_id, stage_instance_id=outcome.stage_instance_id, result=outcome.result) if index == 1 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_WORK_ITEM_ID_REUSED"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=reused_work_item)).run(test_run_id="TR")

    def reused_lease(index, outcome):
        return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id=outcome.work_item_id, lease_id="lease-00", stage_instance_id=outcome.stage_instance_id, result=outcome.result) if index == 1 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_LEASE_ID_REUSED"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=reused_lease)).run(test_run_id="TR")

    def reused_stage_instance(index, outcome):
        return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id=outcome.work_item_id, lease_id=outcome.lease_id, stage_instance_id="stage-instance-00", result=outcome.result) if index == 1 else outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_STAGE_INSTANCE_ID_REUSED"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=reused_stage_instance)).run(test_run_id="TR")


def test_full_loop_runner_requires_attempt_bound_canonical_artifact_evidence() -> None:
    def no_attempt(index, outcome):
        if index == 4:
            result = dict(outcome.result); result["attempt_id"] = ""
            return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id=outcome.work_item_id, lease_id=outcome.lease_id, stage_instance_id=outcome.stage_instance_id, result=result)
        return outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_ATTEMPT_EVIDENCE_MISSING:CODE_SUFFICIENCY"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=no_attempt)).run(test_run_id="TR")

    def stale_ref(index, outcome):
        if index == 7:
            result = dict(outcome.result); result["artifact_ref"] = "synthetic://design"
            return DispatchOutcome(status=outcome.status, stage=outcome.stage, work_item_id=outcome.work_item_id, lease_id=outcome.lease_id, stage_instance_id=outcome.stage_instance_id, result=result)
        return outcome
    with pytest.raises(SingleNodeFullLoopProofError, match="FULL_LOOP_ARTIFACT_EVIDENCE_MISSING:DESIGN_SUFFICIENCY"):
        SingleNodeFullLoopProofRunner(dispatcher=SequencedProductionDispatcherDouble(mutate=stale_ref)).run(test_run_id="TR")
