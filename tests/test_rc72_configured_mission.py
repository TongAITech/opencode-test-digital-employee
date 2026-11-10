"""Owned configuration assembly, cold authority continuity, no execution facts."""
from rc7_runtime.rc72_code_tool_binding import NATIVE_CODE_TOOLS
import json
import os
import sys
from types import ModuleType
from pathlib import Path

import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_mission_factory import ROLES, create_mission_driver
from rc7_runtime.rc72_native_n1_read_gate import TOOL
from rc7_release.rc72_configured_mission import SCHEMA, configured_mission_bindings
from rc7_release.rc72_mission_cli import main
from rc72_n2_test_support import build_truth, start_n1, RELEASE, COMMIT, BATCH
from rc72_formal_runner_support import LocalHTTPEnvironment


def _setup(tmp_path, monkeypatch):
    truth = build_truth(tmp_path)
    root = tmp_path/'package'
    root.mkdir()
    (root/'SOURCE_COMMIT').write_text(COMMIT)
    for name in ('patch.yml','archive.zip','pip-field.json','original-input.json'):
        (tmp_path/name).write_text('{}')
    module = ModuleType('configured_environment_fixture')
    module.create_execution_environment = lambda: LocalHTTPEnvironment('http://127.0.0.1:1',tmp_path/'output')
    monkeypatch.setitem(sys.modules, module.__name__, module)
    config = dict(schema=SCHEMA, release_id=RELEASE, source_commit=COMMIT,
        package_root='package', state_root='owned-state', dsh_bin=sys.executable,
        patch_path='patch.yml', archive='archive.zip', pip_field_config='pip-field.json',
        inputs=[dict(source_ref='release-batch://approved-input',path='original-input.json')],
        role_tools={role: [TOOL] if role=='reality' else list(NATIVE_CODE_TOOLS)
            if role in ('code','code_review') else ['scoped-tool'] for role in ROLES},
        tool_registry={'api_http':['api_http']}, environment_module=module.__name__,
        model_environment_names=['APPROVED_MODEL_API_KEY'])
    monkeypatch.setenv('APPROVED_MODEL_API_KEY','private-model-sentinel')
    monkeypatch.setenv('UNRELATED_MODEL_API_KEY','unrelated-private-sentinel')
    path = tmp_path/'mission-config.json'
    path.write_text(json.dumps(config))
    return truth, config, path


def test_configured_factory_cold_rebuild_keeps_owned_authorities_without_copying_user_profile(tmp_path, monkeypatch):
    truth, _, path = _setup(tmp_path, monkeypatch)
    before = truth.store.path.read_bytes()
    first = configured_mission_bindings(truth, release_id=RELEASE, source_commit=COMMIT,config_path=path)
    cold = TruthRuntime(truth.store.path)
    second = configured_mission_bindings(cold, release_id=RELEASE, source_commit=COMMIT,config_path=path)
    message = {'purpose':'cold-owned-authority-test'}
    assert first.execution_authority._sign(message) == second.execution_authority._sign(message)
    assert first.bank_pip_mirror.authority._sign(message) == second.bank_pip_mirror.authority._sign(message)
    signatures = {first.execution_authority._sign(message), first.bank_pip_mirror.authority._sign(message)}
    for role in ROLES:
        worker, restarted = first.workers[role].launcher, second.workers[role].launcher
        assert worker.authority._sign(message) == restarted.authority._sign(message)
        assert restarted.truth is cold
        signatures.add(worker.authority._sign(message))
        assert worker.env == {'APPROVED_MODEL_API_KEY':'private-model-sentinel'}
    assert len(signatures) == len(ROLES)+2
    driver = create_mission_driver(cold,release_id=RELEASE,source_commit=COMMIT,
        workers=second.workers,bank_pip_mirror=second.bank_pip_mirror,
        execution_authority=second.execution_authority,execution_environment=second.execution_environment,
        tool_registry=second.tool_registry,evidence_root=tmp_path/'evidence')
    assert driver.n10_pipeline.truth is cold
    keys = list((tmp_path/'owned-state').rglob('controller.key'))
    assert len(keys) == 1 and len(keys[0].read_bytes()) == 32
    if os.name != 'nt': assert keys[0].stat().st_mode & 0o777 == 0o600
    for file in (tmp_path/'owned-state').rglob('*'):
        if file.is_file(): assert b'private-model-sentinel' not in file.read_bytes()
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize('mutation,reason',[
    ('pass_claim','EXACT_CAPABILITY_FIELDS'),('source','RELEASE_SOURCE'),
    ('role','EXACT_ROLE_TOOLS'),('wildcard','EXACT_ROLE_TOOLS'),
    ('code_review','EXACT_ROLE_TOOLS'),('registry','EXACT_EXECUTION_TOOLS'),
    ('inputs','ORIGINAL_INPUTS'),('duplicate_input','DUPLICATE_ORIGINAL_INPUT'),
    ('captain','CONTROL_ENVIRONMENT'),('home','CONTROL_ENVIRONMENT'),
    ('missing_model_env','SELECTED_MODEL_ENVIRONMENT_MISSING')])
