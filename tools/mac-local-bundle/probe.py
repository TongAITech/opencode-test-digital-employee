"""Isolated construction diagnosis; never a real-user-turn substitute."""
from __future__ import annotations
import argparse,hashlib,json,os,platform,sqlite3,sys,tempfile,traceback
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    text='CONTROLLED_DIAGNOSTIC_ONLY: test the canonical intake default resolver; no bank facts supplied.'
    with tempfile.TemporaryDirectory(prefix='aitest-r2-probe-') as td:
        root=Path(td);(root/'legacy-sentinel').mkdir();legacy=root/'legacy-sentinel/aitest.db';db=root/'canonical-runtime-spine.db'
        os.environ.update(AITEST_WORKSPACE_ROOT=str(root),AITEST_DB_PATH=str(legacy),AITEST_RUNTIME_SPINE_DB=str(db),PYTHONDONTWRITEBYTECODE='1')
        sys.path.insert(0,str(a.source.resolve()/'workspace-template/ai-test/runtime'))
        from aitest_runtime.canonical_runtime import create_canonical_runtime
        from aitest_runtime.r2_2 import MissionIntakeOrchestrator
        from aitest_runtime.r2_2.normalizer import normalize_request
        request={'intake_id':'mac-package-isolated-default-resolver-probe','operation':'CREATE','scope':{'mode':'EXPLICIT_SET','project_id':'DIAGNOSTIC-ONLY'},'goal':{'intent':text},'source':{'kind':'CONTROL_PLANE','source_ref':'diagnostic:mac-package-default-resolver-probe','source_digest':hashlib.sha256(text.encode('utf-8')).hexdigest(),'observed_at':'2026-09-07T00:00:00Z','valid_until':None,'source_precedence':None},'actor':{'type':'SYSTEM','id':'ISOLATED_CONSTRUCTION_DIAGNOSTIC'}}
        normalized=normalize_request(request);runtime=create_canonical_runtime(root,db_path=db)
        result={'evidence_type':'DIRECT_CANONICAL_API_DIAGNOSTIC_NOT_REAL_USER_TURN','host':{'system':platform.system(),'machine':platform.machine(),'python':platform.python_version(),'platform':platform.platform()},'source_root':str(a.source.resolve()),'request_passes_frozen_normalization':bool(normalized),'injected_resolution':False,'injected_resolver':False,'legacy_schema_initialized':False,'legacy_existed_before_call':legacy.exists(),'real_user_turn':'NOT_EXECUTED','M_S02':'NOT_PASSED'}
        (a.output/'diagnostic-request.json').write_text(json.dumps(request,indent=2))
        try:
            value=MissionIntakeOrchestrator(runtime).intake(request);result.update(outcome='NOT_REPRODUCED',returned=value.to_dict())
        except Exception as exc:
            result.update(outcome='DEFAULT_RESOLVER_FAILURE_REPRODUCED',exception_type=type(exc).__name__,exception_message=str(exc));(a.output/'default-resolver-traceback.txt').write_text(traceback.format_exc())
        result['legacy_exists_after_call']=legacy.exists();result['legacy_size_after_call']=legacy.stat().st_size if legacy.exists() else None
        with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as c:
            result['r1_integrity']=c.execute('PRAGMA integrity_check').fetchone()[0]
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            result['r1_counts']={t:c.execute('SELECT COUNT(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
        result['product_acceptance']=False;result['no_user_mac_or_existing_database_accessed']=True
        (a.output/'default-resolver-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
        return 0 if result.get('exception_type')=='OperationalError' and 'truth_snapshots' in result.get('exception_message','') else 2
if __name__=='__main__':raise SystemExit(main())
