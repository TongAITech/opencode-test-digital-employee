"""Product route integration with real child protocol sessions (not Field proof)."""
from rc72_pip_field_test_support import provider as prior_field_provider
import json
import subprocess
import sys

import pytest
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
from rc7_runtime.rc72_release_driver import ReleaseBatchDriver, _driver_lock
from rc7_runtime.models import ContractError
from rc72_n2_test_support import build_truth, start_n1, BATCH, COMMIT, MISSION, RELEASE, REQUIREMENTS
from test_rc72_n1_completion import _good_candidate
from test_rc72_n1_executable_binding import _binding
from test_rc72_n2_requirement_review import _candidate


def _driver(tmp_path, *, gap=False, runtime_family=None):
    truth = build_truth(tmp_path)
    start_n1(truth)
    script = tmp_path / 'protocol-worker.py'
    script.write_text('import sys,json,uuid\np=json.loads(sys.argv[1])\n'
        'print(json.dumps(dict(type="session",session_id="session-product-"+uuid.uuid4().hex)))\n'
        'print(json.dumps(dict(type="tool_call",tool_name=sys.argv[2])))\n'
        'print(json.dumps(dict(type="final",text=json.dumps(p))))\n')
    patch = tmp_path / 'patch.json'
    patch.write_text('{}')
    calls = []
    def launcher(role):
        def run(command, **kwargs):
            prompt = command[-1]
            if role == 'n1':
                candidate = _good_candidate()
                candidate['facts'].update(release_id=RELEASE, release_batch_id=BATCH, source_commit=COMMIT)
                candidate['facts']['deployment_records'][0]['application_id'] = 'BLOAN'
                binding = _binding()
                binding.update(release_id=RELEASE, mission_id=MISSION, release_batch_id=BATCH, source_commit=COMMIT)
                if runtime_family is not None:
                    binding['tool_route']['family'] = runtime_family
                candidate['facts']['executable_bindings'] = [binding]
            elif role == 'n2':
                reqs = [req for req in REQUIREMENTS if req in prompt]
                assert len(reqs) == 1
                candidate = _candidate(reqs[0], unknowns=['unresolved source'] if gap else [])
            else:
                candidate = dict(decision='PASS', gap_ids=[], summary='independent engineering review')
            calls.append(role)
            return subprocess.run([sys.executable, str(script), json.dumps(candidate), role+'-probe'], **kwargs)
        return DshHeadlessWorkerLauncher(dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
            truth=truth, authority=RC72AuthorityRuntime(('engineering-product-key-'+role).encode()),
            coordinator_instance_id='product-controller', release_id=RELEASE,
            state_root=str(tmp_path / ('runtime-'+role)), command_runner=run)
    n1, n2, reviewer = launcher('n1'), launcher('n2'), launcher('review')
    driver = ReleaseBatchDriver(truth, source_commit=COMMIT, bank_pip_mirror=prior_field_provider(truth,source_commit=COMMIT), n1_launcher=n1, n1_tools=['n1-probe'],
        n2_launcher=n2, n2_tools=['n2-probe'], n2_evaluator=DshRequirementEvaluator(reviewer, allowed_tools=['review-probe']))
    return truth, driver, calls


def test_release_driver_runs_strict_n1_then_every_requirement_and_independent_gate(tmp_path):
    truth, driver, calls = _driver(tmp_path)
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    states = {n['node_type']: n['state'] for n in result['nodes']}
    assert states['N1_REALITY'] == states['N2_REQUIREMENT'] == 'PASS'
    assert states['N3_CODE_ANALYSIS'] == 'READY'
    assert calls == ['n1', 'n2', 'review', 'n2', 'review']
    assert len(truth.query('rc72_n1_executable_binding')) == 1
    assert len(truth.query('rc72_n2_requirement_attempt')) == len(REQUIREMENTS)
    assert result['field_verified'] is result['bank_final'] is False
    before = truth.store.path.read_bytes()
    assert driver.run(release_batch_id=BATCH) == result
    assert truth.store.path.read_bytes() == before and len(calls) == 5
    # Recreate all controller services from independent cold truth; no worker
    # session is launched merely to rediscover already governed decisions.
    cold = TruthRuntime(truth.store.path)
    driver.truth = cold
    driver.bank_pip_mirror=prior_field_provider(cold,source_commit=COMMIT)
    for launcher in (driver.n1_launcher, driver.n2_launcher, driver.n2_evaluator.launcher):
        launcher.truth = cold
    assert driver.run(release_batch_id=BATCH) == result
    assert cold.store.path.read_bytes() == before and len(calls) == 5


