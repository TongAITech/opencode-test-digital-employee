"""M1 with real 009, PostgreSQL, same-origin HTTP and native Chromium fetch."""
import pathlib
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright
import test_dsh_workbench_b_postgres as infra
import test_dsh_workbench_b_project_metadata_postgres as fixture
from rc7_admin.product_server import WorkbenchPublicApplication, create_server
from tools.dsh_workbench.business_http import HostIdentity, scope_handler
from tools.dsh_workbench.business_relations import RelationStore, import_verified_requirement_version
from tools.dsh_workbench.project_metadata_store import ProjectMetadataStore


class ProjectMetadataBrowser(unittest.TestCase):
    def test_native_metadata_preserves_scope_and_recovers_original_commit(self):
        if not infra.DSN or not infra.psycopg:
            self.fail('REAL_POSTGRESQL_REQUIRED')
        data = fixture.MetadataPG(methodName='test_rename_single_fact_receipt_and_zero_batch_effect')
        data.setUp()
        self.addCleanup(data.doCleanups)
        data.govern()
        db = data.db
        db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','bob',true)")
        db.store.create_batch('alice', 'P1', 'B1', '2026-11-12', 'fixture-batch')
        db.store.create_system('alice', 'P1', 'S1', 'src', 'prod', 'sys1', 'r1', 's1')
        db.store.create_version('alice', 'P1', 'V1', 'S1', 'V1', 'src', 'prod', 'v1', 'r1', 'v1')
        relations = RelationStore(db.runtime)
        relations.create_requirement('alice', 'P1', 'R1', 'src', 'prod', 'r1', 'r1', 'source:r1', 'r1')
        relations.attach_member('alice', 'P1', 'B1', 'requirement', 'R1', 1, 'attach-r')
        relations.attach_member('alice', 'P1', 'B1', 'version', 'V1', 2, 'attach-v')
        import_verified_requirement_version(db.owner, 'P1', 'B1', 'R1', 'V1', 'source:rv', 'r1')
        relations.attach_requirement_version('alice', 'P1', 'B1', 'R1', 'V1', 3, 'attach-rv')
        before_batch = db.owner.execute('SELECT * FROM wb.release_batch').fetchall()
        actor = ['alice']
        lose_response = threading.Event()
        response_lost = threading.Event()

        def identify(request):
            origin = f'http://127.0.0.1:{request.server.server_port}'
            proof = request.headers.get('Origin') == origin and request.headers.get('X-CSRF-Token') == 'fixture'
            return HostIdentity(actor[0], proof)

        base = scope_handler(lambda: infra.psycopg.connect(**db.params, autocommit=True),
                             b'fixture-project-metadata-browser-key', identify,
                             metadata_store_factory=ProjectMetadataStore)

        class Handler(base):
            def respond(self, status, value):
                if self.command == 'PATCH' and status == 200 and lose_response.is_set():
                    lose_response.clear()
                    response_lost.set()
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                super().respond(status, value)

        server = create_server(WorkbenchPublicApplication(), port=0, workbench_handler=Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 375, 'height': 812})
            page.add_init_script("""document.addEventListener('DOMContentLoaded', () => {
                const meta = document.createElement('meta');
                meta.name = 'dsh-csrf-token'; meta.content = 'fixture'; document.head.append(meta);
            });""")
            errors, patches, scope_requests = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def observe(request):
                if request.method == 'PATCH':
                    patches.append((request.post_data, request.headers.get('x-dsh-write-context')))
                if '/scope?' in request.url:
                    scope_requests.append(request.url)

            page.on('request', observe)
            page.goto(origin + '/workbench/')
            self.assertIn('[native code]', page.evaluate('Function.prototype.toString.call(fetch)'))
            page.locator('[data-directory-load]').click()
            page.wait_for_selector('#project-directory[data-directory-status=READY]')
            self.assertEqual(page.locator('[data-project-select] option[value=P2]').count(), 0)
            page.locator('[data-project-select]').select_option('P1')
            page.locator('[data-date-select]').select_option('B1')
            page.wait_for_selector('#business-scope[data-scope-status=READY]')
            page.select_option('[data-scope=requirement]', ['R1'])
            page.locator('#project-entry').click()
            panel = page.locator('#project-metadata')
            name = panel.locator('[name=project-name]')
            status = panel.locator('[data-status]')

            def load():
                panel.locator('[data-load]').click()
                page.wait_for_function("""() => document.querySelector('#project-metadata').dataset.metadataStatus === 'READY'""")

            def rename(value):
                name.fill(value)
                panel.locator('[name=rename-reason]').fill('fixture reason')
                panel.locator('[data-save]').click()

            def wait_status(value):
                status.get_by_text(value, exact=False).wait_for()

            load()
            expect(panel.locator('form')).to_be_visible(timeout=2000)
            self.assertEqual(name.input_value(), 'first')
            self.assertIn('U+0020', panel.inner_text())
            page.select_option('#locale', 'en-US')
            rename('second')
            wait_status('Name unavailable')
            self.assertNotIn('P2', status.inner_text())
            self.assertEqual(data.scalar('SELECT count(*) FROM wb.project_metadata_history'), 0)

            lose_response.set()
            rename('  ' + '😀' * 128 + '  ')
            wait_status('outcome is unknown')
            self.assertTrue(response_lost.is_set())
            self.assertEqual(data.scalar("SELECT name FROM wb.project WHERE project_id='P1'"), '😀' * 128)
            original = patches[-1]
            self.assertEqual(data.scalar('SELECT count(*) FROM wb.project_metadata_history'), 1)

            # A later committed rename is the display truth even when the original receipt is recovered.
            latest = 'latest-' + '😀' * 100
            data.store.rename('alice', data.request(latest, key='fixture-later', metadata='2'))
            actor[0] = 'bob'
            count = len(patches)
            panel.locator('[data-check]').click()
            wait_status('permissions or identity')
            self.assertEqual(len(patches), count)
            actor[0] = 'alice'
            panel.locator('[data-check]').click()
            wait_status('original rename was confirmed')
            expect(panel.locator('[data-current]')).to_have_text(latest)
            page.wait_for_selector('#project-directory[data-directory-status=READY]')
            self.assertEqual(patches[-1], original)
            self.assertEqual(panel.locator('[data-current]').inner_text(), latest)
            self.assertEqual(page.locator('[data-project-select] option[value=P1]').inner_text(), latest)
            self.assertEqual(page.locator('[data-date-select]').input_value(), 'B1')
            self.assertEqual(page.locator('[data-scope=requirement]').input_value(), 'R1')
            self.assertEqual(page.locator('#business-scope').get_attribute('data-scope-status'), 'READY')
            self.assertEqual(len(scope_requests), 1)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 375)

            rename(' ' + latest + ' ')
            wait_status('name was unchanged')
            expect(panel.locator('[data-current]')).to_have_text(latest)
            self.assertEqual(data.scalar('SELECT count(*) FROM wb.project_metadata_history'), 2)
            self.assertEqual(data.scalar('SELECT count(*) FROM wb.project_metadata_outbox'), 2)
            data.store.rename('alice', data.request('concurrent', key='fixture-cas', metadata='3'))
            rename('stale request')
            wait_status('revision changed')
            self.assertEqual(data.scalar("SELECT name FROM wb.project WHERE project_id='P1'"), 'concurrent')
            load()
            self.assertEqual(name.input_value(), 'concurrent')
            self.assertEqual(db.owner.execute('SELECT * FROM wb.release_batch').fetchall(), before_batch)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 375)
            name.focus()
            page.keyboard.press('Tab')
            self.assertEqual(page.locator('[name=rename-reason]').evaluate('(el) => el === document.activeElement'), True)
            self.assertNotIn('concurrent', page.evaluate('JSON.stringify(localStorage)'))
            actor[0] = 'reader'
            load()
            expect(panel.locator('form')).to_be_hidden()
            wait_status('read-only')
            actor[0] = 'alice'
            load()

            # Delay delivery of a real authorized P1 response across navigation.
            held = []
            def hold(route):
                if route.request.method == 'GET':
                    held.append((route, route.fetch()))
                else:
                    route.continue_()
            page.route('**/projects/P1/metadata', hold)
            panel.locator('[data-load]').click()
            for _ in range(100):
                if held:
                    break
                page.wait_for_timeout(20)
            self.assertTrue(held)
            actor[0] = 'bob'
            page.locator('[name=project_id]').fill('P2')
            load()
            expect(panel.locator('[data-current]')).to_have_text('second')
            for route, response in held:
                route.fulfill(response=response)
            page.unroute('**/projects/P1/metadata', hold)
            expect(panel.locator('[data-current]')).to_have_text('second')
            # Missing permission hints from an older server fail closed.
            def older_wire(route):
                response = route.fetch()
                value = response.json()
                value.pop('can_rename', None)
                route.fulfill(response=response, json=value)
            page.route('**/projects/P2/metadata', older_wire)
            load()
            expect(panel.locator('[data-current]')).to_have_text('second')
            expect(panel.locator('form')).to_be_hidden()
            wait_status('read-only')
            page.unroute('**/projects/P2/metadata', older_wire)
            self.assertEqual(errors, [])
            browser.close()
