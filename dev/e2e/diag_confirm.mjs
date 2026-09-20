import { chromium } from 'playwright';
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
  const sid = (await rpc('jaot.scenario', 'create', [[{ name: `CONF ${Date.now()}`, recipe_id: 2, company_id: 1 }]])).result[0];
  await rpc('jaot.scenario', 'action_submit', [[sid]]);
  for (let i = 0; i < 40; i++) {
    await rpc('jaot.scenario', 'reconcile_jaot_scenarios', []);
    const row = (await rpc('jaot.scenario', 'read', [[sid], ['state']])).result[0];
    if (row.state === 'solved' || row.state === 'failed') break;
    await sleep(2000);
  }
  await page.goto(`${BASE}/odoo/action-185/${sid}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.o_form_view', { timeout: 15000 });
  await page.getByRole('button', { name: 'Apply' }).first().click();
  await sleep(1500);
  const dlg = page.locator('.o_dialog', { hasText: 'Ok' }).first();
  console.log('dialog count:', await page.locator('.o_dialog').count());
  console.log('dialog isVisible:', await dlg.isVisible());
  console.log('dialog boundingBox:', JSON.stringify(await dlg.boundingBox()));
  const ok = dlg.locator('button', { hasText: 'Ok' });
  console.log('ok count:', await ok.count());
  console.log('ok isVisible:', await ok.isVisible());
  console.log('ok boundingBox:', JSON.stringify(await ok.boundingBox()));
  // compute styles of the dialog
  const styles = await page.evaluate(() => {
    const d = document.querySelector('.o_dialog');
    if (!d) return null;
    const cs = getComputedStyle(d);
    return { display: cs.display, visibility: cs.visibility, position: cs.position, zIndex: cs.zIndex, w: d.offsetWidth, h: d.offsetHeight, cls: d.className };
  });
  console.log('dialog computed style:', JSON.stringify(styles));
  // try the click
  try {
    await ok.click({ timeout: 5000 });
    console.log('CLICK OK succeeded');
  } catch (e) {
    console.log('CLICK OK failed:', e.message.slice(0, 200));
  }
} catch (e) {
  console.error('CONFIRM ERROR:', e.message);
} finally {
  await browser.close();
}
console.log('done');
