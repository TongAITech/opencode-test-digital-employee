"""Real local Chromium/CDP + R1 recovery; synthetic page, never bank validation."""
import argparse,hashlib,json,os,socket,subprocess,sys,tempfile,threading,time,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from unittest.mock import patch
repo=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(repo/'tests/v4'))
from test_human_gate_resume import seed
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.recovery_browser import CDPBrowserProvider
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.human_gate_resume_receipts import GateResumeReceipt

class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'<html><body><div id="auth">Authenticated fixture</div><div id="page">Protected page fixture</div><div id="business">Ready</div></body></html>')
    def log_message(self,*args):pass

def main():
    p=argparse.ArgumentParser();p.add_argument('--chrome',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    server=ThreadingHTTPServer(('127.0.0.1',0),Page);threading.Thread(target=server.serve_forever,daemon=True).start()
    page=f'http://127.0.0.1:{server.server_port}'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='gate-cdp-profile-') as td,(out/'chromium.log').open('wb') as log:
        chrome=subprocess.Popen([str(a.chrome),'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking',
            '--disable-component-update','--disable-sync','--disable-default-apps','--disable-extensions','--metrics-recording-only','--disable-features=MediaRouter','--remote-debugging-address=127.0.0.1','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',f'--remote-debugging-port={port}',f'--user-data-dir={out / "owned-chrome-profile"}',page],stdout=log,stderr=subprocess.STDOUT)
        try:
            endpoint=f'http://127.0.0.1:{port}'
            for _ in range(80):
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(endpoint+'/json/version',timeout=1) as f:version=json.load(f)
                    break
                except Exception:
                    if chrome.poll() is not None:raise RuntimeError('LOCAL_CHROMIUM_EXITED:'+str(chrome.returncode))
                    time.sleep(.1)
            else:raise RuntimeError('LOCAL_CDP_UNAVAILABLE')
            root=out/'workspace';root.mkdir();db=root/'spine.db';runtime=create_canonical_runtime(root,db_path=db)
            checks={'authenticated_selector':'#auth','page_selector':'#page','business_selector':'#business'}
            config={'approved':True,'approval_ref':'disposable-component-fixture','allowed_origins':[page],'cdp_endpoint':endpoint,'resume_checks':checks}
            browser=CDPBrowserProvider(root,config,runtime)
            # Supply the same approved DOM condition used by the existing G4 seed.
            real_request=G4RealExecutionService.request_human_takeover
            def request(service,mid,data):return real_request(service,mid,{**data,'resume_condition':checks})
            with patch.object(G4RealExecutionService,'request_human_takeover',new=request):mid,g4,_,orch,attempt=seed(root,runtime,browser=browser)
            ref=browser.context_ref();assert browser.inspect_lease(ref)=='HUMAN'
            actual=g4.human_gates.record_decision
            def crash(*args,**kwargs):actual(*args,**kwargs);raise SystemExit('COMMITTED_DECISION_LOST_RETURN')
            try:
                with patch.object(g4.human_gates,'record_decision',side_effect=crash):g4.complete_human_takeover(mid,{'human_gate_id':'gate-explicit','completion_mode':'EXPLICIT'})
            except SystemExit:pass
            else:raise AssertionError('CRASH_NOT_INJECTED')
            runtime=create_canonical_runtime(root,db_path=db)
            fresh=CDPBrowserProvider(root,config,runtime);assert fresh is not browser and fresh._pending_owner is None
            assert fresh.inspect_lease(ref)=='AI'
            g4=G4RealExecutionService(runtime,orchestration=orch,browser_provider=fresh)
            with patch.object(fresh,'transfer_lease',side_effect=AssertionError('DUPLICATE_HANDBACK')):
                result=g4.complete_human_takeover(mid,{'human_gate_id':'gate-explicit','completion_mode':'EXPLICIT'})
            assert result['status']=='RESUME_SAFE'
            assert GateResumeReceipt(runtime,mid,'gate-explicit').state().phase=='COMPLETED'
            evidence={'status':'PASS','classification':'REAL_LOCAL_CHROMIUM_CDP_R1_COMPONENT_SYNTHETIC_PAGE_NOT_BANK_NOT_REAL_MODEL',
                'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'working_tree':subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip() or 'CLEAN',
                'browser_version':version.get('Browser'),'chrome_path':str(a.chrome),'chrome_sha256':hashlib.sha256(a.chrome.read_bytes()).hexdigest(),
                'fresh_adapter_pending_owner':None,'fresh_adapter_lease':'AI','same_context_digest':fresh.context_ref().context_binding_digest==ref.context_binding_digest,
                'duplicate_handback':0,'completion':'RESUME_SAFE','runtime_truth':'R1_EVENT_STREAM','bank_field':'NOT_RUN'}
            (out/'result.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence,indent=2))
        finally:
            chrome.terminate()
            try:chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:chrome.kill();chrome.wait()
            server.shutdown();server.server_close()
    return 0
if __name__=='__main__':raise SystemExit(main())
