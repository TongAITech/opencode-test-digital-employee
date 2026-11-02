"""Real MCP subprocess -> live parent authorization -> exact HTTP tool effects.

The DSH protocol worker is an engineering adapter. The production MCP entry,
parent gate, signed assignments, actual tools and native N5 finalizers are real.
"""
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen
from urllib.parse import quote

import pytest
from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_native_n5_launcher import NativeN5FencedDshLauncher
from rc7_runtime.rc72_native_n5_tool_gate import N5ToolHandler
from rc7_runtime.rc72_n5_existing_data_repair import ExistingDataRepairService
from rc7_runtime.rc72_n5_completion import N5DeliveryGateService
from test_rc72_n8_repair_boundary import _setup
from test_rc72_n7_member_drain import _close

READ = 'mcp__pfc_aitest_rc7__verify_exact_data_ref'
WRITE = 'mcp__pfc_aitest_rc7__prepare_exact_data_ref'

_WORKER = r'''
import json, os, subprocess, sys, uuid
context = json.loads(sys.argv[1].rsplit('\n', 1)[1])
output = context['output_contract']
tool = context['authorized_tools'][0]
args = dict(data_ref=output['data_ref'], precondition_refs=output['precondition_refs'],
            mission_context=json.loads(os.environ['PFC_RC72_TOOL_GATE_CONTEXT']))
mode = os.environ.get('NATIVE_ENGINEERING_CHANGE')
if mode == 'arguments': args['data_ref'] = 'data://outside/approved-scope'
if mode == 'identity': args['mission_context']['worker_id'] = 'CAPTAIN'
if mode != 'fake_call':
    message = dict(jsonrpc='2.0', id=1, method='tools/call',
        params=dict(name=tool[len('mcp__pfc_aitest_rc7__'):], arguments=args))
    command = [sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from rc7_release.mcp_server_authorized import main; main()', sys.argv[2]]
    result = subprocess.run(command, input=json.dumps(message)+'\n', capture_output=True, text=True, check=True)
    response = json.loads(result.stdout)['result']
    if mode == 'replay':
        replay = subprocess.run(command, input=json.dumps(message)+'\n', capture_output=True, text=True, check=True)
        assert json.loads(replay.stdout)['result'] == response
    if response.get('isError'): raise RuntimeError(response['content'][0]['text'])
    actual = json.loads(response['content'][0]['text'])
    success = actual['data_exists'] and all(actual['precondition_results'].values())
else: success = True
output['status'] = ('PREPARED' if 'PREPARATION' in output['schema'] else 'VERIFIED') if success else 'REPAIR_REQUIRED'
if mode == 'fake_success': output['status'] = 'VERIFIED'
output['verification'] = 'Actual scoped parent tools observed the exact resource and frozen preconditions'
output['unknowns'] = []
output['gaps'] = [] if success else ['actual scoped data/precondition observation failed']
print(json.dumps(dict(type='session',session_id='session-fenced-n5-'+uuid.uuid4().hex)))
print(json.dumps(dict(type='tool_call',tool_name=tool)))
print(json.dumps(dict(type='final',text=json.dumps(output))))
'''


