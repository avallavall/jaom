import { chromium } from 'playwright';
import fs from 'node:fs';
const BASE = 'http://127.0.0.1:8069';
const KEY_FILE = process.env.JAOT_E2E_KEY_FILE || 'C:/Users/vall-/.qwen/tmp/jaom/e2e_key.txt';
const API_KEY = fs.readFileSync(KEY_FILE, 'utf8').trim();
const ENDPOINT = 'http://host.docker.internal:8001';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch();
const page = await browser.newPage();
// RAW rpc: returns the full jsonrpc response (no throw).
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
const FIELDS = ['state', 'whatif_state', 'line_count', 'objective_value', 'solver_status', 'jaot_error', 'baseline_scenario_id', 'data_stale'];
try {
  await page.goto(`${BASE}/web/login?db=e2e`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="login"]', 'jaotmgr');
  await page.fill('input[name="password"]', 'JaotE2e-1!');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/odoo/**', { timeout: 20000 });
  // ensure config exists
  const cfg = await rpcRaw('jaot.config', 'search_read', [[['company_id', '=', 1]], ['id', 'endpoint_url', 'api_key_set']]);
  console.log('CONFIG search_read:', JSON.stringify(cfg));
  const recipe = { id: 2 };
  const created = await rpcRaw('jaot.scenario', 'create', [[{ name: `HASH ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]);
  console.log('CREATE:', JSON.stringify(created));
  const sid = created.result[0];
  const sub = await rpcRaw('jaot.scenario', 'action_submit', [[sid]]);
  console.log('SUBMIT:', JSON.stringify(sub).slice(0, 200));
  for (let i = 0; i < 8; i++) {
    const rec = await rpcRaw('jaot.scenario', 'reconcile_jaot_scenarios', []);
    console.log(`[${i}] reconcile:`, JSON.stringify(rec).slice(0, 200));
    const rd = await rpcRaw('jaot.scenario', 'read', [[sid], FIELDS]);
    if (rd.error) {
      console.log(`[${i}] READ ERROR:`, JSON.stringify(rd.error));
    } else {
      console.log(`[${i}] read state:`, JSON.stringify(rd.result[0]));
    }
    const row = rd.result && rd.result[0];
    if (row && (row.state === 'solved' || row.state === 'failed')) {
      // stable now: read once more after a pause
      await sleep(1500);
      const rd2 = await rpcRaw('jaot.scenario', 'read', [[sid], FIELDS]);
      console.log(`[${i}] READ after pause:`, rd2.error ? JSON.stringify(rd2.error) : JSON.stringify(rd2.result[0]));
      break;
    }
    await sleep(2000);
  }
} catch (e) {
  console.error('HASH ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
