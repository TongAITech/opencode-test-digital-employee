"""Mission-bound auxiliary model entry; internal import/review services stay owned.

Actual ToolContext confers caller identity, never wider filesystem, knowledge
scope or approval authority. These gates supplement the original domain checks.
"""
from contextlib import contextmanager
import os
from pathlib import Path
from .dispatch_receipts import runtime_coordination
from .general_work.execution_contract import require
from .host_tool_call import actual_tool_call
from .mission_session_authority import MissionSessionOwner
from .mission_controls import require_no_pending_control

@contextmanager
def auxiliary_call(service,tool,action,payload,*,raw_input=False):
    require(tool in {'aitest_knowledge','aitest_recovery','aitest_context'},'AUXILIARY_TOOL_INVALID')
    require(isinstance(payload,dict) and isinstance(payload.get('mission_id'),str) and bool(payload['mission_id']),'MISSION_CALL_SCOPE_REQUIRED')
    with runtime_coordination(service.runtime.db_path):
        grant=MissionSessionOwner(service).current(payload['mission_id'],os.environ.get('AITEST_HOST_SESSION_ID',''))
        actual_tool_call(service.raw_session_provider,agent=grant['agent_name'],tool=tool,action=action,payload=payload,
            expected_input=payload if raw_input else None)
        for k in ('task_id','attempt_id','session_id','root_attempt_id','logical_agent_id','epoch'):
            require(k not in payload or payload[k]==grant.get(k),'MISSION_CALL_BINDING_MISMATCH')
        if tool=='aitest_knowledge':require(grant['role']!='PLANNER','AUXILIARY_ROLE_NOT_AUTHORIZED')
        if tool=='aitest_recovery':require(grant['role']=='REQUIREMENT_ANALYST','AUXILIARY_ROLE_NOT_AUTHORIZED')
        if tool!='aitest_context' and action not in {'task_view','intake_context','read_intake_source'}:
            require_no_pending_control(service.runtime,payload['mission_id'])
        yield grant


def knowledge_command(service,action,payload,grant):
    from . import recovery_knowledge as knowledge
    require(action in {'candidate','task_view','apply_review','link'},'KNOWLEDGE_ACTION_UNSUPPORTED')
    mid=payload['mission_id'];state=service.runtime.replay_composed(mid)
    goal=state.core_state.goal(state.core_state.mission.active_goal_id)
    execution_scope=dict(goal.definition.get('execution_scope') or {})
    scope={'project_id':execution_scope.get('project_id'),'environment_id':execution_scope.get('environment_id'),
        'version_scope':execution_scope.get('version_scope') or execution_scope.get('version')}
    require(all(isinstance(v,str) and bool(v) for v in scope.values()),'KNOWLEDGE_EXACT_SCOPE_REQUIRED')
    require('scope' not in payload or payload['scope']==scope,'KNOWLEDGE_MISSION_SCOPE_MISMATCH')
    require('role' not in payload or payload['role']==grant['agent_name'],'KNOWLEDGE_CALLER_ROLE_MISMATCH')
    data=dict(payload);data.pop('mission_id')
    if action=='task_view':
        data.pop('scope',None);data.pop('role',None);data.pop('task_id',None)
        task=state.extension_state('r1_2_work_graph').task(grant['task_id'])
        data.setdefault('query',task.intent)
        result=knowledge.task_view(service.runtime,scope=scope,task_id=grant['task_id'],role=grant['agent_name'],**data)
    elif action=='candidate':
        data['scope']=scope;result=knowledge.candidate(service.runtime,mid,**data)
    else:
        # Review/link retain the original local human approval and provenance
        # checks. Also bind endpoints to this exact Mission's knowledge scope.
        from contextlib import closing
        import sqlite3
        from .r3_e1.contracts import KnowledgeScopeIdentity
        ids=[data.get('version_id')] if action=='apply_review' else [data.get('from_version_id'),data.get('to_version_id')]
        scope_key=KnowledgeScopeIdentity.from_dict(scope).key
        with closing(sqlite3.connect(service.runtime.db_path)) as conn:
            for vid in ids:
                rows=conn.execute('SELECT scope_key FROM r3e1_versions WHERE version_id=?',(vid,)).fetchall()
                require(len(rows)==1 and rows[0][0]==scope_key,'KNOWLEDGE_MISSION_SCOPE_MISMATCH')
        result=knowledge.review(service.runtime,service.workspace_root,mid,**data) if action=='apply_review' else knowledge.link(service.runtime,mid,**data)
    return {'truth_source':'R1_EVENT_STREAM',**result}


def recovery_command(service,action,payload):
    from .recovery_intake import dispatch, RecoveryIntakeService
    data=dict(payload)
    if action=='import_document':
        root=Path(service.workspace_root).resolve();path=Path(data.get('path','')).expanduser()
        path=(path if path.is_absolute() else root/path).resolve()
        allowed=(root/'attachments',root/'data/intake')
        require(any(path.is_relative_to(p) and p.resolve()==p for p in allowed),'RECOVERY_MODEL_DOCUMENT_SCOPE_DENIED')
        raw=scoped_document_bytes(root,path.relative_to(root).as_posix())
        data.pop('path');mid=data.pop('mission_id')
        return RecoveryIntakeService(service.runtime).import_document_bytes(mid,raw,suffix=path.suffix.lower(),locator=path.as_uri(),**data)
    return dispatch(service.workspace_root,action,data,runtime=service.runtime)


def scoped_document_bytes(root,relative):
    """Reuse established directory guards; keep the document's 20 MiB contract."""
    from contextlib import ExitStack
    import stat
    from .general_work.scoped_files import ScopedFiles, windows_guard
    from .recovery_intake import MAX_DOCUMENT_BYTES
    files=ScopedFiles(root,(),root);rel=files.relative(relative)
    with files.parent(rel) as (parent,fd),ExitStack() as stack:
        if os.name=='nt':
            stack.enter_context(windows_guard(parent/rel.name,directory=False))
            handle=os.open(parent/rel.name,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT)
        else:handle=os.open(rel.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        stack.callback(os.close,handle);before=os.fstat(handle)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1,'RECOVERY_DOCUMENT_LINK_OR_TYPE_DENIED')
        require(before.st_size<=MAX_DOCUMENT_BYTES,'RECOVERY_DOCUMENT_TOO_LARGE')
        chunks=[];total=0
        while True:
            chunk=os.read(handle,min(65536,MAX_DOCUMENT_BYTES+1-total))
            if not chunk:break
            chunks.append(chunk);total+=len(chunk)
            require(total<=MAX_DOCUMENT_BYTES,'RECOVERY_DOCUMENT_TOO_LARGE')
        after=os.fstat(handle)
        require((before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns),'RECOVERY_DOCUMENT_CHANGED')
        return b''.join(chunks)
