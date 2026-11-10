import tempfile,threading
from pathlib import Path
from playwright.sync_api import sync_playwright
from rc7_admin.product_server import ProductAdminApplication,create_server
with tempfile.TemporaryDirectory() as root:
 s=create_server(ProductAdminApplication(str(Path(root)/'r1')),port=0);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
 try:
  with sync_playwright() as p:
   b=p.chromium.launch();page=b.new_page()
   for suffix in ['/workbench/','/workbench']:
    failures=[];page.on('requestfailed',lambda r:failures.append(r.url))
    page.goto('http://127.0.0.1:%s%s'%(s.server_port,suffix));page.wait_for_timeout(500)
    print(suffix,'navigation_buttons',page.locator('#pages button').count(),'heading',page.locator('#heading').inner_text())
   page.goto('http://127.0.0.1:%s/workbench/'%s.server_port);page.wait_for_selector('#pages button')
   page.locator('#pages button').nth(1).focus();page.keyboard.press('Enter')
   print('keyboard_active_after_navigation',page.evaluate('document.activeElement.tagName'),page.evaluate('document.activeElement.id'))
   b.close()
 finally:s.shutdown();s.server_close();t.join()
