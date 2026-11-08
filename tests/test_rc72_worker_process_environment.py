"""Real child-process environment probes; synthetic markers, no bank secrets."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher,AgentRuntimeError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_authority import RC72AuthorityRuntime

ROLES=['REALITY_RECON_WORKER','REQUIREMENT_ANALYSIS_WORKER','SOURCE_TARGET_DISCOVERY_WORKER',
       'SOURCE_TARGET_REVIEWER','CODE_ANALYSIS_WORKER','TEST_DESIGN_WORKER','DATA_PREPARER','DATA_VERIFIER']


def _launcher(tmp_path,monkeypatch,*,env=None):
    captain=tmp_path/'captain-profile';captain.mkdir()
    (captain/'marker.txt').write_text('synthetic-captain-marker')
    monkeypatch.setenv('HOME',str(captain));monkeypatch.setenv('DSH_HOME',str(captain))
    monkeypatch.setenv('RC72_CAPTAIN_CANARY','synthetic-control-token')
    script=tmp_path/'worker.py'
    script.write_text('''import json,os,uuid
from pathlib import Path
profile=Path(os.environ['DSH_HOME'])
result={'captain_visible':'RC72_CAPTAIN_CANARY' in os.environ,
        'captain_profile_readable':(profile/'marker.txt').is_file(),
        'scoped_provider_present':os.environ.get('WORKER_MODEL_TOKEN')=='scoped-test-provider',
        'home':os.environ['HOME'],'dsh_home':str(profile),'mode':os.environ['PFC_RC7_DSH_SESSION_MODE']}
print(json.dumps({'type':'session','session_id':'session-'+uuid.uuid4().hex}))
print(json.dumps({'type':'tool_call','tool_name':'file_read'}))
print(json.dumps({'type':'final','text':json.dumps(result)}))
''')
    patch=tmp_path/'patch.json';patch.write_text('{}')
    truth=TruthRuntime(tmp_path/'r1.jsonl');authority=RC72AuthorityRuntime(b'process-scope-unit-test-signing-key')
    calls=[]
    def run(_command,**kwargs):
        calls.append(True)
        return subprocess.run([sys.executable,str(script)],**kwargs)
    launcher=DshHeadlessWorkerLauncher(dsh_bin=sys.executable,patch_path=str(patch),cwd=str(tmp_path),
        truth=truth,authority=authority,coordinator_instance_id='synthetic-captain',release_id='PROCESS-SCOPE',
        state_root=str(tmp_path/'state'),env=env,command_runner=run)
    return launcher,truth,authority,calls,captain


def _assignment(launcher,role='REALITY_RECON_WORKER',tools=('file_read',)):
    return launcher.assign(agent_id='process-probe',role=role,phase='NATIVE_PROCESS_SCOPE',mission_id='MISSION-PROBE',
        attempt_id='ATTEMPT-PROBE',scope='task:WORK-PROBE/attempt:ATTEMPT-PROBE',input_refs=['fixture://approved-input'],
        allowed_artifact_types=[],allowed_tools=tools)


@pytest.mark.parametrize('role',ROLES)
def test_all_native_professional_roles_drop_parent_credentials_and_keep_explicit_worker_provider(tmp_path,monkeypatch,role):
    launcher,truth,authority,calls,captain=_launcher(tmp_path,monkeypatch,env={'WORKER_MODEL_TOKEN':'scoped-test-provider'})
    assignment=_assignment(launcher,role)
    invocation,output=launcher.execute(assignment,'Read only synthetic environment markers.')
    assert invocation.exit_code==0 and calls==[True]
    assert output['captain_visible'] is False and output['captain_profile_readable'] is False
    assert output['scoped_provider_present'] is True and output['mode']=='LEASE_BOUND_WORKER'
    Path(output['home']).relative_to(launcher.state_root/'worker-home')
    Path(output['dsh_home']).relative_to(Path(output['home']))
    assert 'synthetic-control-token' not in truth.store.path.read_text()


def test_different_workers_have_distinct_private_homes(tmp_path,monkeypatch):
    launcher,*_=_launcher(tmp_path,monkeypatch)
    outputs=[launcher.execute(_assignment(launcher),'Environment probe.')[1] for _ in range(2)]
    assert outputs[0]['home']!=outputs[1]['home'] and outputs[0]['dsh_home']!=outputs[1]['dsh_home']


@pytest.mark.parametrize('key',['CAPTAIN_TOKEN','COORDINATOR_PASSWORD','WORKER_SIGNING_KEY','RUNTIME_HMAC_KEY','AUTHORITY_KEY'])
def test_explicit_control_credentials_fail_before_a_child_or_started_event(tmp_path,monkeypatch,key):
    launcher,truth,authority,calls,captain=_launcher(tmp_path,monkeypatch,env={key:'synthetic-forbidden'})
    assignment=_assignment(launcher)
    with pytest.raises(AgentRuntimeError,match='WORKER_PROCESS_ADMISSION_DENIED'):
        launcher.execute(assignment,'Must not execute.')
    assert not calls
    events=list(truth.store.iter_raw())
    assert not any(r['event_type']=='WORKER_STARTED' for r in events)
    assert any(r['event_type']=='ROUTING_INTEGRITY_FAIL' for r in events)
    assert 'synthetic-forbidden' not in truth.store.path.read_text()


@pytest.mark.parametrize('key',['HOME','USERPROFILE','APPDATA','LOCALAPPDATA','DSH_HOME','XDG_CONFIG_HOME'])
def test_explicit_profile_cannot_redirect_worker_to_parent_home(tmp_path,monkeypatch,key):
    launcher,truth,authority,calls,captain=_launcher(tmp_path,monkeypatch)
    launcher.env[key]=str(captain)
    with pytest.raises(AgentRuntimeError,match='WORKER_PROCESS_ADMISSION_DENIED'):
        launcher.execute(_assignment(launcher),'Must not execute.')
    assert not calls


@pytest.mark.parametrize('change',['revoked','expired','scope','worker','signature'])
def test_invalid_live_assignment_cannot_start_a_real_process(tmp_path,monkeypatch,change):
    launcher,truth,authority,calls,_=_launcher(tmp_path,monkeypatch)
    assignment=_assignment(launcher)
    if change=='revoked':authority.revoke_worker_lease(assignment.lease.lease_id)
    elif change=='scope':assignment=replace(assignment,scope='task:OTHER/attempt:OTHER')
    elif change=='worker':assignment=replace(assignment,worker_instance_id='other-worker')
    elif change=='signature':assignment=replace(assignment,lease=replace(assignment.lease,signature='0'*64))
    else:
        # A validly signed, indexed past lease must reach the live TTL guard.
        lease=replace(assignment.lease,issued_at=1,expires_at=2)
        payload=dict(lease.__dict__);payload.pop('signature')
        lease=replace(lease,signature=authority._sign(payload))
        authority._leases[lease.lease_id]=lease
        assignment=replace(assignment,lease=lease)
    with pytest.raises(AgentRuntimeError,match='WORKER_PROCESS_ADMISSION_DENIED'):
        launcher.execute(assignment,'Must not execute.')
    assert not calls and not any(r['event_type']=='WORKER_STARTED' for r in truth.store.iter_raw())


@pytest.mark.parametrize('env',[{'PFC_RC7_DSH_SESSION_MODE':'INTERACTIVE_CONTROL'},
    {'PFC_RC7_DSH_ALLOWED_TOOLS':'["*"]'}, {'PFC_RC7_DSH_ALLOWED_TOOLS':'["unleased_tool"]'}])
def test_explicit_interactive_or_broader_tool_projection_is_rejected(tmp_path,monkeypatch,env):
    launcher,truth,authority,calls,_=_launcher(tmp_path,monkeypatch,env=env)
    with pytest.raises(AgentRuntimeError,match='WORKER_PROCESS_ADMISSION_DENIED'):
        launcher.execute(_assignment(launcher),'Must not execute.')
    assert not calls


def test_exact_tool_membership_may_be_projected_in_a_different_order(tmp_path,monkeypatch):
    launcher,*_=_launcher(tmp_path,monkeypatch,env={'PFC_RC7_DSH_ALLOWED_TOOLS':'["other_read","file_read"]'})
    assignment=_assignment(launcher,tools=('file_read','other_read'))
    assert launcher.execute(assignment,'Environment probe.')[1]['captain_visible'] is False


def test_separate_signed_grants_do_not_share_a_profile_even_for_one_identity(tmp_path,monkeypatch):
    launcher,truth,authority,calls,_=_launcher(tmp_path,monkeypatch)
    original=_assignment(launcher)
    first=launcher.execute(original,'Environment probe.')[1]
    lease=authority.issue_lease(original.identity.worker_id,'task:OTHER/attempt:OTHER',[],['file_read'])
    # A fresh, independently authorized scope requires a NEW Assignment ID.
    # Reusing the old Assignment ID even with a different lease is a
    # fail-closed replay, not an independent task.
    successor=replace(original,lease=lease,scope=lease.scope_ref,attempt_id='OTHER',
                      assignment_id=original.assignment_id+'-OTHER-GRANT')
    second=launcher.execute(successor,'Environment probe.')[1]
    assert first['home']!=second['home'] and first['dsh_home']!=second['dsh_home']
    assert len(calls)==2
    before=truth.store.path.read_bytes()
    with pytest.raises(AgentRuntimeError,match='WORKER_ASSIGNMENT_REPLAY_FORBIDDEN_RECONCILE_R1'):
        launcher.execute(original,'Old assignment cannot be replayed.')
    assert len(calls)==2 and truth.store.path.read_bytes()==before


@pytest.mark.parametrize('env',[{'pfc_rc7_dsh_session_mode':'INTERACTIVE_CONTROL'},
    {'pfc_rc7_dsh_allowed_tools':'["*"]'},
    {'PFC_RC7_DSH_SESSION_MODE':'LEASE_BOUND_WORKER','pfc_rc7_dsh_session_mode':'INTERACTIVE_CONTROL'}])
def test_case_insensitive_environment_alias_cannot_bypass_windows_worker_policy(tmp_path,monkeypatch,env):
    launcher,truth,authority,calls,_=_launcher(tmp_path,monkeypatch,env=env)
    with pytest.raises(AgentRuntimeError,match='WORKER_PROCESS_ADMISSION_DENIED'):
        launcher.execute(_assignment(launcher),'Must not execute.')
    assert not calls


@pytest.mark.parametrize('key',['PFC_RC7_MCP_MISSION_ID','PFC_RC7_MCP_WORKER_ID',
    'PFC_RC7_MCP_LEASE_ID','PFC_RC7_MCP_SCOPE_REF','PFC_RC7_MCP_TASK_ID','pfc_rc7_mcp_worker_id'])
def test_explicit_caller_projection_cannot_impersonate_a_different_grant(tmp_path,monkeypatch,key):
    launcher,truth,authority,calls,_=_launcher(tmp_path,monkeypatch,env={key:'other-context'})
    with pytest.raises(AgentRuntimeError,match='WORKER_PROCESS_ADMISSION_DENIED'):
        launcher.execute(_assignment(launcher),'Must not execute.')
    assert not calls



def test_signed_worker_identity_and_tools_are_projected_into_real_child_environment(
        tmp_path, monkeypatch):
    """A checked but missing worker/lease projection is an authorization bypass."""
    launcher, truth, authority, calls, captain = _launcher(tmp_path, monkeypatch)
    assignment = _assignment(launcher, tools=('file_read', 'other_read'))
    captured = {}

    def inspect(_command, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.run([sys.executable, str(tmp_path / 'worker.py')], **kwargs)

    launcher.command_runner = inspect
    invocation, output = launcher.execute(assignment, 'Scoped Worker identity.')
    assert calls == []
    assert captured['PFC_RC7_MCP_MISSION_ID'] == assignment.mission_id
    assert captured['PFC_RC7_MCP_WORKER_ID'] == assignment.worker_instance_id
    assert captured['PFC_RC7_MCP_LEASE_ID'] == assignment.lease.lease_id
    assert captured['PFC_RC7_MCP_SCOPE_REF'] == assignment.scope
    assert captured['PFC_RC7_MCP_TASK_ID'] == 'WORK-PROBE'
    assert set(json.loads(captured['PFC_RC7_DSH_ALLOWED_TOOLS'])) == set(assignment.allowed_tools)
    assert captured['PFC_RC7_DSH_SESSION_MODE'] == 'LEASE_BOUND_WORKER'
    assert output['captain_visible'] is False
    assert 'RC72_CAPTAIN_CANARY' not in captured
    assert captured['HOME'] != str(captain)
    assert invocation.worker_instance_id == assignment.worker_instance_id
