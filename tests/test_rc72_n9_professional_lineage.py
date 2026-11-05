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


@pytest.mark.parametrize('tamper', [
    'replaced_active_generation', 'old_delivery_ref', 'missing_delivery',
    'duplicate_delivery', 'foreign_delivery_mission', 'foreign_gate_node',
    'swapped_active_delivery',
])
def test_real_n9_current_delivery_gate_rejects_stale_or_forged_r1_without_io(
        tmp_path, monkeypatch, tamper):
    """Exercise the exact production gate using an actual signed N8 diagnosis."""
    truth, plan, prep, server, url, pipeline = _failed_business(tmp_path, monkeypatch)
    try:
        result = pipeline.complete(release_batch_id=BATCH)
        assert result['failure_class'] == 'VALID_TEST_FAILURE'
        assert len(server.calls) == 1
        original = truth.query
        receipt = original('rc72_n8_process_diagnosis')[0]
        node = original('rc72_mission_node', node_type='N8_DIAGNOSIS_RECOVERY')[0]
        gate = next(g for g in original('rc72_node_gate',
                    mission_node_id=node['mission_node_id'])
                    if g['delivery_id'] == receipt['delivery_id'])
        delivery = original('rc72_node_delivery', mission_node_id=node['mission_node_id'])[0]
        intake = NativeN9ProfessionalIntakeService(pipeline)
        assert delivery['version'] == node['active_delivery_version']
        # Positive control must come from the same local HTTP failure and
        # real signed N8 process/reviewer, not a fabricated PASS row.
        intake._assert_current_n8_delivery(node, receipt, gate, node['mission_id'])
        before = truth.store.path.read_bytes()

        altered_node = dict(node)
        altered_gate = dict(gate)
        if tamper == 'replaced_active_generation':
            altered_node['active_delivery_version'] += 1
        elif tamper == 'old_delivery_ref':
            altered_node['delivery_refs'] = ['N8-OLD-DELIVERY']
        elif tamper == 'foreign_gate_node':
            altered_gate['mission_node_id'] = 'N8-FOREIGN-NODE'

        def changed(artifact_kind, **filters):
            rows = original(artifact_kind, **filters)
            if (artifact_kind == 'rc72_node_delivery'
                    and filters.get('mission_node_id') == node['mission_node_id']):
                if tamper == 'missing_delivery':
                    return []
                if tamper == 'duplicate_delivery':
                    return rows + rows
                if tamper == 'foreign_delivery_mission':
                    return [dict(row, mission_id='MISSION-FOREIGN') for row in rows]
                if tamper == 'swapped_active_delivery':
                    return [dict(row, delivery_id='N8-OLD-DELIVERY') for row in rows]
            return rows

        monkeypatch.setattr(truth, 'query', changed)
        with pytest.raises(ContractError, match='N9_PROFESSIONAL_CURRENT_N8_DELIVERY'):
            intake._assert_current_n8_delivery(
                altered_node, receipt, altered_gate, node['mission_id'])
        assert truth.store.path.read_bytes() == before
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
