"""Real directory -> product selector -> Scope, with disposable PostgreSQL/Host fixture."""
import sys,pathlib,threading,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_b_scope_postgres as fixture
import test_dsh_workbench_b_milestone_postgres as assets_fixture
from tools.dsh_workbench.business_http import scope_handler,HostIdentity
from tools.dsh_workbench.business_store import provision_project
from rc7_admin.product_server import WorkbenchPublicApplication,create_server
from playwright.sync_api import sync_playwright

class DirectoryBrowser(unittest.TestCase):
 def test_real_authorized_directory_selection_paging_and_recovery(self):
  if not fixture.prior.prior.DSN or not fixture.prior.prior.psycopg:self.fail('REAL_POSTGRESQL_REQUIRED')
  db=assets_fixture.Milestone(methodName='test_same_milestone_calendar_detail_update_idempotency_retire_restore');db.setUp();server=None
  try:
   db.scope_seed();db.batch('B2','2026-11-19','directory-b2')
   provision_project(db.owner,'P_EMPTY','没有排期的项目','alice','empty-project')
   for i in range(100):provision_project(db.owner,'Z%03d'%i,'Project %03d'%i,'alice','directory-%s'%i)
   state={'actor':'alice','available':True}
   def connection():
    if not state['available']:raise ConnectionError('disposable fixture service unavailable')
    return fixture.prior.prior.psycopg.connect(**db.params,autocommit=True)
   server=create_server(WorkbenchPublicApplication(),port=0,workbench_handler=scope_handler(connection,db.scope.key,lambda req:HostIdentity(state['actor'],req.headers.get('X-CSRF-Token')=='directory-fixture-csrf') if req.headers.get('Cookie')=='fixture=directory' else None))
   threading.Thread(target=server.serve_forever,daemon=True).start();origin='http://127.0.0.1:'+str(server.server_port)
   with sync_playwright() as p:
    browser=p.chromium.launch();page=browser.new_page();errors=[];requests=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url));page.context.add_cookies([{'name':'fixture','value':'directory','url':origin}])
    page.add_init_script("""const original=window.fetch.bind(window);window.fetch=async(...args)=>{const result=await original(...args);if(window.dropWrite&&args[1]?.method==='POST'&&String(args[0]).endsWith('/assets')){window.dropWrite=false;throw Error('fixture committed response lost');}if(window.delayDates&&String(args[0]).includes('/P1/release-dates'))await new Promise(r=>setTimeout(r,700));return result;};""")
    page.goto(origin+'/workbench/');page.evaluate("const m=document.createElement('meta');m.name='dsh-csrf-token';m.content='directory-fixture-csrf';document.head.append(m)");page.locator('[data-directory-load]').click();page.wait_for_selector('#project-directory[data-directory-status=READY]')
    count=db.owner.execute("SELECT count(*) FROM wb.project_acl WHERE principal='alice'").fetchone()[0]
    self.assertEqual(page.locator('[data-project-cards] article').count(),count)
    self.assertTrue(any('/projects?' in r and 'page_cursor=' in r for r in requests))
    self.assertEqual(page.locator('[data-project-select] option[value=P2]').count(),0)
    page.select_option('[data-project-select]','P1');page.wait_for_function("document.querySelector('[data-date-select] option[value=B1]')")
    self.assertEqual(page.locator('[data-date-select] option[value=B1]').inner_text(),'2026-11-12')
    page.select_option('[data-date-select]','B1');page.wait_for_selector('#business-scope[data-scope-status=READY]')
    self.assertEqual(page.locator('[name=batch_id]').input_value(),'B1');self.assertEqual(page.locator('[name=release_date]').input_value(),'2026-11-12')
    page.select_option('#locale','en-US');self.assertEqual(page.locator('[data-project-select]').input_value(),'P1');self.assertEqual(page.locator('[data-date-select]').input_value(),'B1')
    page.locator('[data-project-cards] article[data-project-id=P1] button').click();self.assertEqual(page.locator('#heading').inner_text(),'Project details');page.wait_for_function("document.querySelector('[data-date-select] option[value=B1]')")
    page.select_option('[data-date-select]','B1');page.wait_for_selector('#business-scope[data-scope-status=READY]')
    page.locator('#sections button[data-id=milestones]').click();page.locator('[name=milestone-title]').fill('directory recovery fixture');page.locator('[name=milestone-date]').fill('2026-11-20');page.evaluate('window.dropWrite=true');page.locator('#milestones form button').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]')
    self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
    db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','bob',true)");state['actor']='bob';page.locator('[data-directory-load]').click();page.wait_for_selector('#project-directory[data-directory-status=READY]');self.assertEqual(page.locator('[data-project-cards] article').count(),2)
    self.assertEqual(page.locator('[name=milestone-title]').input_value(),'');page.select_option('[data-project-select]','P1');page.wait_for_function("document.querySelector('[data-date-select] option[value=B1]')");page.select_option('[data-date-select]','B1');page.wait_for_selector('#business-scope[data-scope-status=READY]');page.locator('#milestones [data-action=retry]').click();page.wait_for_function("document.querySelector('#milestones [data-status]').textContent.includes('409')");self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
    state['actor']='alice';page.locator('[data-directory-load]').click();page.wait_for_selector('#project-directory[data-directory-status=READY]');page.select_option('[data-project-select]','P1');page.wait_for_function("document.querySelector('[data-date-select] option[value=B1]')");page.select_option('[data-date-select]','B1');page.wait_for_selector('#business-scope[data-scope-status=READY]');page.locator('#milestones [data-action=retry]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1);self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_outbox').fetchone()[0],1)
    page.select_option('[data-project-select]','P_EMPTY');self.assertEqual(page.locator('[name=batch_id]').input_value(),'');self.assertEqual(page.locator('[data-scope=requirement] option').count(),0)
    page.wait_for_function("document.querySelector('[data-directory-status]').textContent.includes('No release dates')")
    page.evaluate('window.delayDates=true');page.select_option('[data-project-select]','P1');page.select_option('[data-project-select]','P_EMPTY');page.wait_for_timeout(900)
    self.assertEqual(page.locator('[data-date-select] option').count(),1);self.assertEqual(page.locator('[name=project_id]').input_value(),'P_EMPTY');page.evaluate('window.delayDates=false')
    db.store.reschedule('alice','P1','B1','2026-11-13',1,'directory-move','fixture approved change','fixture-approval')
    page.select_option('[data-project-select]','P1');page.wait_for_function("document.querySelector('[data-date-select] option[value=B1]')?.textContent==='2026-11-13'")
    page.select_option('[data-date-select]','B1');page.wait_for_selector('#business-scope[data-scope-status=READY]');self.assertEqual(page.locator('[name=batch_id]').input_value(),'B1')
    db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'")
    page.select_option('[data-project-select]','P_EMPTY');page.wait_for_function("document.querySelector('[data-directory-status]').textContent.includes('No release dates')")
    page.select_option('[data-project-select]','P1');page.wait_for_selector('#project-directory[data-directory-status=ERROR]');self.assertEqual(page.locator('[data-date-select] option').count(),1);self.assertEqual(page.locator('[data-scope=requirement] option').count(),0);self.assertEqual(page.locator('[data-project-select] option[value=P1]').count(),0,'Forbidden project remains in authorized project selector');self.assertEqual(page.locator('[data-project-cards] article[data-project-id=P1]').count(),0,'Forbidden project remains in authorized project cards')
    state['available']=False;page.locator('[data-directory-load]').click();page.wait_for_selector('#project-directory[data-directory-status=ERROR]');self.assertEqual(page.locator('[data-project-cards] article').count(),0)
    state['available']=True;state['actor']='nobody';page.locator('[data-directory-load]').click();page.wait_for_selector('#project-directory[data-directory-status=READY]');self.assertEqual(page.locator('[data-project-cards] article').count(),0)
    state['actor']='alice';page.locator('[data-directory-load]').click();page.wait_for_selector('#project-directory[data-directory-status=READY]');self.assertEqual(page.locator('[data-project-select] option[value=P1]').count(),0)
    self.assertEqual(errors,[]);browser.close()
  finally:
   if server:server.shutdown();server.server_close()
   db.doCleanups()
