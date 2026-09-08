"""Generated pytest assets resolve immutable R1 cases and execute through G4."""
import json
import os
from pathlib import Path
import pytest
from .durable_core import RuntimeError, canonical_sha256


def run_bound_case(root, identity):
    from .product_entry import g4_service
    path=Path(root)/'bindings/automation-runs.json'
    config=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    run_id=os.environ.get('AITEST_AUTOMATION_RUN_ID')
    entry=(config.get('runs') or {}).get(run_id) or {}
    if entry.get('approved') is not True or not entry.get('approval_ref'):
        raise RuntimeError('AUTOMATION_RUN_BINDING_REQUIRED','Select a locally approved execution attempt')
    request=dict(entry.get('execution_request') or {})
    mission=entry['mission_id'];service=g4_service(Path(root))
    fact,_,_,_=service._resolve_governed_case(mission,identity['tc_id'],identity['case_version_id'])
    case=dict(fact.payload['r3_3_case'])
    if canonical_sha256(case)!=identity['case_digest']:raise RuntimeError('AUTOMATION_CASE_DIGEST_MISMATCH',identity['case_version_id'])
    if request.get('case_id')!=identity['tc_id'] or request.get('case_version')!=identity['case_version_id']:
        raise RuntimeError('AUTOMATION_CASE_BINDING_MISMATCH',run_id)
    if request.get('capability_id')!='API' or not case.get('execution_profile',{}).get('api_journey'):
        raise RuntimeError('AUTOMATION_API_CASE_REQUIRED',run_id)
    request['step']={'step_id':'pytest:'+run_id,'expected':{'business_assertions':'all frozen StandardCase assertions pass'}}
    result=service.execute_capability(mission,request)
    fact=(result.get('result') or {}).get('payload') or {}
    return {'oracle_result':fact.get('oracle_result','FAIL'),'evidence_refs':fact.get('evidence_refs',[]),
            'case_version_id':identity['case_version_id'],'truth_source':'R1_EVENT_STREAM'}


@pytest.fixture
def aitest_governed_case_runner():
    root=Path(os.environ['AITEST_WORKSPACE_ROOT']).resolve()
    return lambda identity:run_bound_case(root,identity)
