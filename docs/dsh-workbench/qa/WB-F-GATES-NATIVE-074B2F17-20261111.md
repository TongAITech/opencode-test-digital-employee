# F independent Gates / native transport recheck

Candidate PR #215, exact source `074b2f17eb36b49222e48058c6fbd4fd9bd0693f`. Date: 2026-11-11.

**GATES_READONLY_COMPONENT_QA_ACCEPTED_EXACT_074B2F17**. The P1_NATIVE_FETCH_RECEIVER counterexample in F PR #221 is resolved on this exact source. That historical failure remains valid for `60f013d95171ad0c54851adcc5a87a8872fd77e4`. No result transfers to an older integrated f1/16fe source or any future joint HEAD: A must integrate both transport fixes and verify its resulting source.

## Source review

The product delta from 60f013d9 changes exactly two calls: RuntimeClient and DirectoryClient invoke `(0,this.fetcher)(...)` instead of a member invocation. ScopeClient's existing closure is unchanged. No backend, formal runtime writer, Mission creation, NodeGate authority, approval or production binding is added. Tasks and Gates use one RuntimeClient snapshot; switching those views does not query automatically. Readiness describes business Scope READY, not Host or whole-product readiness. Gates renders returned N10 records and original NodeGate decisions; absent nodes are missing, and Human approval remains UNKNOWN_NOT_QUERIED. “History” here is returned Gate records by ID, not a guarantee of every historical event revision.

## New actual verification at this SHA

- `node --test tests/test_dsh_workbench*.mjs`: **120/120**, no skip, 0.565 seconds.
- `python3 -m unittest discover -s tests/browser -p 'test*.py' -v`: **9/9**, 41.591 seconds; actual PostgreSQL 17.6, persisted synthetic R1, HTTP and Chromium. This includes the new unwrapped native default path; it is newly run by F, not C/A's result.
- Previous full F independent combined probe rerun against this SHA: **1/1**, 7.688 seconds. Its old failing ordinary second-window read now works. This probe includes a wrapped first window for delayed-response control, so it alone is insufficient to prove both default clients.
- New independent combined probe with **no assignment, binding or wrapper of window.fetch in either window**: **1/1**, 7.294 seconds before adding explicit request-count assertions; final exact rerun with both three-GET assertions **1/1, 7.245 seconds**. Both windows assert native-code function identity, traverse real directory → project → date → authorized Scope → runtime read, and observe graph/workitems/quality GETs. A deliberate `receiver={fetcher:fetch}; receiver.fetcher(...)` negative control still raises Illegal invocation. That failure is expected browser behavior, not a product PASS or hidden replacement of native fetch.

Commands use `PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages"` and `WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres'`. The final independent script is included below; no tested source was modified.

## Independent oracles and boundaries

Both first and second native windows require exactly three runtime GETs per initial read. Keyboard Tasks↔Gates navigation and zh-CN/en-US changes preserve Mission, R1 digest and as-of metadata with zero new runtime GETs. The second window starts empty. After explicit synthetic N10 PASS and two different Gate records PASS/BLOCKED are appended by the fixture writer, only manual refresh sees them; the other window retains its prior snapshot until refreshed. Every display remains HOLD and Human UNKNOWN_NOT_QUERIED. Controlled evidence bytes initially hash-match, then a file alteration yields HASH_MISMATCH only after that window's refresh. Neither hash equality nor Gate/N10 PASS grants release.

Independent failures injected into actual HTTP responses cover workitems 503, quality source_refs drift and a Gate referencing foreign delivery. Each clears all result rows, N10 summary and Mission/revision/as-of metadata in both views. Requirement, version and SST filters each block whole-batch runtime reads without issuing requests. Actual PostgreSQL ACL deletion causes runtime 403 and clears data; Scope reload loses READY, regrant plus explicit reload recovers. A real workitems response delayed at Playwright's network route is released after switching Tasks and changing batch; the late snapshot stays cleared. This route does not replace Window.fetch. At 375px the document fits. Both windows have no page errors, observed requests are GET-only and business API paths only, storage lacks Mission/snapshot facts, and UI reads leave persisted R1 bytes unchanged.

