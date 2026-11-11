"""Calendar projection and mutation oracle: real PostgreSQL/HTTP, explicit test Host only."""
import json
import pathlib
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import test_dsh_workbench_b_milestone_postgres as fixture
from rc7_admin.product_server import ProductAdminApplication, create_server
from tools.dsh_workbench.business_http import HostIdentity, scope_handler
from playwright.sync_api import sync_playwright


class CalendarProduct(unittest.TestCase):
    def test_year_month_day_real_asset_identity_recovery_and_revocation(self):
        if not fixture.infra.DSN or not fixture.infra.psycopg:
            self.fail('REAL_PG_REQUIRED')
        db = fixture.Milestone(methodName='test_same_milestone_calendar_detail_update_idempotency_retire_restore')
        db.setUp()
        server = None
        try:
            db.scope_seed()
            dates = ['2024-02-29', '2024-02-29', '2024-03-01', '2024-12-31', '2025-01-01']
            seeded = [db.assets.mutate('alice', 'P1', 'B1', 'create', db.body(
                'calendar-seed-' + str(index), title='<img src=x onerror=alert(1)>', payload={'due_date':date}
            ))['record']['asset_id'] for index, date in enumerate(dates)]
            with tempfile.TemporaryDirectory() as temp:
                r1 = pathlib.Path(temp) / 'r1.jsonl'
                r1.write_bytes(b'')
                def connect():
                    return fixture.infra.psycopg.connect(**db.params, autocommit=True)
                def identity(request):
                    if request.headers.get('Cookie') != 'fixture=calendar-host':
                        return None
                    return HostIdentity('alice', request.headers.get('Origin') == origin and request.headers.get('X-CSRF-Token') == 'calendar-fixture-csrf')
                server = create_server(ProductAdminApplication(str(r1)), port=0, workbench_handler=scope_handler(connect, db.scope.key, identity))
                origin = 'http://127.0.0.1:' + str(server.server_port)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    errors = []
                    def open_calendar(timezone):
                        context = browser.new_context(timezone_id=timezone)
                        context.add_cookies([{'name':'fixture', 'value':'calendar-host', 'url':origin}])
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.add_init_script("document.addEventListener('DOMContentLoaded',()=>{const m=document.createElement('meta');m.name='dsh-csrf-token';m.content='calendar-fixture-csrf';document.head.append(m);});")
                        page.add_init_script("const calendarFetch=window.fetch.bind(window);window.fetch=async(...args)=>{const response=await calendarFetch(...args);if(window.delayCalendarReads && String(args[0]).includes('/assets?')){window.calendarReadHeld=true;await new Promise(resolve=>window.releaseCalendarRead=resolve);window.calendarReadReleased=true;}return response;};")
                        page.goto(origin + '/workbench/')
                        page.locator('[name=project_id]').fill('P1')
                        page.locator('[name=batch_id]').fill('B1')
                        page.locator('[name=release_date]').fill('2026-11-12')
                        page.locator('#business-scope button').click()
                        page.wait_for_selector('#business-scope[data-scope-status=READY]')
                        page.locator('#pages [data-id=calendar]').click()
                        page.locator('#milestones [data-action=load]').click()
                        page.wait_for_selector('#milestones[data-milestone-status=READY]')
                        page.locator('[data-calendar-control=jump]').fill('2024-02-29')
                        page.locator('[data-calendar-control=jump]').dispatch_event('change')
                        return context, page
                    context, page = open_calendar('America/Los_Angeles')
                    panel = page.locator('#milestones')
                    calendar = panel.locator('[data-calendar]')
                    def ids():
                        return set(panel.locator('[data-records] article').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.assetId)'))
                    self.assertEqual(ids(), set(seeded[:2]))
                    self.assertEqual(calendar.locator('[data-calendar-date]').count(), 29)
                    self.assertIn('2', calendar.locator('[data-calendar-date="2024-02-29"]').inner_text())
                    self.assertEqual(calendar.locator('thead th').all_text_contents(), ['一','二','三','四','五','六','日'])
                    self.assertEqual(panel.locator('img').count(), 0)  # Untrusted title remains text.
                    calendar.locator('[data-calendar-control=view]').select_option('year')
                    self.assertEqual(calendar.locator('[data-calendar-date]').count(), 12)
                    self.assertEqual(ids(), set(seeded[:4]))
                    calendar.locator('[data-calendar-date="2024-02-01"]').click()
                    self.assertEqual(calendar.locator('[data-calendar-control=view]').input_value(), 'month')
                    calendar.locator('[data-calendar-date="2024-02-29"]').click()
                    self.assertEqual(calendar.locator('[data-calendar-control=view]').input_value(), 'day')
                    self.assertEqual(panel.locator('[name=milestone-date]').input_value(), '2024-02-29')
                    self.assertEqual(ids(), set(seeded[:2]))
                    page.select_option('#locale', 'en-US')
                    self.assertEqual(calendar.locator('h4').inner_text(), 'Milestone calendar')
                    calendar.locator('[data-calendar-control=next]').focus()
                    page.keyboard.press('Enter')
                    self.assertEqual(calendar.locator('[data-calendar-period]').inner_text(), '2024-03-01')
                    self.assertEqual(page.evaluate('document.activeElement.dataset.calendarControl'), 'next')
                    self.assertEqual(ids(), {seeded[2]})
                    calendar.locator('[data-calendar-control=previous]').click()
                    panel.locator('[name=milestone-title]').fill('Created from leap day')
                    panel.locator('form button').click()
                    page.wait_for_function("document.querySelectorAll('#milestones [data-records] article').length===3")
                    created = (ids() - set(seeded)).pop()
                    self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0], 6)
                    # The calendar edits the same ID and revision as project detail.
                    row = panel.locator('article[data-asset-id="' + created + '"]')
                    row.locator('[data-action=edit]').click()
                    panel.locator('[name=milestone-date]').fill('2024-03-02')
                    panel.locator('[name=milestone-reason]').fill('Calendar date correction')
                    panel.locator('form button').click()
                    page.wait_for_function("document.querySelector('#milestones').dataset.milestoneStatus==='READY' && document.querySelectorAll('#milestones [data-records] article').length===2")
                    calendar.locator('[data-calendar-control=jump]').fill('2024-03-02')
                    calendar.locator('[data-calendar-control=jump]').dispatch_event('change')
                    self.assertEqual(ids(), {created})
                    self.assertEqual(panel.locator('article').get_attribute('data-revision'), '2')
                    page.locator('#project-entry').click()
                    page.locator('#sections [data-id=milestones]').click()
                    self.assertEqual(panel.locator('article[data-asset-id="' + created + '"]').get_attribute('data-revision'), '2')
                    self.assertEqual(calendar.locator('[data-calendar-date]').count(), 0)  # Hidden projection cleared.
                    page.locator('#pages [data-id=calendar]').click()
                    self.assertEqual(ids(), {created})
                    # Submitted write loses its response; calendar navigation must not reset original recovery.
                    def lose_response(route):
                        route.fetch()
                        route.abort('failed')
                    page.route('**/assets', lose_response)
                    panel.locator('[name=milestone-title]').fill('Unknown calendar submission')
                    panel.locator('[name=milestone-date]').fill('2024-03-02')
                    panel.locator('form button').click()
                    page.wait_for_selector('#milestones[data-milestone-status=ERROR]')
                    page.unroute('**/assets', lose_response)
                    self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0], 7)
                    calendar.locator('[data-calendar-control=view]').select_option('year')
                    self.assertTrue(panel.locator('form button').is_disabled())
                    self.assertTrue(panel.locator('[data-action=retry]').is_visible())
                    panel.locator('[data-action=retry]').click()
                    page.wait_for_selector('#milestones[data-milestone-status=READY]')
                    self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_root').fetchone()[0], 7)
                    self.assertEqual(db.owner.execute('SELECT count(*) FROM wb.asset_outbox').fetchone()[0], 8)
                    # Invalid date in an HTTP response fails the whole loaded projection, not just one cell.
                    def invalid_date(route):
                        response = route.fetch()
                        value = response.json()
                        value['records'][0]['payload']['due_date'] = '2024-02-30'
                        route.fulfill(response=response, json=value)
                    page.route('**/assets?*', invalid_date)
                    panel.locator('[data-action=load]').click()
                    page.wait_for_selector('#milestones[data-milestone-status=ERROR]')
                    self.assertEqual(ids(), set())
                    self.assertIn('INVALID_CALENDAR_DATE', panel.locator('[data-status]').inner_text())
                    self.assertNotIn('0 milestones', calendar.locator('[data-calendar-summary]').inner_text())
                    page.unroute('**/assets?*', invalid_date)
                    panel.locator('[data-action=load]').click()
                    page.wait_for_selector('#milestones[data-milestone-status=READY]')
                    # A real ACL revoke returns 403; no prior title or event counts survive.
                    db.owner.execute("DELETE FROM wb.project_acl WHERE project_id='P1' AND principal='alice'")
                    panel.locator('[data-action=load]').click()
                    page.wait_for_selector('#milestones[data-milestone-status=ERROR]')
                    self.assertEqual(ids(), set())
                    self.assertNotIn('Unknown calendar submission', panel.inner_text())
                    self.assertIn('—', calendar.locator('[data-calendar-date]').first.inner_text())
                    page.locator('#business-scope button').click()
                    page.wait_for_selector('#business-scope[data-scope-status=ERROR]')
                    self.assertEqual(calendar.locator('[data-calendar-date]').count(), 0)
                    self.assertTrue(calendar.locator('[data-calendar-control=jump]').is_disabled())
                    db.owner.execute("INSERT INTO wb.project_acl VALUES('P1','alice',true)")
                    page.locator('#business-scope button').click()
                    page.wait_for_selector('#business-scope[data-scope-status=READY]')
                    panel.locator('[data-action=load]').click()
                    page.wait_for_selector('#milestones[data-milestone-status=READY]')
                    # Late completed old-scope response cannot repopulate a newly cleared calendar.
                    page.evaluate('window.delayCalendarReads=true')
                    panel.locator('[data-action=load]').click()
                    page.wait_for_function('window.calendarReadHeld===true')
                    page.locator('[name=batch_id]').fill('other-scope')
                    page.evaluate('window.releaseCalendarRead()')
                    page.wait_for_function('window.calendarReadReleased===true')
                    self.assertEqual(ids(), set())
                    self.assertEqual(calendar.locator('[data-calendar-date]').count(), 0)
                    context.close()
                    # Same business leap day under a viewer timezone across the international date line.
                    context2, page2 = open_calendar('Pacific/Kiritimati')
                    self.assertEqual(page2.locator('[data-calendar-date]').count(), 29)
                    self.assertEqual(page2.locator('[data-records] article').count(), 2)
                    context2.close()
                    self.assertEqual(errors, [])
                    browser.close()
                self.assertEqual(r1.read_bytes(), b'')
        finally:
            if server:
                server.shutdown()
                server.server_close()
            db.doCleanups()
