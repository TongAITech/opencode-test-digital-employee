"""Native N6 partial contract/delivery recovery on one complete product flow."""
from rc72_pip_field_test_support import provider as prior_field_provider
import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_n6_executable_readiness import EVENT_N6_EXECUTABLE_CONTRACT_COMPILED
from test_rc72_release_driver_n5 import _n5_driver
from rc72_n2_test_support import BATCH


def test_n6_contract_and_delivery_interruptions_resume_without_upstream_workers(tmp_path,monkeypatch):
    truth,driver,calls = _n5_driver(tmp_path,materialized=True)
    append=truth.append_atomic
    hit=[]
    def first_contract(kind,payload,**kwargs):
        result=append(kind,payload,**kwargs)
        if kind==EVENT_N6_EXECUTABLE_CONTRACT_COMPILED and not hit:
            hit.append(True)
            raise OSError('interrupted after first compiled contract fsync')
        return result
    monkeypatch.setattr(truth,'append_atomic',first_contract)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert hit and len(truth.query('rc72_n6_executable_contract'))==1
    assert truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='NOT_STARTED'
    count=len(calls)
    def cold_resume():
        cold=TruthRuntime(truth.store.path)
        driver.truth=cold
        driver.bank_pip_mirror=prior_field_provider(cold,release_batch_id=BATCH,source_commit=driver.source_commit)
        for pipeline in (driver.n3_pipeline,driver.n4_pipeline,driver.n5_pipeline):
            pipeline.truth=cold
        for launcher in (driver.n1_launcher,driver.n2_launcher,driver.n2_evaluator.launcher)+driver.n3_pipeline.launchers+driver.n4_pipeline.launchers+driver.n5_pipeline.launchers:
            launcher.truth=cold
        return cold
    cold=cold_resume()
    append=cold.append_atomic
    def after_delivery(kind,payload,**kwargs):
        result=append(kind,payload,**kwargs)
        if kind=='RC72_MISSION_NODE_UPSERTED' and payload['node_type']=='N6_EXECUTABLE_READINESS' and payload['state']=='REVIEW_PENDING':
            raise OSError('interrupted after N6 Delivery before Gate')
        return result
    monkeypatch.setattr(cold,'append_atomic',after_delivery)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert len(calls)==count
    contract_ids={c['contract_id'] for c in cold.query('rc72_n6_executable_contract')}
    assert cold.query('rc72_mission_node',node_type='N6_EXECUTABLE_READINESS')[0]['state']=='REVIEW_PENDING'
    cold=cold_resume()
    result=driver.run(release_batch_id=BATCH)
    assert result['reason']=='NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    assert cold.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='READY'
    assert {c['contract_id'] for c in cold.query('rc72_n6_executable_contract')}==contract_ids
    assert len(calls)==count and not cold.query('rc72_data_lease')
