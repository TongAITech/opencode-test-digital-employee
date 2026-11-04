"""C08 CLI must reject incomplete N1-N10 denominators even under optimistic producer status."""
import pytest

from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc7_release.rc72_mission_cli import _accepted_ten_node_completion


def _full():
    return [dict(node_type=node.value, state='PASS')
            for node in AutonomousMissionNode.ordered()]


def test_complete_ten_node_set_only_accepts_all_pass():
    nodes = _full()
    assert len(nodes) == 10
    assert _accepted_ten_node_completion(nodes) is True
    assert _accepted_ten_node_completion(list(reversed(nodes))) is True


@pytest.mark.parametrize('mutation', [
    'no_n8', 'no_n9', 'no_n10', 'duplicate_n7',
    'unknown_node', 'blocked_n7', 'human_gate_n10', 'missing_state',
    'empty', 'non_list', 'nondict',
])
def test_missing_extra_or_nonpass_nodes_never_support_cli_mission_pass(mutation):
    rows = _full()
    if mutation.startswith('no_n'):
        target = 'N' + mutation.split('_n', 1)[1] + '_'
        rows = [row for row in rows if not row['node_type'].startswith(target)]
    elif mutation == 'duplicate_n7':
        rows[-1] = dict(rows[6])
    elif mutation == 'unknown_node':
        rows[-1] = dict(node_type='N11_UNKNOWN', state='PASS')
    elif mutation == 'blocked_n7':
        rows[6]['state'] = 'BLOCKED'
    elif mutation == 'human_gate_n10':
        rows[9]['state'] = 'HUMAN_GATE'
    elif mutation == 'missing_state':
        del rows[9]['state']
    elif mutation == 'empty':
        rows = []
    elif mutation == 'non_list':
        rows = tuple(rows)
    elif mutation == 'nondict':
        rows[-1] = 'N10_RELEASE_CONVERGENCE'
    assert _accepted_ten_node_completion(rows) is False


def _bypassed_n8():
    rows = _full()
    for row in rows:
        row['mission_id'] = 'MISSION-BYPASS'
        row['mission_node_id'] = 'NODE-' + row['node_type']
        row['gate_refs'] = ['GATE-' + row['node_type']]
        row['delivery_refs'] = ['DELIVERY-' + row['node_type']]
        row['active_delivery_version'] = 1
    n8 = next(row for row in rows if row['node_type'] == 'N8_DIAGNOSIS_RECOVERY')
    n8.update(state='NOT_STARTED', gate_refs=[], delivery_refs=[],
              active_delivery_version=None)
    edge = dict(mission_id='MISSION-BYPASS', kind='FORWARD',
        from_node_type='N7_EXECUTION', to_node_type='N9_DEFECT',
        from_mission_node_id='NODE-N7_EXECUTION',
        to_mission_node_id='NODE-N9_DEFECT',
        source_gate_id='GATE-N7_EXECUTION')
    return rows, edge


def test_valid_n7_forward_n9_must_not_require_synthetic_n8_pass():
    rows, edge = _bypassed_n8()
    assert _accepted_ten_node_completion(rows, transitions=[edge]) is True
    assert _accepted_ten_node_completion(list(reversed(rows)), transitions=[edge]) is True
    assert _accepted_ten_node_completion(rows) is False
    assert _accepted_ten_node_completion(rows, transitions=[]) is False


@pytest.mark.parametrize('corruption', [
    'foreign_mission', 'wrong_gate', 'wrong_origin_node', 'wrong_target_node',
    'back_edge', 'wrong_source_type', 'wrong_target_type', 'stale_n8_gate',
    'n9_not_pass', 'missing_n7_gate', 'n8_missing', 'untrusted_edge',
])
def test_n8_bypass_rejects_wrong_or_missing_signed_forward_route(corruption):
    rows, edge = _bypassed_n8()
    n8 = next(r for r in rows if r['node_type'] == 'N8_DIAGNOSIS_RECOVERY')
    n7 = next(r for r in rows if r['node_type'] == 'N7_EXECUTION')
    n9 = next(r for r in rows if r['node_type'] == 'N9_DEFECT')
    if corruption == 'foreign_mission':
        edge['mission_id'] = 'OTHER'
    elif corruption == 'wrong_gate':
        edge['source_gate_id'] = 'GATE-OLD'
    elif corruption == 'wrong_origin_node':
        edge['from_mission_node_id'] = 'NODE-N1_REALITY'
    elif corruption == 'wrong_target_node':
        edge['to_mission_node_id'] = 'NODE-N10_RELEASE_CONVERGENCE'
    elif corruption == 'back_edge':
        edge['kind'] = 'BACK_EDGE'
    elif corruption == 'wrong_source_type':
        edge['from_node_type'] = 'N6_EXECUTABLE_READINESS'
    elif corruption == 'wrong_target_type':
        edge['to_node_type'] = 'N8_DIAGNOSIS_RECOVERY'
    elif corruption == 'stale_n8_gate':
        n8['gate_refs'] = ['GATE-N8']
    elif corruption == 'n9_not_pass':
        n9['state'] = 'REVIEW_PENDING'
    elif corruption == 'missing_n7_gate':
        n7['gate_refs'] = []
    elif corruption == 'n8_missing':
        rows.remove(n8)
    elif corruption == 'untrusted_edge':
        edge = 'N7-N9'
    assert _accepted_ten_node_completion(rows, transitions=[edge]) is False
