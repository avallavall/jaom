import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8069';
const browser = await chromium.launch();
const page = await browser.newPage();
async function rpc(model, method, args = [], kwargs = {}) {
  const res = await page.evaluate(
    ([base, model, method, args, kwargs]) =>
      fetch(`${base}/web/dataset/call_kw/${model}/${method}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: { model, method, args, kwargs } }),
      }).then((r) => r.json()),
    [BASE, model, method, args, kwargs]
  );
  if (res.error) { const et = res.error.data?.message || res.error.message || JSON.stringify(res.error); return { __err: et }; }
  return res.result;
}
try {
  await page.goto(`${BASE}/web/login?db=e2e`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name="login"]', 'jaotmgr');
  await page.fill('input[name="password"]', 'JaotE2e-1!');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/odoo/**', { timeout: 20000 });

  // jaot.config read for id 1
  console.log('config read [[1]]:', JSON.stringify(await rpc('jaot.config', 'read', [[1], ['endpoint_url', 'api_key_set', 'api_key_masked']])));

  const fields = ['state', 'whatif_state', 'line_count', 'objective_value', 'solver_status', 'jaot_error', 'baseline_scenario_id', 'data_stale'];
  for (const id of [1, 7]) {
    console.log(`--- scenario ${id} ---`);
    for (const f of fields) {
      const r = await rpc('jaot.scenario', 'read', [[id], [f]]);
      console.log(`  ${f}:`, r.__err ? `ERR ${r.__err}` : JSON.stringify(r));
    }
    console.log(`  all:`, JSON.stringify(await rpc('jaot.scenario', 'read', [[id], fields])));
  }
  console.log('reconcile:', JSON.stringify(await rpc('jaot.scenario', 'reconcile_jaot_scenarios', [])));
} catch (e) {
  console.error('DIAG ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
