import { chromium } from 'playwright';
import fs from 'node:fs';
const BASE = 'http://127.0.0.1:8069';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch();
const page = await browser.newPage();
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
  const sid = (await rpc('jaot.scenario', 'create', [[{ name: `APPLY ${Date.now()}`, recipe_id: 2, company_id: 1 }]])).result[0];
  await rpc('jaot.scenario', 'action_submit', [[sid]]);
  for (let i = 0; i < 40; i++) {
    await rpc('jaot.scenario', 'reconcile_jaot_scenarios', []);
    const row = (await rpc('jaot.scenario', 'read', [[sid], ['state']])).result[0];
    if (row.state === 'solved' || row.state === 'failed') break;
    await sleep(2000);
  }
  console.log('state:', (await rpc('jaot.scenario', 'read', [[sid], ['state']])).result[0].state);
  await page.goto(`${BASE}/odoo/action-185/${sid}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.o_form_view', { timeout: 15000 });
  const applyHtml = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Apply');
    return b ? b.outerHTML : 'NO_APPLY_BUTTON';
  });
  console.log('APPLY BUTTON HTML:', applyHtml);
  await page.getByRole('button', { name: 'Apply' }).first().click();
  for (const t of [800, 2000, 4000]) {
    await sleep(t === 800 ? 800 : t - (t === 2000 ? 800 : 2000));
    const dialogs = await page.evaluate(() =>
      [...document.querySelectorAll('.o_dialog')].map((d) => ({
        id: d.id, cls: d.className,
        visible: !!(d.offsetWidth || d.offsetHeight || getComputedStyle(d).display !== 'none'),
        text: d.textContent.trim().slice(0, 120),
      })));
    console.log(`t=${t} dialogs:`, JSON.stringify(dialogs));
  }
} catch (e) {
  console.error('APPLY ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
