"""Real persistent Chromium + G4 R1 actions/leases. Local fixture, never bank PASS."""
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

WORKSPACE=Path(os.environ.get('AITEST_TEST_RUNTIME_SOURCE') or Path(__file__).resolve().parents[2])
sys.path[:0]=[str(WORKSPACE/'ai-test/runtime'),str(Path(__file__).parent)]
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.recovery_browser import CDPBrowserProvider,TeachingObserver
from aitest_runtime.recovery_executors import OfflineExecutor
from test_g2_1_session_router_control_loop import request
from test_recovery_browser import governed_case,exec_task


class Pages(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.path=='/frame':raw=b'<button data-testid="frame-button">Frame action</button>'
        elif self.path=='/popup':raw=b'<div data-testid="popup-state">Popup ready</div>'
        elif self.path=='/api':raw=b'{"code":"OK"}'
        else:raw=b'''<html><head><title>Loan qualification</title></head><body>
        <label>Amount<input id="amount" data-testid="amount" /></label>
        <select data-testid="term"><option value="12">12 months</option></select>
        <input data-testid="agree" type="checkbox" />
        <button data-testid="submit" onclick="document.querySelector('#state').textContent='Submitted';fetch('/api')">Submit loan</button>
        <div id="state" data-testid="state">Draft</div><div id="page-ready">Loan page</div>
        <button data-testid="finish" onclick="document.querySelector('#authenticated').hidden=false;document.querySelector('#business').hidden=false">Finish human step</button>
        <div id="authenticated" hidden>Signed in</div><div id="business" hidden>Ready</div>
        <iframe name="loan-frame" src="/frame"></iframe>
        <a data-testid="popup" href="/popup" target="_blank">Open popup</a></body></html>'''
        self.send_response(200);self.send_header('Content-Type','application/json' if self.path=='/api' else 'text/html');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


def actions(origin,human=False):
    steps=[{'action':'navigate','url':origin+'/'},{'action':'fill','locator':{'testid':'amount'},'value':'100'},
      {'action':'assert_value','locator':{'testid':'amount'},'value':'100'},
      {'action':'select','locator':{'testid':'term'},'value':'12'},
      {'action':'check','locator':{'testid':'agree'}},
      {'action':'assert_state','locator':{'testid':'agree'},'state':'checked'},
      {'action':'uncheck','locator':{'testid':'agree'}},
      {'action':'hover','locator':{'testid':'submit'}},
      {'action':'keyboard','locator':{'testid':'amount'},'value':'Tab'}]
    if human:steps.append({'action':'human_gate','description':'Complete synthetic controlled browser step',
      'resume_condition':{'authenticated_selector':'#authenticated','page_selector':'#page-ready','business_selector':'#business'}})
    steps += [{'action':'click','locator':{'testid':'submit'}},
      {'action':'wait_for','locator':{'testid':'state'}},
      {'action':'assert_text','locator':{'testid':'state'},'value':'Submitted'},
      {'action':'assert_network','path':'/api','status':200},
      {'action':'frame','frame':'iframe[name="loan-frame"]'},
      {'action':'click','locator':{'testid':'frame-button','frame':'iframe[name="loan-frame"]'}},
      {'action':'screenshot'},
      {'action':'popup','locator':{'testid':'popup'}},
      {'action':'assert_url','url':origin+'/popup'},
      {'action':'assert_visible','locator':{'testid':'popup-state'}}]
    return steps


@unittest.skipUnless(os.environ.get('AITEST_BROWSER_SMOKE_CHROMIUM'),'Explicit real Chromium required')
class BrowserJourney(unittest.TestCase):
    def run_mode(self,mode,human=False):
        from playwright.sync_api import sync_playwright
        server=ThreadingHTTPServer(('127.0.0.1',0),Pages);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();pid=None
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
                root=Path(directory);origin='http://127.0.0.1:'+str(server.server_port)
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                config={'approved':True,'approval_ref':'LOCAL-SYNTHETIC-ONLY','allowed_origins':[origin],'allowed_methods':['GET','POST'],
                    'start_url':origin+'/','cdp_endpoint':'http://127.0.0.1:'+str(port),
                    'local_chromium_path':os.environ['AITEST_BROWSER_SMOKE_CHROMIUM'],
                    'resume_checks':{'authenticated_selector':'#authenticated','page_selector':'#page-ready','business_selector':'#business'}}
                (root/'bindings').mkdir();(root/'bindings/browser.json').write_text(json.dumps(config))
                (root/'bindings/execution.json').write_text(json.dumps(config))
                with patch.dict(os.environ,{'AITEST_WORKSPACE_ROOT':str(root),'AITEST_RUNTIME_SPINE_DB':str(root/'runtime.db'),'PFC_LOCAL_STATE_ROOT':str(root/'data')}):
                    runtime=create_canonical_runtime(root,db_path=root/'runtime.db');orch=G21AutonomousOrchestrationService(runtime,root,session_provider=FakeOpenCodeSessionProvider(root))
                    mission=orch.start_test(request('real-ui',mode))['intake']['intake']['mission_id']
                    profile={'ui_journey':{'mode':mode,'steps':actions(origin,human)}}
                    case_fact,strategy=governed_case(root,runtime,mission,profile);case=case_fact['payload']['r3_3_case']
                    first=orch.propose_plan(mission,{'objective':'Real UI governed qualification','tasks':[exec_task('ui-journey',case_fact['fact_id'])],'dependencies':[]})['next']
                    provider=CDPBrowserProvider(root,config=config,runtime=runtime)
                    with patch.object(provider,'_chromium_path',return_value=Path(os.environ['AITEST_BROWSER_SMOKE_CHROMIUM'])):
                        started=provider.launch_browser(headless=True)
                    pid=started['pid'];ref=provider.context_ref()
                    g4=G4RealExecutionService(runtime,orchestration=orch,browser_provider=provider,
                        capability_executors={'BROWSER_UI':OfflineExecutor(root,'BROWSER_UI',config)})
                    g4.create_goal(mission,{'goal_id':'goal-ui','project_id':'LOCAL','release_id':'1.13.0','requirement_scope':['LOCAL-REQUIREMENT'],
                      'affected_applications':['local-target'],'affected_application_target_versions':{'local-target':'1.13.0'},'coverage_policy':{'target_pct':95}})
                    g4.create_batch(mission,{'batch_id':'batch-ui','goal_id':'goal-ui','case_refs':[case_fact['fact_id']],
                      'strategy_version_id':strategy,'target_application':'local-target','status':'RUNNING'})
                    execution={'task_id':first['task_id'],'attempt_id':first['attempt']['attempt_id'],'case_id':case['tc_id'],
                      'case_version':case['case_version_id'],'execution_batch_id':'batch-ui','goal_id':'goal-ui','capability_id':'BROWSER_UI',
                      'executor_request':{'url':origin+'/','authorized_scope':{'origins':[origin]},'browser_context_ref':ref.to_dict()}}
                    for _ in range(65):
                        result=g4.execute_capability(mission,execution)
                        if result.get('complete') or result['status']!='PASS':break
                    if human:
                        self.assertEqual(result['status'],'WAITING_HUMAN',result)
                        observer=TeachingObserver(provider,mission)
                        self.assertTrue(observer.execution_lineage)
                        with self.assertRaises(Exception):g4.complete_human_takeover(mission,{'completion_mode':'EXPLICIT'})
                        with sync_playwright() as driver:
                            browser=driver.chromium.connect_over_cdp(provider.endpoint);page=browser.contexts[0].pages[0]
                            observer.snapshot(page);page.get_by_test_id('finish').click();page.wait_for_timeout(150)
                            asset=observer.flush()
                            self.assertTrue(asset['payload']['execution_lineage']['root_attempt_id'])
                            self.assertTrue(any(x.get('element',{}).get('locator_candidates') for x in asset['payload']['observations']))
                        completed=g4.complete_human_takeover(mission,{'completion_mode':'EXPLICIT'})
                        self.assertEqual(completed['status'],'RESUME_SAFE',completed)
                        result=completed['ui_continuation']
                        from aitest_runtime.recovery_teaching import generate_candidate,validate_replay
                        candidate=generate_candidate(runtime,mission,asset['fact_id'])
                        config['replay_approvals']=[{'approved':True,'approval_ref':'SYNTHETIC_REPLAY_APPROVAL',
                          'candidate_ref':candidate['fact_id'],'program_sha256':candidate['payload']['program_sha256']}]
                        (root/'bindings/browser.json').write_text(json.dumps(config))
                        with sync_playwright() as driver:
                            browser=driver.chromium.connect_over_cdp(provider.endpoint)
                            page=next(p for p in browser.contexts[0].pages if p.url==origin+'/')
                            replay=validate_replay(runtime,mission,candidate['fact_id'],page=page,variables={},
                              evidence_root=root/'data/evidence/replay',approval_ref='SYNTHETIC_REPLAY_APPROVAL',context_ref=ref.to_dict())
                            self.assertEqual(replay['payload']['replay_status'],'PASS',replay)
                            self.assertFalse(replay['payload']['automatic_promotion']);self.assertEqual(replay['payload']['g6'],'HOLD')
                    self.assertEqual(result['status'],'PASS',result);self.assertTrue(result.get('complete'),result)
                    self.assertEqual(provider.context_ref().context_binding_digest,ref.context_binding_digest)
                    receipts=g4.state(mission).by_kind('EXECUTION_STEP_RESULT')
                    self.assertEqual(len(receipts),len(actions(origin,human))-(1 if human else 0))
                    self.assertTrue(all(r.payload['oracle_result']=='PASS' for r in receipts))
                    self.assertFalse((root/'ai-test/state/aitest.db').exists())
        finally:
            if pid:
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
            server.shutdown();server.server_close();thread.join()

    def test_scripted_multistep(self):self.run_mode('PLAYWRIGHT_SCRIPTED_AUTOMATION')
    def test_ai_interactive_same_case_truth(self):self.run_mode('AI_BROWSER_INTERACTIVE_EXECUTION')
    def test_human_gate_same_context_automatically_continues(self):self.run_mode('PLAYWRIGHT_SCRIPTED_AUTOMATION',True)


if __name__=='__main__':unittest.main(verbosity=2)
