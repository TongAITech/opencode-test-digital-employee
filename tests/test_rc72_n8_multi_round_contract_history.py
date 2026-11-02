"""A historical contract identity cannot be repointed to another valid digest."""
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n6_completion import _digest
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from test_rc72_n8_multi_round import _second_repair
from test_rc72_n7_member_drain import _close


def test_rehashed_contract_under_old_identity_cannot_enter_a_new_retry_round(tmp_path, monkeypatch):
    truth, prep, server, completed, failed, child, first_row, diagnosis = _second_repair(tmp_path, monkeypatch)
    try:
        plan = prep._one('rc72_n7_execution_plan', plan_id=child['plan_id'])
        contract = prep._one('rc72_n6_executable_contract', contract_id=plan['items'][0]['contract_id'])
        contract['input']['unapproved_historical_input'] = 'changed'
        contract['contract_sha256'] = _digest(contract)
        contract['artifact_version'] += 1
        from rc7_runtime.rc72_n6_executable_readiness import EVENT_N6_EXECUTABLE_CONTRACT_COMPILED
        truth.append_atomic(EVENT_N6_EXECUTABLE_CONTRACT_COMPILED, contract)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='HISTORICAL_ADMISSION_OR_CONTRACT_CHANGED'):
            DataRepairContinuationService(diagnosis).reconcile(child['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert len(truth.query('rc72_n8_retry_reconciliation')) == 1
        assert len(truth.query('execution_attempt')) == 3 and len(server.calls) == 1
    finally:
        _close(server)
