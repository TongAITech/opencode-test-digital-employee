"""Actual N7 local HTTP failure -> independent N8 -> signed N5 compensation.

These are source-level tests using a real local SUT and real subprocess
diagnosis/cleanup. No fake Case PASS, DataRef or field qualification is issued.
"""
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc72_formal_runner_support import LocalHTTPEnvironment
from test_rc72_n8_execution_diagnosis import _failure


def _product(tmp_path,monkeypatch,*,mode='data'):
    truth,prep,server,p=_failure(tmp_path,monkeypatch,mode)
    root=tmp_path/'n8-product-native'
    url='http://127.0.0.1:%d'%server.server_address[1]
    runner=FormalN7RunnerAdapter(prep,evidence_root=root/'runner',
        environment_adapter=LocalHTTPEnvironment(url,root/'cleanup'))
    pipeline=N7PipelineService(prep,runner=runner,capture_root=root/'evidence')
    return truth,p,server,NativeN8ProductRecoveryService(pipeline)


def test_n8_product_accepts_actual_failed_n7_then_opens_verified_n5_repair_only(tmp_path,monkeypatch):
    truth,p,server,service=_product(tmp_path,monkeypatch)
    try:
        old=truth.query('execution_attempt',attempt_id=p['attempt_id'])[0]
        result=service.complete(release_batch_id=p['release_batch_id'])
        assert result['status']=='HOLD' and result['reason']=='N8_VERIFIED_N5_REPAIR_REQUIRED'
        assert result['failure_class']=='TEST_DATA_GAP'
        assert result['affected_data_refs']
        assert result['field_verified'] is result['bank_final'] is False
        assert truth.query('rc72_mission_node',node_type='N8_DIAGNOSIS_RECOVERY')[0]['state']=='PASS'
        assert truth.query('rc72_mission_node',node_type='N5_TEST_DATA')[0]['state']=='RUNNING'
        assert truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='NOT_STARTED'
        assert truth.query('rc72_n8_repair_boundary')[0]['state']=='REPAIR_OPEN'
        assert truth.query('execution_attempt',attempt_id=p['attempt_id'])[0]==old
        assert not truth.query('rc72_diagnosis_repair')
        assert not truth.query('rc7_defect')
        assert server.calls==[]
        before=truth.store.path.read_bytes()
        repeat=service.complete(release_batch_id=p['release_batch_id'])
        assert repeat==result and truth.store.path.read_bytes()==before
        assert server.calls==[] and not truth.query('rc72_diagnosis_recovery')
    finally:
        server.shutdown();server.server_close()


def test_n8_product_unknown_causality_has_no_gate_compensation_or_business_replay(tmp_path,monkeypatch):
    truth,p,server,service=_product(tmp_path,monkeypatch,mode='precondition')
    try:
        result=service.complete(release_batch_id=p['release_batch_id'])
        assert result['status']=='HOLD' and result['reason']=='N8_UNKNOWN_CAUSE_NO_AUTO_PASS'
        assert result['failure_class']=='UNKNOWN'
        assert truth.query('rc72_mission_node',node_type='N8_DIAGNOSIS_RECOVERY')[0]['state']=='BLOCKED'
        assert not truth.query('rc72_n8_repair_boundary')
        assert not truth.query('rc72_node_gate',node_type='N8_DIAGNOSIS_RECOVERY')
        assert not truth.query('rc7_defect')
        assert server.calls==[]
        before=truth.store.path.read_bytes()
        assert service.complete(release_batch_id=p['release_batch_id'])==result
        assert truth.store.path.read_bytes()==before and server.calls==[]
    finally:
        server.shutdown();server.server_close()


def test_n8_product_rejects_edited_r1_failure_edge_before_cleanup(tmp_path,monkeypatch):
    truth,p,server,service=_product(tmp_path,monkeypatch)
    try:
        # Independently perform only the N8 signed diagnosis; never invoke
        # compensation before checking the persisted original transition.
        service.diagnosis.run(p['preparation_id'])
        edge=truth.query('rc72_node_transition',kind='DIAGNOSIS')[0]
        truth.append_atomic('RC72_NODE_TRANSITION_UPSERTED',dict(edge,
            evidence_refs=['foreign-evidence-proof'],
            artifact_version=edge['artifact_version']+1))
        before=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match='N8_PRODUCT_ORIGINAL_FAILURE_EVIDENCE_CHANGED'):
            service.complete(release_batch_id=p['release_batch_id'])
        assert truth.store.path.read_bytes()==before
        assert not truth.query('rc72_n8_repair_boundary')
        assert server.calls==[]
    finally:
        server.shutdown();server.server_close()


