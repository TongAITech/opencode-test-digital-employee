"""Real same-origin product UI/PG/R1; synthetic Host provider, no SSO claim."""
import sys,pathlib,threading,json,unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_e01_postgres as fixture
from rc7_admin.product_server import ProductAdminApplication,create_server
from tools.dsh_workbench.business_http import scope_handler,HostIdentity
from tools.dsh_workbench.e01_service import E01Service
from playwright.sync_api import sync_playwright

class SameOrigin(unittest.TestCase):
 def test_real_mount_defaults_acl_quality_and_browser_recovery(self):
  if not fixture.prior.prior.prior.DSN or not fixture.prior.prior.prior.psycopg:self.fail('REAL_PG_REQUIRED')
  db=fixture.E01(methodName='test_e01_real_pg_http_persistent_r1_readonly_and_cold_recovery');db.setUp();servers=[]
  try:
   db.scope_seed();db.setup_r1();app=ProductAdminApplication(str(db.r1))
   def start(handler=None):
    server=create_server(app,port=0,workbench_handler=handler);servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start();return 'http://127.0.0.1:'+str(server.server_port)
   def request(origin,path,headers=None,method='GET',data=None):
    try:
     with urlopen(Request(origin+path,headers=headers or {},method=method,data=data),timeout=5) as r:return r.status,r.read()
    except HTTPError as e:return e.code,e.read()
   path='/api/workbench/v1/projects/P1/release-dates/2026-11-12/scope?batch_id=B1'
   default=start()
   for headers in ({},{'X-Principal':'alice'},{'Authorization':'Bearer alice'}):self.assertEqual(request(default,path,headers)[0],503)
   self.assertEqual(request(default,path+'&principal=alice')[0],503)
   self.assertEqual(request(default,path,method='POST',data=b'{"principal":"alice"}')[0],405)
   self.assertEqual(request(default,'/api/meta')[0],200)
   handler=scope_handler(lambda:fixture.prior.prior.prior.psycopg.connect(**db.params,autocommit=True),db.scope.key,
       lambda req:HostIdentity('alice') if req.headers.get('Cookie')=='fixture=host-approved' else None,
       lambda store:E01Service(store,db.r1,db.root))
   origin=start(handler)
   self.assertEqual(request(origin,path,{'X-Principal':'alice'})[0],403)
   self.assertEqual(request(origin,path+'&principal=alice',{'Cookie':'fixture=host-approved'})[0],400)
   quality='/api/workbench/v1/projects/P1/release-dates/2026-11-12/quality?batch_id=B1&mission_id=M1'
   status,value=request(origin,quality,{'Cookie':'fixture=host-approved'});self.assertEqual(status,200);self.assertEqual(json.loads(value)['release_decision'],'HOLD')
   self.assertEqual(request(origin,quality.replace('M1','foreign'),{'Cookie':'fixture=host-approved'})[0],403)
   self.assertEqual(db.r1.read_bytes(),db.before)
   with sync_playwright() as p:
    browser=p.chromium.launch();page=browser.new_page();page.context.add_cookies([{'name':'fixture','value':'host-approved','url':origin}])
    page.goto(origin+'/workbench');page.wait_for_selector('#pages button')
    page.locator('[name=project_id]').fill('P1');page.locator('[name=batch_id]').fill('B1');page.locator('[name=release_date]').fill('2026-11-12');page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]')
    self.assertEqual(page.locator('[data-scope=requirement] option').count(),db.owner.execute('SELECT count(*) FROM wb.batch_requirement_version').fetchone()[0])
    db.owner.execute("DELETE FROM wb.project_acl WHERE principal='alice'");page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]');self.assertEqual(page.locator('[data-scope=requirement] option').count(),0)
    db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)");page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]');browser.close()
   self.assertEqual(db.r1.read_bytes(),db.before)
  finally:
   for server in servers:server.shutdown();server.server_close()
   db.doCleanups()
