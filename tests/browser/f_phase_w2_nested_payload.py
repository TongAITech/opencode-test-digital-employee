"""Six draft forms, real HTTP/PG, no formal R1 or field qualification."""
import sys,pathlib,threading,tempfile,json,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]));sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_b_drafts_postgres as fixture
from rc7_admin.product_server import ProductAdminApplication,create_server
from tools.dsh_workbench.business_http import scope_handler,HostIdentity
from playwright.sync_api import sync_playwright
class DraftFormsUI(unittest.TestCase):
 def test_six_kinds_real_versions_and_cross_kind_unknown_subject_recovery(self):
  if not fixture.infra.DSN or not fixture.infra.psycopg:self.fail('REAL_PG_REQUIRED')
  db=fixture.DraftKinds(methodName='test_six_kinds_create_patch_retire_restore_original_response_and_filter');db.setUp()
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  try:
   db.scope_seed();db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','bob',true)");actor=['alice'];r1=pathlib.Path(temp.name)/'r1';r1.write_bytes(b'')
   def provider(req):
    return HostIdentity(actor[0],req.headers.get('Origin')==origin and req.headers.get('X-CSRF-Token')=='draft-fixture') if req.headers.get('Cookie')=='fixture=host' else None
   server=create_server(ProductAdminApplication(str(r1)),port=0,workbench_handler=scope_handler(lambda:fixture.infra.psycopg.connect(**db.params,autocommit=True),db.scope.key,provider));origin='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start()
   try:
    with sync_playwright() as p:
     browser=p.chromium.launch();page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.context.add_cookies([{'name':'fixture','value':'host','url':origin}]);page.add_init_script("document.addEventListener('DOMContentLoaded',()=>{let m=document.createElement('meta');m.name='dsh-csrf-token';m.content='draft-fixture';document.head.append(m);});")
     page.goto(origin+'/workbench/');page.locator('[name=project_id]').fill('P1');page.locator('[name=batch_id]').fill('B1');page.locator('[name=release_date]').fill('2026-11-12');page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]');page.locator('#project-entry').click();self.assertEqual(page.locator('#sections button').count(),10);panel=page.locator('#milestones')
     sections={'case_draft':'cases','obligation_draft':'cases','defect_note':'defects','report_draft':'reports','knowledge':'knowledge','meeting_minutes':'minutes'}
     def view(kind):
      page.locator('#sections [data-id='+sections[kind]+']').click()
      if sections[kind]=='cases':page.select_option('[data-case-kind]',kind)
      page.wait_for_selector('#milestones[data-asset-kind='+kind+']')
     def fill(kind,title):
      panel.locator('[name=milestone-title]').fill(title)
      for key,value in fixture.PAYLOADS[kind].items():panel.locator('[name=asset-'+key+']').fill('\n'.join(value) if isinstance(value,list) else value)
     for kind in sections:
      view(kind);panel.locator('[data-retired]').uncheck();panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertEqual(panel.locator('article').count(),0)
      fill(kind,'人工资料 '+kind)
      if kind=='case_draft':
       def nested(route):
        body=route.request.post_data_json;body['payload']['steps']=[{'nodegate':'PASS'}];route.continue_(post_data=json.dumps(body))
       page.route('**/assets',nested);panel.locator('form button').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertIn('HTTP_400',panel.locator('[data-status]').inner_text());self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],0);page.unroute('**/assets',nested)
       panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');fill(kind,'人工资料 '+kind)
      if kind=='case_draft':
       before=db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0];panel.locator('[name=asset-steps]').fill('   ');panel.locator('form button').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],before);fill(kind,'人工资料 '+kind)
      panel.locator('form button').click();panel.locator('article[data-revision="1"]').wait_for();asset=panel.locator('article').get_attribute('data-asset-id');self.assertIn('UNRESOLVED',panel.locator('[data-label=draft]').inner_text())
      page.select_option('#locale','en-US');self.assertEqual(panel.locator('article').get_attribute('data-asset-id'),asset)
      panel.locator('[data-action=edit]').click();panel.locator('[name=milestone-title]').fill('edited '+kind);panel.locator('[name=milestone-reason]').fill('reviewed edit');panel.locator('form button').click();panel.locator('article[data-revision="2"]').wait_for()
      panel.locator('[name=milestone-reason]').fill('retire draft');panel.locator('[data-action=retire]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertEqual(panel.locator('article').count(),0);panel.locator('[data-retired]').check();panel.locator('article[data-revision="3"]').wait_for();panel.locator('[name=milestone-reason]').fill('restore draft');panel.locator('[data-action=restore]').click();panel.locator('article[data-revision="4"]').wait_for();self.assertEqual(panel.locator('article').get_attribute('data-asset-id'),asset)
      stored=db.assets.get('alice','P1','B1',asset)['record'];self.assertEqual(stored['payload'],{k:v for k,v in fixture.PAYLOADS[kind].items() if v or k in ['steps','expected_results']});self.assertEqual(stored['r1_reference_state'],'UNRESOLVED')
     self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],6);self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_revision').fetchone()[0],24)
     view('case_draft');panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');fill('case_draft','private unknown case')
     def lost(route):route.fetch();route.abort('failed')
     page.route('**/assets',lost);panel.locator('form button').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');page.unroute('**/assets',lost);self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],7)
     view('report_draft');self.assertEqual(panel.locator('[name=milestone-title]').input_value(),'');self.assertEqual(panel.locator('[name=asset-body]').input_value(),'');self.assertEqual(panel.locator('article').count(),0);self.assertTrue(panel.locator('form button').is_disabled());self.assertTrue(panel.locator('[data-action=retry]').is_visible())
     actor[0]='bob';panel.locator('[data-action=retry]').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertIn('HTTP_409',panel.locator('[data-status]').inner_text());self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],7)
     panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertTrue(panel.locator('form button').is_disabled());actor[0]='alice';panel.locator('[data-action=retry]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],7);self.assertFalse(panel.locator('[data-action=retry]').is_visible());self.assertEqual(r1.read_bytes(),b'');self.assertEqual(errors,[]);browser.close()
   finally:server.shutdown();server.server_close()
  finally:db.doCleanups()
