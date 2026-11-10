"""Milestone vertical slice, real product HTTP/PG Oracle; synthetic Host/CSRF only."""
import sys,pathlib,threading,json,unittest,tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]));sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_b_milestone_postgres as fixture
from rc7_admin.product_server import ProductAdminApplication,create_server
from tools.dsh_workbench.business_http import scope_handler,HostIdentity
from playwright.sync_api import sync_playwright
class MilestoneUI(unittest.TestCase):
 def test_detail_calendar_same_asset_versions_retire_restore_and_errors(self):
  if not fixture.infra.DSN or not fixture.infra.psycopg:self.fail('REAL_PG_REQUIRED')
  db=fixture.Milestone(methodName='test_same_milestone_calendar_detail_update_idempotency_retire_restore');db.setUp()
  try:
   db.scope_seed();db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','bob',true)");actor=['alice'];outage=[False];temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);r1=pathlib.Path(temp.name)/'r1.jsonl';r1.write_bytes(b'')
   def connect():
    if outage[0]:raise ConnectionError('fixture DB outage')
    return fixture.infra.psycopg.connect(**db.params,autocommit=True)
   def identity(req):
    if req.headers.get('Cookie')!='fixture=host':return None
    return HostIdentity(actor[0],req.headers.get('Origin')==origin and req.headers.get('X-CSRF-Token')=='bound-fixture')
   server=create_server(ProductAdminApplication(str(r1)),port=0,workbench_handler=scope_handler(connect,db.scope.key,identity));origin='http://127.0.0.1:'+str(server.server_port)
   threading.Thread(target=server.serve_forever,daemon=True).start()
   try:
    with sync_playwright() as p:
     browser=p.chromium.launch();page=browser.new_page();page.context.add_cookies([{'name':'fixture','value':'host','url':origin}])
     page.add_init_script("document.addEventListener('DOMContentLoaded',()=>{let m=document.createElement('meta');m.name='dsh-csrf-token';m.content='bound-fixture';document.head.append(m);});")
     page.goto(origin+'/workbench/');page.locator('[name=project_id]').fill('P1');page.locator('[name=batch_id]').fill('B1');page.locator('[name=release_date]').fill('2026-11-12');page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]');page.locator('#project-entry').click();page.locator('#sections [data-id=milestones]').click()
     panel=page.locator('#milestones')
     panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]')
     panel.locator('[name=milestone-title]').fill('投产评审');panel.locator('[name=milestone-date]').fill('2026-11-11');panel.locator('form button').click();panel.locator('article').wait_for()
     asset=panel.locator('article').get_attribute('data-asset-id');self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],1)
     page.locator('#pages [data-id=calendar]').click();self.assertEqual(panel.locator('article').get_attribute('data-asset-id'),asset)
     page.select_option('#locale','en-US');self.assertIn('Milestones',panel.locator('h3').inner_text());self.assertEqual(panel.locator('article').get_attribute('data-asset-id'),asset)
     panel.locator('[data-action=edit]').click();panel.locator('[name=milestone-date]').fill('2026-11-13');panel.locator('[name=milestone-reason]').fill('date revised');panel.locator('form button').click();page.wait_for_selector('#milestones article[data-revision="2"]');self.assertEqual(panel.locator('article').get_attribute('data-asset-id'),asset)
     self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_revision').fetchone()[0],2)
     panel.locator('[name=milestone-reason]').fill('retire approved');panel.locator('[data-action=retire]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertEqual(panel.locator('article').count(),0)
     panel.locator('[data-retired]').check();page.wait_for_selector('#milestones article[data-revision="3"]');panel.locator('[name=milestone-reason]').fill('restore approved');panel.locator('[data-action=restore]').click();page.wait_for_selector('#milestones article[data-revision="4"]')
     self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_revision').fetchone()[0],4);self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_outbox').fetchone()[0],4)
     # Wrong CSRF is rejected by the real provider, not a simulated success.
     page.evaluate("document.querySelector('meta[name=dsh-csrf-token]').content='wrong'");panel.locator('[name=milestone-reason]').fill('csrf rejection')
     panel.locator('[data-action=retire]').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertIn('HTTP_403',panel.locator('[data-status]').inner_text());self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_revision').fetchone()[0],4)
     page.evaluate("document.querySelector('meta[name=dsh-csrf-token]').content='bound-fixture'");panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones article[data-revision="4"]')
     # Stale revision and illegal exact relation are sent to the real API; no fixture success response.
     def stale(route):
      body=route.request.post_data_json;body['expected_asset_revision']=1;route.continue_(post_data=json.dumps(body))
     page.route('**/assets/*',stale);panel.locator('[data-action=edit]').click();panel.locator('[name=milestone-title]').fill('stale edit');panel.locator('[name=milestone-reason]').fill('conflict');panel.locator('form button').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertIn('HTTP_409',panel.locator('[data-status]').inner_text());page.unroute('**/assets/*',stale)
     panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones article[data-revision="4"]')
     def illegal(route):
      body=route.request.post_data_json;body.update(scope_level='EXACT_RELATIONS',brv_links=[],brvs_links=[{'requirement_id':'R2','system_version_id':'V1','sst_id':'SST1'}]);route.continue_(post_data=json.dumps(body))
     page.route('**/assets',illegal);panel.locator('[name=milestone-title]').fill('illegal relation');panel.locator('[name=milestone-date]').fill('2026-11-11');panel.locator('form button').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertIn('HTTP_422',panel.locator('[data-status]').inner_text());self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_revision').fetchone()[0],4);page.unroute('**/assets',illegal)
     panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones article[data-revision="4"]')
     outage[0]=True;panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertIn('HTTP_503',panel.locator('[data-status]').inner_text());self.assertEqual(panel.locator('article').count(),0)
     outage[0]=False;panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones article[data-revision="4"]');# Commit succeeds but transport loses response: explicit retry must reuse the same request ID.
     def lose_response(route):
      route.fetch();route.abort('failed')
     page.route('**/assets',lose_response);panel.locator('[name=milestone-title]').fill('uncertain transport');panel.locator('[name=milestone-date]').fill('2026-11-15');panel.locator('form button').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],2);page.unroute('**/assets',lose_response)
     panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertTrue(panel.locator('[data-action=retry]').is_visible());self.assertTrue(panel.locator('form button').is_disabled())
     actor[0]='bob';panel.locator('[data-action=retry]').click();page.wait_for_selector('#milestones[data-milestone-status=ERROR]');self.assertIn('HTTP_409',panel.locator('[data-status]').inner_text());self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],2)
     panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertTrue(panel.locator('form button').is_disabled());self.assertTrue(panel.locator('[data-action=retry]').is_visible());actor[0]='alice'
     page.select_option('#locale','zh-CN');page.locator('#project-entry').click();page.locator('#sections [data-id=milestones]').click();self.assertTrue(panel.locator('[data-action=retry]').is_visible());self.assertTrue(panel.locator('form button').is_disabled())
     page.locator('[name=batch_id]').fill('new-private-scope');self.assertEqual(panel.locator('[name=milestone-title]').input_value(),'');self.assertTrue(panel.locator('[data-action=retry]').is_disabled());self.assertTrue(panel.locator('form button').is_disabled())
     page.locator('[name=batch_id]').fill('B1');db.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'");page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]');self.assertTrue(panel.locator('[data-action=retry]').is_disabled())
     db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)");page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]');self.assertTrue(panel.locator('form button').is_disabled());panel.locator('[data-action=retry]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0],2)
     page.select_option('[data-scope=requirement]',['R2']);self.assertEqual(panel.locator('article').count(),0);panel.locator('[data-action=load]').click();page.wait_for_selector('#milestones[data-milestone-status=READY]');self.assertEqual(panel.locator('article').count(),0)
     panel.locator('[name=milestone-title]').fill('UNSPLIT requirement milestone');panel.locator('[name=milestone-date]').fill('2026-11-16');panel.locator('form button').click();panel.locator('article').wait_for();self.assertEqual(db.owner.execute('SELECT requirement_id FROM wb.asset_brv_link').fetchall(),[('R2',)])
     self.assertEqual(r1.read_bytes(),b'');browser.close()
   finally:server.shutdown();server.server_close()
  finally:db.doCleanups()