def test_invalid_config_fails_before_creating_authority_or_launching_workers(tmp_path,monkeypatch,mutation,reason):
    truth,config,path = _setup(tmp_path,monkeypatch)
    if mutation=='pass_claim':config['status']='PASS'
    elif mutation=='source':config['source_commit']='f'*40
    elif mutation=='role':config['role_tools'].pop('data_verify')
    elif mutation=='wildcard':config['role_tools']['design']=['*']
    elif mutation=='code_review':config['role_tools']['code_review']=['git']
    elif mutation=='registry':config['tool_registry']={'api_http':['*']}
    elif mutation=='inputs':config['inputs']=[]
    elif mutation=='duplicate_input':config['inputs']*=2
    elif mutation=='captain':config['model_environment_names']=['CAPTAIN_SIGNING_KEY']
    elif mutation=='home':config['model_environment_names']=['HOME']
    elif mutation=='missing_model_env':config['model_environment_names']=['MISSING_APPROVED_MODEL_VAR']
    path.write_text(json.dumps(config))
    before=truth.store.path.read_bytes()
    with pytest.raises(ContractError,match=reason):
        configured_mission_bindings(truth,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    assert not (tmp_path/'owned-state').exists()
    assert truth.store.path.read_bytes()==before


def test_existing_captain_release_refuses_unfenced_config_before_controller_bootstrap(tmp_path, monkeypatch):
    """C07: JSON cannot impersonate the DSH Captain or create an unfenced worker."""
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc72_n2_test_support import MISSION

    truth, _, path = _setup(tmp_path, monkeypatch)
    start_n1(truth)
    fencer = CaptainDispatchFencer(truth, release_id=RELEASE)
    fencer.acquire_initial(mission_id=MISSION, team_id='TEAM-CONFIG-DENY',
                           captain_session_id='DSH-REAL-CAPTAIN-SESSION')
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='MISSION_CONFIG_CAPTAIN_HOST_BINDING_REQUIRED'):
        configured_mission_bindings(
            truth, release_id=RELEASE, source_commit=COMMIT, config_path=path)
    assert truth.store.path.read_bytes() == before
    assert not (tmp_path / 'owned-state').exists()
    # Cold recovery must not drop the Captain lease and silently downgrade.
    cold = TruthRuntime(truth.store.path)
    with pytest.raises(ContractError, match='MISSION_CONFIG_CAPTAIN_HOST_BINDING_REQUIRED'):
        configured_mission_bindings(
            cold, release_id=RELEASE, source_commit=COMMIT, config_path=path)
    assert cold.store.path.read_bytes() == before
    assert not (tmp_path / 'owned-state').exists()


def test_configured_captain_preflight_restricts_exact_batch_not_sibling(tmp_path, monkeypatch):
    """A prior Captain in another batch of the same release must not block this batch."""
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc72_n2_test_support import MISSION

    truth, _, path = _setup(tmp_path, monkeypatch)
    start_n1(truth)
    owner = CaptainDispatchFencer(truth, release_id=RELEASE)
    owner.acquire_initial(mission_id=MISSION, team_id='TEAM-SIBLING',
                          captain_session_id='DSH-SIBLING-CAPTAIN')
    source = truth.query('rc72_release_batch', release_batch_id=BATCH)[0]
    other = {k: v for k, v in source.items() if k != 'artifact_type'}
    other.update(release_batch_id='RB-C07-INDEPENDENT', mission_id='MISSION-C07-INDEPENDENT',
                 artifact_version=1)
    truth.append_atomic('RC72_RELEASE_BATCH_UPSERTED', other)
    before = truth.store.path.read_bytes()

    # The actual CLI calls with its exact canonical batch ID.
    scoped = configured_mission_bindings(
        truth, release_id=RELEASE, source_commit=COMMIT, config_path=path,
        release_batch_id='RB-C07-INDEPENDENT')
    assert scoped.captain_binding is None
    assert truth.store.path.read_bytes() == before

    # The already Captain-owned batch cannot be downgraded, even after
    # a fresh process projects the same R1.
    cold = TruthRuntime(truth.store.path)
    with pytest.raises(ContractError, match='MISSION_CONFIG_CAPTAIN_HOST_BINDING_REQUIRED'):
        configured_mission_bindings(
            cold, release_id=RELEASE, source_commit=COMMIT, config_path=path,
            release_batch_id=BATCH)
    assert cold.store.path.read_bytes() == before


