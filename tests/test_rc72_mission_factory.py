"""Composition boundaries: no worker/process/bank qualification during wiring."""
from rc7_runtime.rc72_code_tool_binding import NATIVE_CODE_TOOLS
from dataclasses import replace
import sys

import pytest
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_native_n1_launcher import NativeN1ReadDshLauncher
from rc7_runtime.rc72_native_n1_read_gate import N1ReadResource, TOOL
from rc7_runtime.rc72_mission_factory import ROLES, MissionWorkerBinding, create_mission_driver
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService
from rc7_runtime.rc72_native_coverage_rerun import NativeCoverageRerunService, CoverageRerunPlanningService
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc72_n2_test_support import build_truth, RELEASE, COMMIT
from rc7_runtime.rc72_bank_pip_mirror import NativeBankPipMirrorService
from rc72_formal_runner_support import LocalHTTPEnvironment


def _setup(tmp_path, truth=None):
    truth = truth if truth is not None else build_truth(tmp_path)
    patch = tmp_path/'patch.json'
    patch.write_text('{}')
    source = tmp_path/'approved-input.json'
    source.write_text('{}')
    workers = {}
    def forbidden(*args, **kwargs):
        pytest.fail('composition launched a process')
    for role in ROLES:
        options = dict(dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
            truth=truth, authority=RC72AuthorityRuntime(('engineering-factory-'+role).encode()),
            coordinator_instance_id='factory-controller', release_id=RELEASE,
            state_root=str(tmp_path/('worker-'+role)), command_runner=forbidden)
        if role == 'reality':
            worker = NativeN1ReadDshLauncher(resources=[N1ReadResource('release-batch://input',source)], **options)
            tools = (TOOL,)
        else:
            worker = DshHeadlessWorkerLauncher(**options)
            tools = NATIVE_CODE_TOOLS if role in ('code','code_review') else ('scoped-tool',)
        workers[role] = MissionWorkerBinding(worker, tools)
    return truth, dict(release_id=RELEASE, source_commit=COMMIT, workers=workers,
        bank_pip_mirror=NativeBankPipMirrorService(truth, release_id=RELEASE, source_commit=COMMIT,
            authority=RC72AuthorityRuntime(b'engineering-factory-mirror'), package_root=tmp_path/'package',
            archive=tmp_path/'package.zip', field_config=tmp_path/'field.json', evidence_root=tmp_path/'mirror'),
        execution_authority=RC72AuthorityRuntime(b'factory-execution-authority'),
        execution_environment=LocalHTTPEnvironment('http://127.0.0.1:1',tmp_path/'environment'),
        tool_registry={'api_http':('api_http',)}, evidence_root=tmp_path/'evidence')