These are explicit synthetic R1 records, including manually appended N10, not production Mission creation, genuine autonomous N10 execution or Human approval. No SSE multiwindow synchronization is claimed. Native DSH, Windows/offline installation and final release remain outside this component acceptance. F modified only this independent report; 08/09/10 and tested implementation remain untouched.

## Executable independent probe

```python
import hashlib,json,os,pathlib,sys,threading,unittest
from dataclasses import asdict
from urllib.parse import urlsplit
sys.path.insert(0,os.getcwd());sys.path.insert(0,os.path.join(os.getcwd(),'tests'))
import test_dsh_workbench_e01_postgres as fixture
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Evidence
from rc7_runtime.rc72_domain import MissionNodeRecord,NodeDelivery,NodeGate
from rc7_runtime.rc72_truth import append_rc72_entity
from rc7_admin.product_server import ProductAdminApplication,create_server
from tools.dsh_workbench.business_http import HostIdentity,scope_handler
from tools.dsh_workbench.e02_service import E02Service
from playwright.sync_api import sync_playwright

class IndependentGates(unittest.TestCase):
 def test_shared_snapshot_history_two_windows_and_all_clear_paths(self):
  db=fixture.E01(methodName='test_e01_real_pg_http_persistent_r1_readonly_and_cold_recovery');db.setUp();self.addCleanup(db.doCleanups);db.scope_seed();db.setup_r1()
  # Only explicit persistent synthetic R1 fixture, not production Mission creation or accepted N10 execution.
  truth=TruthRuntime(db.r1);file=db.root/'F-file';file.write_bytes(b'F fixture evidence bytes only');file_before=file.read_bytes()
  truth.append_atomic('RC7_EVIDENCE_UPSERTED',dict(asdict(Evidence(evidence_id='F_EVIDENCE',mission_id='M1',kind='fixture',source_ref='F:fixture-only',content_ref=file.as_uri(),content_hash='sha256:'+hashlib.sha256(file_before).hexdigest())),release_id='B1'))
  handler=scope_handler(lambda:fixture.prior.prior.prior.psycopg.connect(**db.params,autocommit=True),db.scope.key,lambda req:HostIdentity('alice') if req.headers.get('Cookie')=='fixture=f-gates' else None,lambda store:E02Service(store,db.r1,db.root))
  server=create_server(ProductAdminApplication(str(db.r1)),port=0,workbench_handler=handler);origin='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  with sync_playwright() as p:
   browser=p.chromium.launch();context=browser.new_context(viewport={'width':375,'height':812});context.add_cookies([{'name':'fixture','value':'f-gates','url':origin}]);page=context.new_page();requests=[];errors=[]
   page.on('request',lambda req:requests.append((req.method,req.url)));page.on('pageerror',lambda error:errors.append(str(error)))

   def open_scope(target):
    target.goto(origin+'/workbench/');self.assertIn('[native code]',target.evaluate('Function.prototype.toString.call(window.fetch)'));target.locator('#project-entry').click();target.locator('#sections [data-id=gates]').click();target.locator('[data-directory-load]').click();target.wait_for_selector('#project-directory[data-directory-status=READY]');target.select_option('[data-project-select]','P1');target.wait_for_function("document.querySelector('[data-date-select] option[value=B1]')");target.select_option('[data-date-select]','B1');target.wait_for_selector('#business-scope[data-scope-status=READY]')
   def read(target):
    panel=target.locator('#runtime-facts');panel.locator('[name=runtime-mission-id]').fill('M1');panel.locator('[data-runtime-load]').click();target.wait_for_selector('#runtime-facts[data-runtime-status=READY],#runtime-facts[data-runtime-status=ERROR]');self.assertEqual(panel.get_attribute('data-runtime-status'),'READY',panel.inner_text())
   def metadata(panel):return [panel.get_attribute('data-runtime-'+key) for key in ['mission','revision','as-of']]
   def clear(panel):
    self.assertEqual(panel.locator('[data-runtime-results] tr').count(),0);self.assertEqual(metadata(panel),[None,None,None]);self.assertEqual(panel.locator('[data-runtime-n10]').count(),0)
   def runtime_requests():return [(m,u) for m,u in requests if '/missions/' in u or '/quality?' in u]
   open_scope(page);panel=page.locator('#runtime-facts');self.assertIn('业务范围已加载',page.locator('#readiness').inner_text());read(page);self.assertEqual(panel.locator('[data-runtime-n10]').get_attribute('data-runtime-n10'),'NOT_RECORDED');first_meta=metadata(panel);first_count=len(runtime_requests());self.assertEqual(first_count,3)
   for section in ['tasks','gates','tasks','gates']:
    page.locator('#sections [data-id='+section+']').focus();page.keyboard.press('Enter');self.assertEqual(metadata(panel),first_meta)
   page.select_option('#locale','en-US');self.assertEqual(metadata(panel),first_meta);page.select_option('#locale','zh-CN');self.assertEqual(metadata(panel),first_meta);self.assertEqual(len(runtime_requests()),first_count)
   self.assertNotEqual(page.evaluate('document.activeElement.tagName'),'BODY')
   append_rc72_entity(truth,MissionNodeRecord(mission_node_id='F_N10',mission_id='M1',node_type='N10_RELEASE_CONVERGENCE',scope_ref='B1',state='PASS'),release_id='B1')
   append_rc72_entity(truth,NodeDelivery(delivery_id='F_D10',mission_id='M1',mission_node_id='F_N10',node_type='N10_RELEASE_CONVERGENCE',version=1,producer_ref='F-fixture'),release_id='B1')
   for gate,decision in [('F_G10_PASS','PASS'),('F_G10_BLOCK','BLOCKED')]:
    append_rc72_entity(truth,NodeGate(gate_id=gate,mission_id='M1',mission_node_id='F_N10',node_type='N10_RELEASE_CONVERGENCE',delivery_id='F_D10',decision=decision,reviewer_worker_id='fixture-reviewer',reviewer_session_id='fixture-session',criteria=['fixture-only']),release_id='B1')
   
   before=db.r1.read_bytes();self.assertEqual(metadata(panel),first_meta);self.assertEqual(panel.locator('[data-runtime-n10]').get_attribute('data-runtime-n10'),'NOT_RECORDED')
   # A new page shares only saved UI preferences, not Scope, Mission, facts or subscriptions.
   second=context.new_page();second.on('request',lambda req:requests.append((req.method,req.url)));second.on('pageerror',lambda error:errors.append(str(error)));second.goto(origin+'/workbench/');second.locator('#project-entry').click();second.locator('#sections [data-id=gates]').click();self.assertEqual(second.locator('[name=runtime-mission-id]').input_value(),'');clear(second.locator('#runtime-facts'))
   open_scope(second);self.assertIn('Illegal invocation',second.evaluate("async()=>{const receiver={fetcher:fetch};try{await receiver.fetcher('/workbench/');return 'UNEXPECTED_SUCCESS'}catch(e){return e.name+':'+e.message}}"));read(second);self.assertEqual(len(runtime_requests()),6);second_panel=second.locator('#runtime-facts');self.assertEqual(second_panel.locator('[data-runtime-n10]').get_attribute('data-runtime-n10'),'RECORDED');self.assertNotEqual(metadata(second_panel)[1],first_meta[1]);self.assertEqual(metadata(panel),first_meta)
   read(page);self.assertEqual(panel.locator('[data-runtime-n10]').get_attribute('data-runtime-n10'),'RECORDED');self.assertIn('PASS',panel.locator('[data-record-id=F_G10_PASS]').inner_text());self.assertIn('BLOCKED',panel.locator('[data-record-id=F_G10_BLOCK]').inner_text());self.assertEqual(panel.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'),'HOLD');self.assertEqual(panel.locator('[data-runtime-human]').get_attribute('data-runtime-human'),'UNKNOWN_NOT_QUERIED');self.assertIn('HASH_VERIFIED_ONLY',panel.locator('[data-record-id=F_EVIDENCE]').inner_text());self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
   # Integrity changes require each window's explicit refresh; no claimed SSE synchronization.
   file.write_bytes(b'changed fixture content');read(second);self.assertIn('HASH_MISMATCH',second_panel.inner_text());self.assertIn('HASH_VERIFIED_ONLY',panel.inner_text());self.assertEqual(second_panel.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'),'HOLD');file.write_bytes(file_before)
   def failure(route):route.fulfill(status=503,json={'error':{'code':'F_UNAVAILABLE'}})
   def bad_source(route):
    response=route.fetch();value=response.json();value['source_refs']=['F:wrong-source'];route.fulfill(response=response,json=value)
   def bad_gate(route):
    response=route.fetch();value=response.json();value['records']['rc72_node_gate'][0]['delivery_id']='FOREIGN';route.fulfill(response=response,json=value)
   for pattern,handler,code in [('**/missions/M1/workitems?*',failure,'HTTP_503'),('**/quality?*',bad_source,'RUNTIME_SOURCE_CHANGED'),('**/missions/M1/graph?*',bad_gate,'INVALID_CANONICAL_GATE')]:
    read(page);page.route(pattern,handler);panel.locator('[data-runtime-load]').click();page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]');self.assertIn(code,panel.locator('[data-runtime-status]').inner_text());clear(panel);n=len(runtime_requests());page.locator('#sections [data-id=tasks]').click();clear(panel);page.locator('#sections [data-id=gates]').click();clear(panel);self.assertEqual(len(runtime_requests()),n);page.unroute(pattern,handler)
   read(page);self.assertIn('业务范围已加载',page.locator('#readiness').inner_text())
   for key,values in [('requirement',['R2']),('version',['V1']),('sst',['SST1'])]:
    page.select_option('[data-scope='+key+']',values);clear(panel);self.assertTrue(panel.locator('[data-runtime-load]').is_disabled());self.assertIn('整批次',panel.locator('[data-runtime-status]').inner_text());n=len(runtime_requests());page.locator('#sections [data-id=tasks]').click();clear(panel);page.locator('#sections [data-id=gates]').click();clear(panel);self.assertEqual(len(runtime_requests()),n);page.select_option('[data-scope='+key+']',[]);read(page)
   db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'");panel.locator('[data-runtime-load]').click();page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]');self.assertIn('HTTP_403',panel.locator('[data-runtime-status]').inner_text());clear(panel);page.locator('#sections [data-id=tasks]').click();clear(panel);page.locator('#sections [data-id=gates]').click();clear(panel);page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]');self.assertNotIn('业务范围已加载',page.locator('#readiness').inner_text())
   db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)");page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]');read(page)
   pending=[]
   def delayed(route):pending.append((route,route.fetch()))
   page.route('**/missions/M1/workitems?*',delayed);panel.locator('[data-runtime-load]').click();page.wait_for_timeout(250);self.assertEqual(len(pending),1);clear(panel);n=len(runtime_requests());page.locator('#sections [data-id=tasks]').click();clear(panel);self.assertEqual(len(runtime_requests()),n);page.locator('[name=batch_id]').fill('foreign-scope');pending[0][0].fulfill(response=pending[0][1]);page.wait_for_timeout(100);clear(panel);page.locator('#sections [data-id=gates]').click();clear(panel);self.assertNotIn('业务范围已加载',page.locator('#readiness').inner_text());self.assertIn('[native code]',page.evaluate('Function.prototype.toString.call(window.fetch)'));self.assertIn('[native code]',second.evaluate('Function.prototype.toString.call(window.fetch)'))
   storage=page.evaluate('JSON.stringify({local:{...localStorage},session:{...sessionStorage}})');self.assertNotIn('M1',storage);self.assertNotIn('F_N10',storage);self.assertNotIn(first_meta[1],storage);self.assertTrue(all(method=='GET' for method,url in requests));self.assertTrue(all(urlsplit(url).path.startswith('/api/workbench/v1/') for method,url in requests if urlsplit(url).path.startswith('/api/')));self.assertEqual(errors,[]);self.assertEqual(db.r1.read_bytes(),before);second.close();browser.close()

unittest.main(verbosity=2)
```
