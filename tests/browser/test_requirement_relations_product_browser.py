"""Native browser, same ScopeClient and real PostgreSQL relation Oracle; no requirement-document claim."""
import json
import pathlib
import sys
import threading
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_b_scope_postgres as fixture
from tools.dsh_workbench.business_relations import import_sst_identity,import_verified_sst_link,import_verified_requirement_version
from tools.dsh_workbench.business_http import scope_handler,HostIdentity
from rc7_admin.product_server import WorkbenchPublicApplication,create_server
from playwright.sync_api import sync_playwright

class RequirementRelationsBrowser(unittest.TestCase):
 def test_native_scope_exact_edges_sources_pagination_selection_and_recovery(self):
  if not fixture.prior.prior.DSN or not fixture.prior.prior.psycopg:self.fail('REAL_POSTGRESQL_REQUIRED')
  db=fixture.Scope(methodName='test_scope_pages_real_join_unsplit_sources_and_bound_cursors');db.setUp();server=None
  try:
   db.scope_seed()
   import_sst_identity(db.owner,'P1','V1','SST2','src','prod','raw2','r2','source:sst2')
   import_verified_sst_link(db.owner,'P1','B1','R2','V1','SST2','source:link2','link-r2')
   revision=db.relations.attach_sst('alice','P1','B1','R2','V1','SST2',7,'attach2')
   hostile='source:<img src=x onerror=window.injected=true>'
   for i in range(3,102):
    req='R%03d'%i
    db.relations.create_requirement('alice','P1',req,'src','prod',req,'r1','source:'+req,'create:'+req)
    revision=db.relations.attach_member('alice','P1','B1','requirement',req,revision,'member:'+req)
    import_verified_requirement_version(db.owner,'P1','B1',req,'V1',hostile if i==101 else 'source:rv:'+req,'rv-revision:'+req)
    revision=db.relations.attach_requirement_version('alice','P1','B1',req,'V1',revision,'rv:'+req)
   oracle=db.owner.execute('''SELECT r.requirement_id,r.version_id,s.sst_id,rv.source_link_ref,rv.source_revision,l.source_link_ref,l.verified_source_revision FROM wb.batch_requirement_version r JOIN wb.verified_requirement_version rv USING(project_id,batch_id,requirement_id,version_id) LEFT JOIN wb.batch_requirement_version_sst s USING(project_id,batch_id,requirement_id,version_id) LEFT JOIN wb.verified_sst_link l USING(project_id,batch_id,requirement_id,version_id,sst_id) WHERE r.project_id='P1' AND r.batch_id='B1' ORDER BY r.requirement_id,r.version_id,s.sst_id NULLS FIRST''').fetchall()
   available=[True]
   def connect():
    if not available[0]:raise ConnectionError('explicit fixture service unavailable')
    return fixture.prior.prior.psycopg.connect(**db.params,autocommit=True)
   server=create_server(WorkbenchPublicApplication(),port=0,workbench_handler=scope_handler(connect,db.scope.key,lambda request:HostIdentity('alice') if request.headers.get('Cookie')=='fixture=requirement-relations' else None))
   threading.Thread(target=server.serve_forever,daemon=True).start();origin='http://127.0.0.1:'+str(server.server_port)
   with sync_playwright() as p:
    browser=p.chromium.launch();context=browser.new_context(viewport={'width':375,'height':812});context.add_cookies([{'name':'fixture','value':'requirement-relations','url':origin}]);page=context.new_page();requests=[];errors=[]
    page.on('request',lambda req:requests.append((req.method,req.url)));page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(origin+'/workbench/');self.assertIn('[native code]',page.evaluate('Function.prototype.toString.call(fetch)'))
    page.locator('#project-entry').click();page.locator('#sections [data-id=requirements]').focus();page.keyboard.press('Enter');panel=page.locator('#requirement-relations')
    self.assertEqual(panel.get_attribute('data-relations-status'),'NOT_READY');self.assertEqual(panel.locator('article').count(),0)
    page.locator('[name=project_id]').fill('P1');page.locator('[name=batch_id]').fill('B1');page.locator('[name=release_date]').fill('2026-11-12')
    def load():
     page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]')
    def keys():return [json.loads(value) for value in panel.locator('article').evaluate_all('(rows)=>rows.map(row=>row.dataset.relationKey)')]
    def clear():
     self.assertEqual(panel.locator('article').count(),0);self.assertIsNone(panel.get_attribute('data-relation-scope'));self.assertIsNone(panel.get_attribute('data-relation-revision'))
    load();self.assertEqual(keys(),[list(row[:3]) for row in oracle]);self.assertEqual(len(oracle),101)
    self.assertTrue(any('page_cursor=' in url for method,url in requests));self.assertEqual(panel.get_attribute('data-relation-revision'),str(revision))
    self.assertEqual(json.loads(panel.get_attribute('data-relation-scope')),['P1','B1','2026-11-12'])
    for row in oracle:
     article=panel.locator('article').filter(has=page.locator('h4',has_text=row[0]+' →'))
     for value in row[3:]:
      if value is not None:self.assertIn(value,article.inner_text())
    self.assertIn('待拆分（UNSPLIT）',panel.inner_text());self.assertEqual(panel.locator('img').count(),0);self.assertIsNone(page.evaluate('window.injected'))
    page.select_option('[data-scope=requirement]',['R1','R2']);self.assertEqual(keys(),[['R1','V1','SST1'],['R2','V1','SST2']])
    page.select_option('[data-scope=version]',['V1']);page.select_option('[data-scope=sst]',['SST2']);self.assertEqual(keys(),[['R2','V1','SST2']])
    reads=len(requests);page.select_option('#locale','en-US');self.assertEqual(keys(),[['R2','V1','SST2']]);self.assertIn('not requirement document sources',panel.inner_text());self.assertEqual(len(requests),reads)
    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
    page.locator('#sections [data-id=requirements]').focus();page.keyboard.press('Tab');self.assertNotEqual(page.evaluate('document.activeElement.tagName'),'BODY')
    page.select_option('[data-scope=requirement]',[]);self.assertEqual(len(keys()),101)
    # Source refs belong to the complete validated Scope, not a new view query/cache.
    for section in ['overview','gates','requirements']:
     page.locator('#sections [data-id='+section+']').click()
    self.assertEqual(len(keys()),101)
    # Real second-page delivery is held; no partial first page can appear, then Scope edit aborts it.
    held=[]
    def hold_page(route):
     response=route.fetch()
     if 'page_cursor=' in route.request.url:held.append((route,response))
     else:route.fulfill(response=response)
    page.route('**/scope?*',hold_page);page.locator('#business-scope button').click();page.wait_for_function('document.querySelector("#business-scope").dataset.scopeStatus==="LOADING"')
    for _ in range(100):
     if held:break
     page.wait_for_timeout(20)
    self.assertTrue(held);clear();page.locator('[name=batch_id]').fill('other')
    for route,response in held:
     try:route.fulfill(response=response)
     except Exception:pass  # Browser may already have aborted the request.
    page.unroute('**/scope?*',hold_page);clear();self.assertEqual(panel.get_attribute('data-relations-status'),'NOT_READY')
    page.locator('[name=batch_id]').fill('B1');load();self.assertEqual(len(keys()),101)
    db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'");page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]');clear()
    db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)");load();self.assertEqual(len(keys()),101)
    available[0]=False;page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]');clear();available[0]=True;load()
    db.store.reschedule('alice','P1','B1','2026-11-13',1,'fixture-move','explicit fixture approved date change','fixture-approval')
    page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]');clear()
    page.locator('[name=release_date]').fill('2026-11-13');load();self.assertEqual(json.loads(panel.get_attribute('data-relation-scope')),['P1','B1','2026-11-13']);self.assertEqual(len(keys()),101)
    self.assertTrue(all(method=='GET' for method,url in requests));self.assertFalse(any('/api/' in url and '/api/workbench/v1/' not in url for method,url in requests));self.assertEqual(errors,[])
    self.assertNotIn('R101',page.evaluate('localStorage.getItem("dsh-workbench-settings")'))
    browser.close()
  finally:
   if server:server.shutdown();server.server_close()
   db.doCleanups()
