import { chromium } from 'playwright';
import fs from 'node:fs';
const BASE = 'http://127.0.0.1:8069';
const KEY_FILE = process.env.JAOT_E2E_KEY_FILE || 'C:/Users/vall-/.qwen/tmp/jaom/e2e_key.txt';
const API_KEY = fs.readFileSync(KEY_FILE, 'utf8').trim();
const ENDPOINT = 'http://host.docker.internal:8001';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch();
const page = await browser.newPage();
function rpcRaw(model, method, args = [], kwargs = {}) {
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
  // login_manager equivalent: navigate to config action, wait for list view.
  await page.goto(`${BASE}/odoo/action-184`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.o_list_view, .o_form_view', { timeout: 15000 });
  // NOW immediately do the connection steps (no sleep), exactly like the suite.
  const s = await rpcRaw('jaot.config', 'search_read', [[['company_id', '=', 1]], ['id', 'endpoint_url', 'api_key_set']]);
  console.log('search:', JSON.stringify(s));
  const existing = s.result;
  let cfg = existing[0]?.id;
  const w = await rpcRaw('jaot.config', 'write', [[cfg], { endpoint_url: ENDPOINT, api_key_input: API_KEY }]);
  console.log('write:', JSON.stringify(w));
  const rd = await rpcRaw('jaot.config', 'read', [[cfg], ['endpoint_url', 'api_key_set', 'api_key_masked']]);
  console.log('read1:', JSON.stringify(rd));
  await sleep(500);
  const rd2 = await rpcRaw('jaot.config', 'read', [[cfg], ['endpoint_url', 'api_key_set', 'api_key_masked']]);
  console.log('read2 (after 500ms):', JSON.stringify(rd2));
  // raw read via browse to be sure
  const ids = await rpcRaw('jaot.config', 'search', [[['company_id', '=', 1]]]);
  console.log('search ids after write:', JSON.stringify(ids));
} catch (e) {
  console.error('CONN ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