def test_factory_owns_whole_native_chain_without_starting_work(tmp_path):
    truth, options = _setup(tmp_path)
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    assert driver.n3_pipeline.truth is driver.n4_pipeline.truth is driver.n5_pipeline.truth is truth
    assert driver.n7_pipeline.preparation.authority is options['execution_authority']
    assert driver.n9_pipeline.pipeline is driver.n7_pipeline
    assert isinstance(driver.n8_pipeline, NativeN8ProductRecoveryService)
    assert driver.n8_pipeline.n7 is driver.n7_pipeline
    assert driver.n8_pipeline.diagnosis is driver.n7_pipeline.diagnosis
    assert driver.n8_pipeline.continuation.diagnosis is driver.n7_pipeline.diagnosis
    assert driver.n10_pipeline.n9 is driver.n9_pipeline
    assert driver.n10_pipeline.expected_scope is driver.expected_scope
    # This must be the *product* chain, not a test-only N10 with no repair.
    assert isinstance(driver.n10_pipeline.repair, NativeCoverageRepairService)
    assert isinstance(driver.n10_pipeline.rerun, NativeCoverageRerunService)
    assert driver.n10_pipeline.repair.diagnosis is driver.n10_pipeline.diagnosis
    assert driver.n10_pipeline.rerun.repair is driver.n10_pipeline.repair
    assert driver.n10_pipeline.rerun.pipeline is driver.n7_pipeline
    assert isinstance(driver.n7_pipeline.preparation.planning, CoverageRerunPlanningService)
    assert driver.n7_pipeline.preparation.planning.owner is driver.n10_pipeline.rerun
    assert driver.expected_scope.pipeline.handoff_service.launcher is driver.n1_launcher
    assert driver.bank_pip_mirror is options['bank_pip_mirror']
    assert driver.n7_pipeline.runner.environment_adapter is options['execution_environment']
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize('mutation,reason', [
    ('missing_role','EXACT_ROLES'), ('extra_role','EXACT_ROLES'),
    ('shared_worker','PRIVATE_ROLE_ROOT'), ('nested_root','PRIVATE_ROLE_ROOT'),
    ('wrong_release','WORKER_SCOPE'), ('wildcard','EXACT_TOOLS'),
    ('source','MIRROR_SCOPE'), ('bare_mirror','MIRROR_SCOPE'),
    ('mirror_subclass','MIRROR_SCOPE'),
    ('environment','EXECUTION_ENVIRONMENT'), ('registry','EXACT_EXECUTION_TOOLS'),
    ('code_tools','REQUIRED_CODE_TOOLS'),
])
def test_factory_rejects_partial_or_cross_scope_binding_without_effects(tmp_path, mutation, reason):
    truth, options = _setup(tmp_path)
    workers = options['workers']
    if mutation == 'missing_role': workers.pop('data_verify')
    elif mutation == 'extra_role': workers['callback'] = lambda: 'PASS'
    elif mutation == 'shared_worker': workers['requirement_review'] = workers['requirement']
    elif mutation == 'nested_root': workers['requirement_review'].launcher.state_root = workers['requirement'].launcher.state_root/'nested'
    elif mutation == 'wrong_release': workers['design'].launcher.release_id = 'another-release'
    elif mutation == 'wildcard': workers['design'] = replace(workers['design'], tools=('*',))
    elif mutation == 'source': options['source_commit'] = 'f'*40
    elif mutation == 'bare_mirror': options['bank_pip_mirror'] = {'status':'PASS'}
    elif mutation == 'mirror_subclass':
        class SubstituteMirror(NativeBankPipMirrorService):
            def run(self, **kwargs):
                return dict(status='PASS',bank_pc_mirror_field_fact=True)
        options['bank_pip_mirror'] = object.__new__(SubstituteMirror)
    elif mutation == 'environment': options['execution_environment'] = {'status':'PASS'}
    elif mutation == 'registry': options['tool_registry'] = {'api_http':('*',)}
    elif mutation == 'code_tools': workers['code_review'] = replace(workers['code_review'], tools=('git',))
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match=reason):
        create_mission_driver(truth, **options)
    assert truth.store.path.read_bytes() == before


def test_factory_cold_reconstruction_keeps_repair_rerun_owned_and_side_effect_free(tmp_path):
    """Rebuilding the public entry must preserve wiring without writing fake R1."""
    truth, options = _setup(tmp_path)
    before = truth.store.path.read_bytes()
    for _ in range(2):
        driver = create_mission_driver(truth, **options)
        assert driver.n10_pipeline.rerun.pipeline is driver.n7_pipeline
        assert driver.n8_pipeline.n7 is driver.n7_pipeline
        assert driver.n8_pipeline.boundary.preparation is driver.n7_pipeline.preparation
        assert driver.n8_pipeline.continuation.preparation is driver.n7_pipeline.preparation
        assert driver.n10_pipeline.rerun.truth is truth
        assert driver.n10_pipeline.repair.truth is truth
        assert driver.n10_pipeline.rerun.source_commit == options['source_commit']
        assert driver.n10_pipeline.rerun.release_id == options['release_id']
        assert truth.store.path.read_bytes() == before
    assert not truth.query('rc72_native_coverage_repair')
    assert not truth.query('rc72_native_coverage_rerun')


def test_factory_n10_rejects_detached_rerun_before_side_effect(tmp_path):
    """A replacement repair object cannot stand in for the signed original."""
    truth, options = _setup(tmp_path)
    driver = create_mission_driver(truth, **options)
    before = truth.store.path.read_bytes()
    driver.n10_pipeline.rerun.repair = object()
    with pytest.raises(ContractError, match='N10_NATIVE_RERUN_COMPOSITION_REQUIRED'):
        driver.n10_pipeline._assert_inputs()
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize('mutation', ['cleanup_tool','diagnosis','continuation'])
def test_factory_driver_refuses_n8_detached_native_recovery_before_any_r1_effect(tmp_path,mutation):
    truth,options=_setup(tmp_path)
    driver=create_mission_driver(truth,**options)
    before=truth.store.path.read_bytes()
    if mutation=='cleanup_tool':
        driver.n8_pipeline.boundary.cleanup.adapters={'api_http':lambda **kwargs: {'fake':'cleanup'}}
    elif mutation=='diagnosis':
        driver.n8_pipeline.boundary.diagnosis=object()
    else:
        driver.n8_pipeline.continuation.diagnosis=object()
    with pytest.raises(ContractError,match='RC72_RELEASE_DRIVER_N8_NATIVE_SCOPE_MISMATCH'):
        driver._assert_n8_scope()
    assert truth.store.path.read_bytes()==before
    assert not truth.query('rc72_n8_repair_boundary')
    assert not truth.query('rc72_n8_process_diagnosis')