@pytest.mark.parametrize('bad_batch', ['', 'RB-MISSING', 42])
def test_configured_captain_preflight_rejects_unknown_batch_before_key(
        tmp_path, monkeypatch, bad_batch):
    truth, _, path = _setup(tmp_path, monkeypatch)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='RELEASE_BATCH_'):
        configured_mission_bindings(
            truth, release_id=RELEASE, source_commit=COMMIT,
            config_path=path, release_batch_id=bad_batch)
    assert truth.store.path.read_bytes() == before
    assert not (tmp_path / 'owned-state').exists()


def test_full_carried_environment_is_owned_and_model_credentials_do_not_enter_runner(tmp_path,monkeypatch):
    from test_rc72_tool_environment import _paths
    from rc7_release.rc72_tool_environment import package_tool_environment
    truth,_,path=_setup(tmp_path,monkeypatch)
    _paths(tmp_path/'package') # path-selection fixture, not package qualification
    before=truth.store.path.read_bytes()
    bindings=configured_mission_bindings(truth,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    selected=package_tool_environment(tmp_path/'package')
    assert bindings.execution_env==selected
    assert 'APPROVED_MODEL_API_KEY' not in bindings.execution_env
    for binding in bindings.workers.values():
        assert binding.launcher.env['PFC_PYTHON']==selected['PFC_PYTHON']
        assert binding.launcher.env['PFC_CODEGRAPH_BIN']==selected['PFC_CODEGRAPH_BIN']
        assert binding.launcher.env['APPROVED_MODEL_API_KEY']=='private-model-sentinel'
    assert truth.store.path.read_bytes()==before


def test_corrupt_owned_key_is_not_silently_replaced(tmp_path,monkeypatch):
    truth,_,path=_setup(tmp_path,monkeypatch)
    configured_mission_bindings(truth,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    key=next((tmp_path/'owned-state').rglob('controller.key'))
    key.write_bytes(b'invalid')
    with pytest.raises(ContractError,match='CONTROLLER_KEY_INVALID'):
        configured_mission_bindings(truth,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    assert key.read_bytes()==b'invalid'


def test_different_ledgers_cannot_share_controller_authority_through_one_config(tmp_path,monkeypatch):
    truth,_,path=_setup(tmp_path,monkeypatch)
    first=configured_mission_bindings(truth,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    other=TruthRuntime(tmp_path/'other-ledger'/Path(truth.store.path).name)
    second=configured_mission_bindings(other,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    assert first.execution_authority._sign({'scope':'test'}) != second.execution_authority._sign({'scope':'test'})


def test_cli_uses_package_config_factory_without_operator_mission_code(tmp_path,monkeypatch,capsys):
    truth,_,path=_setup(tmp_path,monkeypatch)
    start_n1(truth)
    admission=truth.query('rc72_q7_admission')[0]
    admission.update(status='HOLD',reason='upstream engineering admission withheld',
        hold_reasons=['Q7 withheld'],artifact_version=admission['artifact_version']+1)
    truth.append_atomic('RC72_Q7_ADMISSION_UPSERTED',admission)
    before=truth.store.path.read_bytes()
    code=main(['run','--ledger',str(truth.store.path),'--source-commit',COMMIT,
        '--release-batch',BATCH,'--release-id',RELEASE,'--package-root',str(tmp_path/'package'),
        '--evidence-root',str(tmp_path/'evidence'),'--mission-config',str(path)])
    result=json.loads(capsys.readouterr().out)
    assert code==37 and result['reason']=='FIELD_MISSION_Q7_ADMISSION_HOLD'
    assert result['field_verified'] is result['bank_final'] is False
    assert truth.store.path.read_bytes()==before


def test_adapter_error_cannot_expose_private_configuration_or_create_authority(tmp_path,monkeypatch):
    truth,config,path=_setup(tmp_path,monkeypatch)
    def unavailable():
        raise ValueError('private adapter credential value')
    sys.modules[config['environment_module']].create_execution_environment=unavailable
    with pytest.raises(ContractError) as error:
        configured_mission_bindings(truth,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    assert str(error.value)=='MISSION_CONFIG_EXECUTION_ENVIRONMENT_UNAVAILABLE'
    assert error.value.__suppress_context__ is True
    assert not (tmp_path/'owned-state').exists()


def test_native_mirror_cli_refuses_unqualified_component_and_cannot_start_nodes(tmp_path,monkeypatch,capsys):
    truth,_,path=_setup(tmp_path,monkeypatch)
    start_n1(truth)
    nodes=truth.query('rc72_mission_node')
    code=main(['mirror-check','--ledger',str(truth.store.path),'--source-commit',COMMIT,
        '--release-batch',BATCH,'--release-id',RELEASE,'--package-root',str(tmp_path/'package'),
        '--evidence-root',str(tmp_path/'evidence'),'--mission-config',str(path)])
    result=json.loads(capsys.readouterr().out)
    assert code==37 and result['status']=='HOLD'
    assert result['field_verified'] is result['bank_final'] is False
    truth.rebuild_projection()
    assert truth.query('rc72_mission_node')==nodes
    assert not truth.query('rc72_mission_node_worker_attempt')


def _n9_v2_config(tmp_path, monkeypatch):
    from rc7_release.rc72_configured_mission import SCHEMA_V2

    truth, config, path = _setup(tmp_path, monkeypatch)
    config['schema'] = SCHEMA_V2
    config['n9_read_only_tools'] = ['read_only_diagnostic']
    path.write_text(json.dumps(config))
    return truth, config, path


def test_configured_v2_product_owns_real_independent_n9_dsh_and_no_r1_side_effects(
        tmp_path, monkeypatch):
    """C04 product ingress genuinely owns a separate DSH analyst, not a label."""
    from dataclasses import fields
    from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
    from rc7_runtime.rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService

    truth, config, path = _n9_v2_config(tmp_path, monkeypatch)
    before = truth.store.path.read_bytes()
    bindings = configured_mission_bindings(
        truth, release_id=RELEASE, source_commit=COMMIT, config_path=path)
    professional = bindings.professional_dsh_binding
    assert professional is not None
    assert type(professional.launcher) is DshHeadlessWorkerLauncher
    assert professional.tools == ('read_only_diagnostic',)
    assert professional.launcher.truth is truth
    assert professional.launcher.release_id == RELEASE
    assert professional.launcher.env['APPROVED_MODEL_API_KEY'] == 'private-model-sentinel'
    assert all(professional.launcher is not w.launcher
               for w in bindings.workers.values())
    assert all(professional.launcher.state_root != w.launcher.state_root
               for w in bindings.workers.values())
    assert all(professional.launcher.authority is not w.launcher.authority
               for w in bindings.workers.values())
    driver = create_mission_driver(
        truth, release_id=RELEASE, source_commit=COMMIT,
        evidence_root=tmp_path / 'n9-independent-evidence',
        **{field.name: getattr(bindings, field.name) for field in fields(bindings)})
    assert type(driver.n8_pipeline.professional_dsh) is NativeN9ProfessionalDshAnalysisService
    assert driver.n8_pipeline.professional_dsh.launcher is professional.launcher
    assert driver.n8_pipeline.professional_dsh.pipeline is driver.n7_pipeline
    assert driver.n8_pipeline.professional_dsh.allowed_tools == ('read_only_diagnostic',)
    assert truth.store.path.read_bytes() == before
    assert not truth.query('rc72_n9_professional_dsh_analysis')
    assert not truth.query('rc7_defect')

    cold = TruthRuntime(truth.store.path)
    again = configured_mission_bindings(
        cold, release_id=RELEASE, source_commit=COMMIT, config_path=path)
    assert again.professional_dsh_binding.launcher.truth is cold
    specimen = {'purpose': 'n9-review-private-authority'}
    assert (again.professional_dsh_binding.launcher.authority._sign(specimen)
            == professional.launcher.authority._sign(specimen))
    assert (again.professional_dsh_binding.launcher.authority._sign(specimen)
            != again.execution_authority._sign(specimen))
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize('mutation,reason', [
    ('missing', 'EXACT_CAPABILITY_FIELDS'),
    ('v1_extra', 'EXACT_CAPABILITY_FIELDS'),
    ('wildcard', 'N9_EXACT_READ_ONLY_TOOLS'),
    ('api_write', 'N9_EXACT_READ_ONLY_TOOLS'),
    ('empty', 'N9_EXACT_READ_ONLY_TOOLS'),
    ('duplicate', 'N9_EXACT_READ_ONLY_TOOLS'),
    ('overlap_registry', 'N9_EXACT_READ_ONLY_TOOLS'),
    ('extra_secret', 'EXACT_CAPABILITY_FIELDS'),
])
def test_configured_v2_n9_denies_implicit_full_access_before_controller_key_or_r1(
        tmp_path, monkeypatch, mutation, reason):
    truth, config, path = _n9_v2_config(tmp_path, monkeypatch)
    if mutation == 'missing':
        config.pop('n9_read_only_tools')
    elif mutation == 'v1_extra':
        config['schema'] = SCHEMA
    elif mutation == 'wildcard':
        config['n9_read_only_tools'] = ['*']
    elif mutation == 'api_write':
        config['n9_read_only_tools'] = ['api_http']
    elif mutation == 'empty':
        config['n9_read_only_tools'] = []
    elif mutation == 'duplicate':
        config['n9_read_only_tools'] = ['read_only_diagnostic'] * 2
    elif mutation == 'overlap_registry':
        config['tool_registry']['diagnostic'] = ['read_only_diagnostic']
    elif mutation == 'extra_secret':
        config['n9_captain_token'] = 'invalid-unsafe-value'
    path.write_text(json.dumps(config))
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match=reason):
        configured_mission_bindings(
            truth, release_id=RELEASE, source_commit=COMMIT, config_path=path)
    assert truth.store.path.read_bytes() == before
    assert not (tmp_path / 'owned-state').exists()



def _observed_live_captain(truth, *, team="BANK-DSH-TEAM"):
    """Deterministic signed Host observation; no fake bank Field PASS."""
    from dataclasses import replace
    import time
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    from rc7_release.rc72_captain_host_reentry import ObservedDshCaptain
    from rc72_n2_test_support import MISSION
    start_n1(truth)
    lease = CaptainDispatchFencer(truth, release_id=RELEASE).acquire_initial(
        mission_id=MISSION, team_id=team,
        captain_session_id="LIVE-DSH-AGENTTEAMS-CAPTAIN",
        ttl_seconds=300)
    host = RC72AuthorityRuntime(b"isolated-bank-approved-agentteams-host-observer")
    claimed = ObservedDshCaptain(
        release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, mission_id=MISSION,
        team_id=lease["team_id"],
        captain_session_id=lease["captain_session_id"],
        captain_lease_id=lease["lease_id"],
        captain_generation=lease["generation"],
        dsh_session_ref="dsh://agentteams/host-observed-live-session",
        observed_at=int(time.time()), state="ACTIVE", signature="pending")
    observed = replace(claimed, signature=host._sign(claimed.signed_fields()))
    return lease, host, observed


def _live_capabilities(host, observed, *, include_n9=False):
    roles = {"L3_EXECUTE": ("api_http",)}
    allowed = ("api_http",)
    if include_n9:
        roles["N9_QUALIFY"] = ("defect_analysis",)
        allowed = ("api_http", "defect_analysis")
    return dict(observed_captain=observed, host_authority=host,
                captain_role_profiles=roles, captain_approved_capabilities=allowed)


def test_configured_host_live_captain_governs_real_factory_and_cold_restart(
        tmp_path, monkeypatch):
    """One exact ACTIVE DSH Captain and scoped N9, no unfenced local fallback."""
    from dataclasses import fields
    from rc7_release.rc72_configured_mission import SCHEMA_V2
    from rc7_runtime.rc72_n9_captain_worker_bridge import NativeN9CaptainSignedDshBridge

    truth, config, path = _setup(tmp_path, monkeypatch)
    config["schema"] = SCHEMA_V2
    config["n9_read_only_tools"] = ["read_only_diagnostic"]
    path.write_text(json.dumps(config))
    lease, host, observed = _observed_live_captain(truth)
    scope = _live_capabilities(host, observed, include_n9=True)
    before = truth.store.path.read_bytes()
    first = configured_mission_bindings(
        truth, release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, config_path=path, **scope)
    assert first.captain_binding.captain_lease_id == lease["lease_id"]
    assert first.captain_binding.captain_session_id == lease["captain_session_id"]
    assert first.captain_binding.team_id == lease["team_id"]
    assert first.captain_binding.scheduler.role_profiles["N9_QUALIFY"] == frozenset(("defect_analysis",))
    assert first.professional_dsh_binding.captain_governed_dsh is True
    assert first.professional_dsh_binding.tools == ("read_only_diagnostic",)
    driver = create_mission_driver(
        truth, release_id=RELEASE, source_commit=COMMIT,
        evidence_root=tmp_path/"governed-evidence",
        **{field.name: getattr(first, field.name) for field in fields(first)})
    assert driver.n7_pipeline.captain_scheduler is first.captain_binding.scheduler
    assert driver.n8_pipeline.professional_dsh.captain_dsh_bridge is not None
    assert isinstance(driver.n8_pipeline.professional_dsh.captain_dsh_bridge,
                      NativeN9CaptainSignedDshBridge)
    driver._assert_captain_product_entry(lease["mission_id"])
    assert truth.store.path.read_bytes() == before
    assert not truth.query("execution_attempt")
    assert not truth.query("rc72_captain_etu_admission")
    assert not truth.query("rc72_n9_professional_dsh_analysis")
    assert not truth.query("rc7_defect")

    cold = TruthRuntime(truth.store.path)
    again = configured_mission_bindings(
        cold, release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, config_path=path, **scope)
    assert again.captain_binding.scheduler.truth is cold
    assert again.captain_binding.captain_lease_id == lease["lease_id"]
    assert again.professional_dsh_binding.captain_governed_dsh
    assert again.professional_dsh_binding.launcher.truth is cold
    assert (again.professional_dsh_binding.launcher.authority._sign({"proof": 1})
            == first.professional_dsh_binding.launcher.authority._sign({"proof": 1}))
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize("mutation,reason", [
    ("missing", "CAPTAIN_HOST_BINDING_REQUIRED"),
    ("unsigned", "OBSERVATION_SIGNATURE_INVALID"),
    ("other_host", "OBSERVATION_SIGNATURE_INVALID"),
    ("other_batch", "OBSERVED_SESSION_SCOPE_CHANGED"),
    ("other_team", "OBSERVATION_SIGNATURE_INVALID"),
    ("role_escalation", "ROLE_CAPABILITY_SCOPE_CHANGED"),
    ("tool_escalation", "ROLE_CAPABILITY_SCOPE_CHANGED"),
    ("wrong_n9_role", "ROLE_CAPABILITY_SCOPE_CHANGED"),
    ("no_batch", "CAPTAIN_EXACT_BATCH_REQUIRED"),
])
def test_configured_host_denies_unverified_captain_or_escalation_before_controller_bootstrap(
        tmp_path, monkeypatch, mutation, reason):
    from dataclasses import replace
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    from rc7_release.rc72_configured_mission import SCHEMA_V2

    truth, config, path = _setup(tmp_path, monkeypatch)
    config["schema"] = SCHEMA_V2
    config["n9_read_only_tools"] = ["read_only_diagnostic"]
    path.write_text(json.dumps(config))
    lease, host, observed = _observed_live_captain(truth)
    params = _live_capabilities(host, observed, include_n9=True)
    batch = BATCH
    if mutation == "missing":
        params = {}
    elif mutation == "unsigned":
        params["observed_captain"] = replace(observed, signature="INVALID")
    elif mutation == "other_host":
        params["host_authority"] = RC72AuthorityRuntime(b"foreign-host-not-authorized")
    elif mutation == "other_batch":
        changed = replace(observed, release_batch_id="RB-OTHER")
        params["observed_captain"] = replace(
            changed, signature=host._sign(changed.signed_fields()))
    elif mutation == "other_team":
        params["observed_captain"] = replace(observed, team_id="FOREIGN-TEAM")
    elif mutation == "role_escalation":
        params["captain_role_profiles"] = {"L3_EXECUTE": ("api_http", "db_write"),
                                           "N9_QUALIFY": ("defect_analysis",)}
    elif mutation == "tool_escalation":
        params["captain_approved_capabilities"] = ("api_http", "defect_analysis", "db_write")
    elif mutation == "wrong_n9_role":
        params["captain_role_profiles"] = {"L3_EXECUTE": ("api_http",),
                                           "N9_QUALIFY": ("api_http",)}
    elif mutation == "no_batch":
        batch = None
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match=reason):
        configured_mission_bindings(
            truth, release_id=RELEASE, source_commit=COMMIT,
            config_path=path, release_batch_id=batch, **params)
    assert truth.store.path.read_bytes() == before
    assert not (tmp_path/"owned-state").exists()
    assert not truth.query("rc72_captain_etu_admission")


def test_signed_host_configured_entry_can_be_loaded_by_official_batch_aware_module(
        tmp_path, monkeypatch):
    """The fixed host-module API, not a JSON session string, is the CLI entry."""
    from rc7_release.rc72_mission_bindings import load_mission_bindings
    truth, config, path = _setup(tmp_path, monkeypatch)
    lease, host, observed = _observed_live_captain(truth)
    signed = _live_capabilities(host, observed)
    module = ModuleType("bank_approved_c07_agentteams_host")
    module.create_mission_bindings = (
        lambda *, truth, release_id, source_commit, release_batch_id:
        configured_mission_bindings(
            truth, release_id=release_id, source_commit=source_commit,
            release_batch_id=release_batch_id, config_path=path, **signed))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    before = truth.store.path.read_bytes()
    bindings = load_mission_bindings(
        module.__name__, truth=truth, release_id=RELEASE,
        source_commit=COMMIT, release_batch_id=BATCH)
    assert bindings.captain_binding.captain_lease_id == lease["lease_id"]
    assert bindings.professional_dsh_binding is None
    assert truth.store.path.read_bytes() == before




def test_package_config_live_dsh_host_starts_first_captain_and_n9_with_one_signed_generation(
        tmp_path, monkeypatch):
    from dataclasses import fields, replace
    import time
    from rc7_release.rc72_captain_host_reentry import ObservedDshCaptainStartup
    from rc7_release.rc72_configured_mission import SCHEMA_V2
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    from rc72_n2_test_support import MISSION

    truth, config, path = _setup(tmp_path, monkeypatch)
    config["schema"] = SCHEMA_V2
    config["n9_read_only_tools"] = ["read_only_diagnostic"]
    path.write_text(json.dumps(config))
    start_n1(truth)
    host_key = RC72AuthorityRuntime(b"bank-agentteams-host-first-captain-key")
    proposed = ObservedDshCaptainStartup(
        release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, mission_id=MISSION,
        team_id="REAL-BANK-AGENTTEAMS-TEAM",
        captain_session_id="ACTUAL-DSH-HOST-OBSERVED-CAPTAIN",
        dsh_session_ref="dsh://agentteams/host-verified-first-session",
        observed_at=int(time.time()), state="ACTIVE", signature="PENDING")
    attested = replace(proposed, signature=host_key._sign(proposed.signed_fields()))
    kwargs = dict(
        release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, config_path=path,
        observed_captain_startup=attested, host_authority=host_key,
        captain_role_profiles={"L3_EXECUTE": ("api_http",),
                               "N9_QUALIFY": ("defect_analysis",)},
        captain_approved_capabilities=("api_http", "defect_analysis"))
    before = truth.store.path.read_bytes()
    bindings = configured_mission_bindings(truth, **kwargs)
    assert truth.store.path.read_bytes() != before
    lease = truth.query("rc72_captain_dispatch_lease")
    assert len(lease) == 1
    assert lease[0]["generation"] == 1 and lease[0]["state"] == "ACTIVE"
    assert lease[0]["captain_session_id"] == proposed.captain_session_id
    assert bindings.captain_binding.captain_lease_id == lease[0]["lease_id"]
    assert bindings.professional_dsh_binding.captain_governed_dsh is True
    driver = create_mission_driver(
        truth, release_id=RELEASE, source_commit=COMMIT,
        evidence_root=tmp_path/"first-captain-evidence",
        **{field.name: getattr(bindings, field.name) for field in fields(bindings)})
    assert driver.n7_pipeline.captain_scheduler is bindings.captain_binding.scheduler
    assert driver.n8_pipeline.professional_dsh.captain_dsh_bridge is not None
    assert driver._assert_captain_product_entry(MISSION) is None
    assert not truth.query("execution_attempt")
    assert not truth.query("rc72_captain_etu_admission")
    assert not truth.query("rc7_defect")
    after = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="MISSION_CONFIG_CAPTAIN_HOST_BINDING_REQUIRED"):
        configured_mission_bindings(truth, **kwargs)
    assert truth.store.path.read_bytes() == after

    # Host module with exact batch scope drives the fixed CLI product binding,
    # never a mission JSON field containing a forged Captain session.
    module = ModuleType("bank_signed_first_captain_host_module")
    def trusted_host(*, truth, release_id, source_commit, release_batch_id):
        # The real external Host obtains the *current* signed observation.
        from rc7_release.rc72_captain_host_reentry import ObservedDshCaptain
        owner = truth.query("rc72_captain_dispatch_lease", mission_id=MISSION)[0]
        current = ObservedDshCaptain(
            release_id=release_id, source_commit=source_commit,
            release_batch_id=release_batch_id, mission_id=MISSION,
            team_id=owner["team_id"],
            captain_session_id=owner["captain_session_id"],
            captain_lease_id=owner["lease_id"],
            captain_generation=owner["generation"],
            dsh_session_ref=attested.dsh_session_ref,
            observed_at=int(time.time()), state="ACTIVE", signature="PENDING")
        current = replace(current, signature=host_key._sign(current.signed_fields()))
        opts = dict(kwargs, release_id=release_id,
                    source_commit=source_commit, release_batch_id=release_batch_id)
        opts.pop("observed_captain_startup")
        opts["observed_captain"] = current
        return configured_mission_bindings(truth, **opts)
    module.create_mission_bindings = trusted_host
    monkeypatch.setitem(sys.modules, module.__name__, module)
    from rc7_release.rc72_mission_bindings import load_mission_bindings
    cold = TruthRuntime(truth.store.path)
    restored = load_mission_bindings(
        module.__name__, truth=cold, release_id=RELEASE,
        source_commit=COMMIT, release_batch_id=BATCH)
    assert restored.captain_binding.captain_lease_id == lease[0]["lease_id"]
    assert truth.store.path.read_bytes() == after


def test_full_package_field_run_requires_actual_host_captain(tmp_path):
    """GAP-02: full Field run cannot fall back to DSH chat-only team."""
    from types import SimpleNamespace
    import pytest
    from rc7_runtime.models import ContractError
    from rc7_release.rc72_mission_cli import _require_field_captain
    (tmp_path / 'PACKAGE_MANIFEST.json').write_text('{}', encoding='utf-8')
    ungoverned = SimpleNamespace(captain_binding=None)
    with pytest.raises(ContractError, match='C07_REAL_DSH_CAPTAIN_HOST_REQUIRED_FOR_FIELD_RUN'):
        _require_field_captain('run', tmp_path, ungoverned)
    # Read-only mirror or component checks do not claim a Captain or Field run.
    _require_field_captain('mirror-check', tmp_path, ungoverned)
    (tmp_path / 'PACKAGE_MANIFEST.json').unlink()
    _require_field_captain('run', tmp_path, ungoverned)
    # Positive Host observation remains the responsibility of the signed
    # captain_bootstrap/reentry and MissionFactory, not a string in a config.


def test_trusted_local_agentteams_factory_probes_dsh_before_real_captain_binding(tmp_path, monkeypatch):
    """GAP-02: package factory accepts only separately signed live membership."""
    from rc7_release.rc72_dsh_agentteams_factory import (
        BankCaptainTrustRoots, CaptainProviderWiring, configured_agentteams_host_bindings)
    from test_rc72_dsh_agentteams_host import _local_server, _host, _proof

    truth, _config, path = _setup(tmp_path, monkeypatch)
    start_n1(truth)
    server = _local_server()
    try:
        host, membership_key = _host(server)
        provider = ModuleType('bank_agentteams_control_plane_provider')
        def observe(**kwargs):
            assert kwargs['truth'] is truth
            assert kwargs['release_batch_id'] == BATCH
            return CaptainProviderWiring(
                proof=_proof(membership_key),
                membership_authority=membership_key,
                host_authority=host.host_authority,
                role_profiles={'L3_EXECUTE': ('api_http',)},
                approved_capabilities=('api_http',))
        provider.create_captain_observation_provider = observe
        monkeypatch.setitem(sys.modules, provider.__name__, provider)
        bound = configured_agentteams_host_bindings(
            truth, release_id=RELEASE, source_commit=COMMIT,
            release_batch_id=BATCH, config_path=path,
            provider_module=provider.__name__,
            dsh_base_url='http://127.0.0.1:%d' % server.server_port,
            bank_trust_roots=BankCaptainTrustRoots(
                provider.__name__, membership_key, host.host_authority))
        assert bound.captain_binding is not None
        assert bound.captain_binding.captain_session_id == 'session-real-dsh-captain-001'
        assert len(truth.query('rc72_captain_dispatch_lease')) == 1
        assert not truth.query('execution_attempt')
    finally:
        server.shutdown()
        server.server_close()


def test_run_rejects_q7_hold_before_any_signed_host_observation_or_lease(tmp_path, monkeypatch, capsys):
    """GAP-02: failed bank admission must not even invoke DSH Host provider."""
    truth, _config, path = _setup(tmp_path, monkeypatch)
    start_n1(truth)
    admission = truth.query('rc72_q7_admission')[0]
    admission.update(status='HOLD', reason='unaccepted bank mirror',
                     hold_reasons=['bank mirror not verified'],
                     artifact_version=admission['artifact_version'] + 1)
    truth.append_atomic('RC72_Q7_ADMISSION_UPSERTED', admission)
    provider = ModuleType('must_not_observe_dsh_before_q7')
    def forbidden(**kwargs):
        pytest.fail('real DSH provider called before Q7 admission')
    provider.create_captain_observation_provider = forbidden
    monkeypatch.setitem(sys.modules, provider.__name__, provider)
    before = truth.store.path.read_bytes()
    code = main(['run', '--ledger', str(truth.store.path),
        '--source-commit', COMMIT, '--release-batch', BATCH,
        '--release-id', RELEASE, '--package-root', str(tmp_path / 'package'),
        '--evidence-root', str(tmp_path / 'evidence'), '--mission-config', str(path),
        '--captain-observer-module', provider.__name__])
    result = json.loads(capsys.readouterr().out)
    assert code == 37 and result['reason'] == 'FIELD_MISSION_Q7_ADMISSION_HOLD'
    assert truth.store.path.read_bytes() == before
    assert not truth.query('rc72_captain_dispatch_lease')
    assert not (tmp_path / 'owned-state').exists()
