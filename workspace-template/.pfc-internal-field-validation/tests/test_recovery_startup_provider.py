"""Actual normal entry with auth pending; governed host projection and custom SDK.

Only the terminal attach seam is replaced. OpenCode and Control Loop are actual
processes. The local synthetic wizard fixture is not a bank model qualification.
"""
from __future__ import annotations
import base64
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.request

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE.parent / 'tools/recovery'))
import launcher
import host_provider


def contract_checks(root):
    home = root / 'host'
    cfgroot = home / '.config/opencode'
    cfgroot.mkdir(parents=True)
    path = cfgroot / 'opencode.jsonc'
    sdk = cfgroot / 'wizard.mjs'
    sdk.write_text('''export function createWizard() {
      return { languageModel: (id) => ({specificationVersion:"v2", provider:"wizard-local", modelId:id,
        supportedUrls:{}, async doStream() {return {stream:new ReadableStream({start(c) {
          c.enqueue({type:"stream-start",warnings:[]});
          c.enqueue({type:"text-start",id:"local"});
          c.enqueue({type:"text-delta",id:"local",delta:"LOCAL_CUSTOM_SDK_BOUND"});
          c.enqueue({type:"text-end",id:"local"});
          c.enqueue({type:"finish",finishReason:"stop",usage:{inputTokens:1,outputTokens:1}});c.close();
        }})};}})};
    }''', encoding='utf-8')
    plugin = cfgroot / 'fixture-plugin.mjs'
    plugin.write_text('export default async () => ({config: async (cfg) => { cfg.provider["wizard-local"].models["aicoder-plus"].name="APPROVED_LOCAL_PLUGIN_LOADED"; }});', encoding='utf-8')
    config = {'model': 'wizard-local/aicoder-plus', 'plugin': ['./fixture-plugin.mjs'],
        'provider': {'wizard-local': {'npm': './wizard.mjs', 'options': {'apiKey': '{env:AITEST_FIXTURE_AUTH}'},
          'models': {'aicoder-plus': {'name':'aicoder-plus','limit':{'context':32000,'output':1000},'tool_call':True}}}},
        'permission': {'*': 'allow'}, 'agent': {'unsafe-host-agent': {'mode': 'primary'}},
        'mcp': {'unsafe-host-mcp': {'type':'local','command':['unused']}}}
    path.write_text('// explicit fixture config\n'+json.dumps(config,ensure_ascii=False),encoding='utf-8')
    with patch.object(Path, 'read_text', side_effect=AssertionError('Discovery must not read config content')):
        discovery = host_provider.discover({}, home)
    assert discovery['status'] == 'DISCOVERED' and discovery['secret_access'] == 'NONE'
    assert discovery['candidates'][0]['content_inspected'] is False
    before = path.read_bytes()
    assert host_provider.inspect_approved(path, 'fixture:approved')['preferred_model'] == config['model']
    binding = host_provider.create_binding(path, config['model'], 'fixture:approved')
    projected = host_provider.resolve(binding)
    assert not {'permission','agent','mcp'} & projected.keys()
    assert projected['model'] == 'wizard-local/aicoder-plus'
    assert projected['provider']['wizard-local']['npm'] == sdk.resolve().as_uri()
    assert 'baseURL' not in projected['provider']['wizard-local']['options']
    assert path.read_bytes() == before
    assert 'apiKey' not in json.dumps(binding)
    config['provider']['wizard-local']['options']['apiKey'] = 'fixture-secret-do-not-copy'
    path.write_text(json.dumps(config),encoding='utf-8')
    try: host_provider.create_binding(path, config['model'], 'fixture:approved')
    except host_provider.BindingRequired as exc:
        assert 'INLINE_SECRET_FORBIDDEN' in str(exc) and 'fixture-secret' not in str(exc)
    else: raise AssertionError('Inline secret must not be copied into config')
    path.write_bytes(before)
    config['provider']['wizard-local']['options']['apiKey'] = '{file:never-read-secret.txt}'
    path.write_text(json.dumps(config),encoding='utf-8')
    try: host_provider.create_binding(path, config['model'], 'fixture:approved')
    except host_provider.BindingRequired: pass
    else: raise AssertionError('File secret must not be read')
    path.write_bytes(before)
    config['provider']['wizard-local']['options'] = {'headers': {'X-Auth': 'fixture-do-not-copy'}}
    path.write_text(json.dumps(config),encoding='utf-8')
    try: host_provider.create_binding(path, config['model'], 'fixture:approved')
    except host_provider.BindingRequired as exc: assert str(exc)=='HEADER_VALUES_REQUIRE_ENV_REFERENCES'
    else: raise AssertionError('Nonstandard auth headers must not copy literal tokens')
    path.write_bytes(before)
    sdk.write_text(sdk.read_text()+'\n// change',encoding='utf-8')
    try: host_provider.resolve(binding)
    except host_provider.BindingRequired as exc: assert 'CHANGED_REAPPROVAL' in str(exc)
    else: raise AssertionError('Changed local module requires reapproval')
    binding = host_provider.create_binding(path, config['model'], 'fixture:approved')
    return binding, before, path


