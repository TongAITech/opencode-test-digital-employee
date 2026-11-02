"""Each check runs in a fresh interpreter without test warm-up imports."""
import subprocess
import sys
import textwrap

import pytest


def _cold(script):
    result = subprocess.run(
        [sys.executable, '-c', textwrap.dedent(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('module,types', [
    ('rc72_n2_requirement_handoff', ['rc72_n2_requirement_attempt']),
    ('rc72_n5_data_verification_finalization',
     ['rc72_n5_data_verification_result', 'rc72_data_resource']),
    ('rc72_n6_completion', ['rc72_n2_requirement_attempt',
     'rc72_n5_data_verification_result', 'rc72_data_resource']),
])
def test_service_cold_start_has_complete_schema(module, types):
    _cold('''
        import importlib
        import tempfile
        from pathlib import Path
        importlib.import_module('rc7_runtime.' + %r)
        from rc6_runtime.truth import TruthRuntime, EVENT_TYPES, BUCKETS, IDENTITY_FIELDS
        from rc6_runtime.contracts import VALIDATORS
        with tempfile.TemporaryDirectory() as directory:
            runtime = TruthRuntime(Path(directory) / 'r1.jsonl')
            for kind in %r:
                assert kind in VALIDATORS and kind in IDENTITY_FIELDS
                assert any(item[0] == kind for item in EVENT_TYPES.values())
                assert runtime.query(kind) == []
                assert runtime.projection.history(kind, 'missing') == []
                assert hasattr(runtime.projection, BUCKETS[kind])
    ''' % (module, types))


def test_projection_created_before_rc72_registration_can_apply_and_replay():
    _cold('''
        from rc6_runtime.truth import Projection
        projection = Projection()
        assert not hasattr(projection, 'rc72_decomposition_snapshots')
        from rc7_runtime.rc72_decomposition_truth import install_rc72_decomposition_truth_overlay
        install_rc72_decomposition_truth_overlay()
        payload = dict(snapshot_id='S-1', mission_id='M-1', release_batch_id='RB-1',
                       current_node='N4_TEST_DESIGN', config_version='v1', release_id='R-1',
                       created_at=1, artifact_version=1)
        for field in ('obligation_ids', 'case_ids', 'completed_case_ids', 'etu_ids',
                      'planning_cases', 'coverage_gaps', 'execution_history',
                      'planning_signals', 'coverage_routes'):
            payload[field] = []
        for field in ('priority_weights', 'obligation_priorities',
                      'priority_explanations', 'replan_reasons'):
            payload[field] = {}
        event = dict(event_type='RC72_DECOMPOSITION_SNAPSHOT_UPSERTED', payload=payload)
        projection.apply_atomic(event)
        projection.apply_atomic(event)
        assert len(projection.query('rc72_decomposition_snapshot')) == 1
        assert len(projection.history('rc72_decomposition_snapshot', 'S-1')) == 1
        assert projection.get('rc72_decomposition_snapshot', 'S-1')['snapshot_id'] == 'S-1'
        assert projection.full_inventory()['rc72_decomposition_snapshot'] == 1
        assert len(projection.snapshot()['rc72_decomposition_snapshots']) == 1
    ''')


def test_bootstrap_is_idempotent_and_unknown_events_stay_closed():
    _cold('''
        import tempfile
        from pathlib import Path
        from rc7_runtime.rc72_truth_bootstrap import bootstrap_rc72_truth
        from rc6_runtime import truth, contracts
        def registry():
            return (dict(truth.EVENT_TYPES), dict(truth.BUCKETS),
                    dict(truth.IDENTITY_FIELDS), dict(contracts.VALIDATORS))
        bootstrap_rc72_truth()
        before = registry()
        bootstrap_rc72_truth()
        assert registry() == before
        with tempfile.TemporaryDirectory() as directory:
            runtime = truth.TruthRuntime(Path(directory) / 'r1.jsonl')
            for operation, error in (
                (lambda: runtime.append_atomic('RC72_UNKNOWN_UPSERTED', {}), truth.EventValidationError),
                (lambda: runtime.projection.apply_atomic(dict(event_type='RC72_UNKNOWN_UPSERTED', payload={})), truth.ProjectionIntegrityError),
                (lambda: runtime.query('rc72_unknown'), truth.ProjectionIntegrityError),
                (lambda: runtime.projection.history('rc72_unknown', 'x'), truth.ProjectionIntegrityError),
            ):
                try:
                    operation()
                except error:
                    pass
                else:
                    raise AssertionError('unknown type accepted')
            assert list(runtime.store.iter_raw()) == []
            assert 'rc72_unknown' not in runtime.projection._versions
    ''')
