import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8069';
const KEY_FILE = process.env.JAOT_E2E_KEY_FILE || 'C:\\Users\\vall-\\.qwen\\tmp\\jaom\\e2e_key.txt';
const api_key = fs.readFileSync(KEY_FILE, 'utf8').trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function rpc(page, model, method, args = [], kwargs = {}) {
  const res = await page.evaluate(
    ([base, model, method, args, kwargs]) =>
      fetch(`${base}/web/dataset/call_kw/${model}/${method}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: { model, method, args, kwargs } }),
      }).then((r) => r.json()),
    [BASE, model, method, args, kwargs]
  );
  if (res.error) {
    const et = res.error.data?.message || res.error.message || JSON.stringify(res.error);
    throw new Error(`${model}.${method}: ${et}`);
  }
  return res.result;
}
async function dumpDialogs(page, label) {
  const info = await page.evaluate(() => {
    const sels = ['.o_confirm_dialog', '.modal', '.o_dialog', '[role="dialog"]', '.o_notification', '.o_notification_content', '.o_form_statusbar', '.o_statusbar'];
    const out = [];
    for (const s of sels) {
      document.querySelectorAll(s).forEach((el) => {
        const t = (el.innerText || '').trim().slice(0, 200);
        if (t) out.push({ sel: s, text: t, visible: el.offsetParent !== null });
      });
    }
    return out;
  });
  console.log(`-- ${label} --`, JSON.stringify(info, null, 1));
}

const browser = await chromium.launch();
const page = await browser.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 300)); });
try {
  await page.goto(`${BASE}/web/login?db=e2e`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="login"]', 'jaotmgr');
  await page.fill('input[name="password"]', 'JaotE2e-1!');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/odoo/**', { timeout: 20000 });

  const recipe = await rpc(page, 'jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]);
  const sid = (await rpc(page, 'jaot.scenario', 'create', [[{ name: 'UI PROBE', recipe_id: recipe[0].id, company_id: 1 }]]))[0];
  console.log('scenario', sid);

  // open form, click Solve via UI
  await page.goto(`${BASE}/odoo/action-185/${sid}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  const solve = page.getByRole('button', { name: 'Solve' });
  console.log('Solve visible count:', await solve.count(), 'first visible:', await solve.first().isVisible().catch(() => false));
  await solve.first().click();
  await page.waitForTimeout(2500);
  let st = (await rpc(page, 'jaot.scenario', 'read', [[sid], ['state']]))[0].state;
  console.log('state after UI Solve click:', st);
  await dumpDialogs(page, 'after Solve click');

  // poll to solved
  for (let i = 0; i < 20 && st !== 'solved' && st !== 'failed'; i++) {
    await rpc(page, 'jaot.scenario', 'reconcile_jaot_scenarios', []);
    await sleep(3000);
    st = (await rpc(page, 'jaot.scenario', 'read', [[sid], ['state']]))[0].state;
  }
  console.log('state after poll:', st);

  if (st === 'solved') {
    await page.goto(`${BASE}/odoo/action-185/${sid}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    const apply = page.getByRole('button', { name: 'Apply' });
    console.log('Apply visible count:', await apply.count(), 'first visible:', await apply.first().isVisible().catch(() => false));
    await apply.first().click();
    await page.waitForTimeout(2500);
    await dumpDialogs(page, 'after Apply click');
    st = (await rpc(page, 'jaot.scenario', 'read', [[sid], ['state']]))[0].state;
    console.log('state after Apply click (no confirm click):', st);
  }
} catch (e) {
  console.error('UI PROBE ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
