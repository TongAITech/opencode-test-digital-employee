"""One full workflow interrupted at three separate durable native boundaries."""
import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_n5_workitem_acceptance import N5WorkItemFinalizer
from test_rc72_release_driver_n5 import _n5_driver
from rc72_n2_test_support import BATCH


def test_partial_finalization_replan_and_delivery_resume_without_repeating_workers(tmp_path, monkeypatch):
    truth,driver,calls = _n5_driver(tmp_path)
    original_final = N5WorkItemFinalizer.finalize
    hit = []
    def after_first_owned(self, **scope):
        result = original_final(self, **scope)
        if not hit:
            hit.append(True)
            raise OSError('interrupted after first accepted data WorkItem')
        return result
    monkeypatch.setattr(N5WorkItemFinalizer,'finalize',after_first_owned)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert len(truth.query('rc72_n5_data_binding'))==1
    first = next(item[1] for item in calls if isinstance(item,tuple))
    monkeypatch.setattr(N5WorkItemFinalizer,'finalize',original_final)

    def cold_resume():
        cold = TruthRuntime(driver.truth.store.path)
        driver.truth = cold
        for pipeline in (driver.n3_pipeline,driver.n4_pipeline,driver.n5_pipeline):
            pipeline.truth = cold
        for launcher in (driver.n1_launcher,driver.n2_launcher,driver.n2_evaluator.launcher)+driver.n3_pipeline.launchers+driver.n4_pipeline.launchers+driver.n5_pipeline.launchers:
            launcher.truth = cold
        return cold
    cold = cold_resume()
    append = cold.append_atomic
    stages = []
    def interrupt_replan(kind,payload,**kwargs):
        result = append(kind,payload,**kwargs)
        if kind=='RC72_N5_DATA_RESOLUTION_PLAN_UPSERTED' and payload['status']=='REUSE_VERIFIED' and not stages:
            stages.append('replanned-one')
            raise OSError('interrupted after first re-planned verified binding')
        return result
    monkeypatch.setattr(cold,'append_atomic',interrupt_replan)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert stages==['replanned-one']
    assert sum(p['status']=='REUSE_VERIFIED' for p in cold.query('rc72_n5_data_resolution_plan'))==1
    worker_count = len(calls)
    cold = cold_resume()
    append = cold.append_atomic
    def interrupt_gate(kind,payload,**kwargs):
        result = append(kind,payload,**kwargs)
        if kind=='RC72_MISSION_NODE_UPSERTED' and payload['node_type']=='N5_TEST_DATA' and payload['state']=='REVIEW_PENDING':
            raise OSError('interrupted after formal Delivery before Gate')
        return result
    monkeypatch.setattr(cold,'append_atomic',interrupt_gate)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert cold.query('rc72_mission_node',node_type='N5_TEST_DATA')[0]['state']=='REVIEW_PENDING'
    assert len(calls)==worker_count
    cold = cold_resume()
    result = driver.run(release_batch_id=BATCH)
    assert result['reason']=='N6_APPROVED_INPUTS_INCOMPLETE'
    assert cold.query('rc72_mission_node',node_type='N5_TEST_DATA')[0]['state']=='PASS'
    assert cold.query('rc72_mission_node',node_type='N6_EXECUTABLE_READINESS')[0]['state']=='READY'
    assert len(calls)==worker_count
    assert sum(item==('data-discover',first) for item in calls)==1
    assert sum(item==('data-verify',first) for item in calls)==1
    assert all(t['state']=='PASS' for t in cold.query('rc7_task',node='TEST_DATA'))
