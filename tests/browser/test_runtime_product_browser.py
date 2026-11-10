"""Read-only runtime UI against PostgreSQL and persisted synthetic R1, not native creation QA."""
import hashlib
import pathlib
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_e01_postgres as fixture
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_truth import append_rc72_entity
from rc7_runtime.rc72_domain import MissionNodeRecord, NodeDelivery, NodeGate
from rc7_admin.product_server import ProductAdminApplication, create_server
from tools.dsh_workbench.business_http import scope_handler, HostIdentity
from tools.dsh_workbench.e02_service import E02Service
from playwright.sync_api import sync_playwright


class RuntimeProduct(unittest.TestCase):
    def test_snapshot_graph_gate_evidence_scope_errors_and_cold_recovery(self):
        if not fixture.prior.prior.prior.DSN or not fixture.prior.prior.prior.psycopg:
            self.fail('REAL_PG_REQUIRED')
        db = fixture.E01(methodName='test_e01_real_pg_http_persistent_r1_readonly_and_cold_recovery')
        db.setUp()
        server = None
        try:
            db.scope_seed()
            db.setup_r1()  # Explicit synthetic binding: production typed creation is not implemented.
            runtime = TruthRuntime(db.r1)
            append_rc72_entity(runtime, MissionNodeRecord(mission_node_id='NODE1', mission_id='M1', node_type='N1_REALITY', scope_ref='B1'), release_id='B1')
            append_rc72_entity(runtime, NodeDelivery(delivery_id='DELIVERY1', mission_id='M1', mission_node_id='NODE1', node_type='N1_REALITY', version=1, producer_ref='explicit-fixture'), release_id='B1')
            append_rc72_entity(runtime, NodeGate(gate_id='GATE1', mission_id='M1', mission_node_id='NODE1', node_type='N1_REALITY', delivery_id='DELIVERY1', decision='PASS', reviewer_worker_id='fixture-reviewer', reviewer_session_id='fixture-session', criteria=['fixture-only']), release_id='B1')
            before = db.r1.read_bytes()
            enabled = [True]
            handler = scope_handler(lambda:fixture.prior.prior.prior.psycopg.connect(**db.params,autocommit=True), db.scope.key,
                lambda request:HostIdentity('alice') if request.headers.get('Cookie')=='fixture=runtime-host' else None,
                lambda store:E02Service(store, db.r1 if enabled[0] else db.root/'missing-r1', db.root))
            server = create_server(ProductAdminApplication(str(db.r1)), port=0, workbench_handler=handler)
            origin = 'http://127.0.0.1:' + str(server.server_port)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(viewport={'width':390, 'height':844})
                context.add_cookies([{'name':'fixture', 'value':'runtime-host', 'url':origin}])
                page = context.new_page()
                errors, mutations = [], []
                page.on('pageerror', lambda error:errors.append(str(error)))
                page.on('request', lambda request:mutations.append(request.url) if request.method!='GET' else None)
                # Delay delivery of real API responses only when explicitly requested by a test.
                page.add_init_script("const actualFetch=window.fetch.bind(window);window.fetch=async(...args)=>{const response=await actualFetch(...args);if(window.delayRuntimeReads && String(args[0]).includes('/missions/')){window.runtimeReadHeld=true;await new Promise(resolve=>(window.runtimeResolvers??=[]).push(resolve));}return response;};")
                page.goto(origin+'/workbench/')
                page.locator('#project-entry').click()
                page.locator('#sections [data-id=tasks]').click()
                panel = page.locator('#runtime-facts')
                self.assertTrue(panel.is_visible())
                self.assertTrue(panel.locator('[data-runtime-load]').is_disabled())
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                page.locator('[name=project_id]').fill('P1')
                page.locator('[name=batch_id]').fill('B1')
                page.locator('[name=release_date]').fill('2026-11-12')
                page.locator('#business-scope button').click()
                page.wait_for_selector('#business-scope[data-scope-status=READY]')
                def read(mission='M1'):
                    panel.locator('[name=runtime-mission-id]').fill(mission)
                    panel.locator('[data-runtime-load]').click()
                    page.wait_for_selector('#runtime-facts[data-runtime-status=READY]')
                read()
                self.assertEqual(panel.locator('[data-runtime-collection=nodes] tbody tr').count(), 10)
                self.assertIn('NOT_STARTED', panel.locator('[data-record-id=NODE1]').inner_text())
                self.assertIn('PASS', panel.locator('[data-record-id=GATE1]').inner_text())
                self.assertEqual(panel.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'), 'HOLD')
                self.assertIn('未查询', panel.inner_text())
                self.assertIn('sha256:'+hashlib.sha256(before).hexdigest(), panel.inner_text())
                self.assertEqual(panel.locator('button').count(), 1)  # No pretend command or approval controls.
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                page.select_option('#locale', 'en-US')
                self.assertIn('read-only snapshot', panel.locator('h3').inner_text())
                self.assertIn('not queried', panel.inner_text())
                self.assertEqual(panel.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'), 'HOLD')
                # A narrower global filter is not silently ignored by an unfiltered Mission API.
                page.select_option('[data-scope=requirement]', ['R2'])
                self.assertTrue(panel.locator('[data-runtime-load]').is_disabled())
                self.assertIn('whole-batch', panel.locator('[data-runtime-status]').inner_text())
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                page.select_option('[data-scope=requirement]', [])
                read()
                # Foreign Mission returns the real server's scope-first 403, with no previous graph remaining.
                panel.locator('[name=runtime-mission-id]').fill('foreign')
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                panel.locator('[data-runtime-load]').click()
                page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]')
                self.assertIn('HTTP_403', panel.locator('[data-runtime-status]').inner_text())
                self.assertNotIn('NODE1', panel.inner_text())
                read()
                # One mismatched response cannot leave partial data from the other two successful reads.
                def drift(route):
                    response = route.fetch()
                    value = response.json()
                    value['truth_revision'] = 'sha256:'+'f'*64
                    route.fulfill(response=response, json=value)
                page.route('**/missions/M1/workitems?*', drift)
                panel.locator('[data-runtime-load]').click()
                page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]')
                self.assertIn('RUNTIME_SNAPSHOT_CHANGED', panel.locator('[data-runtime-status]').inner_text())
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                page.unroute('**/missions/M1/workitems?*', drift)
                read()
                enabled[0] = False
                panel.locator('[data-runtime-load]').click()
                page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]')
                self.assertIn('HTTP_503', panel.locator('[data-runtime-status]').inner_text())
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                enabled[0] = True
                read()
                db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'")
                panel.locator('[data-runtime-load]').click()
                page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]')
                self.assertIn('HTTP_403', panel.locator('[data-runtime-status]').inner_text())
                self.assertNotIn('GATE1', panel.inner_text())
                db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
                page.locator('#business-scope button').click()
                page.wait_for_selector('#business-scope[data-scope-status=READY]')
                read()
                page.evaluate('window.delayRuntimeReads=true')
                panel.locator('[data-runtime-load]').click()
                page.wait_for_function('window.runtimeReadHeld===true')
                page.locator('[name=batch_id]').fill('other-private-scope')
                page.evaluate('window.runtimeResolvers.forEach(resolve=>resolve())')
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                self.assertTrue(panel.locator('[data-runtime-load]').is_disabled())
                self.assertEqual(panel.locator('[name=runtime-mission-id]').input_value(), '')
                # New browser page has no persisted Mission data and can recover only through the real API.
                page.reload()
                page.locator('#project-entry').click()
                page.locator('#sections [data-id=tasks]').click()
                self.assertEqual(page.locator('[name=runtime-mission-id]').input_value(), '')
                self.assertEqual(page.locator('[data-runtime-results] tr').count(), 0)
                self.assertEqual(errors, [])
                self.assertEqual(mutations, [])
                browser.close()
            self.assertEqual(db.r1.read_bytes(), before)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            db.doCleanups()
