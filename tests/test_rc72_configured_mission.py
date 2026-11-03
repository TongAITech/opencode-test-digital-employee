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
