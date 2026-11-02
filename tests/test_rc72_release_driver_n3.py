"""Native N1-N3 composition; child workers are engineering protocol adapters."""
import json
import subprocess
import sys

import pytest
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n3_pipeline import N3PipelineService
from rc7_runtime.dsh_code_evaluator import DshCodeEvaluator
from test_rc72_release_driver import _driver
from test_rc72_n3_source_target_handoff import _candidate as source_candidate
from test_rc72_n3_completion import _canonical_candidate
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE


def _n3_driver(tmp_path, *, source_gap=False, two_targets=False, code_gap=False):
    truth, driver, calls = _driver(tmp_path)
    script = tmp_path / 'n3-protocol-worker.py'
    script.write_text('import sys,json,uuid\n'
        'print(json.dumps(dict(type="session",session_id="session-n3-product-"+uuid.uuid4().hex)))\n'
        'for name in json.loads(sys.argv[2]): print(json.dumps(dict(type="tool_call",tool_name=name)))\n'
        'print(json.dumps(dict(type="final",text=sys.argv[1])))\n')
    patch = tmp_path / 'n3-patch.json'
    patch.write_text('{}')
    targets = source_candidate('BLOAN')['targets']
    if two_targets:
        targets.append(dict(target_id='SRC-TARGET-BLOAN-SECOND', repository_ref='git://repo/BLOAN_SECOND',
            source_revision='b'*40, evidence_refs=['tool://source-target-probe/BLOAN_SECOND']))
    def launcher(role, tools):
        def run(command, **kwargs):
            prompt = command[-1]
            if role == 'source':
                candidate = source_candidate('BLOAN', targets=targets,
                    gaps=['unresolved repository identity'] if source_gap else [])
            elif role == 'source-review':
                candidate = dict(decision='PASS', reviewed_target_ids=[t['target_id'] for t in targets],
                    gap_ids=[], summary='independent mapping review')
            elif role == 'code':
                truth.rebuild_projection()
                rows = truth.query('rc72_n3_code_analysis_assignment')
                row = next(row for row in rows if '"target_id": "%s"' % row['target_id'] in prompt)
                candidate = _canonical_candidate(row)
                if code_gap:
                    candidate['symbol_explanations'][0]['impact_surfaces'] = []
            else:
                candidate = dict(decision='PASS', gap_ids=[], summary='independent full impact review')
            calls.append(role)
            return subprocess.run([sys.executable, str(script), json.dumps(candidate), json.dumps(tools)], **kwargs)
        return DshHeadlessWorkerLauncher(dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
            truth=truth, authority=RC72AuthorityRuntime(('engineering-n3-product-'+role).encode()),
            coordinator_instance_id='n3-product-controller', release_id=RELEASE,
            state_root=str(tmp_path / ('runtime-'+role)), command_runner=run)
    source = launcher('source', ['source-target-probe'])
    source_review = launcher('source-review', ['source-target-probe'])
    code = launcher('code', ['git', 'codegraph'])
    evaluator = DshCodeEvaluator(launcher('code-review', ['git', 'codegraph']), reviewer_allowed_tools=['git', 'codegraph'])
    driver.n3_pipeline = N3PipelineService(truth, source_commit=COMMIT,
        source_launcher=source, source_tools=['source-target-probe'], source_reviewer=source_review,
        source_review_tools=['source-target-probe'], code_launcher=code, code_tools=['git', 'codegraph'], code_evaluator=evaluator)
    return truth, driver, calls


