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
from rc72_n2_test_support import build_truth, RELEASE, COMMIT, BATCH
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


def _real_captain_binding(truth):
    """Actual B-group scheduler objects, with no leased/forged authority."""
    from rc7_runtime.control_plane import TaskScheduler
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc7_runtime.rc72_captain_scheduling import CaptainFencedWorkItemScheduler
    from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
    from rc7_runtime.rc72_mission_factory import MissionCaptainBinding

    governed = CaptainFencedWorkItemScheduler(
        truth=truth, release_id=RELEASE,
        fencer=CaptainDispatchFencer(truth, release_id=RELEASE),
        lifecycle=WorkerLifecycleService(truth, release_id=RELEASE),
        scheduler=TaskScheduler(truth, release_id=RELEASE),
        role_profiles={'L3_EXECUTE': ('api_http',)})
    return MissionCaptainBinding(governed, 'captain-session', 'signed-captain-lease', 'real-team')


def test_factory_binds_governed_b_captain_into_actual_a_product_n7(tmp_path):
    """A's real MissionFactory must not discard B's fenced scheduler."""
    from rc7_runtime.rc72_mission_factory import MissionCaptainBinding
    truth, options = _setup(tmp_path)
    binding = _real_captain_binding(truth)
    before = truth.store.path.read_bytes()
    options['captain_binding'] = binding
    driver = create_mission_driver(truth, **options)
    n7 = driver.n7_pipeline
    assert n7.captain_scheduler is binding.scheduler
    assert n7.captain_lease_id == binding.captain_lease_id
    assert n7.captain_session_id == binding.captain_session_id
    assert n7.team_id == binding.team_id
    assert driver.n8_pipeline.n7 is n7
    assert driver.n9_pipeline.pipeline is n7
    assert driver.n10_pipeline.rerun.pipeline is n7
    assert isinstance(binding, MissionCaptainBinding)
    # Composition must not create Captain/Worker/Attempt/PASS, nor call DSH.
    assert truth.store.path.read_bytes() == before
    assert not truth.query('rc72_captain_dispatch_lease')
    assert not truth.query('rc72_captain_etu_admission')


@pytest.mark.parametrize('mutation,reason', [
    ('bare', 'TYPED_CAPTAIN_BINDING'),
    ('no_team', 'CAPTAIN_SCOPE'),
    ('no_captain_lease', 'CAPTAIN_SCOPE'),
    ('foreign_release', 'CAPTAIN_CANONICAL_RUNTIME'),
    ('foreign_fencer', 'CAPTAIN_CANONICAL_RUNTIME'),
    ('foreign_scheduler', 'CAPTAIN_CANONICAL_RUNTIME'),
])
def test_factory_denies_unowned_or_partial_captain_without_r1_effects(tmp_path, mutation, reason):
    from rc7_runtime.rc72_mission_factory import MissionCaptainBinding
    truth, options = _setup(tmp_path)
    binding = _real_captain_binding(truth)
    scheduler = binding.scheduler
    if mutation == 'bare':
        binding = {'scheduler': scheduler, 'status': 'PASS'}
    elif mutation == 'no_team':
        binding = replace(binding, team_id='')
    elif mutation == 'no_captain_lease':
        binding = replace(binding, captain_lease_id='')
    elif mutation == 'foreign_release':
        scheduler.release_id = 'foreign-release'
    elif mutation == 'foreign_fencer':
        scheduler.fencer.release_id = 'foreign-release'
    elif mutation == 'foreign_scheduler':
        scheduler.scheduler.release_id = 'foreign-release'
    assert mutation == 'bare' or isinstance(binding, MissionCaptainBinding)
    options['captain_binding'] = binding
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='MISSION_FACTORY_' + reason):
        create_mission_driver(truth, **options)
    assert truth.store.path.read_bytes() == before
    assert not truth.query('execution_attempt')


