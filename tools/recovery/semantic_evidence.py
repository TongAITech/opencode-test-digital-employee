"""Admit separately executed real-model proof for this exact source revision."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def admit_semantic_report(path, source_head, harness):
    path=Path(path)
    if path.stat().st_size>256*1024:raise ValueError('SEMANTIC_REPORT_BUDGET_EXCEEDED')
    raw=path.read_bytes();report=json.loads(raw)
    required={
        'schema_version':'aitest.real-semantic-planner-proof.v1',
        'classification':'REAL_HOST_MODEL_SEMANTIC_PLANNING_ONLY',
        'source_head':source_head,'source_clean':True,'status':'PASS',
        'product_version':'1.13.0','semantic_planner':'REAL_HOST_MODEL',
        'script_authored_plan':False,'host_provider_auth_copied':False,
        'BANK_FIELD_VALIDATION_REQUIRED':True,
        'external_input_scope':'PUBLIC_PACKAGE_AND_SYNTHETIC_LOCAL_LOAN_ONLY',
        'user_request':'测试 BLOAN-PF1.1.0',
        'harness_sha256':hashlib.sha256(Path(harness).read_bytes()).hexdigest(),
    }
    for key,value in required.items():
        if type(report.get(key)) is not type(value) or report[key]!=value:raise ValueError('SEMANTIC_IDENTITY_MISMATCH:'+key)
    if report.get('gates',{}).get('AUTONOMOUS_PLAN')!='PASS':raise ValueError('SEMANTIC_GATE_NOT_PASS')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(report['completed_at'])).total_seconds()
    if not -300<=age<=86400:raise ValueError('SEMANTIC_PROOF_NOT_FRESH')
    director=report.get('director_session_id');planners=report.get('planner_sessions',[]);workers=report.get('worker_sessions',[])
    if not director or not planners or not workers or director in planners+workers or set(planners)&set(workers):raise ValueError('SEMANTIC_SESSIONS_NOT_INDEPENDENT')
    if report.get('task_count',0)<2 or report.get('r1_cursor',0)<1 or not report.get('plan_events'):raise ValueError('SEMANTIC_DURABLE_PLAN_MISSING')
    models=report.get('model_identities',[])
    if not models or any(not m.get('provider_id') or not m.get('model_id') or 'fixture' in (m['provider_id']+' '+m['model_id']).lower() for m in models):raise ValueError('SEMANTIC_ACTUAL_MODEL_MISSING')
    receipts=report.get('tool_receipts',[])
    if not any(r.get('tool')=='aitest_director' and r.get('action')=='start_test' and r.get('session_id')==director and r.get('status') in ('running','completed') for r in receipts):raise ValueError('SEMANTIC_DIRECTOR_RECEIPT_MISSING')
    if not any(r.get('tool')=='aitest_planner' and r.get('action')=='propose_plan' and r.get('session_id') in planners and r.get('task_count',0)>=2 and r.get('proposal_digest') and r.get('status') in ('running','completed') for r in receipts):raise ValueError('SEMANTIC_PLANNER_RECEIPT_MISSING')
    return {'status':'PASS','sha256':hashlib.sha256(raw).hexdigest(),'report':report,
            'scope':'Real host model semantic planning on synthetic inputs; separate from Windows execution and bank validation'}