def test_n8_product_historical_repaired_n7_replay_reaudits_old_diagnosis_without_cleanup(tmp_path,monkeypatch):
    """Accepted N5 repair→new N6→physical new N7 must preserve old N8 truth."""
    from test_rc72_n8_retry_continuation import _whole_inventory_repaired
    from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
    from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
    from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
    from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
    from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
    values=_whole_inventory_repaired(tmp_path,monkeypatch)
    truth,prep,server,p,_,data,_,_,_=values
    try:
        replay=DataRepairContinuationService(data.boundary.diagnosis)
        new=replay.prepare_replacement(p['preparation_id'])
        plan=prep.planning.assert_current(new['plan_id'])
        root=tmp_path/'n8-audited-retry'
        env=LocalHTTPEnvironment('http://127.0.0.1:%d'%server.server_address[1],root)
        runner=FormalN7RunnerAdapter(prep,evidence_root=root,environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT':str(root)},timeout_seconds=30)
        for item in plan['items']:
            prepared=prep.prepare(plan_id=plan['plan_id'],workitem_id=item['workitem_id'])
            assert SignedToolDispatchService(prep,adapters={'api_http':runner}).dispatch(
                prepared['preparation_id'])['state']=='RETURNED'
            assert ExecutionCleanupService(prep,adapters={'api_http':env.cleanup}).run(
                prepared['preparation_id'])['state']=='CLEANUP_VERIFIED'
        review=ExecutionEvidenceReviewService(prep,adapter_output_root=root,
            capture_root=tmp_path/'accepted-n7')
        bundle=review.build(plan['plan_id'])
        assert ExecutionFinalizationService(review).finalize(bundle['bundle_id'])['state']=='N7_PASS'
        original=truth.query('execution_attempt',attempt_id=p['attempt_id'])[0]
        pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'native-n8')
        service=NativeN8ProductRecoveryService(pipeline)
        before=truth.store.path.read_bytes()
        result=service.audit(release_batch_id=p['release_batch_id'])
        assert result['status']=='AUDITED'
        assert result['diagnosis_ids']==[truth.query('rc72_diagnosis_case')[0]['diagnosis_id']]
        assert truth.store.path.read_bytes()==before
        assert truth.query('execution_attempt',attempt_id=p['attempt_id'])[0]==original
        assert len(server.calls)==len(plan['items'])
        assert not truth.query('rc7_defect')
        assert service.audit(release_batch_id=p['release_batch_id'])==result
        assert truth.store.path.read_bytes()==before
    finally:
        server.shutdown();server.server_close()


def test_native_n8_product_consumes_real_repaired_n5_gate_and_driver_admits_new_n7_only(tmp_path,monkeypatch):
    """No synthetic repair marker: real independent N5 physical evidence must exist."""
    from test_rc72_n8_retry_continuation import _whole_inventory_repaired
    from rc7_runtime.rc72_release_driver import ReleaseBatchDriver
    from rc7_runtime.rc72_n7_execution_planning import ExecutionPlanningService
    values=_whole_inventory_repaired(tmp_path,monkeypatch)
    truth,prep,server,original,_,data,_,_,_=values
    try:
        root=tmp_path/'native-n8-resume-accepted'
        runner=FormalN7RunnerAdapter(prep,evidence_root=root,
            environment_adapter=LocalHTTPEnvironment(
                'http://127.0.0.1:%d'%server.server_address[1],root),
            execution_env={'RC72_OUTPUT_ROOT':str(root)},timeout_seconds=30)
        n7=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'native-n8-retry')
        n8=NativeN8ProductRecoveryService(n7)
        old=truth.query('execution_attempt',attempt_id=original['attempt_id'])[0]
        before_business=len(server.calls)
        resumed=n8.complete(release_batch_id=original['release_batch_id'])
        assert resumed['status']=='CONTINUE'
        assert resumed['reason']=='N8_ACCEPTED_N5_REPAIR_N7_RETRY_READY'
        assert resumed['original_attempt_id']==old['attempt_id']
        assert resumed['recovery_plan_id']!=original['plan_id']
        assert truth.query('execution_attempt',attempt_id=original['attempt_id'])[0]==old
        # The real product driver's continuation barrier must see a fresh
        # planner with exact R1 admission and a READY/RUNNING N7.
        driver=object.__new__(ReleaseBatchDriver)
        driver.truth,driver.n7_pipeline=truth,n7
        batch=truth.query('rc72_release_batch',release_batch_id=original['release_batch_id'])[0]
        actual=driver._validated_n8_continue(batch,resumed)
        assert actual['plan_id']==resumed['recovery_plan_id']
        assert actual['recovery_id']
        assert len(server.calls)==before_business
        before=truth.store.path.read_bytes()
        assert n8.complete(release_batch_id=original['release_batch_id'])==resumed
        assert truth.store.path.read_bytes()==before
        assert not truth.query('rc7_defect')
        with pytest.raises(ContractError,match='UNVERIFIED_N8_CONTINUATION'):
            driver._validated_n8_continue(batch,dict(resumed,
                reason='UNKNOWN_CAUSE_CANNOT_RESTART'))
        with pytest.raises(ContractError,match='N8_FRESH_N7_NOT_ADMITTED'):
            driver._validated_n8_continue(batch,dict(resumed,
                recovery_plan_id=original['plan_id']))
        assert truth.store.path.read_bytes()==before and len(server.calls)==before_business
    finally:
        server.shutdown();server.server_close()