def test_release_product_entry_blocks_legacy_n7_if_captain_exists(tmp_path, monkeypatch):
    """A real persisted B Captain cannot be bypassed through A's driver."""
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc72_formal_runner_support import formal_setup
    truth, plan, preparation, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        owner = CaptainDispatchFencer(truth, release_id=RELEASE).acquire_initial(
            mission_id=plan['mission_id'], team_id='TEAM-APPROVED',
            captain_session_id='CAPTAIN-APPROVED')
        _, options = _setup(tmp_path, truth)
        driver = create_mission_driver(truth, **options)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='RELEASE_DRIVER_CAPTAIN_CONTEXT_REQUIRED'):
            driver._assert_captain_product_entry(plan['mission_id'])
        # The real public product entry, not only the helper, must reject
        # an unfenced Captain Mission before dispatching any Node or tool.
        with pytest.raises(ContractError, match='RELEASE_DRIVER_CAPTAIN_CONTEXT_REQUIRED'):
            driver.run(release_batch_id=BATCH)
        assert truth.store.path.read_bytes() == before
        assert server.calls == []
        assert not truth.query('rc72_n7_execution_preparation')
        assert owner['state'] == 'ACTIVE'
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('mutation,reason', [
    ('valid', None),
    ('wrong_team', 'RELEASE_DRIVER_CAPTAIN_SCOPE_MISMATCH'),
    ('wrong_session', 'CAPTAIN_DISPATCH_FENCED'),
    ('wrong_lease', 'CAPTAIN_DISPATCH_FENCED'),
])
def test_release_product_entry_requires_exact_live_captain_authority(
        tmp_path, monkeypatch, mutation, reason):
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc72_formal_runner_support import formal_setup
    truth, plan, preparation, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        owner = CaptainDispatchFencer(truth, release_id=RELEASE).acquire_initial(
            mission_id=plan['mission_id'], team_id='TEAM-GOVERNED',
            captain_session_id='CAPTAIN-GOVERNED')
        binding = replace(_real_captain_binding(truth),
                          captain_session_id=owner['captain_session_id'],
                          captain_lease_id=owner['lease_id'],
                          team_id=owner['team_id'])
        if mutation == 'wrong_team':
            binding = replace(binding, team_id='TEAM-FOREIGN')
        elif mutation == 'wrong_session':
            binding = replace(binding, captain_session_id='CAPTAIN-FOREIGN')
        elif mutation == 'wrong_lease':
            binding = replace(binding, captain_lease_id='CAPF-FOREIGN')
        _, options = _setup(tmp_path, truth)
        options['captain_binding'] = binding
        driver = create_mission_driver(truth, **options)
        before = truth.store.path.read_bytes()
        if reason:
            with pytest.raises(ContractError, match=reason):
                driver._assert_captain_product_entry(plan['mission_id'])
        else:
            assert driver._assert_captain_product_entry(plan['mission_id']) is None
        assert truth.store.path.read_bytes() == before
        assert server.calls == []
        assert not truth.query('rc72_n7_execution_preparation')
    finally:
        server.shutdown()
        server.server_close()


def test_release_product_entry_rejects_exact_expired_captain_after_cold_reconstruction(
        tmp_path, monkeypatch):
    """TTL expiry persists in R1; rebuilding the host cannot resurrect dispatch."""
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc72_formal_runner_support import formal_setup
    truth, plan, preparation, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        fencer = CaptainDispatchFencer(truth, release_id=RELEASE)
        owner = fencer.acquire_initial(
            mission_id=plan['mission_id'], team_id='TEAM-TTL-REAL',
            captain_session_id='CAPTAIN-TTL-REAL', ttl_seconds=3)
        binding = replace(
            _real_captain_binding(truth),
            captain_session_id=owner['captain_session_id'],
            captain_lease_id=owner['lease_id'],
            team_id=owner['team_id'])
        _, options = _setup(tmp_path, truth)
        options['captain_binding'] = binding
        driver = create_mission_driver(truth, **options)
        assert driver._assert_captain_product_entry(plan['mission_id']) is None
        # The exact exclusive expiry second must not authorize more work.
        monkeypatch.setattr(
            'rc7_runtime.rc72_captain_dispatch_fencing._now',
            lambda: owner['expires_at'])
        with pytest.raises(ContractError, match='CAPTAIN_DISPATCH_LEASE_EXPIRED'):
            driver._assert_captain_product_entry(plan['mission_id'])
        assert not server.calls
        latest = truth.query('rc72_captain_dispatch_lease', lease_id=owner['lease_id'])
        assert len(latest) == 1 and latest[0]['state'] == 'EXPIRED'
        before = truth.store.path.read_bytes()
        rebuilt = create_mission_driver(truth, **options)
        with pytest.raises(ContractError, match='CAPTAIN_DISPATCH_NOT_ACTIVE'):
            rebuilt._assert_captain_product_entry(plan['mission_id'])
        assert truth.store.path.read_bytes() == before
        assert not truth.query('rc72_n7_execution_preparation')
        assert not server.calls
    finally:
        server.shutdown()
        server.server_close()
