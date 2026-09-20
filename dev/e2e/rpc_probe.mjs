import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8069';
const DB = 'e2e';
const KEY_FILE = process.env.JAOT_E2E_KEY_FILE || 'C:\\Users\\vall-\\.qwen\\tmp\\jaom\\e2e_key.txt';
const api_key = fs.readFileSync(KEY_FILE, 'utf8').trim();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function rpc(page, model, method, args = [], kwargs = {}) {
  const res = await page.evaluate(
    ([base, model, method, args, kwargs]) =>
      fetch(`${base}/web/dataset/call_kw/${model}/${method}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: { model, method, args, kwargs } }),
      }).then((r) => r.json()),
    [BASE, model, method, args, kwargs]
  );
  if (res.error) {
    const et = res.error.data?.message || res.error.message || JSON.stringify(res.error);
    throw new Error(`${model}.${method} RPC error: ${et}`);
  }
  return res.result;
}

const browser = await chromium.launch();
const page = await browser.newPage();
try {
  await page.goto(`${BASE}/web/login?db=${DB}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('input[name="login"]');
  await page.fill('input[name="login"]', 'jaotmgr');
  await page.fill('input[name="password"]', 'JaotE2e-1!');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/odoo/**', { timeout: 20000 });
  console.log('login OK ->', page.url());

  const ENDPOINT = 'http://host.docker.internal:8001';
  const existing = await rpc(page, 'jaot.config', 'search_read', [[['company_id', '=', 1]], ['id', 'endpoint_url', 'api_key_set']]);
  console.log('existing configs:', JSON.stringify(existing));
  let cfg;
  if (existing.length) {
    cfg = existing[0].id;
    await rpc(page, 'jaot.config', 'write', [[cfg], { endpoint_url: ENDPOINT, api_key_input: api_key }]);
  } else {
    cfg = (await rpc(page, 'jaot.config', 'create', [[{ company_id: 1, endpoint_url: ENDPOINT, api_key_input: api_key }]]))[0];
  }
  console.log('config id', cfg);
  const test = await rpc(page, 'jaot.config', 'action_test_connection', [[cfg]]);
  console.log('test connection ->', JSON.stringify(test).slice(0, 240));

  const recipe = await rpc(page, 'jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]);
  const recipe_id = recipe[0].id;
  const created = await rpc(page, 'jaot.scenario', 'create', [[{ name: 'PROBE SCENARIO', recipe_id, company_id: 1 }]]);
  const sid = created[0];
  console.log('created scenario id', sid);
  const st0 = await rpc(page, 'jaot.scenario', 'read', [[sid], ['state']]);
  console.log('initial state', JSON.stringify(st0));

  await page.goto(`${BASE}/odoo/action-185/${sid}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  const formLoaded = await page.locator('.o_form_view').count();
  console.log('form deep-link loaded (.o_form_view count):', formLoaded, 'url:', page.url());

  const btns = await page.evaluate(() =>
    Array.from(document.querySelectorAll('header button, .o_form_buttonsbar button, .o_statusbar button'))
      .map((b) => b.textContent.trim())
      .filter(Boolean)
  );
  console.log('header/form buttons:', JSON.stringify(btns));

  try {
    const sub = await rpc(page, 'jaot.scenario', 'action_submit', [[sid]]);
    console.log('action_submit OK ->', JSON.stringify(sub));
  } catch (e) {
    console.log('action_submit ERROR:', e.message);
  }
  let state = '';
  for (let i = 0; i < 30; i++) {
    await rpc(page, 'jaot.scenario', 'reconcile_jaot_scenarios', []);
    const rows = await rpc(page, 'jaot.scenario', 'read', [[sid], ['state', 'line_count', 'objective_value', 'solver_status', 'jaot_error']]);
    state = rows[0].state;
    console.log(`poll ${i}: state=${state} line_count=${rows[0].line_count} obj=${rows[0].objective_value} solver=${rows[0].solver_status} err=${rows[0].jaot_error}`);
    if (state === 'solved' || state === 'failed') break;
    await sleep(4000);
  }
  console.log('final state:', state);

  if (state === 'solved') {
    await page.goto(`${BASE}/odoo/action-185/${sid}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    const applyBtn = page.getByRole('button', { name: 'Apply', exact: false });
    console.log('Apply button count:', await applyBtn.count());
    if (await applyBtn.count() > 0) {
      await applyBtn.first().click();
      await page.waitForTimeout(1500);
      const confirmDialog = await page.locator('.o_confirm_dialog').count();
      console.log('confirm dialog (.o_confirm_dialog) present after Apply:', confirmDialog);
      for (const sel of ['.o_confirm_dialog .btn-primary', '.o_confirm_dialog button.o_confirm_dialog_confirm', '.o_confirm_dialog button']) {
        const el = page.locator(sel).first();
        if (await el.count() > 0) { await el.click().catch(() => {}); console.log('clicked confirm via', sel); break; }
      }
      await page.waitForTimeout(2500);
      const stAfter = await rpc(page, 'jaot.scenario', 'read', [[sid], ['state']]);
      console.log('state after Apply:', JSON.stringify(stAfter));
    }
  }

  const mos = await rpc(page, 'mrp.production', 'search_read', [[['name', 'like', 'E2E MO']], ['id', 'name', 'date_start']], {}, { limit: 10 });
  console.log('MRPs:', JSON.stringify(mos, null, 1));

  const html = await page.content();
  const m = html.match(/"uid":\s*(\d+)/);
  console.log('session uid:', m ? m[1] : '(none)');
} catch (e) {
  console.error('PROBE ERROR:', e.message);
  try { await page.screenshot({ path: 'C:\\Users\\vall-.qwen\\tmp\\jaom\\probe_err.png' }); } catch {}
} finally {
  await browser.close();
}
console.log('done');
