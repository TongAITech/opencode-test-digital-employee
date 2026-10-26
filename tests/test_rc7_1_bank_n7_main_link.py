import inspect
from types import SimpleNamespace

import pytest

import rc7_runtime.bank_n7_execution_closure as n7_link
from rc7_runtime.autonomous_contract import CoverageDenominatorSnapshot, LayerCoverageReceipt
from rc7_runtime.autonomous_coverage_closure import DurableCoverageDenominator, DurableLayerCoverageReceipt
from rc7_runtime.autonomous_node_adoption import AutonomousNodeAdoptionError
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.bank_mission_autopilot import BankMissionAutopilot
from rc7_runtime.bank_n7_execution_closure import (
    BankN7ExecutionClosureCoordinator,
    BankN7ExecutionClosureError,
)
from rc7_runtime.case_fanout_conformance import AcceptedCase, AcceptedCaseInventory
from rc7_runtime.execution_fanout_conformance import ExecutionFanoutBarrierResult


class _Truth:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def query(self, entity_type, **filters):
        rows = [row for row in self.rows if row.get("entity_type") == entity_type]
        for key, value in filters.items():
            rows = [row for row in rows if row.get(key) == value]
        return rows


class _Control:
    def __init__(self, rows=None):
        self.truth = _Truth(rows)
        self.mission_id = "M-N7-BANK"
        self.release_id = "R-N7-BANK"


def _inventory():
    case = AcceptedCase(tc_id="TC-1", case_version=1, layer="L3", case_hash="sha256:case")
    return AcceptedCaseInventory(
        mission_id="M-N7-BANK",
        design_task_id="T-DESIGN",
        design_artifact_id="ART-DESIGN",
        design_content_hash="sha256:design",
        cases=(case,),
    )


def _barrier(*, status="PASS", outcome_receipts=("EVD-EXEC-1",), missing=(), blocked=()):
    return ExecutionFanoutBarrierResult(
        status=status,
        mission_id="M-N7-BANK",
        design_artifact_id="ART-DESIGN",
        required_tc_ids=("TC-1",),
        pass_ready_tc_ids=(() if missing else ("TC-1",)),
        blocked_tc_ids=tuple(blocked),
        missing_tc_ids=tuple(missing),
        receipt_ids=tuple(outcome_receipts),
    )


def _terminal(outcome="PASS"):
    return {
        "mission_id": "M-N7-BANK",
        "design_artifact_id": "ART-DESIGN",
        "design_content_hash": "sha256:design",
        "tc_id": "TC-1",
        "case_version": 1,
        "layer": "L3",
        "target_id": "BANK-TARGET",
        "execution_task_id": "T-EXEC",
        "execution_artifact_id": "ART-EXEC",
        "attempt_id": "ATT-1",
        "outcome": outcome,
        "oracle_fingerprint": "sha256:oracle",
        "prepared_evidence_id": "EVD-PREP",
        "record_evidence_id": "EVD-RECORD",
        "evaluation_id": "EVAL-EXEC",
    }


def test_bank_execution_autopilot_remains_per_case_and_does_not_close_whole_n7():
    source = inspect.getsource(BankExecutionAutopilot.run)
    assert "self.execution.execute_active_task" in source
    assert "close_current_batch" not in source


def test_bank_mission_convergence_closes_n7_before_n10_and_return_path():
    source = inspect.getsource(BankMissionAutopilot._convergence)
    assert "self.n7.close_current_batch" in source
    assert source.index("self.n7.close_current_batch") < source.index("self.n10.prepare_ready")
    drive = inspect.getsource(BankMissionAutopilot.drive)
    assert "convergence_handler=self._convergence" in drive


