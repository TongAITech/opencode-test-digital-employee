"""Generated boot-time native MCP capability projection; no real model calls."""
import json
import shutil
import subprocess

import pytest
from rc7_release import dsh
from rc7_release.rc72_configured_mission import configured_mission_bindings
from rc7_runtime.models import ContractError
from test_rc72_configured_mission import _setup
from rc72_n2_test_support import RELEASE,COMMIT


def test_native_gate_token_is_explicit_boot_expression_without_materialized_secret(tmp_path,monkeypatch):
    for key in dsh.NATIVE_WORKER_MCP_ENV_KEYS:
        monkeypatch.setenv(key,'synthetic-private-'+key)
    monkeypatch.setenv('CAPTAIN_SIGNING_KEY','synthetic-control-key')
    monkeypatch.setenv('MODEL_API_TOKEN','synthetic-model-token')
    path=dsh.write_patch(tmp_path/'worker.yml',tmp_path,'carried-python.exe')
    text=path.read_text()
    assert 'synthetic-private-' not in text
    assert 'synthetic-control-key' not in text and 'synthetic-model-token' not in text
    assert 'CAPTAIN_SIGNING_KEY' not in text and 'MODEL_API_TOKEN' not in text
    for key in dsh.NATIVE_WORKER_MCP_ENV_KEYS:
        assert key+": !!js process.env."+key+" ?? ''" in text


def test_boot_expressions_restore_only_current_native_capability_after_sdk_scrub(tmp_path):
    node=shutil.which('node')
    if not node:pytest.skip('Node is required to evaluate SDK JavaScript patch expressions')
    path=dsh.write_patch(tmp_path/'worker.yml',tmp_path,'carried-python.exe')
    expressions={}
    for line in path.read_text().splitlines():
        if ': !!js ' in line:
            name,expression=line.strip().split(': !!js ',1)
            expressions[name]=expression
    script='''const expressions=JSON.parse(process.argv[1]);
const original={PFC_RC72_TOOL_GATE_URL:'http://127.0.0.1:1/call',
 PFC_RC72_TOOL_GATE_TOKEN:'ephemeral-worker-capability',
 PFC_RC72_TOOL_GATE_CONTEXT:'current-task-context',PFC_RC72_TOOL_GATE_PROTOCOL:'current-protocol',
 MODEL_API_TOKEN:'private-model-token',CAPTAIN_SIGNING_KEY:'private-control-key'};
const scrubbed=Object.fromEntries(Object.entries(original).filter(([k])=>!/KEY|PASSWORD|SECRET|TOKEN/i.test(k)&&!k.toUpperCase().startsWith('DSH_')));
if ('PFC_RC72_TOOL_GATE_TOKEN' in scrubbed) throw Error('scrub fixture did not exercise token removal');
const extra=Object.fromEntries(Object.entries(expressions).map(([k,v])=>[k,Function('process','return ('+v+')')({env:original})]));
const child={...scrubbed,...extra};
if (child.PFC_RC72_TOOL_GATE_TOKEN!=='ephemeral-worker-capability') throw Error('capability lost');
if ('MODEL_API_TOKEN' in child || 'CAPTAIN_SIGNING_KEY' in child) throw Error('unrelated credential forwarded');
for (const [k,v] of Object.entries(expressions)) if(Function('process','return ('+v+')')({env:{}})!=='') throw Error('stale fallback');
console.log(JSON.stringify({verified:true,keys:Object.keys(extra)}));'''
    result=subprocess.run([node,'-e',script,json.dumps(expressions)],capture_output=True,text=True,check=True,timeout=15)
    assert json.loads(result.stdout)==dict(verified=True,keys=list(dsh.NATIVE_WORKER_MCP_ENV_KEYS))


@pytest.mark.parametrize('name',dsh.NATIVE_WORKER_MCP_ENV_KEYS)
def test_model_environment_selection_cannot_supply_native_gate_capabilities(tmp_path,monkeypatch,name):
    truth,config,path=_setup(tmp_path,monkeypatch)
    config['model_environment_names']=[name]
    path.write_text(json.dumps(config))
    before=truth.store.path.read_bytes()
    with pytest.raises(ContractError,match='CONTROL_ENVIRONMENT_FORBIDDEN'):
        configured_mission_bindings(truth,release_id=RELEASE,source_commit=COMMIT,config_path=path)
    assert not (tmp_path/'owned-state').exists() and truth.store.path.read_bytes()==before


@pytest.mark.parametrize('forward_native',[False,True],ids=['scrub-without-capability','explicit-native-capability'])
def test_actual_parent_read_through_child_mcp_after_sdk_credential_scrub(tmp_path,forward_native):
    node=shutil.which('node')
    if not node:pytest.skip('Node is required for boot expression evaluation')
    from test_rc72_native_n1_read_gate import _service, BATCH, MISSION
    service,truth,calls,_source=_service(tmp_path)
    generated=dsh.write_patch(tmp_path/'generated-worker.yml',tmp_path,'carried-python.exe')
    expressions={}
    for line in generated.read_text().splitlines():
        if ': !!js ' in line:
            name,expression=line.strip().split(': !!js ',1)
            expressions[name]=expression
    original=service.launcher.command_runner
    script='''const expressions=JSON.parse(process.argv[1]);
const env=Object.fromEntries(Object.entries(process.env).filter(([k])=>!/KEY|PASSWORD|SECRET|TOKEN/i.test(k)&&!k.toUpperCase().startsWith('DSH_')));
if (process.argv[2]==='forward') for (const [key,value] of Object.entries(expressions)) env[key]=Function('process','return ('+value+')')(process);
console.log(JSON.stringify(env));'''
    def runner(command,**kwargs):
        projected=subprocess.run([node,'-e',script,json.dumps(expressions),'forward' if forward_native else 'scrub'],
            env=kwargs['env'],capture_output=True,text=True,check=True,timeout=15)
        environment=json.loads(projected.stdout)
        assert bool(environment.get('PFC_RC72_TOOL_GATE_TOKEN')) is forward_native
        return original(command,**dict(kwargs,env=environment))
    service.launcher.command_runner=runner
    if forward_native:
        assert service.handoff(release_batch_id=BATCH)['status']=='SESSION_OBSERVED'
        reads=truth.query('rc72_n1_native_read',kind='CALL')
        assert len(reads)==1 and reads[0]['state']=='RETURNED'
        assert json.loads(reads[0]['result']['text'])=={'actual':'observed'}
    else:
        with pytest.raises(Exception):service.handoff(release_batch_id=BATCH)
        assert not truth.query('rc72_n1_native_read',kind='CALL')
        assert not truth.query('rc72_mission_node_worker_attempt',mission_id=MISSION)
