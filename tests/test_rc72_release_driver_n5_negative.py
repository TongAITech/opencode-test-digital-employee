"""A negative actual verifier result closes work for repair, never data PASS."""
from test_rc72_release_driver_n5 import _n5_driver
from rc72_n2_test_support import BATCH


def test_independent_negative_data_results_retain_full_scope_and_never_open_n6(tmp_path):
    truth,driver,calls = _n5_driver(tmp_path,negative=True)
    result = driver.run(release_batch_id=BATCH)
    assert result['status']=='HOLD' and result['reason']=='N5_INDEPENDENT_VERIFICATION_NOT_ACCEPTED'
    rows = truth.query('rc72_n5_data_discovery_dispatch')
    required = {r['data_requirement_id'] for r in rows}
    assert {c[1] for c in calls if isinstance(c,tuple) and c[0]=='data-discover'}==required
    assert {c[1] for c in calls if isinstance(c,tuple) and c[0]=='data-verify'}==required
    assert not truth.query('rc72_n5_data_binding') and not truth.query('rc72_data_lease')
    assert all(truth.query('rc7_task',task_id=r['workitem_id'])[0]['state']=='REPAIR_REQUIRED' for r in rows)
    assert len(truth.query('rc7_gap',category='TEST_DATA_GAP'))==len(required)
    repairs = truth.query('rc7_task',node='TEST_DATA',task_type='REPAIR')
    assert len(repairs)==len(required) and all(t['required_capabilities']==['test_data'] for t in repairs)
    assert truth.query('rc72_mission_node',node_type='N6_EXECUTABLE_READINESS')[0]['state']=='NOT_STARTED'
    count = len(calls)
    before = truth.store.path.read_bytes()
    assert driver.run(release_batch_id=BATCH)==result
    assert len(calls)==count and truth.store.path.read_bytes()==before