def test_missing_current_execution_receipt_blocks_n7(monkeypatch):
    control = _Control()
    coordinator = BankN7ExecutionClosureCoordinator(target_id="BANK-TARGET", evidence_root=".")
    monkeypatch.setattr(n7_link, "check_execution_barrier", lambda *_args, **_kwargs: _barrier(status="INCOMPLETE", outcome_receipts=(), missing=("TC-1",)))
    monkeypatch.setattr(n7_link.AcceptedCaseInventoryReader, "load", lambda *_args, **_kwargs: _inventory())
    with pytest.raises(BankN7ExecutionClosureError, match="CURRENT_EXECUTION_RECEIPTS_INCOMPLETE"):
        coordinator._validate_execution_batch(control, run_id="RUN-CURRENT")


@pytest.mark.parametrize("outcome", ["UNKNOWN", "NOT_EXECUTED"])
def test_unknown_or_not_executed_receipt_blocks_n7(monkeypatch, outcome):
    control = _Control()
    coordinator = BankN7ExecutionClosureCoordinator(target_id="BANK-TARGET", evidence_root=".")
    monkeypatch.setattr(n7_link, "check_execution_barrier", lambda *_args, **_kwargs: _barrier())
    monkeypatch.setattr(n7_link.AcceptedCaseInventoryReader, "load", lambda *_args, **_kwargs: _inventory())
    monkeypatch.setattr(n7_link, "load_execution_terminal_receipt", lambda *_args, **_kwargs: _terminal(outcome))
    with pytest.raises(BankN7ExecutionClosureError, match="EXECUTION_RECEIPT_NOT_EXECUTED"):
        coordinator._validate_execution_batch(control, run_id="RUN-CURRENT")


def test_run_mismatch_in_current_attempt_binding_blocks_n7(monkeypatch):
    control = _Control()
    coordinator = BankN7ExecutionClosureCoordinator(target_id="BANK-TARGET", evidence_root=".")
    monkeypatch.setattr(n7_link, "_file_payload", lambda *_args, **_kwargs: {
        "run_id": "RUN-OLD",
        "target_id": "BANK-TARGET",
        "attempt_id": "ATT-1",
        "tc_id": "TC-1",
        "execution_task_id": "T-EXEC",
        "status": "PREPARED_FOR_EXECUTION",
    })
    control.truth.rows.append({
        "entity_type": "rc7_artifact",
        "mission_id": control.mission_id,
        "artifact_id": "ART-N5-OLD",
        "artifact_type_name": coordinator.N5_FINALIZATION_TYPE,
        "state": "VALID",
    })
    with pytest.raises(BankN7ExecutionClosureError, match="CURRENT_ATTEMPT_N5_FINALIZATION_REQUIRED"):
        coordinator._current_n5_finalization(control, run_id="RUN-CURRENT", terminal=_terminal())


def test_stale_denominator_from_other_run_blocks_n7(monkeypatch):
    control = _Control()
    coordinator = BankN7ExecutionClosureCoordinator(target_id="BANK-TARGET", evidence_root=".")
    snapshot = CoverageDenominatorSnapshot(
        mission_id=control.mission_id,
        layer="L1",
        source_revision="rev",
        target_id="BANK-TARGET",
        denominator_version="v0001",
        denominator_hash="sha256:denom",
        obligation_ids=("O-1",),
        evidence_refs=("EVD-DENOM",),
    )
    durable = DurableCoverageDenominator("ART-DENOM", "EVD-DENOM", snapshot)
    monkeypatch.setattr(coordinator.service.coverage, "current_denominator", lambda *_args, **_kwargs: durable)
    monkeypatch.setattr(coordinator, "_artifact_row", lambda *_args, **_kwargs: {"artifact_id": "ART-DENOM"})
    monkeypatch.setattr(n7_link, "_file_payload", lambda *_args, **_kwargs: {
        "run_id": "RUN-OLD",
        "snapshot": {"target_id": "BANK-TARGET"},
    })
    with pytest.raises(BankN7ExecutionClosureError, match="STALE_DENOMINATOR_RUN:L1"):
        coordinator._current_layer_receipts(control, run_id="RUN-CURRENT")


