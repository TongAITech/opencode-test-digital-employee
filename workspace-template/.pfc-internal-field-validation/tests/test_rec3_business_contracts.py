"""Real local HTTP business service and R1 knowledge/case checks; no bank proof."""
import copy
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from contextlib import closing
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

WORKSPACE=Path(os.environ.get('AITEST_TEST_RUNTIME_SOURCE') or Path(__file__).resolve().parents[2])
sys.path[:0]=[str(WORKSPACE/'ai-test/runtime'),str(Path(__file__).parent)]
from aitest_runtime.recovery_api import expression, run_journey, pytest_asset
from aitest_runtime.recovery_executors import OfflineExecutor
from aitest_runtime.r3_3.contracts import StandardTestCase
from aitest_runtime.r3_3.engine import build_risk_vector
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.recovery_knowledge import task_view, candidate, TYPES
from aitest_runtime.r3_e1.contracts import KnowledgeFact, KnowledgeVersion, KnowledgeScopeIdentity, KnowledgeSourceRef, KnowledgeFreshness
from aitest_runtime.r3_e1.service import R3E1ApplicationService
from test_g2_1_session_router_control_loop import request


def standard_case(profile=None):
    result = {'tc_id':'TC-BUSINESS','case_version_id':'TC-BUSINESS:1','version':1,'lifecycle_status':'DRAFT',
      'strategy_version_id':'strategy:1','test_point_id':'point:1','batch_id':'batch:1','coverage_obligation_refs':['obligation:amount'],
      'requirement_id':'REQ-amount','sst_id':'SST-amount','layer_id':'L3','layer_profile_version':'r3.3.layer-profile.v1','case_type':'BOUNDARY',
      'priority':'HIGH','risk':build_risk_vector({},'risk-v1').to_dict(),'objective':'Reject amount exceeding approved credit and preserve repayment equality',
      'title':'Approved loan amount boundary','preconditions':[{'description':'Approved synthetic business service with isolated records'}],
      'test_data':[{'name':'approved_amount','value':100}], 'environment_and_boundary':{'scope':'loopback qualification'},
      'steps':[{'step':1,'action':'Submit limit boundary and inspect durable business state'}],
      'expected_results':[{'step':1,'expected':'Only positive amount within credit is accepted; total equals principal plus fee'}],
      'postconditions':[{'applicable':False,'reason':'Fixture records are discarded when the isolated local service stops'}],
      'oracle_contract':{'business_property':'approved_amount <= credit_limit','observation_fields':['amount','fee','total','state']},
      'evidence_requirements':[{'channel':'API','required':'Per-step response digest and business assertion outcomes'}],
      'execution_profile':profile or {'capability':'API'},'specification_status':'DETAILED','source_provenance':['qualification:business']}
    if profile and profile.get('api_journey'):
        from api_case_fixture import api_case_spec
        detail = api_case_spec(profile)
        result.update(steps=detail['ordered_steps'], expected_results=detail['expected_results'])
        result['oracle_contract'].update(detail['oracle'])
    return result


class BusinessService(BaseHTTPRequestHandler):
    bug=False
    def log_message(self,*_): pass
    def reply(self,body):
        raw=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));amount=body['amount']
        if amount<=0 or amount>100:self.reply({'code':'REJECTED','state':'REJECTED'});return
        self.reply({'id':'loan-1','code':'OK','state':'APPROVED','amount':amount,'fee':2,'total':amount+(3 if self.bug else 2)})
    def do_GET(self): self.reply({'id':'loan-1','code':'OK','state':'FUNDED'})