def api(env, path, payload=None):
    token = base64.b64encode(('opencode:'+env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
    request = urllib.request.Request(env['AITEST_OPENCODE_ENDPOINT']+path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization':'Basic '+token, 'Content-Type':'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=90) as response: return json.load(response)


def main():
    binary = Path(os.environ.get('AITEST_REAL_OPENCODE') or WORKSPACE / 'runtime/opencode/opencode.exe')
    if not binary.is_file(): raise RuntimeError('Actual pinned OpenCode required')
    old = dict(os.environ)
    gates = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory, ExitStack() as stack:
        root = Path(directory)
        binding, host_original, host_path = contract_checks(root)
        data = root / 'package-data'
        stack.enter_context(patch.object(launcher, 'DATA', data))
        stack.enter_context(patch.object(launcher, 'OPENCODE', binary))
        stack.enter_context(patch.object(launcher, 'HOST_CONFIG_ENV', {'XDG_CONFIG_HOME':str(root/'host/.config')}))
        if os.name != 'nt':
            # Native construction proof only; Windows qualification uses real
            # installed identity, all package hashes and the packaged Python.
            stack.enter_context(patch.object(launcher, 'windows_host', return_value=True))
            stack.enter_context(patch.object(launcher, 'display_doctor', return_value={'integrity_failures': [], 'matrix': {'OpenCode':'READY'}}))
        else:
            launcher.verify_daily_install()
        try:
            os.environ.pop('AITEST_MODEL_KEY', None)
            assert launcher.model_configuration({})['enabled_providers'] == []
            launcher.prepare()
            def auth_pending_attach(argv, cwd, env):
                assert argv[1]=='attach' and cwd == WORKSPACE
                assert not any(key in env for key in ('OPENCODE_CONFIG','OPENCODE_CONFIG_DIR'))
                assert env['XDG_CONFIG_HOME'] == str(data/'opencode-config')
                assert json.loads(env['OPENCODE_CONFIG_CONTENT'])['enabled_providers'] == []
                assert isinstance(api(env, '/session'), list)
                deadline = time.monotonic()+30
                while True:
                    heartbeat = launcher.read(data/'state/control-loop-heartbeat.json', {})
                    if heartbeat.get('status') in ('RUNNING','WAITING_OPENCODE') or heartbeat.get('pid'): break
                    if time.monotonic()>deadline: raise AssertionError('Actual Control Loop heartbeat missing')
                    time.sleep(.2)
                readiness = launcher.read(data/'state/startup-readiness.json')
                assert readiness['AUTH_READY']=='AUTH_REQUIRED'
                assert readiness['OPENCODE_PROCESS_READY']=='PASS'
                assert readiness['R2_SESSION_READY']=='PASS'
                assert argv[-2:] == ['--session', readiness['director_session_id']]
                actual = api(env, '/session/'+readiness['director_session_id'])
                assert 'AUTH_REQUIRED' in actual['title']
                gates.update(OPENCODE_START_WITH_MODEL_AUTH_PENDING='PASS', CONTROL_LOOP_START='PASS')
                return 0
            assert launcher.start_conversation(attach_runner=auth_pending_attach)==0
            # Broken/changed binding stays visible as a model gate and still
            # yields a valid no-provider process configuration.
            launcher.write(data/'provider-binding.json', {**binding,'source_sha256':'0'*64})
            pending, status = launcher.provider_configuration()
            assert pending['enabled_providers']==[] and status['auth']=='AUTH_REQUIRED'
            for invalid in ('not-json', '[]', 'null'):
                (data/'provider-binding.json').write_text(invalid,encoding='utf-8')
                pending, status = launcher.provider_configuration()
                assert pending['enabled_providers']==[] and status['auth']=='AUTH_REQUIRED'
            launcher.write(data/'provider-binding.json', binding)
            os.environ['AITEST_FIXTURE_AUTH']='local-fixture-not-a-bank-credential'
            def custom_attach(argv, cwd, env):
                projected = json.loads(env['OPENCODE_CONFIG_CONTENT'])
                assert projected['model']=='wizard-local/aicoder-plus'
                assert 'baseURL' not in projected['provider']['wizard-local']['options']
                catalog = api(env, '/provider')
                assert 'wizard-local' in catalog['connected']
                config = api(env, '/config')
                assert config['default_agent']=='aitest-director'
                assert 'unsafe-host-agent' not in config.get('agent',{})
                assert config['permission']['read']=='deny'
                assert config['provider']['wizard-local']['models']['aicoder-plus']['name']=='APPROVED_LOCAL_PLUGIN_LOADED'
                session = api(env, '/session', {'title':'Synthetic custom SDK binding proof'})
                message = api(env, '/session/'+session['id']+'/message',
                    {'agent':'aitest-director','model':{'providerID':'wizard-local','modelID':'aicoder-plus'},
                     'parts':[{'type':'text','text':'Local custom SDK binding fixture. No bank work.'}]})
                assert any(p.get('text')=='LOCAL_CUSTOM_SDK_BOUND' for p in message.get('parts',[])), message
                assert host_path.read_bytes()==host_original
                gates.update(HOST_PROVIDER_DISCOVERY='PARTIAL_BANK_BINDING', CUSTOM_LOCAL_PLUGIN_SDK_REUSE='PASS')
                return 0
            assert launcher.start_conversation(attach_runner=custom_attach)==0
            # An approved plugin that stalls during config/auth initialization
            # must still lead to the actual no-model setup shell and Control Loop.
            plugin = host_path.parent/'fixture-plugin.mjs'
            plugin.write_text('export default async () => ({config: async () => { await new Promise(() => {}); }});',encoding='utf-8')
            launcher.write(data/'provider-binding.json', host_provider.create_binding(host_path, binding['model'], 'fixture:approved'))
            def fallback_attach(argv, cwd, env):
                assert json.loads(env['OPENCODE_CONFIG_CONTENT'])['enabled_providers']==[]
                assert isinstance(api(env, '/session'), list)
                readiness = launcher.read(data/'state/startup-readiness.json')
                assert readiness['provider_binding']['binding_error']=='BANK_PROVIDER_BINDING_REQUIRED_PROVIDER_INIT_FAILED'
                assert readiness['AUTH_READY']=='AUTH_REQUIRED' and readiness['CONTROL_LOOP_START']=='PASS'
                gates['PROVIDER_INIT_FAILURE_FALLBACK']='PASS'
                return 0
            assert launcher.start_conversation(attach_runner=fallback_attach)==0
        finally:
            os.environ.clear(); os.environ.update(old)
    result = {'status':'PASS','classification':'ACTUAL_OPENCODE_NORMAL_ENTRY_SYNTHETIC_PROVIDER',
              'gates':gates,'bank_gate':'BANK_PROVIDER_BINDING_REQUIRED', 'bank_model_turn':'NOT_EXECUTED',
              'host_secret_read':'NONE','host_secret_copy':'NONE','host_config_changed':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__': raise SystemExit(main())