def test_worker_uncertainty_cannot_be_hidden_and_every_requirement_still_reviewed(tmp_path):
    truth, driver, calls = _driver(tmp_path, gap=True)
    result = driver.run(release_batch_id=BATCH)
    assert result['status'] == 'HOLD' and result['reason'] == 'NATIVE_NODE_GATE_NOT_PASS'
    assert calls == ['n1', 'n2', 'review', 'n2', 'review']
    assert truth.query('rc72_mission_node', node_type='N2_REQUIREMENT')[0]['state'] == 'NEEDS_REVISION'
    assert truth.query('rc72_mission_node', node_type='N3_CODE_ANALYSIS')[0]['state'] == 'NOT_STARTED'
    assert len(truth.query('rc7_gap')) >= len(REQUIREMENTS)
    before = truth.store.path.read_bytes()
    resumed = driver.run(release_batch_id=BATCH)
    assert resumed['status'] == 'HOLD' and truth.store.path.read_bytes() == before and len(calls) == 5


def test_status_is_readonly_and_a_concurrent_controller_cannot_launch_workers(tmp_path):
    truth, driver, calls = _driver(tmp_path)
    before = truth.store.path.read_bytes()
    assert len(driver.status(release_batch_id=BATCH)['nodes']) == 10
    assert truth.store.path.read_bytes() == before
    with _driver_lock(truth, BATCH):
        with pytest.raises(ContractError, match='ALREADY_RUNNING'):
            driver.run(release_batch_id=BATCH)
    assert not calls and truth.store.path.read_bytes() == before


def test_source_mismatch_cannot_reuse_admission_or_launch_any_worker(tmp_path):
    truth, driver, calls = _driver(tmp_path)
    driver.source_commit = 'f'*40
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError):
        driver.run(release_batch_id=BATCH)
    assert not calls and truth.store.path.read_bytes() == before


def test_cold_status_entry_needs_no_worker_configuration_and_never_writes_ledger(tmp_path):
    truth, driver, calls = _driver(tmp_path)
    from pathlib import Path
    before = truth.store.path.read_bytes()
    result = subprocess.run([sys.executable, '-I', '-c',
        'import sys;sys.path.insert(0,sys.argv[1]);from rc7_release.rc72_mission_cli import main;main(sys.argv[2:])',
        str(Path(__file__).resolve().parents[1]), 'status', '--ledger', str(truth.store.path),
        '--source-commit', COMMIT, '--release-batch', BATCH], capture_output=True, text=True, check=True)
    snapshot = json.loads(result.stdout)
    assert snapshot == driver.status(release_batch_id=BATCH)
    assert len(snapshot['nodes']) == 10 and not calls
    assert truth.store.path.read_bytes() == before


def test_cold_resume_rechecks_completed_n1_raw_evidence_before_any_new_work(tmp_path):
    truth, driver, calls = _driver(tmp_path)
    driver.run(release_batch_id=BATCH)
    anchor = truth.query('rc72_n1_dsh_evidence_anchor')[0]
    # Locate the actual raw evidence file, not an in-memory candidate copy.
    from pathlib import Path
    path = Path(anchor['raw_output_ref'][len('file://'):])
    path.write_text(path.read_text() + '\nchanged accepted source bytes\n')
    before = truth.store.path.read_bytes()
    with pytest.raises(Exception):
        driver.run(release_batch_id=BATCH)
    assert len(calls) == 5 and truth.store.path.read_bytes() == before


