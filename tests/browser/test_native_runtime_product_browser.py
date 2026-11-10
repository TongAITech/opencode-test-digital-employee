"""Read-only runtime UI against PostgreSQL and persisted synthetic R1, not native creation QA."""
from dataclasses import asdict
import hashlib
import pathlib
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_e01_postgres as fixture
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Evidence
from rc7_runtime.rc72_truth import append_rc72_entity
from rc7_runtime.rc72_domain import MissionNodeRecord, NodeDelivery, NodeGate
from rc7_admin.product_server import ProductAdminApplication, create_server
from tools.dsh_workbench.business_http import scope_handler, HostIdentity
from tools.dsh_workbench.e02_service import E02Service
from playwright.sync_api import sync_playwright


class NativeRuntimeProduct(unittest.TestCase):
    def test_unwrapped_directory_scope_tasks_gates_two_windows_recovery(self):
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
            evidence_file = db.root/'fixture-evidence.bin'
            evidence_file.write_bytes(b'explicit synthetic evidence; no business acceptance')
            runtime.append_atomic('RC7_EVIDENCE_UPSERTED', dict(release_id='B1', **asdict(Evidence(evidence_id='E1', mission_id='M1', kind='fixture', source_ref='explicit-fixture', content_ref=evidence_file.as_uri(), content_hash='sha256:'+hashlib.sha256(evidence_file.read_bytes()).hexdigest()))))
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
                context = browser.new_context(viewport={'width':375, 'height':844})
                context.add_cookies([{'name':'fixture', 'value':'runtime-host', 'url':origin}])
                page = context.new_page()
                errors, mutations, requests = [], [], []
                page.on('request', lambda request:requests.append(request.url))
                page.on('pageerror', lambda error:errors.append(str(error)))
                page.on('request', lambda request:mutations.append(request.url) if request.method!='GET' else None)
                # Delay delivery of real API responses only when explicitly requested by a test.
                page.goto(origin+'/workbench/')
                self.assertIn('[native code]', page.evaluate('Function.prototype.toString.call(window.fetch)'))
                page.locator('#project-entry').click()
                page.locator('#sections [data-id=tasks]').click()
                panel = page.locator('#runtime-facts')
                self.assertTrue(panel.is_visible())
                self.assertTrue(panel.locator('[data-runtime-load]').is_disabled())
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                def directory_scope(target):
                    target.locator('[data-directory-load]').click()
                    target.wait_for_selector('#project-directory[data-directory-status=READY],#project-directory[data-directory-status=ERROR]')
                    self.assertEqual(target.locator('#project-directory').get_attribute('data-directory-status'), 'READY')
                    self.assertEqual(target.locator('[data-project-select] option[value=P1]').count(), 1)
                    target.select_option('[data-project-select]', 'P1')
                    target.wait_for_function("document.querySelector('[data-date-select] option[value=B1]')")
                    self.assertEqual(target.locator('[data-date-select] option[value=B1]').inner_text(), '2026-11-12')
                    target.select_option('[data-date-select]', 'B1')
                    target.wait_for_selector('#business-scope[data-scope-status=READY]')
                directory_scope(page)
                self.assertIn('业务范围已加载', page.locator('#readiness').inner_text())
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
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 375)
                page.select_option('#locale', 'en-US')
                self.assertIn('read-only snapshot', panel.locator('h3').inner_text())
                self.assertIn('not queried', panel.inner_text())
                self.assertEqual(panel.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'), 'HOLD')
                page.locator('#sections [data-id=gates]').click()
                self.assertEqual(panel.locator('[data-runtime-n10]').get_attribute('data-runtime-n10'), 'NOT_RECORDED')
                self.assertIn('no pass inferred', panel.locator('[data-runtime-n10]').inner_text())
                # The explicit fixture writer now records N10; UI remains read-only and needs manual refresh.
                append_rc72_entity(runtime, MissionNodeRecord(mission_node_id='NODE10', mission_id='M1', node_type='N10_RELEASE_CONVERGENCE', scope_ref='B1', state='PASS'), release_id='B1')
                append_rc72_entity(runtime, NodeDelivery(delivery_id='DELIVERY10', mission_id='M1', mission_node_id='NODE10', node_type='N10_RELEASE_CONVERGENCE', version=1, producer_ref='explicit-fixture'), release_id='B1')
                append_rc72_entity(runtime, NodeGate(gate_id='GATE10', mission_id='M1', mission_node_id='NODE10', node_type='N10_RELEASE_CONVERGENCE', delivery_id='DELIVERY10', decision='PASS', reviewer_worker_id='fixture-reviewer', reviewer_session_id='fixture-session', criteria=['fixture-only']), release_id='B1')
                before = db.r1.read_bytes()
                self.assertEqual(panel.locator('[data-runtime-n10]').get_attribute('data-runtime-n10'), 'NOT_RECORDED')
                read()
                self.assertEqual(panel.locator('[data-runtime-n10]').get_attribute('data-runtime-n10'), 'RECORDED')
                page.locator('#sections [data-id=tasks]').click()
                # Tasks and Gates share exactly one Mission snapshot; navigation never silently re-reads.
                snapshot = panel.get_attribute('data-runtime-as-of')
                revision = panel.get_attribute('data-runtime-revision')
                gate_reads = []
                page.on('request', lambda request:gate_reads.append(request.url) if '/missions/' in request.url else None)
                page.locator('#sections [data-id=gates]').focus()
                page.keyboard.press('Enter')
                self.assertTrue(panel.is_visible())
                self.assertEqual(panel.get_attribute('data-runtime-mission'), 'M1')
                self.assertEqual(panel.get_attribute('data-runtime-as-of'), snapshot)
                self.assertEqual(panel.get_attribute('data-runtime-revision'), revision)
                self.assertEqual(gate_reads, [])
                self.assertIn('PASS', panel.locator('[data-record-id=GATE10]').inner_text())
                self.assertIn('HASH_VERIFIED_ONLY', panel.locator('[data-record-id=E1]').inner_text())
                self.assertIn('not business acceptance', panel.locator('[data-record-id=E1]').inner_text())
                self.assertIn('DELIVERY10', panel.locator('[data-record-id=GATE10]').inner_text())
                self.assertIn('NODE10', panel.locator('[data-runtime-n10]').inner_text())
                self.assertEqual(panel.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'), 'HOLD')
                self.assertEqual(panel.locator('[data-runtime-human]').get_attribute('data-runtime-human'), 'UNKNOWN_NOT_QUERIED')
                self.assertEqual(panel.locator('[data-runtime-collection=workitems]').count(), 0)
                page.keyboard.press('Tab')
                self.assertNotEqual(page.evaluate('document.activeElement.tagName'), 'BODY')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 375)
                page.locator('#sections [data-id=tasks]').click()
                self.assertEqual(panel.get_attribute('data-runtime-as-of'), snapshot)
                self.assertEqual(gate_reads, [])
                page.locator('#sections [data-id=gates]').click()
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
                self.assertIsNone(panel.get_attribute('data-runtime-as-of'))
                page.locator('#sections [data-id=tasks]').click()
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                page.locator('#sections [data-id=gates]').click()
                read()
                # A fresh window cannot inherit another window's Mission or private snapshot.
                cold = context.new_page()
                cold_requests = []
                cold.on('request', lambda request:cold_requests.append((request.method, request.url)))
                cold.goto(origin+'/workbench/')
                cold.locator('#project-entry').click()
                cold.locator('#sections [data-id=gates]').click()
                self.assertEqual(cold.locator('[name=runtime-mission-id]').input_value(), '')
                self.assertEqual(cold.locator('[data-runtime-results] tr').count(), 0)
                self.assertEqual(panel.get_attribute('data-runtime-mission'), 'M1')
                self.assertIn('[native code]', cold.evaluate('Function.prototype.toString.call(window.fetch)'))
                directory_scope(cold)
                cold.locator('[name=runtime-mission-id]').fill('M1')
                cold.locator('[data-runtime-load]').click()
                cold.wait_for_selector('#runtime-facts[data-runtime-status=READY],#runtime-facts[data-runtime-status=ERROR]')
                self.assertEqual(cold.locator('#runtime-facts').get_attribute('data-runtime-status'), 'READY')
                self.assertEqual(cold.locator('[data-runtime-decision]').get_attribute('data-runtime-decision'), 'HOLD')
                self.assertTrue(all(method=='GET' for method,url in cold_requests))
                for path in ['/missions/M1/graph?', '/missions/M1/workitems?', '/quality?']:
                    self.assertTrue(any(path in url for method,url in cold_requests), path)
                self.assertFalse(any('/api/' in url and '/api/workbench/v1/' not in url for method,url in cold_requests))
                cold.close()
                # Corrupt a real Gate delivery reference as an explicit negative transport fixture.
                def bad_gate(route):
                    response = route.fetch()
                    value = response.json()
                    value['records']['rc72_node_gate'][0]['delivery_id'] = 'FOREIGN'
                    route.fulfill(response=response, json=value)
                page.route('**/missions/M1/graph?*', bad_gate)
                panel.locator('[data-runtime-load]').click()
                page.wait_for_selector('#runtime-facts[data-runtime-status=ERROR]')
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                self.assertIsNone(panel.get_attribute('data-runtime-as-of'))
                page.unroute('**/missions/M1/graph?*', bad_gate)
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
                page.locator('#business-scope button').click()
                page.wait_for_selector('#business-scope[data-scope-status=ERROR]')
                self.assertNotIn('Business scope loaded', page.locator('#readiness').inner_text())
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
                page.locator('#business-scope button').click()
                page.wait_for_selector('#business-scope[data-scope-status=READY]')
                read()
                self.assertIn('Business scope loaded', page.locator('#readiness').inner_text())
                page.locator('[name=batch_id]').fill('other-private-scope')
                self.assertEqual(panel.locator('[data-runtime-results] tr').count(), 0)
                # New browser page has no persisted Mission data and can recover only through the real API.
                page.reload()
                page.locator('#project-entry').click()
                page.locator('#sections [data-id=tasks]').click()
                self.assertEqual(page.locator('[name=runtime-mission-id]').input_value(), '')
                self.assertEqual(page.locator('[data-runtime-results] tr').count(), 0)
                self.assertTrue(any('/missions/M1/graph?' in url for url in requests))
                self.assertTrue(any('/missions/M1/workitems?' in url for url in requests))
                self.assertTrue(any('/quality?' in url for url in requests))
                self.assertFalse(any('/api/' in url and '/api/workbench/v1/' not in url for url in requests))
                self.assertEqual(errors, [])
                self.assertEqual(mutations, [])
                browser.close()
            self.assertEqual(db.r1.read_bytes(), before)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            db.doCleanups()
