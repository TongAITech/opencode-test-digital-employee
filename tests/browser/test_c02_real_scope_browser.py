"""C-owned real browser + B06 HTTP + disposable PostgreSQL integration.

Host identity is an explicit synthetic fixture, never bank qualification.
"""
import pathlib
import sys
import threading
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_b_scope_postgres as fixture
from playwright.sync_api import sync_playwright

class BrowserScope(unittest.TestCase):
    def test_real_pg_oracle_permission_loss_and_recovery(self):
        if not fixture.prior.prior.DSN or not fixture.prior.prior.psycopg:
            self.fail('REAL_POSTGRESQL_DSN_REQUIRED')
        db=fixture.Scope(methodName='test_scope_pages_real_join_unsplit_sources_and_bound_cursors')
        db.setUp()
        try:
            db.scope_seed()
            from tools.dsh_workbench.business_http import create_scope_server,HostIdentity
            server=create_scope_server(('127.0.0.1',0),lambda:fixture.prior.prior.psycopg.connect(**db.params,autocommit=True),db.scope.key,
                lambda req:HostIdentity('alice') if req.headers.get('Authorization')=='Bearer browser-host-fixture' else None)
            base=server.RequestHandlerClass
            module=(pathlib.Path(__file__).resolve().parents[2]/'rc7_admin/static/workbench/scope-client.mjs').read_bytes()
            class Handler(base):
                def do_GET(self):
                    if self.path in ('/','/scope-client.mjs'):
                        data=b'<!doctype html><title>C02 integration fixture</title>' if self.path=='/' else module
                        self.send_response(200);self.send_header('Content-Type','text/html' if self.path=='/' else 'application/javascript');self.end_headers();self.wfile.write(data)
                    elif self.path.startswith('/workbench/'):
                        name=self.path.removeprefix('/workbench/') or 'index.html'
                        if name not in ('index.html','app.mjs','state.mjs','scope-client.mjs','scope-panel.mjs','milestone-panel.mjs','calendar-model.mjs','calendar-panel.mjs','runtime-client.mjs','runtime-panel.mjs','requirements-panel.mjs','asset-forms.mjs','directory-panel.mjs','directory-client.mjs','style.css'):
                            self.send_error(404);return
                        data=(pathlib.Path(__file__).resolve().parents[2]/'rc7_admin/static/workbench'/name).read_bytes()
                        self.send_response(200);self.send_header('Content-Type','application/javascript' if name.endswith('.mjs') else 'text/css' if name.endswith('.css') else 'text/html');self.end_headers();self.wfile.write(data)
                    else:super().do_GET()
            server.RequestHandlerClass=Handler
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch();page=browser.new_page(extra_http_headers={'Authorization':'Bearer browser-host-fixture'})
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    result=page.evaluate('''async()=>{const {ScopeClient,httpScopePort}=await import('/scope-client.mjs');window.client=new ScopeClient(httpScopePort(fetch));return await client.load({project_id:'P1',batch_id:'B1',release_date:'2026-11-12'});}''')
                    self.assertTrue(result)
                    state=page.evaluate('client.state')
                    oracle=db.owner.execute('SELECT requirement_id,version_id FROM wb.batch_requirement_version ORDER BY requirement_id,version_id').fetchall()
                    self.assertEqual([(r['requirement_id'],r['system_version_id']) for r in state['records']],oracle)
                    self.assertEqual(state['relation_revision'],db.owner.execute("SELECT relation_revision FROM wb.release_batch WHERE project_id='P1' AND batch_id='B1'").fetchone()[0])
                    self.assertEqual(state['records'][0]['sst_id'],'SST1');self.assertEqual(state['records'][1]['split_state'],'UNSPLIT')
                    db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'")
                    self.assertFalse(page.evaluate('client.load({project_id:"P1",batch_id:"B1",release_date:"2026-11-12"})'))
                    self.assertEqual(page.evaluate('client.state.error'),'HTTP_403');self.assertEqual(page.evaluate('client.state.records'),[])
                    db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
                    self.assertTrue(page.evaluate('client.load({project_id:"P1",batch_id:"B1",release_date:"2026-11-12"})'))
                    self.assertEqual(page.evaluate('client.state.status'),'READY')
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/workbench/')
                    page.locator('[name=project_id]').fill('P1');page.locator('[name=batch_id]').fill('B1');page.locator('[name=release_date]').fill('2026-11-12')
                    page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]')
                    self.assertEqual(page.locator('[data-scope=requirement] option').count(),len(oracle))
                    page.select_option('[data-scope=requirement]',['R2'])
                    self.assertEqual(page.locator('[data-scope=sst] option').count(),0)
                    page.locator('#project-entry').click()
                    for button in page.locator('#sections button').all():button.click()
                    page.select_option('#locale','en-US')
                    self.assertEqual(page.locator('[data-scope=requirement]').input_value(),'R2')
                    self.assertEqual(page.locator('[name=batch_id]').input_value(),'B1')
                    page.locator('[name=batch_id]').fill('missing')
                    self.assertEqual(page.locator('[data-scope=requirement] option').count(),0)
                    page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=ERROR]')
                    page.locator('[name=batch_id]').fill('B1');page.locator('#business-scope button').click();page.wait_for_selector('#business-scope[data-scope-status=READY]')
                    browser.close()
            finally:server.shutdown();server.server_close();thread.join()
        finally:db.doCleanups()
