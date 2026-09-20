import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:8069';
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
  const s7 = (await rpc('jaot.scenario', 'read', [[7], ['kpi_summary', 'objective_value', 'baseline_scenario_id', 'state']])).result[0];
  console.log('S7:', JSON.stringify(s7));
  const s8 = (await rpc('jaot.scenario', 'read', [[8], ['kpi_summary', 'objective_value', 'is_baseline', 'state']])).result[0];
  console.log('S8:', JSON.stringify(s8));
  const lines7 = (await rpc('jaot.scenario.line', 'search_read', [[['scenario_id', '=', 7]], ['res_model', 'res_id', 'decision', 'delta_vs_baseline', 'kpi_contribution']])).result;
  console.log('S7 lines:', JSON.stringify(lines7, null, 1));
  const lines8 = (await rpc('jaot.scenario.line', 'search_read', [[['scenario_id', '=', 8]], ['res_model', 'res_id', 'decision', 'kpi_contribution']])).result;
  console.log('S8 lines:', JSON.stringify(lines8, null, 1));
} catch (e) {
  console.error('DELTA ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
