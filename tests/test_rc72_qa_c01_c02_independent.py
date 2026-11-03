"""Independent C01/C02 acceptance: physical N5 -> N6 -> fresh N7, not a PASS fixture.

This uses the actual local HTTP SUT, signed tool dispatch, independent N5
preparer/verifier, N6 product compilation and durable R1 records. It is an
engineering qualification only and MUST NOT be reported as bank Field evidence.
"""
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from test_rc72_n8_retry_continuation import _whole_inventory_repaired
from test_rc72_n7_execution_preparation import _service
from test_rc72_n5_existing_data_repair import _close
from rc72_formal_runner_support import LocalHTTPEnvironment


def test_qa_c01_c02_physical_repair_recompile_fresh_execution_preserves_history(tmp_path, monkeypatch):
    values, _ = _whole_inventory_repaired(tmp_path, monkeypatch)
    truth, prep, server, failed_preparation, _, data, _, _, _ = values
    try:
        original_failure = prep._one('execution_attempt', attempt_id=failed_preparation['attempt_id'])
        old_plan = prep._one('rc72_n7_execution_plan', plan_id=failed_preparation['plan_id'])
        old_n6_deliveries = list(truth.query('rc72_node_delivery', node_type='N6_EXECUTABLE_READINESS'))
        old_n6_gates = list(truth.query('rc72_node_gate', node_type='N6_EXECUTABLE_READINESS'))
        assert old_n6_deliveries and old_n6_gates
        assert truth.query('rc7_evidence', kind='N5_EXISTING_DATA_REVERIFICATION')
        repair_rows = truth.query('rc72_n5_existing_data_repair')
        assert repair_rows and all(row['state'] == 'VERIFIED' for row in repair_rows)
        assert all(row.get('producer', {}).get('state') == 'PREPARED' for row in repair_rows)
        assert all(row['identity']['worker_id'] != row['producer']['identity']['worker_id'] for row in repair_rows)
        assert all(prep.authority.is_lease_revoked(row['lease']['lease_id']) for row in repair_rows)
        assert all(prep.authority.is_lease_revoked(row['producer']['lease']['lease_id']) for row in repair_rows)

        service = DataRepairContinuationService(data.boundary.diagnosis)
        new_plan = service.reconcile(failed_preparation['preparation_id'])
        assert new_plan['plan_id'] != old_plan['plan_id']
        assert new_plan['snapshot_id'] == old_plan['snapshot_id']
        assert [(x['case_id'], x['etu_id'], x['workitem_id']) for x in new_plan['items']] == [
            (x['case_id'], x['etu_id'], x['workitem_id']) for x in old_plan['items']]
        assert truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]['state'] == 'PASS'
        assert len(truth.query('rc72_node_delivery', node_type='N6_EXECUTABLE_READINESS')) > len(old_n6_deliveries)
        assert len(truth.query('rc72_node_gate', node_type='N6_EXECUTABLE_READINESS')) > len(old_n6_gates)
        assert all(row in truth.query('rc72_node_delivery') for row in old_n6_deliveries)
        assert all(row in truth.query('rc72_node_gate') for row in old_n6_gates)

        replacement = service.prepare_replacement(failed_preparation['preparation_id'])
        assert replacement['attempt_id'] != failed_preparation['attempt_id']
        assert replacement['worker_id'] != failed_preparation['worker_id']
        assert replacement['session_id'] != failed_preparation['session_id']
        assert replacement['attempt_generation'] == failed_preparation['attempt_generation'] + 1
        assert prep._one('rc72_workitem_attempt_binding', binding_id=replacement['binding_id'])['parent_attempt_id'] == failed_preparation['attempt_id']
        assert prep._one('execution_attempt', attempt_id=failed_preparation['attempt_id']) == original_failure

        root = tmp_path / 'qa-actual-reexecution'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        for item in new_plan['items']:
            prepared = prep.prepare(plan_id=new_plan['plan_id'], workitem_id=item['workitem_id'])
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(prepared['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(prepared['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        reviewer = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'qa-review')
        bundle = reviewer.build(new_plan['plan_id'])
        result = ExecutionFinalizationService(reviewer).finalize(bundle['bundle_id'])
        assert result['state'] == 'N7_PASS'
        assert len(server.calls) == len(new_plan['items'])
        assert prep._one('execution_attempt', attempt_id=failed_preparation['attempt_id']) == original_failure

        cold = _service(TruthRuntime(truth.store.path))
        cold_review = ExecutionEvidenceReviewService(cold, adapter_output_root=root, capture_root=reviewer.capture_root)
        before_r1 = cold.truth.store.path.read_bytes()
        assert ExecutionFinalizationService(cold_review).finalize(bundle['bundle_id']) == result
        assert cold.truth.store.path.read_bytes() == before_r1
        assert not cold.authority._leases
        assert cold.truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
    finally:
        _close(server)


def test_qa_c01_c02_changed_independent_verifier_bytes_stop_n6_before_any_new_attempt(tmp_path, monkeypatch):
    values, _ = _whole_inventory_repaired(tmp_path, monkeypatch)
    truth, prep, server, failed_preparation, _, data, _, _, _ = values
    try:
        old_failed = prep._one('execution_attempt', attempt_id=failed_preparation['attempt_id'])
        evidences = truth.query('rc7_evidence', kind='N5_EXISTING_DATA_REVERIFICATION')
        assert evidences
        evidence_path = Path(evidences[0]['content_ref'][len('file://'):])
        evidence_path.write_bytes(evidence_path.read_bytes() + b'QA-TAMPER-MUST-BLOCK')
        before_r1 = truth.store.path.read_bytes()
        before_count = len(truth.query('execution_attempt'))
        before_calls = list(server.calls)
        with pytest.raises(ContractError):
            DataRepairContinuationService(data.boundary.diagnosis).reconcile(failed_preparation['preparation_id'])
        assert truth.store.path.read_bytes() == before_r1
        assert len(truth.query('execution_attempt')) == before_count
        assert server.calls == before_calls
        assert prep._one('execution_attempt', attempt_id=failed_preparation['attempt_id']) == old_failed
    finally:
        _close(server)