def journey(origin):
    return {'variables':{'requested':100},'steps':[
      {'step_id':'reject-boundary','url':origin+'/loans','method':'POST','json':{'amount':101},'status_code':200,
       'assertions':[{'op':'eq','path':'$.code','value':'REJECTED'}]},
      {'step_id':'reject-zero','url':origin+'/loans','method':'POST','json':{'amount':0},'status_code':200,
       'assertions':[{'op':'eq','path':'$.state','value':'REJECTED'}]},
      {'step_id':'approve','url':origin+'/loans','method':'POST','json':{'amount':'${requested}'},'headers':{'Idempotency-Key':'synthetic-1'},
       'status_code':200,'extract':{'loan':'$.id','prior_state':'$.state','amount':'$.amount','fee':'$.fee','total':'$.total'},
       'assertions':[{'op':'expression','expression':'amount + fee == total and amount <= 100'},
         {'op':'not_null','path':'$.id'},{'op':'range','path':'$.amount','min':1,'max':100},
         {'op':'in','path':'$.code','values':['OK']},{'op':'schema','path':'$','schema':{'type':'object','required':['id','total'],'properties':{'total':{'type':'number','minimum':1}}}}],
       'idempotency':{'paths':['$.id','$.amount','$.total']}},
      {'step_id':'fund','url':origin+'/loans/${loan}','method':'GET','status_code':200,
       'assertions':[{'op':'eq','path':'$.id','value':'${loan}'},{'op':'transition','path':'$.state','previous':'prior_state','from':'APPROVED','to':'FUNDED'}]}]}