def test_interrupted_before_review_resumes_promoted_requirement_without_second_analyzer(tmp_path, monkeypatch):
    from rc7_runtime.rc72_n2_requirement_review import N2RequirementReviewService
    truth, driver, calls = _driver(tmp_path)
    original = N2RequirementReviewService.review_and_apply
    def interrupted(*args, **kwargs):
        raise OSError('controller interrupted after durable candidate promotion')
    monkeypatch.setattr(N2RequirementReviewService, 'review_and_apply', interrupted)
    with pytest.raises(OSError):
        driver.run(release_batch_id=BATCH)
    assert calls == ['n1', 'n2']
    assert len(truth.query('rc72_n2_requirement_attempt')) == 1
    monkeypatch.setattr(N2RequirementReviewService, 'review_and_apply', original)
    cold = TruthRuntime(truth.store.path)
    driver.truth = cold
    driver.bank_pip_mirror=prior_field_provider(cold,source_commit=COMMIT)
    for launcher in (driver.n1_launcher, driver.n2_launcher, driver.n2_evaluator.launcher):
        launcher.truth = cold
    result = driver.run(release_batch_id=BATCH)
    assert result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    assert calls == ['n1', 'n2', 'review', 'n2', 'review']
    assert len(cold.query('rc72_n2_requirement_attempt')) == 2


def test_separate_process_cannot_take_live_release_driver_lock(tmp_path):
    from pathlib import Path
    truth, driver, calls = _driver(tmp_path)
    command = [sys.executable, '-I', '-c',
        'import sys;sys.path.insert(0,sys.argv[1]);from rc6_runtime.truth import TruthRuntime;'
        'from rc7_runtime.rc72_release_driver import _driver_lock;'
        't=TruthRuntime(sys.argv[2]);\n'
        'try:\n with _driver_lock(t,sys.argv[3]): raise AssertionError("second controller admitted")\n'
        'except Exception as exc:\n assert str(exc)=="RC72_RELEASE_DRIVER_ALREADY_RUNNING",str(exc)\n',
        str(Path(__file__).resolve().parents[1]), str(truth.store.path), BATCH]
    before = truth.store.path.read_bytes()
    with _driver_lock(truth, BATCH):
        subprocess.run(command, capture_output=True, text=True, check=True)
    assert not calls and truth.store.path.read_bytes() == before


def test_advanced_downstream_requires_the_original_canonical_forward_lineage(tmp_path):
    truth, driver, calls = _driver(tmp_path)
    driver.run(release_batch_id=BATCH)
    edge = next(edge for edge in truth.query('rc72_node_transition') if edge['from_node_type'] == 'N1_REALITY')
    truth.append_atomic('RC72_NODE_TRANSITION_UPSERTED', dict(edge, source_gate_id='unrelated-gate',
        artifact_version=edge['artifact_version']+1))
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='FORWARD_LINEAGE_REQUIRED'):
        driver.run(release_batch_id=BATCH)
    assert len(calls) == 5 and truth.store.path.read_bytes() == before


@pytest.mark.parametrize('mutation', ['missing_n8', 'missing_n9', 'missing_n10', 'foreign_node'])
def test_c08_status_rejects_corrupt_mission_denominator_without_worker_or_r1_writes(
        tmp_path, monkeypatch, mutation):
    truth, driver, calls = _driver(tmp_path)
    original = truth.query
    def broken(artifact_kind, **filters):
        rows = original(artifact_kind, **filters)
        if artifact_kind != 'rc72_mission_node' or 'mission_id' not in filters:
            return rows
        if mutation.startswith('missing_'):
            missing = mutation.split('_')[1].upper()
            return [row for row in rows if row['node_type'] != ('N8_DIAGNOSIS_RECOVERY' if missing == 'N8'
                else 'N9_DEFECT' if missing == 'N9' else 'N10_RELEASE_CONVERGENCE')]
        return rows + [dict(rows[0], node_type='N11_UNAUTHORIZED_EXTENSION',
                                 mission_node_id='FOREIGN-N11')]
    monkeypatch.setattr(truth, 'query', broken)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='RC72_RELEASE_DRIVER_NODE_DENOMINATOR_INVALID'):
        driver.status(release_batch_id=BATCH)
    assert not calls
    assert truth.store.path.read_bytes() == before


