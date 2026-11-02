"""Real legacy binding finalization alone cannot complete the product node."""
import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n5_workitem_acceptance import N5WorkItemFinalizer
from test_rc72_release_driver_n5 import _n5_driver
from rc72_n2_test_support import BATCH


def test_verified_bindings_cannot_hide_open_work_and_resume_accepts_without_workers(tmp_path,monkeypatch):
    truth,driver,calls = _n5_driver(tmp_path)
    original = N5WorkItemFinalizer.finalize
    monkeypatch.setattr(N5WorkItemFinalizer,'finalize',lambda self,**scope:self.finalizer.finalize(**scope))
    with pytest.raises(ContractError,match='OWNED_WORKITEM_NOT_ACCEPTED'):
        driver.run(release_batch_id=BATCH)
    assert truth.query('rc72_n5_data_binding')
    assert all(p['status']=='REUSE_VERIFIED' for p in truth.query('rc72_n5_data_resolution_plan'))
    assert all(t['state']=='OUTPUT_PRODUCED' for t in truth.query('rc7_task',node='TEST_DATA'))
    assert not truth.query('rc72_node_delivery',node_type='N5_TEST_DATA')
    assert truth.query('rc72_mission_node',node_type='N6_EXECUTABLE_READINESS')[0]['state']=='NOT_STARTED'
    monkeypatch.setattr(N5WorkItemFinalizer,'finalize',original)
    count=len(calls)
    result=driver.run(release_batch_id=BATCH)
    assert result['reason']=='N6_APPROVED_INPUTS_INCOMPLETE'
    assert all(t['state']=='PASS' for t in truth.query('rc7_task',node='TEST_DATA'))
    assert truth.query('rc72_mission_node',node_type='N6_EXECUTABLE_READINESS')[0]['state']=='READY'
    assert len(calls)==count
