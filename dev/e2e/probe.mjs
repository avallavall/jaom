// DOM probe for the Odoo 19 web client (scratch; deleted after use).
import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE = 'http://127.0.0.1:8069';
const DB = 'e2e';
const LOG = 'C:/Users/vall-/.qwen/tmp/jaom/probe_ui.log';
const out = [];
const flush = () => fs.writeFileSync(LOG, out.join('\n'));
const note = (s) => { out.push(s); flush(); };

const browser = await chromium.launch();
const page = await browser.newPage();
page.on('console', (m) => { if (m.type() === 'error') note('[console.error] ' + m.text()); });
page.on('dialog', (d) => { note('[dialog] ' + d.message()); d.accept(); });

async function grab(label, selector, max = 4000, timeout = 8000) {
  const loc = page.locator(selector).first();
  try {
    await loc.waitFor({ timeout });
    note(`\n=== ${label} (${selector}) ===\n${await loc.evaluate((el, m) => el.outerHTML.slice(0, m), max)}`);
  } catch (e) {
    note(`\n=== ${label} (${selector}) MISSING: ${e.message.split('\n')[0]}`);
  }
}
async function tryStep(label, fn) {
  try { await fn(); } catch (e) { note(`\n!! step failed: ${label}: ${e.message.split('\n')[0]}`); }
}

// login
await page.goto(`${BASE}/web/login?db=${DB}`, { waitUntil: 'domcontentloaded' });
await page.fill('input[name="login"]', 'jaotmgr');
await page.fill('input[name="password"]', 'JaotE2e-1!');
await page.click('button[type="submit"]');
await page.waitForLoadState('domcontentloaded');
await page.waitForTimeout(6000);
note('url after login: ' + page.url());

// navigate directly to the Scenarios action URL
await tryStep('goto scenarios action', async () => {
  await page.goto(`${BASE}/odoo/action-185`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
});
note('\nurl after scenarios goto: ' + page.url());
await grab('scenario list (.o_action)', '.o_action', 3000);
await grab('list create button', 'button.o_list_record_create', 400);
await grab('list rows', '.o_list_renderer', 2500);
await grab('statusbar / title', '.o_action', 2000);

// create a scenario
await tryStep('click create', async () => {
  await page.locator('button.o_list_record_create').first().click();
  await page.waitForTimeout(3000);
});
await grab('scenario form view', 'form.o_form_view', 6000);
await grab('notebook tabs', '.o_notebook .o_notebook_tab', 2500);

flush();
await browser.close();
console.log('probe done');