def _fenced_setup(tmp_path, monkeypatch, *, change=None, before_worker=None):
    truth, prep, server, p, diagnosis, boundary, cleanup = _setup(tmp_path, monkeypatch)
    try:
        boundary.open(p['preparation_id'])
        contract = prep._one('rc72_n6_executable_contract', contract_id=p['contract_id'])
        binding = next(b for b in truth.query('rc72_n5_data_binding') if b['data_ref'] == contract['data_refs'][0]['data_ref'])
        url = 'http://127.0.0.1:%d' % server.server_address[1]
        effects = []
        def actual_tool(arguments, *, write=False):
            effects.append(('WRITE' if write else 'READ', arguments['data_ref']))
            target = url + '/repair' if write else url + '/data?ref=' + quote(arguments['data_ref'], safe='')
            request = Request(target, data=json.dumps({'data_ref': arguments['data_ref']}).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST') if write else target
            with urlopen(request, timeout=5) as response:
                actual = json.loads(response.read())
            with urlopen(url + '/precondition', timeout=5) as response:
                ready = json.loads(response.read())['ready']
            return dict(data_ref=actual['data_ref'], data_exists=actual['data_exists'],
                        precondition_results={ref: ready for ref in arguments['precondition_refs']})
        handlers = [N5ToolHandler(READ, 'READ', actual_tool),
                    N5ToolHandler(WRITE, 'WRITE', lambda args: actual_tool(args, write=True))]
        script = tmp_path / 'native-protocol-worker.py'
        script.write_text(_WORKER, encoding='utf-8')
        patch = tmp_path / 'native-worker.patch.json'
        patch.write_text('{}', encoding='utf-8')
        captured = []
        def run(command, **kwargs):
            captured.append(dict(kwargs['env']))
            if before_worker is not None:
                active = verifier._native_gate or producer._native_gate
                before_worker(service, active, truth, prep, server)
            return subprocess.run([sys.executable, str(script), command[-1], str(Path(__file__).resolve().parents[1])], **kwargs)
        def launcher(label, mode=None):
            return NativeN5FencedDshLauncher(handlers=handlers, dsh_bin=sys.executable, patch_path=str(patch),
                cwd=str(tmp_path), truth=truth, authority=prep.authority, coordinator_instance_id='native-coordinator',
                release_id=p['release_id'], state_root=str(tmp_path / label), timeout_seconds=20,
                command_runner=run, env={'NATIVE_ENGINEERING_CHANGE': mode or ''})
        verifier = launcher('native-verifier', change)
        service = ExistingDataRepairService(boundary, launcher=verifier, allowed_tools=[READ])
        verifier.bind_native_service(service)
        producer = launcher('native-preparer')
        producer.bind_native_service(service)
        request = service.request(p['preparation_id'], data_requirement_id=binding['data_requirement_id'],
                                  binding_revision=binding['artifact_version'])
        return truth, prep, server, p, service, request, producer, effects, captured
    except BaseException:
        _close(server)
        raise


def test_actual_mcp_preparer_and_independent_verifier_are_gated_before_effect_and_close_native_n5(tmp_path, monkeypatch):
    monkeypatch.setenv('CAPTAIN_AUTHORITY_TOKEN', 'ambient-control-must-not-enter-worker')
    truth, prep, server, p, service, request, producer, effects, captured = _fenced_setup(tmp_path, monkeypatch)
    try:
        assert service.prepare(request['repair_id'], launcher=producer, allowed_tools=[WRITE])['state'] == 'PREPARED'
        result = service.run(request['repair_id'])
        assert result['state'] == 'VERIFIED'
        assert [phase for phase, ref in effects] == ['WRITE', 'READ']
        assert all(ref == request['original_binding']['data_ref'] for phase, ref in effects)
        gates = truth.query('rc72_native_tool_gate')
        assert len(gates) == 2 and all(g['state'] == 'COMPLETED' for g in gates)
        assert len({g['worker_id'] for g in gates}) == 2
        assert len({g['workitem_id'] for g in gates}) == 2
        assert {r['state'] for r in truth.query('rc72_native_tool_call')} == {'RETURNED'}
        assert all('CAPTAIN_AUTHORITY_TOKEN' not in env for env in captured)
        assert all(env['PFC_RC7_DSH_SESSION_MODE'] == 'LEASE_BOUND_WORKER' for env in captured)
        assert captured[0]['HOME'] != captured[1]['HOME']
        assert producer._native_gate is None and service.launcher._native_gate is None
        before = truth.store.path.read_bytes()
        assert service.run(request['repair_id']) == result
        assert truth.store.path.read_bytes() == before and len(effects) == 2
        gate = N5DeliveryGateService(truth, release_id=p['release_id'], source_commit=p['source_commit']).complete(
            release_batch_id=p['release_batch_id'])
        assert gate['gate']['decision'] == 'PASS'
        assert not truth.query('rc72_mission_node', node_type='N7_EXECUTION')[0]['state'] == 'PASS'
        # Root-only generic cold replay must recognize both new event kinds.
        command = [sys.executable, '-I', '-c',
            'import sys;sys.path.insert(0,sys.argv[1]);import rc7_runtime;from rc6_runtime.truth import TruthRuntime;t=TruthRuntime(sys.argv[2]);assert len(t.query("rc72_native_tool_gate"))==2;assert len(t.query("rc72_native_tool_call"))==2',
            str(Path(__file__).resolve().parents[1]), str(truth.store.path)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        assert 'ambient-control-must-not-enter-worker' not in truth.store.path.read_text()
    finally:
        _close(server)


@pytest.mark.parametrize('change', ['arguments', 'identity', 'fake_call', 'fake_success'])
def test_wrong_arguments_identity_or_model_claim_cannot_certify_or_change_data(tmp_path, monkeypatch, change):
    truth, prep, server, p, service, request, producer, effects, captured = _fenced_setup(tmp_path, monkeypatch, change=change)
    try:
        with pytest.raises((ContractError, AgentRuntimeError)):
            service.run(request['repair_id'])
        assert not truth.query('agent_runtime_event', event_name='HANDOFF_RETURNED', assignment_id=service._one(
            'rc72_n5_existing_data_repair', repair_id=request['repair_id'])['assignment_id'])
        assert all(phase == 'READ' for phase, ref in effects)
        assert len(effects) == (1 if change == 'fake_success' else 0)
        binding = prep._one('rc72_n5_data_binding', binding_id=request['original_binding']['binding_id'])
        assert binding.get('verification_blocked_by_anchor') == request['repair_id']
        assert not truth.query('rc72_native_tool_gate', state='COMPLETED')
        assert not prep.authority._leases
    finally:
        _close(server)