@pytest.mark.parametrize('two_targets', [False, True])
def test_driver_runs_all_discovered_targets_and_independent_code_gate(tmp_path, two_targets):
    truth, driver, calls = _n3_driver(tmp_path, two_targets=two_targets)
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    states = {n['node_type']: n['state'] for n in result['nodes']}
    assert states['N3_CODE_ANALYSIS'] == 'PASS' and states['N4_TEST_DESIGN'] == 'READY'
    count = 2 if two_targets else 1
    assert calls == ['n1', 'n2', 'review', 'n2', 'review', 'source', 'source-review'] + ['code', 'code-review']*count
    assert len(truth.query('rc72_n3_code_analysis_attempt')) == count
    before = truth.store.path.read_bytes()
    assert driver.run(release_batch_id=BATCH) == result
    assert truth.store.path.read_bytes() == before and len(calls) == 7+2*count


def test_unresolved_source_mapping_never_launches_code_or_opens_n4(tmp_path):
    truth, driver, calls = _n3_driver(tmp_path, source_gap=True)
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'N3_SOURCE_MAPPING_NOT_ACCEPTED'
    assert calls == ['n1', 'n2', 'review', 'n2', 'review', 'source']
    assert not truth.query('rc72_n3_code_analysis_attempt')
    assert truth.query('rc72_mission_node', node_type='N4_TEST_DESIGN')[0]['state'] == 'NOT_STARTED'
    before = truth.store.path.read_bytes()
    assert driver.run(release_batch_id=BATCH) == result
    assert truth.store.path.read_bytes() == before and len(calls) == 6


def test_incomplete_code_impact_cannot_pass_and_other_targets_still_execute(tmp_path):
    truth, driver, calls = _n3_driver(tmp_path, two_targets=True, code_gap=True)
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'NATIVE_NODE_GATE_NOT_PASS'
    assert calls == ['n1', 'n2', 'review', 'n2', 'review', 'source', 'source-review', 'code', 'code-review', 'code', 'code-review']
    assert truth.query('rc72_mission_node', node_type='N3_CODE_ANALYSIS')[0]['state'] == 'NEEDS_REVISION'
    assert truth.query('rc72_mission_node', node_type='N4_TEST_DESIGN')[0]['state'] == 'NOT_STARTED'


@pytest.mark.parametrize('stage', ['source-review', 'code-assignment', 'code-review'])
def test_cold_resume_after_promotion_does_not_repeat_discovery_or_analysis(tmp_path, monkeypatch, stage):
    from rc6_runtime.truth import TruthRuntime
    from rc7_runtime.rc72_n3_source_target_review import N3SourceTargetReviewService
    from rc7_runtime.rc72_n3_code_analysis_review import N3CodeAnalysisReviewService
    truth, driver, calls = _n3_driver(tmp_path, two_targets=True)
    from rc7_runtime.rc72_n3_code_analysis_assignment import N3CodeAnalysisAssignmentService
    cls, method = {'source-review': (N3SourceTargetReviewService, 'review_and_apply'),
        'code-assignment': (N3CodeAnalysisAssignmentService, 'assign_all'),
        'code-review': (N3CodeAnalysisReviewService, 'review')}[stage]
    original = getattr(cls, method)
    def interrupted(*args, **kwargs):
        raise OSError('controller interrupted after durable candidate promotion')
    monkeypatch.setattr(cls, method, interrupted)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert calls.count('source') == 1
    assert calls.count('code') == (1 if stage == 'code-review' else 0)
    monkeypatch.setattr(cls, method, original)
    cold = TruthRuntime(truth.store.path)
    driver.truth = cold
    driver.n3_pipeline.truth = cold
    for launcher in (driver.n1_launcher, driver.n2_launcher, driver.n2_evaluator.launcher) + driver.n3_pipeline.launchers:
        launcher.truth = cold
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    assert cold.query('rc72_mission_node', node_type='N3_CODE_ANALYSIS')[0]['state'] == 'PASS'
    assert calls == ['n1', 'n2', 'review', 'n2', 'review', 'source', 'source-review', 'code', 'code-review', 'code', 'code-review']
    assert len(cold.query('rc72_n3_source_target_attempt')) == 1
    assert len(cold.query('rc72_n3_code_analysis_attempt')) == 2