def test_covered_fail_is_forwarded_as_coverage_truth_not_quality_pass(monkeypatch):
    control = _Control(rows=[{
        "entity_type": "rc7_control_event",
        "event_id": "EVT-N7-TERMINAL",
        "mission_id": "M-N7-BANK",
        "data": {"run_id": "RUN-CURRENT", "node_id": "N7", "state": "PASS"},
    }])
    coordinator = BankN7ExecutionClosureCoordinator(target_id="BANK-TARGET", evidence_root=".")
    receipt = LayerCoverageReceipt(
        layer="L1",
        source_revision="rev",
        target_id="BANK-TARGET",
        denominator_version="v0001",
        denominator_hash="sha256:d",
        covered=1,
        total=1,
        covered_pass=0,
        covered_fail=1,
        excluded_with_evidence=0,
        open_gap_ids=(),
        blocked_obligation_ids=(),
        evidence_refs=("EVD-FAIL",),
        status="READY",
    )
    durable = DurableLayerCoverageReceipt("ART-R", "EVD-R", receipt, {"line_coverage": 1.0, "logic_coverage": 1.0})
    receipts = tuple(durable for _ in range(7))
    seen = {}
    monkeypatch.setattr(coordinator, "_validate_execution_batch", lambda *_args, **_kwargs: (_terminal("PRODUCT_DEFECT"),))
    monkeypatch.setattr(coordinator, "_current_layer_receipts", lambda *_args, **_kwargs: receipts)
    monkeypatch.setattr(coordinator, "_input_version", lambda *_args, **_kwargs: "CURRENT")

    class _NodeControl:
        @staticmethod
        def latest_iteration(**_kwargs):
            return None

    class _Adoption:
        node_control = _NodeControl()

        @staticmethod
        def director_accept(**_kwargs):
            return SimpleNamespace(accepted=True, terminal_event_id="EVT-N7-TERMINAL")

    coordinator.adoption = _Adoption()

    def publish(_control, *, run_id, receipts):
        seen["covered_fail"] = receipts[0].receipt.covered_fail
        seen["quality"] = getattr(receipts[0].receipt, "product_quality_pass", None)

    monkeypatch.setattr(coordinator.service, "publish_ready", publish)
    coordinator.close_current_batch(control, run_id="RUN-CURRENT")
    assert seen == {"covered_fail": 1, "quality": None}


def test_director_identity_collision_is_fail_closed(monkeypatch):
    control = _Control()
    coordinator = BankN7ExecutionClosureCoordinator(target_id="BANK-TARGET", evidence_root=".")
    coordinator.director_ref = "rc7-runtime-coverage-authority"
    monkeypatch.setattr(coordinator, "_validate_execution_batch", lambda *_args, **_kwargs: (_terminal(),))
    monkeypatch.setattr(coordinator, "_current_layer_receipts", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(coordinator, "_input_version", lambda *_args, **_kwargs: "CURRENT")
    monkeypatch.setattr(coordinator.service, "publish_ready", lambda *_args, **_kwargs: None)

    class _NodeControl:
        @staticmethod
        def latest_iteration(**_kwargs):
            return None

    class _Adoption:
        node_control = _NodeControl()

        @staticmethod
        def director_accept(**_kwargs):
            raise AutonomousNodeAdoptionError("DIRECTOR_CANNOT_REUSE_SOURCE_EVALUATOR_IDENTITY")

    coordinator.adoption = _Adoption()
    with pytest.raises(BankN7ExecutionClosureError, match="DIRECTOR_GATE_FAILED"):
        coordinator.close_current_batch(control, run_id="RUN-CURRENT")


def test_n7_production_link_uses_existing_n7_service_and_shared_director_gate():
    source = inspect.getsource(BankN7ExecutionClosureCoordinator.close_current_batch)
    assert "self.service.publish_ready" in source
    assert "adoption.director_accept" in source
    assert "node_id=\"N7\"" in source
    assert "terminal_event_id" in source
