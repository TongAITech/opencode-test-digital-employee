"""Full validation and collision checks survive removal of duplicate replay work."""
from copy import deepcopy
import json

import pytest
from rc6_runtime import truth as module
from rc6_runtime.truth import TruthRuntime,ProjectionIntegrityError
from test_truth_layer import make_intent


def test_every_replayed_payload_is_fully_validated_once_and_snapshot_is_optional(tmp_path,monkeypatch):
    runtime=TruthRuntime(tmp_path/'r1.jsonl')
    runtime.append_atomic('TEST_INTENT_UPSERTED',make_intent(1))
    runtime.append_atomic('TEST_INTENT_UPSERTED',make_intent(2))
    expected=runtime.projection.snapshot()
    validate=module._canonical_payload
    observed=[]
    def checked(event,payload):
        observed.append(payload['id'])
        return validate(event,payload)
    monkeypatch.setattr(module,'_canonical_payload',checked)
    assert runtime.rebuild_projection(include_snapshot=False) is None
    assert observed==['INT-01','INT-02']
    assert runtime.projection.snapshot()==expected
    observed.clear()
    assert runtime.rebuild_projection()==expected
    assert observed==['INT-01','INT-02']


def test_forged_event_metadata_does_not_bypass_payload_validation_or_replace_good_projection(tmp_path):
    runtime=TruthRuntime(tmp_path/'r1.jsonl')
    runtime.append_atomic('TEST_INTENT_UPSERTED',make_intent(1))
    before=runtime.projection.snapshot()
    event=next(runtime.store.iter_raw())
    event['payload']['objective']=None
    event['entity_type']='test_intent'
    event['entity_id']='INT-01'
    event['entity_version']=1
    with runtime.store.path.open('a',encoding='utf-8') as out:
        out.write(json.dumps(event)+'\n')
    with pytest.raises(ProjectionIntegrityError):
        runtime.rebuild_projection(include_snapshot=False)
    assert runtime.projection.snapshot()==before


def test_conflicting_same_version_is_not_hidden_by_validated_fast_path(tmp_path):
    runtime=TruthRuntime(tmp_path/'r1.jsonl')
    runtime.append_atomic('TEST_INTENT_UPSERTED',make_intent(1))
    before=runtime.projection.snapshot()
    event=deepcopy(next(runtime.store.iter_raw()))
    event['payload']['objective']='conflicting same-version intent'
    with runtime.store.path.open('a',encoding='utf-8') as out:
        out.write(json.dumps(event)+'\n')
    with pytest.raises(ProjectionIntegrityError,match='CONFLICTING_SAME_ENTITY_VERSION'):
        runtime.rebuild_projection(include_snapshot=False)
    assert runtime.projection.snapshot()==before
