"""N1-N4 concrete route; real child protocols are not bank tool-body proof."""
from copy import deepcopy
import hashlib
import json
import subprocess
import sys

import pytest
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n4_pipeline import N4PipelineService
from rc7_runtime.rc72_n4_parent_guard import N4ParentScopedDesignEvaluator
from test_rc72_release_driver_n3 import _n3_driver
from test_rc72_n4_test_design_handoff import _candidate
from rc72_n2_test_support import BATCH, COMMIT, RELEASE


def _n4_driver(tmp_path, *, incomplete_parent=False, explicit_gap=False, shallow=False, invalid_oracle=False, compact=False):
    truth, driver, calls = _n3_driver(tmp_path, two_targets=True)
    script = tmp_path / 'n4-protocol-worker.py'
    script.write_text('import sys,json,uuid\n'
        'print(json.dumps(dict(type="session",session_id="session-n4-product-"+uuid.uuid4().hex)))\n'
        'for name in ["filesystem","codegraph"]: print(json.dumps(dict(type="tool_call",tool_name=name)))\n'
        'print(json.dumps(dict(type="final",text=sys.argv[1])))\n')
    patch = tmp_path / 'n4-patch.json'
    patch.write_text('{}')
    def launcher(role):
        def run(command, **kwargs):
            if role == 'design':
                truth.rebuild_projection()
                rows = truth.query('rc72_n4_test_design_assignment')
                row = next(r for r in rows if r['requirement_id'] in command[-1] and r['sst_id'] in command[-1])
                dispatch = truth.query('rc72_n4_test_design_dispatch', dispatch_id=row['dispatch_id'])[0]
                base = _candidate(row['requirement_id'], row['sst_id'])
                candidate = dict(base, obligations=[], cases=[])
                sources = sorted(dispatch['parent_obligation_source_refs'])
                for source in sources:
                    kind = source.split(':', 1)[0]
                    suffix = hashlib.sha256((row['sst_id']+'|'+source).encode()).hexdigest()[:20]
                    obligation, case = deepcopy(base['obligations'][0]), deepcopy(base['cases'][0])
                    oid = 'OBL-PARENT-' + suffix
                    obligation.update(obligation_id=oid, kind=kind, source_refs=[source])
                    case.update(tc_id='TC-PARENT-'+suffix, obligation_id=oid,
                        coverage_links=[dict(subject_id=oid, evidence_ref=obligation['evidence_refs'][0])])
                    if not invalid_oracle:
                        for check in case['oracle']['checks']:
                            check.update(actual_path='response.status_code', operator='EQ', expected=200)
                    candidate['obligations'].append(obligation)
                    candidate['cases'].append(case)
                if compact:
                    # Preserve every required parent obligation; group bounded
                    # compatible links, still checked by real SufficiencyV2.
                    groups = []
                    for kind in ('CODE_IMPACT','REGRESSION'):
                        same = [o for o in candidate['obligations'] if o['kind']==kind]
                        groups.extend(same[i:i+3] for i in range(0,len(same),3))
                    others = [o for o in candidate['obligations'] if o['kind'] not in {'CODE_IMPACT','REGRESSION'}]
                    groups.extend(others[i:i+4] for i in range(0,len(others),4))
                    by_id = {c['obligation_id']: c for c in candidate['cases']}
                    candidate['cases'] = []
                    for group in groups:
                        case = deepcopy(by_id[group[0]['obligation_id']])
                        case['coverage_links'] = [dict(subject_id=o['obligation_id'], evidence_ref=o['evidence_refs'][0]) for o in group]
                        candidate['cases'].append(case)
                code_obligations = [o for o in candidate['obligations'] if o['kind'] == 'CODE_IMPACT']
                regression = [o for o in candidate['obligations'] if o['kind'] == 'REGRESSION']
                if not shallow and len(code_obligations) >= 2 and len(regression) >= 2:
                    interaction = deepcopy(next(c for c in candidate['cases'] if c['obligation_id'] == code_obligations[0]['obligation_id']))
                    interaction['tc_id'] += '-interaction'
                    interaction['coverage_links'].append(dict(subject_id=regression[0]['obligation_id'],
                        evidence_ref=regression[0]['evidence_refs'][0]))
                    candidate['cases'].append(interaction)
                if incomplete_parent:
                    # Same symbol ID appears in two reviewed repositories. An
                    # obligation for the other parent must not cover this one.
                    symbols = [o for o in candidate['obligations']
                        if o['kind'] == 'CODE_IMPACT' and 'example.ChangedService#execute:' in o['source_refs'][0]]
                    assert len(symbols) == 2
                    symbols[0]['source_refs'] = list(symbols[1]['source_refs'])
                if explicit_gap:
                    candidate['gaps'] = ['parent-derived behavior remains unresolved']
            else:
                candidate = dict(decision='PASS', gap_ids=[], summary='independent full design review')
            calls.append(role)
            return subprocess.run([sys.executable, str(script), json.dumps(candidate)], **kwargs)
        return DshHeadlessWorkerLauncher(dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
            truth=truth, authority=RC72AuthorityRuntime(('engineering-n4-key-'+role).encode()),
            coordinator_instance_id='n4-product-controller', release_id=RELEASE,
            state_root=str(tmp_path / ('runtime-'+role)), command_runner=run)
    designer, reviewer = launcher('design'), launcher('design-review')
    driver.n4_pipeline = N4PipelineService(truth, source_commit=COMMIT, launcher=designer,
        allowed_tools=['filesystem', 'codegraph'], evaluator=N4ParentScopedDesignEvaluator(reviewer,
            reviewer_allowed_tools=['filesystem', 'codegraph']))
    return truth, driver, calls


