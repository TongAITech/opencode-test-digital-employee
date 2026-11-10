"""C01 real browser navigation; no business success fixtures."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from playwright.sync_api import sync_playwright
from rc7_admin.product_server import ProductAdminApplication, create_server

class C01Browser(unittest.TestCase):
    def test_navigation_locales_theme_and_corrupt_preference_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            server=create_server(ProductAdminApplication(str(Path(root)/'r1')),port=0)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch()
                    page=browser.new_page(); errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    for suffix in ['/workbench', '/workbench/']:
                        page.goto('http://127.0.0.1:%s%s'%(server.server_port,suffix))
                        page.wait_for_selector('#pages button')
                        self.assertEqual(page.locator('#pages button').count(),5)
                        self.assertTrue(page.locator('#heading').inner_text())
                    page.locator('#pages button').nth(1).focus()
                    page.keyboard.press('Enter')
                    self.assertEqual(page.evaluate('document.activeElement.dataset.id'),'chat')
                    page.keyboard.press('Tab')
                    self.assertEqual(page.evaluate('document.activeElement.dataset.id'),'board')
                    page.keyboard.press('Enter')
                    self.assertEqual(page.evaluate('document.activeElement.dataset.id'),'board')
                    page.wait_for_selector('#pages button')
                    self.assertEqual(page.locator('html').get_attribute('lang'),'zh-CN')
                    self.assertEqual(page.locator('#pages button').count(),5)
                    for button in page.locator('#pages button').all(): button.click()
                    page.locator('#project-entry').click()
                    self.assertEqual(page.locator('#sections button').count(),10)
                    for button in page.locator('#sections button').all(): button.click()
                    page.locator('#sections button').last.focus()
                    page.keyboard.press('Enter')
                    self.assertEqual(page.evaluate('document.activeElement.dataset.id'),'gates')
                    page.select_option('#locale','en-US')
                    self.assertEqual(page.locator('#heading').inner_text(),'Project details')
                    self.assertEqual(page.locator('#section-title').inner_text(),'Gates')
                    self.assertIn('unavailable',page.locator('#readiness').inner_text())
                    page.select_option('#theme','dark');page.reload();page.wait_for_selector('#pages button')
                    self.assertEqual(page.locator('html').get_attribute('data-theme'),'dark')
                    page.locator('#retry').click();self.assertIn('No business records',page.locator('#readiness').inner_text())
                    page.evaluate("localStorage.setItem('dsh-workbench-settings','{bad')")
                    page.reload();page.wait_for_selector('#pages button')
                    self.assertEqual(page.locator('html').get_attribute('lang'),'zh-CN')
                    self.assertEqual(errors,[]);browser.close()
            finally: server.shutdown();server.server_close();worker.join()
