"""OpenCode-facing authority; trusted internal service calls remain separate."""
from contextlib import contextmanager
import os
from .general_work.execution_contract import require
from .dispatch_receipts import runtime_coordination
from .host_tool_call import actual_tool_call
from .mission_session_authority import MissionSessionOwner
from .primary_sessions import PrimarySessionOwner, primary_coordination

TOOLS={
    'g3':{'DIRECTOR':'aitest_g3_director','REQUIREMENT_ANALYST':'aitest_requirement_analyst',
        'CODE_ANALYST':'aitest_code_analyst','TEST_STRATEGIST':'aitest_test_strategist',
        'CASE_DESIGNER':'aitest_case_designer','EVALUATOR':'aitest_evaluator'},
    'g4':{'DIRECTOR':'aitest_g4_director','EXECUTOR':'aitest_executor'},
    'g5':{'DIAGNOSIS':'aitest_diagnosis','DEFECT_HUNTER':'aitest_diagnosis'},
    'orchestration':{'PLANNER':'aitest_planner','EXECUTOR':('aitest_executor','aitest_worker')},
}

@contextmanager
def model_command(service, family, role, action, data):
    """Keep admission locked through the effect: rotation uses the same mutex."""
    require(role in TOOLS.get(family,{}),'MODEL_ROLE_NOT_AUTHORIZED')
    tool=TOOLS[family][role];sid=os.environ.get('AITEST_HOST_SESSION_ID','')
    if role=='DIRECTOR':
        with primary_coordination(service.runtime):
            PrimarySessionOwner(service.runtime,service.workspace_root,service.raw_session_provider).current(sid)
            actual_tool_call(service.raw_session_provider,agent='aitest-director',tool=tool,action=action,payload=data)
            require(action in {'status','work_context'},'PRIMARY_DIRECT_EXECUTION_BYPASS_DENIED')
            yield
        return
    require(isinstance(data.get('mission_id'),str) and bool(data['mission_id']),'MISSION_CALL_SCOPE_REQUIRED')
    with runtime_coordination(service.runtime.db_path):
        grant=MissionSessionOwner(service).current(data['mission_id'],sid)
        actual=actual_tool_call(service.raw_session_provider,agent=grant['agent_name'],tool=tool,action=action,payload=data)
        if not (family=='orchestration' and actual['tool']=='aitest_worker' and grant['role']!='PLANNER'):
            require(grant['role']==('DEFECT_HUNTER' if role=='DIAGNOSIS' else role),'MISSION_AUTHORITY_ROLE_MISMATCH')
        for key in ('session_id','task_id','attempt_id','root_attempt_id','plan_id','plan_revision_id','logical_agent_id','epoch'):
            require(key not in data or data[key]==grant.get(key),'MISSION_CALL_BINDING_MISMATCH')
        yield
