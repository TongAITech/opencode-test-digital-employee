const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const admin = process.env.RC7_DEMO_ADMIN_URL || 'http://127.0.0.1:8127';
  const report = process.env.RC7_DEMO_REPORT_URL || 'http://127.0.0.1:8128/rc7-mission-report.html';
  const out = path.resolve(process.env.RC7_DEMO_SCREENSHOT_DIR || 'demo-output/screenshots');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

  async function adminShot(resource, name) {
    await page.goto(admin, { waitUntil: 'networkidle' });
    await page.locator(`[data-k="${resource}"]`).click();
    await page.waitForTimeout(700);
    await page.screenshot({ path: path.join(out, name), fullPage: true });
  }

  await page.goto(admin, { waitUntil: 'networkidle' });
  await page.waitForSelector('[data-k="missions"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(out, '01-mission-list.png'), fullPage: true });
  const firstMission = page.locator('#tbody tr').first();
  if (await firstMission.count()) {
    await firstMission.click();
    await page.waitForSelector('#drawer.open');
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(out, '02-mission-detail.png'), fullPage: true });
  }
  await adminShot('requirements', '03-requirements.png');
  await adminShot('code-impacts', '04-code-analysis.png');
  await adminShot('test-cases', '05-test-cases.png');
  await adminShot('executions', '06-executions.png');
  await adminShot('defects', '07-defects.png');
  const firstDefect = page.locator('#tbody tr').first();
  if (await firstDefect.count()) {
    await firstDefect.click();
    await page.waitForSelector('#drawer.open');
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(out, '08-defect-detail.png'), fullPage: true });
  }
  await adminShot('reports', '09-report-index.png');
  await page.goto(report, { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(out, '10-final-report.png'), fullPage: true });
  await browser.close();
  console.log(JSON.stringify({ status: 'PASS', screenshots: fs.readdirSync(out).sort() }));
})().catch(err => { console.error(err); process.exit(1); });
