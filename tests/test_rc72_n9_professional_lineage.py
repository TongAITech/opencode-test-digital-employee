"""Real N7 business mismatch -> signed N8 N9 route must be complete.

A modified/absent semantic route is *not* permission to schedule independent
business RCA; denial must be read-only and must never repeat the HTTP call.
"""
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n9_professional_intake import NativeN9ProfessionalIntakeService
from rc72_n2_test_support import BATCH
from test_rc72_conclusive_failure_evidence import _failed_business


@pytest.mark.parametrize('tamper', [
    'back_edge_missing', 'transition_missing', 'back_edge_target',
    'transition_target', 'gap_description',
])
def test_real_n9_qualification_refuses_broken_n8_semantic_route_readonly(
        tmp_path, monkeypatch, tamper):
    truth, plan, prep, server, url, pipeline = _failed_business(tmp_path, monkeypatch)
    try:
        first = pipeline.complete(release_batch_id=BATCH)
        assert first['failure_class'] == 'VALID_TEST_FAILURE'
        assert len(server.calls) == 1
        original = truth.query
        outcome = original('rc72_diagnosis_outcome')[0]
        diagnosis = original('rc72_diagnosis_case')[0]
        preparation = original('rc72_n7_execution_preparation')[0]
        assert original('rc72_back_edge',back_edge_id=outcome['back_edge_id'])
        assert original('rc72_node_transition',transition_id=outcome['transition_id'])

        def changed(artifact_kind, **filters):
            rows = original(artifact_kind, **filters)
            if artifact_kind == 'rc72_back_edge' and filters.get('back_edge_id') == outcome['back_edge_id']:
                if tamper == 'back_edge_missing':
                    return []
                if tamper == 'back_edge_target':
                    return [dict(rows[0],return_node='N2_REQUIREMENT')]
            if artifact_kind == 'rc72_node_transition' and filters.get('transition_id') == outcome['transition_id']:
                if tamper == 'transition_missing':
                    return []
                if tamper == 'transition_target':
                    return [dict(rows[0],to_mission_node_id='N9-FOREIGN-NODE')]
            if artifact_kind == 'rc7_gap' and filters.get('gap_id') == outcome['gap_id']:
                if tamper == 'gap_description':
                    return [dict(rows[0],description='Rewritten to bypass cause analysis')]
            return rows

        monkeypatch.setattr(truth, 'query', changed)
        saved = truth.store.path.read_bytes()
        intake = NativeN9ProfessionalIntakeService(pipeline)
        with pytest.raises(ContractError, match='N9_PROFESSIONAL_(R1_NOT_UNIQUE|SEMANTIC_ROUTE)'):
            intake.queue_reproduction(
                preparation_id=preparation['preparation_id'],
                diagnosis_id=diagnosis['diagnosis_id'])
        assert truth.store.path.read_bytes() == saved
        assert len(server.calls) == 1
        assert original('rc7_defect') == []
    finally:
        server.shutdown()
        server.server_close()


def test_real_n9_qualification_accepts_original_signed_route_without_new_effect(
        tmp_path, monkeypatch):
    truth, plan, prep, server, url, pipeline = _failed_business(tmp_path, monkeypatch)
    try:
        first = pipeline.complete(release_batch_id=BATCH)
        prep_id = truth.query('rc72_n7_execution_preparation')[0]['preparation_id']
        diag_id = truth.query('rc72_diagnosis_case')[0]['diagnosis_id']
        before = truth.store.path.read_bytes()
        current = NativeN9ProfessionalIntakeService(pipeline).queue_reproduction(
            preparation_id=prep_id, diagnosis_id=diag_id)
        assert current['qualification_workitem_id'] == first['qualification_workitem_id']
        assert current['defect_confirmed'] is False
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()