class Contracts(unittest.TestCase):
    def test_detailed_case_is_same_r33_truth_used_by_g3_and_g4(self):
        from test_recovery_browser import governed_case
        from aitest_runtime.r3_3.service import R33ApplicationService
        from aitest_runtime.durable_core import canonical_sha256
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=create_canonical_runtime(root,db_path=root/'runtime.db')
            orch=G21AutonomousOrchestrationService(runtime,root,session_provider=FakeOpenCodeSessionProvider(root))
            mission=orch.start_test(request('case-qualification','V1'))['intake']['intake']['mission_id']
            fact,_=governed_case(root,runtime,mission)
            product_case=fact['payload']['r3_3_case']
            raw=next(x for x in R33ApplicationService(runtime).state(mission).standard_cases if x.case_version_id==product_case['case_version_id'])
            raw.validate_for_execution()
            self.assertEqual(canonical_sha256(raw.to_dict()),canonical_sha256(product_case))
            self.assertIn('detailed_spec_sha256',raw.source_context)

    def test_standard_case_runtime_rejects_empty_and_placeholder(self):
        StandardTestCase.from_dict(standard_case()).validate_for_execution()
        for key in ('steps','expected_results','test_data','preconditions','postconditions'):
            invalid=standard_case();invalid[key]=[]
            with self.assertRaises(Exception):StandardTestCase.from_dict(invalid).validate_for_execution()
        for placeholder in ['执行正向数据','操作系统','符合预期','功能正常']:
            invalid=standard_case();invalid['steps']=[{'action':placeholder}]
            with self.assertRaises(Exception):StandardTestCase.from_dict(invalid).validate_for_execution()
        invalid=standard_case();invalid['test_data']=[{'applicable':False}]
        with self.assertRaises(Exception):StandardTestCase.from_dict(invalid).validate_for_execution()

    def test_safe_business_expression_rejects_code(self):
        self.assertTrue(expression('principal + fee == total',{'principal':100,'fee':2,'total':102}))
        for source in ['__import__("os").system("id")','(1).__class__','x[0]','2 ** 999999','"x" * 999999','[x for x in y]']:
            with self.assertRaises(Exception):expression(source,{'x':[1],'y':[1]})

    def test_real_http_chain_detects_business_bug_despite_http_200(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),BusinessService);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            origin='http://127.0.0.1:'+str(server.server_port)
            with tempfile.TemporaryDirectory() as directory:
                executor=OfflineExecutor(directory,'API',{'approved':True,'approval_ref':'synthetic-test-only','allowed_origins':[origin],'allowed_methods':['GET','POST']})
                case=standard_case({'api_journey':journey(origin)});request_data={'authorized_scope':{'origins':[origin]}}
                result,passed=run_journey(executor,case,request_data)
                self.assertTrue(passed,result);self.assertEqual(len(result['steps']),4)
                self.assertNotIn('loan-1',json.dumps(result));self.assertLess(len(json.dumps(result).encode()),256*1024)
                BusinessService.bug=True
                result,passed=run_journey(executor,case,request_data)
                self.assertFalse(passed);self.assertEqual(result['steps'][-1]['status_code'],200)
                failed = next(row for row in result['steps'][-1]['oracles'] if row['kind']=='ASSERTION' and row['ordinal']==0)
                self.assertEqual(failed['status'],'FAIL');self.assertFalse(result['complete'])
                self.assertEqual(failed['diagnostic']['actual']['variables']['total'],103)
                # Generated pytest references immutable Case Truth and the G4 fixture.
                asset=pytest_asset(case);self.assertIn('aitest_governed_case_runner',asset);compile(asset,'candidate.py','exec')
                self.assertNotIn(origin,asset)
        finally:BusinessService.bug=False;server.shutdown();server.server_close();thread.join()

    def test_generated_pytest_and_reviewed_knowledge_use_canonical_g4(self):
        from unittest.mock import patch
        from test_recovery_browser import governed_case,exec_task
        from aitest_runtime.g4.service import G4RealExecutionService
        from aitest_runtime.recovery_knowledge import review
        from aitest_runtime.durable_core import canonical_sha256
        import pytest
        server=ThreadingHTTPServer(('127.0.0.1',0),BusinessService)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);origin='http://127.0.0.1:'+str(server.server_port)
                env={'AITEST_WORKSPACE_ROOT':str(root),'AITEST_RUNTIME_SPINE_DB':str(root/'runtime.db'),
                  'PFC_LOCAL_STATE_ROOT':str(root/'data'),'AITEST_AUTOMATION_RUN_ID':'loan-qualification','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
                with patch.dict(os.environ,env):
                    runtime=create_canonical_runtime(root,db_path=root/'runtime.db')
                    orch=G21AutonomousOrchestrationService(runtime,root,session_provider=FakeOpenCodeSessionProvider(root))
                    mission=orch.start_test(request('canonical-api','V1'))['intake']['intake']['mission_id']
                    fact,strategy=governed_case(root,runtime,mission,{'api_journey':journey(origin)})
                    case=fact['payload']['r3_3_case']
                    first=orch.propose_plan(mission,{'objective':'Exercise frozen loan business properties','tasks':[exec_task('loan-api',fact['fact_id'])],'dependencies':[]})['next']
                    config={'approved':True,'approval_ref':'LOCAL-ONLY','allowed_origins':[origin],'allowed_methods':['GET','POST']}
                    g4=G4RealExecutionService(runtime,orchestration=orch,capability_executors={'API':OfflineExecutor(root,'API',config)})
                    g4.create_goal(mission,{'goal_id':'goal-api','project_id':'LOCAL','release_id':'1.13.0','requirement_scope':['LOCAL-REQUIREMENT'],
                      'affected_applications':['local-target'],'affected_application_target_versions':{'local-target':'1.13.0'},'coverage_policy':{'target_pct':95}})
                    g4.create_batch(mission,{'batch_id':'batch-api','goal_id':'goal-api','case_refs':[fact['fact_id']],
                      'strategy_version_id':strategy,'target_application':'local-target','status':'RUNNING'})
                    execute={'task_id':first['task_id'],'attempt_id':first['attempt']['attempt_id'],'case_id':case['tc_id'],'case_version':case['case_version_id'],
                      'execution_batch_id':'batch-api','goal_id':'goal-api','capability_id':'API','executor_request':{'url':origin+'/loans','method':'POST','authorized_scope':{'origins':[origin]}}}
                    (root/'bindings').mkdir(exist_ok=True)
                    (root/'bindings/automation-runs.json').write_text(json.dumps({'runs':{'loan-qualification':{'approved':True,'approval_ref':'LOCAL-PYTEST','mission_id':mission,'execution_request':execute}}}))
                    from aitest_runtime.product_entry import g4_command
                    with patch('aitest_runtime.product_entry.g4_service',return_value=g4):
                        exported=g4_command('EXECUTOR','generate_api_automation',{
                          'mission_id':mission,**execute,'session_id':first['external_session']['session_id']})
                    asset_path=root/'data/evidence/automation'/(exported['program_sha256']+'.py')
                    import hashlib
                    self.assertEqual(hashlib.sha256(asset_path.read_bytes()).hexdigest(),exported['program_sha256'])
                    self.assertEqual(asset_path.read_text(),pytest_asset(case))
                    from aitest_runtime.g3.contracts import EXTENSION_ID as G3_EXTENSION
                    self.assertEqual(g4.runtime.replay_composed(mission).extension_state(G3_EXTENSION).by_id(exported['asset_ref']).payload['lifecycle'],'CANDIDATE')
                    generated=root/'test_generated_loan.py';generated.write_text(asset_path.read_text())
                    # Replace only service composition; admission, case resolution,
                    # actual HTTP execution and R1 Evidence all use the real G4.
                    with patch('aitest_runtime.product_entry.g4_service',return_value=g4):
                        code=pytest.main(['-q','-p','no:cacheprovider',str(generated)])
                    self.assertEqual(code,0)
                    result=g4.state(mission).latest('EXECUTION_STEP_RESULT')
                    self.assertEqual(result.payload['oracle_result'],'PASS');self.assertEqual(len(result.payload['actual']['steps']),4)
                    scope={'project_id':'LOCAL','environment_id':'SYNTHETIC','version_scope':'1.13.0'}
                    registered=candidate(runtime,mission,kind='StandardCase',subject='loan amount case',summary='loan amount and fee equality',source_fact_id=fact['fact_id'],scope=scope)
                    again=candidate(runtime,mission,kind='StandardCase',subject='loan amount case',summary='loan amount and fee equality',source_fact_id=fact['fact_id'],scope=scope)
                    self.assertEqual(again['version_id'],registered['version_id'])
                    with self.assertRaises(Exception):review(runtime,root,mission,registered['version_id'])
                    import sqlite3
                    with closing(sqlite3.connect(str(runtime.db_path))) as db:
                        version=json.loads(db.execute('SELECT state_json FROM r3e1_versions WHERE version_id=?',(registered['version_id'],)).fetchone()[0])
                    approval={'version_id':registered['version_id'],'payload_digest':version['payload_digest'],'approved':True,
                      'reviewer':'LOCAL-TEST-REVIEWER','approval_ref':'LOCAL-REVIEW','evidence_ref':result.fact_id,
                      'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
                    (root/'bindings/knowledge-reviews.json').write_text(json.dumps([approval]))
                    reviewed=review(runtime,root,mission,registered['version_id']);self.assertEqual(reviewed['lifecycle'],'VERIFIED')
                    view=task_view(runtime,scope=scope,task_id=first['task_id'],query='loan',role='aitest-executor')
                    self.assertEqual(view['items'][0]['version_id'],registered['version_id'])
                    from aitest_runtime.recovery_knowledge import link
                    other=candidate(runtime,mission,kind='EvidenceSummary',subject='loan execution',summary='loan business assertions passed',source_fact_id=result.fact_id,scope=scope)
                    with closing(sqlite3.connect(str(runtime.db_path))) as db:
                        ev=json.loads(db.execute('SELECT state_json FROM r3e1_versions WHERE version_id=?',(other['version_id'],)).fetchone()[0])
                    approval2={**approval,'version_id':other['version_id'],'payload_digest':ev['payload_digest'],'approval_ref':'LOCAL-EVIDENCE-REVIEW'}
                    (root/'bindings/knowledge-reviews.json').write_text(json.dumps([approval,approval2]))
                    review(runtime,root,mission,other['version_id'])
                    linked=link(runtime,mission,other['version_id'],registered['version_id']);self.assertTrue(linked['source_derived'])
                    graph=task_view(runtime,scope=scope,task_id=first['task_id'],query='loan',role='aitest-evaluator',max_bytes=8192)
                    self.assertEqual(graph['relations'][0]['semantic'],'DEPENDS_ON')
                    with self.assertRaises(Exception):link(runtime,mission,registered['version_id'],other['version_id'])
                    revised=candidate(runtime,mission,kind='StandardCase',subject='loan amount case',summary='loan revised expected total',source_fact_id=fact['fact_id'],scope=scope)
                    self.assertNotEqual(revised['version_id'],registered['version_id'])
                    self.assertEqual(task_view(runtime,scope=scope,task_id=first['task_id'],query='loan',role='aitest-executor')['items'],[])
        finally:server.shutdown();server.server_close();thread.join()

    def test_knowledge_scope_revision_lifecycle_ranking_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=create_canonical_runtime(root,db_path=root/'runtime.db')
            orch=G21AutonomousOrchestrationService(runtime,root,session_provider=FakeOpenCodeSessionProvider(root))
            mission=orch.start_test(request('knowledge-qualification','V1'))['intake']['intake']['mission_id']
            app=R3E1ApplicationService(runtime);scope=KnowledgeScopeIdentity('PFC','LOCAL','V1')
            now=datetime.now(timezone.utc);captured=now.isoformat();expiry=(now+timedelta(hours=1)).isoformat()
            for n,kind in enumerate(sorted(TYPES)):
                for status in ['CANDIDATE','SOURCE_VERIFIED','RUNTIME_VERIFIED']:
                    identity=f'{kind}:{status}';fid='knowledge:'+identity;vid=fid+':v1';sid='source:'+identity
                    source=KnowledgeSourceRef(sid,'RUNTIME','r1:'+identity,'rev1','hash:'+identity,scope,captured,captured,'BOUNDED')
                    fact=KnowledgeFact(fid,scope,'loan '+kind,kind,{'summary':'loan amount boundary'},vid,('REQ-loan',),{'kind':kind})
                    version=KnowledgeVersion(vid,fid,1,{'summary':'loan amount boundary '+kind},scope,status,'HIGH',(sid,),freshness_id='fresh:'+identity,verification_proof={'runtime_evidence_ref':'local-evidence:'+identity} if status=='RUNTIME_VERIFIED' else {})
                    registered=app.register_version(mission_id=mission,fact=fact,version=version,source_refs=(source,))
                    self.assertTrue(registered.ok,registered.to_dict())
                    fresh=KnowledgeFreshness('fresh:'+identity,vid,scope,'rec3-v1',captured,expiry,None,'FRESH',(sid,))
                    updated=app.record_freshness(mission_id=mission,freshness=fresh,source_refs=(source,))
                    self.assertTrue(updated.ok,updated.to_dict())
            from aitest_runtime.r3_e1.contracts import KnowledgeRelation,KnowledgeEndpointRef
            endpoints=[KnowledgeEndpointRef('knowledge:'+kind+':RUNTIME_VERIFIED',endpoint,'knowledge:'+kind+':RUNTIME_VERIFIED:v1',scope,('source:'+kind+':RUNTIME_VERIFIED',)) for kind,endpoint in [('Page','FRONTEND_PAGE'),('API','API_DEPENDENCY')]]
            relation=KnowledgeRelation('relation:loan-page-api',endpoints[0],endpoints[1],'ROUTES_TO',scope,'RUNTIME_VERIFIED',
                endpoints[0].source_ref_ids+endpoints[1].source_ref_ids,freshness_id='fresh:Page:RUNTIME_VERIFIED')
            recorded=app.record_relation(mission_id=mission,relation=relation,source_refs=())
            self.assertTrue(recorded.ok,recorded.to_dict())
            graph=task_view(runtime,scope=scope.to_dict(),task_id='task-loan',query='loan',role='aitest-executor',max_bytes=8192,max_items=32)
            self.assertEqual(graph['relations'][0]['semantic'],'ROUTES_TO')
            kwargs={'scope':scope.to_dict(),'task_id':'task-loan','query':'loan','role':'aitest-executor','refs':['REQ-loan'],'max_bytes':2048}
            view=task_view(runtime,**kwargs)
            self.assertTrue(view['items']);self.assertTrue(all(x['status']=='VERIFIED' and 'RUNTIME_VERIFIED' in x['fact_id'] for x in view['items']))
            self.assertLessEqual(len(json.dumps(view,ensure_ascii=False).encode()),2048)
            self.assertTrue(view['truncated'])
            restored=create_canonical_runtime(root,db_path=root/'runtime.db')
            self.assertEqual(view,task_view(restored,**kwargs))
            wrong=task_view(restored,**{**kwargs,'scope':{**scope.to_dict(),'version_scope':'V2'}});self.assertEqual(wrong['items'],[])
            for item in view['items']:
                revisions={s['locator']:'changed' for s in item['sources']}
                stale=task_view(restored,**{**kwargs,'source_revisions':revisions})
                self.assertNotIn(item['fact_id'],[x['fact_id'] for x in stale['items']])
            self.assertFalse((root/'ai-test/state/aitest.db').exists())


if __name__=='__main__':unittest.main(verbosity=2)