@pytest.mark.parametrize('corrupt_recovery',[False,True])
def test_second_real_n7_failure_retains_first_blocked_attempt_but_routes_only_new_generation(
        tmp_path,monkeypatch,corrupt_recovery):
    """A repaired N7 failure is historical truth, not a competing live failure."""
    from test_rc72_n8_retry_continuation import _whole_inventory_repaired
    from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
    from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
    from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
    values=_whole_inventory_repaired(tmp_path,monkeypatch)
    truth,prep,server,original,_,data,_,_,_=values
    try:
        old=truth.query('execution_attempt',attempt_id=original['attempt_id'])[0]
        retry=DataRepairContinuationService(data.boundary.diagnosis)
        second=retry.prepare_replacement(original['preparation_id'])
        assert second['attempt_generation']==original['attempt_generation']+1
        server.allowed_data_refs.clear()  # a *second* observed physical failure
        root=tmp_path/'second-n7-failure'
        runner=FormalN7RunnerAdapter(prep,evidence_root=root,
            environment_adapter=LocalHTTPEnvironment(
                'http://127.0.0.1:%d'%server.server_address[1],root),
            execution_env={'RC72_OUTPUT_ROOT':str(root)},timeout_seconds=30)
        assert SignedToolDispatchService(prep,adapters={'api_http':runner}).dispatch(
            second['preparation_id'])['state']=='FAILED'
        fresh=ExecutionEvidenceService(prep).record(second['preparation_id'])
        assert fresh['status']=='BLOCKED' and fresh['attempt_id']!=old['attempt_id']
        assert truth.query('execution_attempt',attempt_id=old['attempt_id'])[0]==old
        n7=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'n8-second-captures')
        product=NativeN8ProductRecoveryService(n7)
        if corrupt_recovery:
            recovered=truth.query('rc72_diagnosis_recovery')[0]
            truth.append_atomic('RC72_DIAGNOSIS_RECOVERY_UPSERTED',
                dict(recovered,replacement_attempt_id='N7ATT-unrelated',
                    artifact_version=recovered['artifact_version']+1))
            before=truth.store.path.read_bytes()
            with pytest.raises(ContractError,match='N8_PRODUCT_HISTORICAL_FAILURE_UNRESOLVED'):
                product.complete(release_batch_id=original['release_batch_id'])
            assert truth.store.path.read_bytes()==before
            assert not truth.query('rc72_n8_repair_boundary',preparation_id=second['preparation_id'])
            assert not truth.query('rc7_defect')
        else:
            result=product.complete(release_batch_id=original['release_batch_id'])
            assert result['reason']=='N8_VERIFIED_N5_REPAIR_REQUIRED'
            assert result['preparation_id']==second['preparation_id']
            assert result['failure_class']=='TEST_DATA_GAP'
            assert len(truth.query('rc72_diagnosis_case'))==2
            assert len(truth.query('execution_attempt'))==2
            assert truth.query('execution_attempt',attempt_id=old['attempt_id'])[0]==old
            assert truth.query('rc72_n8_repair_boundary',preparation_id=second['preparation_id'])[0]['state']=='REPAIR_OPEN'
            before=truth.store.path.read_bytes()
            assert product.complete(release_batch_id=original['release_batch_id'])==result
            assert truth.store.path.read_bytes()==before
            assert not truth.query('rc7_defect')
        assert server.calls==[]
    finally:
        server.shutdown();server.server_close()
