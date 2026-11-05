"""Approved host loader and CLI refuse raw claims and wrong package scope."""
import sys
import json
from types import ModuleType

import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_mission_factory import MissionHostBindings
from rc7_release.rc72_mission_bindings import load_mission_bindings
from rc7_release.rc72_mission_cli import main
from rc72_n2_test_support import BATCH, COMMIT, RELEASE, start_n1
from test_rc72_mission_factory import _setup


def test_host_loader_preserves_typed_capabilities_and_same_truth(tmp_path, monkeypatch):
    truth, options = _setup(tmp_path)
    capabilities = MissionHostBindings(**{k:v for k,v in options.items()
        if k not in {'release_id','source_commit','evidence_root'}})
    module = ModuleType('approved_factory_binding')
    def create(**context):
        assert context == dict(truth=truth, release_id=RELEASE, source_commit=COMMIT)
        return capabilities
    module.create_mission_bindings = create
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert load_mission_bindings(module.__name__, truth=truth,
        release_id=RELEASE, source_commit=COMMIT) is capabilities


@pytest.mark.parametrize('result', [{'status':'PASS'}, lambda: 'PASS', None])
def test_host_loader_refuses_success_documents_and_driver_callbacks(tmp_path, monkeypatch, result):
    truth, _ = _setup(tmp_path)
    module = ModuleType('untyped_factory_binding')
    module.create_mission_bindings = lambda **kwargs: result
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(ContractError, match='TYPED_CAPABILITIES_REQUIRED'):
        load_mission_bindings(module.__name__, truth=truth, release_id=RELEASE, source_commit=COMMIT)


def test_host_failure_does_not_expose_configuration_values(tmp_path, monkeypatch):
    truth, _ = _setup(tmp_path)
    module = ModuleType('failed_factory_binding')
    def create(**kwargs):
        raise RuntimeError('private credential value')
    module.create_mission_bindings = create
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(ContractError) as error:
        load_mission_bindings(module.__name__, truth=truth, release_id=RELEASE, source_commit=COMMIT)
    assert str(error.value) == 'MISSION_BINDINGS_LOAD_FAILED:RuntimeError'


@pytest.mark.parametrize('mutation', ['source', 'release', 'missing_options'])
def test_cli_checks_package_and_batch_before_importing_host(tmp_path, monkeypatch, mutation):
    truth, _ = _setup(tmp_path)
    start_n1(truth)
    root = tmp_path/'package'
    root.mkdir()
    (root/'SOURCE_COMMIT').write_text('f'*40 if mutation == 'source' else COMMIT)
    module = ModuleType('must_not_load_binding')
    def forbidden(**kwargs):
        pytest.fail('invalid CLI context loaded host binding')
    module.create_mission_bindings = forbidden
    monkeypatch.setitem(sys.modules, module.__name__, module)
    args = ['run', '--ledger', str(truth.store.path), '--source-commit', COMMIT,
        '--release-batch', BATCH]
    if mutation != 'missing_options':
        args += ['--release-id', 'wrong-release' if mutation == 'release' else RELEASE,
            '--bindings-module', module.__name__, '--package-root', str(root),
            '--evidence-root', str(tmp_path/'evidence')]
    before = truth.store.path.read_bytes()
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert truth.store.path.read_bytes() == before


def test_cli_run_composes_native_services_but_cannot_bypass_admission(tmp_path, monkeypatch, capsys):
    truth, _ = _setup(tmp_path)
    start_n1(truth)
    admission = truth.query('rc72_q7_admission')[0]
    admission.update(status='HOLD', reason='engineering test admission withheld',
        hold_reasons=['Q7 withheld'], artifact_version=admission['artifact_version']+1)
    truth.append_atomic('RC72_Q7_ADMISSION_UPSERTED', admission)
    root = tmp_path/'package'
    root.mkdir()
    (root/'SOURCE_COMMIT').write_text(COMMIT)
    module = ModuleType('native_admission_binding')
    def create(**context):
        _, options = _setup(tmp_path, truth=context['truth'])
        return MissionHostBindings(**{k:v for k,v in options.items()
            if k not in {'release_id','source_commit','evidence_root'}})
    module.create_mission_bindings = create
    monkeypatch.setitem(sys.modules, module.__name__, module)
    before = truth.store.path.read_bytes()
    code = main(['run','--ledger',str(truth.store.path),'--source-commit',COMMIT,
        '--release-batch',BATCH,'--release-id',RELEASE,'--bindings-module',module.__name__,
        '--package-root',str(root),'--evidence-root',str(tmp_path/'evidence')])
    assert code == 37
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'HOLD' and result['reason'] == 'FIELD_MISSION_Q7_ADMISSION_HOLD'
    assert result['bank_final'] is result['field_verified'] is False
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize('manifest',['missing','invalid'])
def test_deleted_full_manifest_cannot_downgrade_cli_to_component_before_host_loading(tmp_path,monkeypatch,capsys,manifest):
    from rc72_pip_field_test_support import provider
    truth,_=_setup(tmp_path)
    start_n1(truth)
    # Trusted prior Field fixture claims a full package, but deliberately has
    # no live full manifest. The CLI must refuse it before any host callback.
    root=provider(truth,source_commit=COMMIT).root
    if manifest=='invalid':(root/'PACKAGE_MANIFEST.json').write_text('{}')
    module=ModuleType('must_not_load_for_missing_full_manifest')
    def forbidden(**kwargs):pytest.fail('missing full manifest loaded host')
    module.create_mission_bindings=forbidden
    monkeypatch.setitem(sys.modules,module.__name__,module)
    before=truth.store.path.read_bytes()
    code=main(['run','--ledger',str(truth.store.path),'--source-commit',COMMIT,
        '--release-batch',BATCH,'--release-id',RELEASE,'--bindings-module',module.__name__,
        '--package-root',str(root),'--evidence-root',str(tmp_path/'evidence')])
    result=json.loads(capsys.readouterr().out)
    assert code==37 and result['status']=='HOLD'
    assert result['field_verified'] is result['bank_final'] is False
    assert truth.store.path.read_bytes()==before


