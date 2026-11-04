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