def test_driver_designs_every_requirement_sst_and_parent_source_before_n5(tmp_path):
    truth, driver, calls = _n4_driver(tmp_path)
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    states = {n['node_type']: n['state'] for n in result['nodes']}
    assert states['N4_TEST_DESIGN'] == 'PASS' and states['N5_TEST_DATA'] == 'READY'
    dispatches = truth.query('rc72_n4_test_design_dispatch')
    assert len(dispatches) == 2
    assert calls[-4:] == ['design', 'design-review', 'design', 'design-review']
    assert len(truth.query('rc72_n4_test_design_attempt')) == len(dispatches)
    before = truth.store.path.read_bytes()
    assert driver.run(release_batch_id=BATCH) == result
    assert truth.store.path.read_bytes() == before and len(calls) == 15


@pytest.mark.parametrize('failure', ['parent-alias', 'explicit-gap', 'shallow', 'oracle'])
def test_smaller_parent_denominator_or_explicit_gap_never_opens_n5(tmp_path, failure):
    truth, driver, calls = _n4_driver(tmp_path, incomplete_parent=failure=='parent-alias', explicit_gap=failure=='explicit-gap',
        shallow=failure=='shallow', invalid_oracle=failure=='oracle')
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'NATIVE_NODE_GATE_NOT_PASS'
    assert truth.query('rc72_mission_node', node_type='N4_TEST_DESIGN')[0]['state'] == 'NEEDS_REVISION'
    assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'NOT_STARTED'
    assert calls.count('design') == 2
    assert calls.count('design-review') == (0 if failure=='explicit-gap' else 2)
    assert truth.query('rc7_gap', category='TEST_DESIGN_SOURCE_OBLIGATION_GAP') or failure != 'parent-alias'


@pytest.mark.parametrize('stage', ['assignment', 'review'])
def test_n4_cold_resume_keeps_all_scopes_without_repeating_designer(tmp_path, monkeypatch, stage):
    from rc6_runtime.truth import TruthRuntime
    from rc7_runtime.rc72_n4_test_design_review import N4TestDesignReviewService
    from rc7_runtime.rc72_n4_test_design_assignment import N4TestDesignAssignmentService
    truth, driver, calls = _n4_driver(tmp_path)
    cls, method = (N4TestDesignAssignmentService, 'assign_all') if stage == 'assignment' else (N4TestDesignReviewService, 'review')
    original = getattr(cls, method)
    def interrupted(*args, **kwargs):
        raise OSError('controller interrupted at native design boundary')
    monkeypatch.setattr(cls, method, interrupted)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert calls.count('design') == (0 if stage=='assignment' else 1)
    monkeypatch.setattr(cls, method, original)
    cold = TruthRuntime(truth.store.path)
    driver.truth = cold
    driver.n3_pipeline.truth = driver.n4_pipeline.truth = cold
    for launcher in (driver.n1_launcher, driver.n2_launcher, driver.n2_evaluator.launcher) + driver.n3_pipeline.launchers + driver.n4_pipeline.launchers:
        launcher.truth = cold
    result = driver.run(release_batch_id=BATCH)
    assert result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    assert calls.count('design') == calls.count('design-review') == 2
    assert len(cold.query('rc72_n4_test_design_attempt')) == 2
    assert cold.query('rc72_mission_node', node_type='N4_TEST_DESIGN')[0]['state'] == 'PASS'


def test_design_reviewer_candidate_permissions_never_grant_canonical_gate_or_case_write():
    from rc6_runtime.authority import AuthorityError
    authority = RC72AuthorityRuntime(b'native-reviewer-authority-key')
    identity = authority.issue_identity('RC7_TEST_DESIGN_REVIEWER', 'DESIGN_REVIEW', None, 0, 'fresh-independent-session')
    lease = authority.issue_lease(identity.worker_id, 'artifact://design-candidate',
        ('rc7_test_design_review', 'analysis_gap'), ('filesystem',))
    authority.authorize_artifact(identity.worker_id, lease.lease_id, 'rc7_test_design_review')
    for artifact in ('rc72_test_case', 'rc72_test_obligation', 'rc72_node_gate', 'rc7_evaluation'):
        with pytest.raises(AuthorityError, match='ROLE_ARTIFACT_FORBIDDEN'):
            authority.authorize_artifact(identity.worker_id, lease.lease_id, artifact)


@pytest.mark.parametrize('failure,reason', [('parent-alias','PARENT_SOURCE_DENOMINATOR_INCOMPLETE'),
    ('oracle','DETERMINISTIC_ORACLE_REQUIRED'), ('shallow','SUFFICIENCY_V2_REQUIRED')])
def test_formal_gate_rechecks_real_legacy_positive_reviews_before_writing_delivery(tmp_path, monkeypatch, failure, reason):
    from rc7_runtime.dsh_test_design_evaluator import DshTestDesignEvaluator
    from rc7_runtime.models import ContractError
    truth, driver, calls = _n4_driver(tmp_path, incomplete_parent=failure=='parent-alias',
        invalid_oracle=failure=='oracle', shallow=failure=='shallow')
    # Exercise actual inherited reviewer + semantic acceptance, not fabricated
    # evaluation rows. The final native product Gate must independently refuse.
    monkeypatch.setattr(N4ParentScopedDesignEvaluator, 'evaluate', DshTestDesignEvaluator.evaluate)
    with pytest.raises(ContractError, match=reason):
        driver.run(release_batch_id=BATCH)
    node = truth.query('rc72_mission_node', node_type='N4_TEST_DESIGN')[0]
    assert not truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id'])
    assert not truth.query('rc72_node_gate', mission_node_id=node['mission_node_id'])
    assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'NOT_STARTED'
    assert calls.count('design') == calls.count('design-review') == 2
    assert all(t['state']=='PASS' for t in truth.query('rc7_task', node='TEST_DESIGN'))