def test_canonical_host_loader_passes_exact_batch_and_reenters_signed_live_captain(
        tmp_path, monkeypatch):
    """Positive product ingress: approved Host, signed session, R1, factory N7."""
    from rc7_release.rc72_captain_host_reentry import reenter_host_captain
    from rc7_runtime.rc72_mission_factory import create_mission_driver
    from test_rc72_captain_host_reentry import _fixture, _signed, _reenter

    truth, host_key, lease = _fixture(tmp_path)
    ticket = _signed(host_key, lease)
    cold = __import__('rc6_runtime.truth', fromlist=['TruthRuntime']).TruthRuntime(
        truth.store.path)
    module = ModuleType('approved_dsh_host_batch_reentry')

    def create(*, truth, release_id, source_commit, release_batch_id):
        assert release_batch_id == BATCH
        assert release_id == RELEASE and source_commit == COMMIT
        _, options = _setup(tmp_path, truth=truth)
        binding = reenter_host_captain(
            truth, release_id=release_id, source_commit=source_commit,
            release_batch_id=release_batch_id, observed=ticket,
            host_authority=host_key,
            approved_capabilities=('api_http',),
            role_profiles={'L3_EXECUTE': ('api_http',)})
        options['captain_binding'] = binding
        return MissionHostBindings(**{k: v for k, v in options.items()
            if k not in {'release_id', 'source_commit', 'evidence_root'}})

    module.create_mission_bindings = create
    monkeypatch.setitem(sys.modules, module.__name__, module)
    before = truth.store.path.read_bytes()
    bound = load_mission_bindings(
        module.__name__, truth=cold, release_id=RELEASE,
        source_commit=COMMIT, release_batch_id=BATCH)
    assert bound.captain_binding.captain_lease_id == lease['lease_id']
    _, options = _setup(tmp_path, truth=cold)
    options['captain_binding'] = bound.captain_binding
    driver = create_mission_driver(cold, **options)
    driver._assert_captain_product_entry(lease['mission_id'])
    assert truth.store.path.read_bytes() == before
    assert cold.query('execution_attempt') == []


@pytest.mark.parametrize('mutation,reason', [
    ('legacy_factory', 'CAPTAIN_BATCH_AWARE_FACTORY_REQUIRED'),
    ('missing_captain', 'CAPTAIN_HOST_BINDING_REQUIRED'),
])
def test_captain_owned_batch_rejects_legacy_or_unbound_host_before_business_effects(
        tmp_path, monkeypatch, mutation, reason):
    from test_rc72_captain_host_reentry import _fixture
    truth, _, lease = _fixture(tmp_path)
    module = ModuleType('unbound_captain_host')
    observed = []

    if mutation == 'legacy_factory':
        def create(*, truth, release_id, source_commit):
            observed.append('LEGACY_FACTORY_EXECUTED')
            raise AssertionError('must fail before caller code')
    else:
        def create(*, truth, release_id, source_commit, release_batch_id):
            observed.append(release_batch_id)
            _, options = _setup(tmp_path, truth=truth)
            return MissionHostBindings(**{k: v for k, v in options.items()
                if k not in {'release_id', 'source_commit', 'evidence_root'}})
    module.create_mission_bindings = create
    monkeypatch.setitem(sys.modules, module.__name__, module)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='MISSION_BINDINGS_' + reason):
        load_mission_bindings(module.__name__, truth=truth, release_id=RELEASE,
                              source_commit=COMMIT, release_batch_id=BATCH)
    assert observed == ([] if mutation == 'legacy_factory' else [BATCH])
    assert truth.store.path.read_bytes() == before
    assert not truth.query('execution_attempt')
