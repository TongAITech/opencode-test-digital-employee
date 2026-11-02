"""Three approved Cases, real local execution and native mixed-scope data repair."""
from copy import deepcopy

from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc7_runtime.rc72_n7_member_drain import ExecutionMemberDrainService
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
from rc7_runtime.rc72_n5_existing_data_repair import ExistingDataRepairService
from rc7_runtime.rc72_n5_completion import N5DeliveryGateService
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment
from test_rc72_n5_existing_data_repair import _launcher
from test_rc72_n7_member_drain import _close


def mixed_member_repair(tmp_path, monkeypatch):
    import test_rc72_n4_test_design_handoff as n4
    from rc72_n2_test_support import REQUIREMENTS
    candidate = n4._candidate
    def with_extra_approved_case(requirement_id, sst_id, **kwargs):
        result = candidate(requirement_id, sst_id, **kwargs)
        if requirement_id == REQUIREMENTS[0]:
            extra = deepcopy(result['cases'][0])
            extra['tc_id'] += '-SECOND-APPROVED-CASE'
            result['cases'].append(extra)
        return result
    # Extend the upstream design before its real N4 handoff/gate, N5 inventory,
    # native decomposition and each actual script qualification. Never edit an
    # already-approved denominator, execution result or plan.
    monkeypatch.setattr(n4, '_candidate', with_extra_approved_case)
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        assert len(plan['items']) == 3
        root = tmp_path / 'multiple-original-executions'
        env = LocalHTTPEnvironment(url, root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        peers = []
        for item in plan['items'][:2]:
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'RETURNED'
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(p['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
            peers.append(p)
        failed = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][2]['workitem_id'])
        failed_refs = {ref['data_ref'] for ref in prep._one('rc72_n6_executable_contract', contract_id=failed['contract_id'])['data_refs']}
        affected_peer_refs = {ref['data_ref'] for ref in prep._one('rc72_n6_executable_contract', contract_id=peers[0]['contract_id'])['data_refs']}
        unchanged_refs = {ref['data_ref'] for ref in prep._one('rc72_n6_executable_contract', contract_id=peers[1]['contract_id'])['data_refs']}
        assert not (failed_refs | affected_peer_refs) & unchanged_refs
        server.allowed_data_refs.difference_update(failed_refs)
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(failed['preparation_id'])['state'] == 'FAILED'
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'multiple-diagnosis')
        assert diagnosis.run(failed['preparation_id'])['failure_class'] == 'TEST_DATA_GAP'
        drain = ExecutionMemberDrainService(ExecutionEvidenceReviewService(prep, adapter_output_root=root,
                                                                         capture_root=tmp_path / 'captured-original-peers'))
        for p in peers:
            assert drain.drain(p['preparation_id'])['state'] == 'DRAINED'
        boundary = RepairBoundaryService(diagnosis, cleanup_adapters={'api_http': env.cleanup})
        assert boundary.open(failed['preparation_id'])['state'] == 'REPAIR_OPEN'
        changed = failed_refs | affected_peer_refs
        calls = []
        data = ExistingDataRepairService(boundary, launcher=_launcher(tmp_path, prep, server, calls),
                                        allowed_tools=['query-exact-data-ref'])
        for binding in truth.query('rc72_n5_data_binding', release_batch_id=failed['release_batch_id']):
            if binding['data_ref'] not in changed:
                continue
            request = data.request(failed['preparation_id'], data_requirement_id=binding['data_requirement_id'],
                                   binding_revision=binding['artifact_version'])
            data.prepare(request['repair_id'], launcher=_launcher(tmp_path, prep, server, calls),
                         allowed_tools=['repair-exact-data-ref'])
            assert data.run(request['repair_id'])['state'] == 'VERIFIED'
        gate = N5DeliveryGateService(truth, release_id=failed['release_id'], source_commit=failed['source_commit']).complete(
            release_batch_id=failed['release_batch_id'])
        diagnosis.record_accepted_repair(failed['preparation_id'], repair_delivery_id=gate['delivery']['delivery_id'],
            changed_refs=sorted(changed), reason='independent mixed-member data repair retaining full three-Case scope')
        return truth, prep, server, plan, peers, failed, diagnosis
    except BaseException:
        _close(server)
        raise