def test_c08_unbootstrapped_release_status_never_claims_node_pass(tmp_path):
    from rc7_runtime.rc72_release_driver import release_batch_status
    truth = build_truth(tmp_path)
    truth.append_atomic('RC72_RELEASE_BATCH_UPSERTED', dict(
        release_batch_id=BATCH, release_id=RELEASE, mission_id=MISSION,
        name=RELEASE, version_ids=[RELEASE], application_ids=['BLOAN'],
        requirement_ids=list(REQUIREMENTS), state='REGISTERED',
        readiness='UNKNOWN', created_at=1, updated_at=1,
        artifact_version=1))
    # The projection of a registered-but-not-started ReleaseBatch must not
    # manufacture ten PASS labels or launch a worker just to answer status.
    assert not truth.query('rc72_mission_node', mission_id=MISSION)
    before = truth.store.path.read_bytes()
    response = release_batch_status(
        truth, source_commit=COMMIT, release_batch_id=BATCH)
    assert response['nodes'] == []
    assert response['field_verified'] is response['bank_final'] is False
    assert truth.store.path.read_bytes() == before


def test_formal_n7_gate_cannot_be_bypassed_by_resumed_gate_path(tmp_path):
    """GAP-01: both release-driver N7 entrypoints require trusted Host."""
    from types import SimpleNamespace
    root = tmp_path / 'full-package'
    root.mkdir()
    (root / 'PACKAGE_MANIFEST.json').write_text('{"test_fixture":true}')
    calls = []
    batch = dict(release_batch_id='B-C10', release_id='R-C10',
                 mission_id='M-C10')
    driver = ReleaseBatchDriver.__new__(ReleaseBatchDriver)
    driver.bank_pip_mirror = SimpleNamespace(root=root)
    driver.truth = SimpleNamespace(query=lambda kind, **kwargs: [])
    driver.source_commit = 'a' * 40
    driver.n7_pipeline = SimpleNamespace(
        captain_scheduler=None,
        complete=lambda **kwargs: calls.append('SUT_I_O_FORBIDDEN'))
    with pytest.raises(ContractError, match='SCRIPT_READY_FIELD_CAPTAIN_REQUIRED'):
        driver._complete_gate('N7_EXECUTION', batch)
    with pytest.raises(ContractError, match='SCRIPT_READY_FIELD_CAPTAIN_REQUIRED'):
        driver._admit_formal_n7_script_gate(batch)
    assert calls == []


def test_source_only_engineering_mirror_does_not_imply_full_package_field_gate(tmp_path):
    """GAP-01: prior full-package proof persists even after manifest deletion."""
    from types import SimpleNamespace
    root = tmp_path / 'lost-full-package'
    root.mkdir()
    calls = []
    batch = dict(release_batch_id='B-C10', release_id='R-C10',
                 mission_id='M-C10')
    driver = ReleaseBatchDriver.__new__(ReleaseBatchDriver)
    driver.bank_pip_mirror = SimpleNamespace(root=root)
    driver.truth = SimpleNamespace(query=lambda kind, **kwargs:
        [dict(binding=dict(full_package_verified=True, package_root=str(root)))]
        if kind == 'rc72_bank_pip_mirror_execution' else [])
    driver.source_commit = 'a' * 40
    driver.n7_pipeline = SimpleNamespace(
        captain_scheduler=None,
        complete=lambda **kwargs: calls.append('SUT_I_O_FORBIDDEN'))
    assert driver._admit_formal_n7_script_gate(batch) is None
    # This is a source-level component test, not the public Field CLI.
    # The separate CLI regression refuses a deleted real full manifest.
    driver.n7_pipeline.complete = lambda **kwargs: calls.append('COMPONENT_NO_SUT') or {
        'status': 'HOLD', 'reason': 'COMPONENT_ONLY', 'field_verified': False, 'bank_final': False,
    }
    assert driver._complete_gate('N7_EXECUTION', batch)['bank_final'] is False
    assert calls == ['COMPONENT_NO_SUT']
