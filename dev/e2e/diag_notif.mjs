import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:8069';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch();
const page = await browser.newPage();
try {
  await page.goto(`${BASE}/web/login?db=e2e`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="login"]', 'jaotmgr');
  await page.fill('input[name="password"]', 'JaotE2e-1!');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/odoo/**', { timeout: 20000 });
  await page.goto(`${BASE}/odoo/action-182/2`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.o_form_view', { timeout: 15000 });
  await page.getByRole('button', { name: 'Validate' }).first().click();
  let elapsed = 0;
  for (const t of [1000, 2500, 4500, 6500]) {
    await sleep(t - elapsed);
    elapsed = t;
    const html = await page.evaluate(() => {
      const m = document.querySelector('.o_notification_manager');
      return m ? m.innerHTML : 'NO_MANAGER';
    });
    const text = await page.evaluate(() => {
      const m = document.querySelector('.o_notification_manager');
      return m ? m.innerText.trim() : 'NO_MANAGER';
    });
    console.log(`--- t=${t}ms text="${text}" ---`);
    if (html && html !== 'NO_MANAGER') console.log('  html:', html.slice(0, 400));
  }
} catch (e) {
  console.error('NOTIF ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
