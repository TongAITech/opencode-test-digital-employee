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

  async function assertApi(resource, expected) {
    const response = await page.request.get(`${admin}/api/${resource}?page=1&page_size=20`);
    if (!response.ok()) throw new Error(`API ${resource} failed: ${response.status()}`);
    const body = await response.json();
    const text = JSON.stringify(body);
    if (!text.includes(expected)) throw new Error(`API ${resource} missing semantic marker ${expected}: ${text}`);
  }

  async function waitMarker(expected, timeout = 10000) {
    await page.waitForFunction(
      marker => (document.querySelector('#tbody')?.innerText || '').includes(marker),
      expected,
      { timeout }
    );
  }

  async function adminShot(resource, name, expected, preserveFirstStale = false) {
    await assertApi(resource, expected);
    await page.goto(admin, { waitUntil: 'networkidle' });
    await page.locator(`[data-k="${resource}"]`).click();
    try {
      await waitMarker(expected, preserveFirstStale ? 1500 : 10000);
    } catch (err) {
      if (!preserveFirstStale) throw err;
      await page.screenshot({ path: path.join(out, '05a-test-cases-stale-first-click.png'), fullPage: true });
      const stale = (await page.locator('#tbody').innerText()).trim();
      fs.writeFileSync(path.join(out, '05a-test-cases-stale-first-click.txt'), stale, 'utf8');
      await page.locator(`[data-k="${resource}"]`).click();
      await waitMarker(expected, 10000);
    }
    await page.screenshot({ path: path.join(out, name), fullPage: true });
  }

  await page.goto(admin, { waitUntil: 'networkidle' });
  await page.waitForSelector('[data-k="missions"]');
  await waitMarker('MISSION-RC7-REAL-DEMO-001');
  await page.screenshot({ path: path.join(out, '01-mission-list.png'), fullPage: true });
  const firstMission = page.locator('#tbody tr').first();
  if (!(await firstMission.count())) throw new Error('Mission row missing');
  await firstMission.click();
  await page.waitForSelector('#drawer.open');
  await page.waitForFunction(() => (document.querySelector('#detail')?.innerText || '').includes('CONVERGED'));
  await page.screenshot({ path: path.join(out, '02-mission-detail.png'), fullPage: true });
  await page.locator('#close').click();

  await adminShot('requirements', '03-requirements.png', 'REQ-AN-REAL-DEMO');
  await adminShot('code-impacts', '04-code-analysis.png', 'CODE-AN-REAL-DEMO');
  await adminShot('test-cases', '05-test-cases.png', 'TC-RATE-BOUNDARY-001', true);
  await adminShot('executions', '06-executions.png', 'ATT-RATE-001');
  await adminShot('defects', '07-defects.png', 'DEFECT-4aa7667e01d7fb1d1931');

  const firstDefect = page.locator('#tbody tr').first();
  if (!(await firstDefect.count())) throw new Error('Defect row missing');
  await firstDefect.click();
  await page.waitForSelector('#drawer.open');
  await page.waitForFunction(() => {
    const text = document.querySelector('#detail')?.innerText || '';
    return text.includes('DELTA_OUT_OF_RANGE') && text.includes('CLOSED') && text.includes('RCA-RATE-UPPER-BOUND');
  });
  await page.screenshot({ path: path.join(out, '08-defect-detail.png'), fullPage: true });
  await page.locator('#close').click();

  await adminShot('reports', '09-report-index.png', 'REPORT-RC7-REAL-DEMO');
  await page.goto(report, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.body.innerText.includes('CONVERGED') && document.body.innerText.includes('DEFECT-4aa7667e01d7fb1d1931'));
  await page.screenshot({ path: path.join(out, '10-final-report.png'), fullPage: true });
  await browser.close();
  console.log(JSON.stringify({ status: 'PASS', screenshots: fs.readdirSync(out).sort() }));
})().catch(err => { console.error(err); process.exit(1); });
