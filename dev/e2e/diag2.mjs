import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE = 'http://127.0.0.1:8069';
const KEY_FILE = process.env.JAOT_E2E_KEY_FILE || 'C:/Users/vall-/.qwen/tmp/jaom/e2e_key.txt';
const API_KEY = fs.readFileSync(KEY_FILE, 'utf8').trim();
const ENDPOINT = 'http://host.docker.internal:8001';

const browser = await chromium.launch();
const page = await browser.newPage();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function rpc(model, method, args = [], kwargs = {}) {
  return page.evaluate(
    ([base, model, method, args, kwargs]) =>
      fetch(`${base}/web/dataset/call_kw/${model}/${method}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: { model, method, args, kwargs } }),
      }).then((r) => r.json()),
    [BASE, model, method, args, kwargs]
  );
}

try {
  await page.goto(`${BASE}/web/login?db=e2e`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="login"]', 'jaotmgr');
  await page.fill('input[name="password"]', 'JaotE2e-1!');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/odoo/**', { timeout: 20000 });

  // ---- TEST 1: Validate notification DOM ----
  const recipes = await rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id'], 0, 1]);
  const recipe = (recipes[0] && recipes[0].id) ? recipes[0] : { id: 2 };
  await page.goto(`${BASE}/odoo/action-182/${recipe.id}`);
  await page.waitForSelector('.o_form_view', { timeout: 15000 });
  await page.getByRole('button', { name: 'Validate' }).first().click();
  await sleep(1500);
  const notifDump = await page.evaluate(() => {
    const els = [...document.querySelectorAll('.o_notification, .o_notification_center, [class*=notification]')];
    return els.slice(0, 5).map((e) => `${e.className} :: ${e.textContent.trim().slice(0, 120)}`);
  });
  console.log('NOTIFICATION DOM after Validate:', JSON.stringify(notifDump, null, 2));

  // ---- TEST 2: Apply confirm AFTER form reload ----
  const sc = (await rpc('jaot.scenario', 'create', [[{
    recipe_id: recipe.id, name: 'DIAG APPLY', company_id: 1,
  }]]))[0];
  await page.goto(`${BASE}/odoo/action-185/${sc}`);
  await page.waitForSelector('.o_form_view', { timeout: 15000 });
  await page.getByRole('button', { name: 'Solve' }).first().click();
  await sleep(1500);
  for (let i = 0; i < 40; i++) {
    await rpc('jaot.scenario', 'reconcile_jaot_scenarios', []);
    const row = (await rpc('jaot.scenario', 'read', [[sc], ['state']]))[0];
    if (row.state === 'solved' || row.state === 'failed') break;
    await sleep(2000);
  }
  console.log('state after solve:', (await rpc('jaot.scenario', 'read', [[sc], ['state']]))[0].state);
  // RELOAD the form so buttons reflect solved state
  await page.goto(`${BASE}/odoo/action-185/${sc}`);
  await page.waitForSelector('.o_form_view', { timeout: 15000 });
  console.log('Apply button count after reload:', await page.getByRole('button', { name: 'Apply' }).count());
  await page.getByRole('button', { name: 'Apply' }).first().click();
  await sleep(1500);
  const dialogVisible = await page.locator('.o_dialog').isVisible().catch(() => false);
  const dialogDump = await page.evaluate(() => {
    const d = document.querySelector('.o_dialog');
    return d ? { cls: d.className, text: d.textContent.trim().slice(0, 200), buttons: [...d.querySelectorAll('button')].map((b) => b.textContent.trim()) } : null;
  });
  console.log('Apply confirm dialog visible:', dialogVisible, 'dump:', JSON.stringify(dialogDump));
} catch (e) {
  console.error('DIAG2 ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
