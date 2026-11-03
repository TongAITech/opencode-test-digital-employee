"""Measure real MCP model payload reduction while preserving all policy data."""
import json
import pytest
from test_rc72_expected_scope_input import _setup
import test_rc72_n1_completion as original
from rc7_runtime.rc72_native_n1_read_gate import NativeN1ReadGate


def _observe(monkeypatch):
    observations=[]
    original_result=NativeN1ReadGate._child_result
    def result(gate,row):
        value=original_result(gate,row)
        observations.append((row,value))
        return value
    monkeypatch.setattr(NativeN1ReadGate,'_child_result',result)
    return observations


def test_large_original_catalog_is_retained_but_not_echoed_into_n1_model(tmp_path,monkeypatch,record_property):
    ssts=['EXPECTED-SST-%04d'%i for i in range(320)]
    def large(policy):
        requirement=next(iter(policy['requirement_ssts']))
        policy['requirement_ssts']={requirement:ssts}
        policy['required_levels_by_sst']={s:['L1','L2','L3','L4','L5','L6','L7'] for s in ssts}
    truth,pipeline,scope,calls,source=_setup(tmp_path,mutate=large)
    observed=_observe(monkeypatch)
    raw=source.read_text()
    pipeline.complete(release_batch_id=original.BATCH)
    scope.freeze(release_batch_id=original.BATCH)
    row,value=next((r,v) for r,v in observed if r['source_ref']=='release-batch://'+original.BATCH)
    view=value['result']
    assert 'text' not in view and view['projection']=='RC72_EXPECTED_SCOPE_METADATA_V1'
    assert view['expected_sst_count']==320 and view['expected_required_level_count']==2240
    assert row['result']['text']==raw
    manifest=truth.query('rc72_release_scope_manifest')[0]
    assert manifest['requirement_ssts'][next(iter(manifest['requirement_ssts']))]==ssts
    assert set(manifest['required_levels_by_sst'])==set(ssts)
    assert sum(len(v) for v in manifest['required_levels_by_sst'].values())==2240
    # This is the actual serialization used for MCP text content, not a token
    # or billing estimate. The ordinary N1 candidate input still returns text.
    sent=len(json.dumps(view,sort_keys=True).encode())
    full=len(json.dumps(row['result'],sort_keys=True).encode())
    assert sent*10<full
    assert any('text' in v['result'] for r,v in observed if r['source_ref']!='release-batch://'+original.BATCH)
    assert len(calls)==1 and not truth.query('rc72_test_obligation')
    record_property('actual_mcp_content_bytes',sent)
    record_property('unprojected_mcp_content_bytes',full)
    record_property('preserved_expected_ssts',320)
    record_property('preserved_expected_levels',2240)
    record_property('provider_token_usage','UNKNOWN')


def test_invalid_original_policy_returns_diagnostic_without_suppressing_import_rejection(tmp_path,monkeypatch):
    truth,pipeline,scope,calls,source=_setup(tmp_path,mutate=lambda policy:policy.update(version_ids=['FOREIGN-VERSION']))
    observed=_observe(monkeypatch)
    pipeline.complete(release_batch_id=original.BATCH)
    row,value=next((r,v) for r,v in observed if r['source_ref']=='release-batch://'+original.BATCH)
    assert value['result']['policy_error']=='EXPECTED_SCOPE_VERSION_DENOMINATOR_MISMATCH'
    assert row['state']=='RETURNED' and row['result']['text']==source.read_text()
    assert 'text' not in value['result']
    before=truth.store.path.read_bytes()
    with pytest.raises(Exception,match='VERSION_DENOMINATOR_MISMATCH'):scope.freeze(release_batch_id=original.BATCH)
    assert truth.store.path.read_bytes()==before and not truth.query('rc72_release_scope_manifest')
