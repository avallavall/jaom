// JAOM end-to-end suite (Playwright) — drives the real Odoo web client and
// asserts behaviour through JSON-RPC. See dev/e2e/README.md.
//
//   node e2e.mjs
//
// Reads the JAOT API key from a file kept OUTSIDE the repo (never committed):
//   JAOT_E2E_KEY_FILE  (default: C:\Users\vall-\.qwen\tmp\jaom\e2e_key.txt)
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const ROOT = 'C:\\Users\\vall-\\Desktop\\projectes\\jaom';
const RESULTS = path.join(ROOT, 'dev', 'e2e', 'results');
fs.mkdirSync(RESULTS, { recursive: true });

const BASE = process.env.JAOT_E2E_BASE || 'http://127.0.0.1:8069';
const DB = 'e2e';
const MGR = { login: 'jaotmgr', password: 'JaotE2e-1!' };
const VIEW = { login: 'jaotview', password: 'JaotE2e-1!' };
const KEY_FILE = process.env.JAOT_E2E_KEY_FILE || 'C:\\Users\\vall-\\.qwen\\tmp\\jaom\\e2e_key.txt';
const ENDPOINT = 'http://host.docker.internal:8001';
const BAD_ENDPOINT = 'http://127.0.0.1:1';
const API_KEY = fs.readFileSync(KEY_FILE, 'utf8').trim();

// ir.ui.action ids for the `e2e` db (verified).
const A = { config: 184, recipes: 182, bindings: 183, scenarios: 185, applyLog: 186, toy: 187, mrp: 501, vrp: 435 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function assert(cond, msg) { if (!cond) throw new Error(msg); }

function makeRpc(page) {
  return async function rpc(model, method, args = [], kwargs = {}) {
    const res = await page.evaluate(
      ([base, model, method, args, kwargs]) =>
        fetch(`${base}/web/dataset/call_kw/${model}/${method}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: { model, method, args, kwargs } }),
        }).then((r) => r.json()),
      [BASE, model, method, args, kwargs]
    );
    if (res.error) {
      const et = res.error.data?.message || res.error.message || JSON.stringify(res.error);
      const args = res.error.data?.arguments;
      const extra = Array.isArray(args) && args.length ? ` | args=${JSON.stringify(args)}` : '';
      throw new Error(`${model}.${method}: ${et}${extra}`);
    }
    return res.result;
  };
}

async function login(page, creds) {
  await page.goto(`${BASE}/web/login?db=${DB}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('input[name="login"]');
  await page.fill('input[name="login"]', creds.login);
  await page.fill('input[name="password"]', creds.password);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/odoo/**', { timeout: 20000 });
  await page.waitForLoadState('domcontentloaded');
}

async function openForm(page, id) {
  await page.goto(`${BASE}/odoo/action-${A.scenarios}/${id}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.o_form_view', { timeout: 15000 });
  await page.waitForTimeout(800);
}

async function gotoAction(page, actionId) {
  await page.goto(`${BASE}/odoo/action-${actionId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
}

async function readScenario(rpc, id, fields) {
  // A read issued immediately after a reconcile can race a partially-written
  // recordset and raise a spurious server error; retry a couple of times.
  let lastErr;
  for (let i = 0; i < 4; i++) {
    try {
      return (await rpc('jaot.scenario', 'read', [[id], fields]))[0];
    } catch (e) {
      lastErr = e;
      await sleep(400);
    }
  }
  throw lastErr;
}

async function pollTo(rpc, id, field, values, capMs = 120000, interval = 3000) {
  const t0 = Date.now();
  while (Date.now() - t0 < capMs) {
    await rpc('jaot.scenario', 'reconcile_jaot_scenarios', []);
    const row = await readScenario(rpc, id, ['state', 'whatif_state', 'line_count', 'objective_value', 'solver_status', 'jaot_error', 'baseline_scenario_id', 'data_stale']);
    if (values.includes(row[field])) return row;
    await sleep(interval);
  }
  throw new Error(`scenario ${id}: field "${field}" did not reach ${JSON.stringify(values)} within ${capMs}ms`);
}

async function clickBtn(page, name) {
  const btn = page.getByRole('button', { name });
  assert(await btn.count() > 0, `button "${name}" not visible`);
  await btn.first().click();
  await page.waitForTimeout(1500);
}

async function confirmOk(page, timeout = 12000) {
  // The .o_dialog wrapper renders with a zero bounding box, so Playwright
  // treats the container as "hidden"; wait on the Ok button instead.
  const ok = page.locator('.o_dialog button', { hasText: 'Ok' });
  await ok.first().waitFor({ state: 'visible', timeout });
  await ok.first().click();
  await page.waitForTimeout(2500);
}

async function shot(page, name) {
  const p = path.join(RESULTS, name.replace(/[^a-z0-9]+/gi, '_') + '.png');
  await page.screenshot({ path: p }).catch(() => {});
  return p;
}

// ----------------------------------------------------------------------
// cases
// ----------------------------------------------------------------------
const cases = [];
function case_(name, run) { cases.push({ name, run }); }

case_('login_manager', async (ctx) => {
  assert(ctx.page.url().includes('/odoo'), `not logged in: ${ctx.page.url()}`);
  await gotoAction(ctx.page, A.config);
  assert(await ctx.page.locator('.o_list_view, .o_form_view').count() > 0, 'config action did not render');
});

case_('connection_create_and_test', async (ctx) => {
  // find-or-create the main-company connection (manager-gated, stored via sudo).
  const existing = await ctx.rpc('jaot.config', 'search_read', [[['company_id', '=', 1]], ['id', 'endpoint_url', 'api_key_set']]);
  let cfg;
  if (existing.length) {
    cfg = existing[0].id;
    await ctx.rpc('jaot.config', 'write', [[cfg], { endpoint_url: ENDPOINT, api_key_input: API_KEY }]);
  } else {
    cfg = (await ctx.rpc('jaot.config', 'create', [[{ company_id: 1, endpoint_url: ENDPOINT, api_key_input: API_KEY }]]))[0];
  }
  // A read issued immediately after the write can transiently come back empty
  // (a different worker/transaction has not observed the commit yet); retry.
  let rd = [];
  for (let i = 0; i < 6; i++) {
    rd = await ctx.rpc('jaot.config', 'read', [[cfg], ['endpoint_url', 'api_key_set', 'api_key_masked']]);
    if (rd.length) break;
    await sleep(400);
  }
  const row = rd[0];
  assert(row && row.api_key_set, `api_key_set false or config ${cfg} not readable: ${JSON.stringify(rd)}`);
  assert(/.{4}.{1,}.{4}/.test(row.api_key_masked || ''), `masked key not masked: ${row.api_key_masked}`);

  // server-side connectivity check
  const test = await ctx.rpc('jaot.config', 'action_test_connection', [[cfg]]);
  assert(test?.params?.params?.type === 'success', `test connection not success: ${JSON.stringify(test)}`);
  assert(/Solvers available/.test(test.params.params.message), `no solver list in message: ${test.params.params.message}`);

  // UI: open the config, assert the masked key renders, click Test connection.
  const cfgForm = `${BASE}/odoo/action-${A.config}/${cfg}`;
  await ctx.page.goto(cfgForm, { waitUntil: 'domcontentloaded' });
  await ctx.page.waitForSelector('.o_form_view', { timeout: 15000 });
  await ctx.page.waitForTimeout(1000);
  const bodyText = await ctx.page.locator('.o_form_view').innerText();
  assert(bodyText.includes(row.api_key_masked), 'masked key not shown in the config form');
  // The manager can trigger the connectivity test from the UI. The success is
  // already proven by the action_test_connection RPC result above (the toast
  // itself is a fire-and-forget client notification, not a reliable assert).
  await clickBtn(ctx.page, 'Test connection');
  assert(await ctx.page.locator('.o_form_view').count() > 0, 'config form vanished after Test connection');
});

case_('connection_bad_endpoint', async (ctx) => {
  // a second, per-company connection (company 8) with an unreachable endpoint.
  const bad = (await ctx.rpc('jaot.config', 'search_read', [[['company_id', '=', 8]], ['id']]))[0]?.id
    ?? (await ctx.rpc('jaot.config', 'create', [[{ company_id: 8, endpoint_url: BAD_ENDPOINT, api_key_input: API_KEY }]]))[0];
  await ctx.rpc('jaot.config', 'write', [[bad], { endpoint_url: BAD_ENDPOINT, api_key_input: API_KEY }]);
  let failed = false, msg = '';
  try {
    await ctx.rpc('jaot.config', 'action_test_connection', [[bad]]);
  } catch (e) { failed = true; msg = e.message; }
  assert(failed, 'expected the bad endpoint to fail the connectivity check, but it succeeded');
  assert(/connection failed|transport|refused|unreachable|JAOT/i.test(msg), `unexpected failure: ${msg}`);
});

case_('recipe_validate', async (ctx) => {
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id', 'name']]))[0];
  assert(recipe, 'mrp recipe not found');
  await ctx.page.goto(`${BASE}/odoo/action-${A.recipes}/${recipe.id}`, { waitUntil: 'domcontentloaded' });
  await ctx.page.waitForSelector('.o_form_view', { timeout: 15000 });
  await ctx.page.waitForTimeout(1000);
  // manager-gated Validate button must be visible to the manager.
  assert(await ctx.page.getByRole('button', { name: 'Validate' }).count() > 0, 'Validate button not visible to the manager');
  await clickBtn(ctx.page, 'Validate');
  // The action syntax-checks every binding domain + expression; a valid
  // recipe returns the success client action, an invalid one raises.
  const result = await ctx.rpc('jaot.recipe', 'action_validate', [[recipe.id]]);
  assert(result?.type === 'ir.actions.client', `Validate did not return a client action: ${JSON.stringify(result)}`);
  assert(/validated|no syntax errors/i.test(result.params.params.message), `unexpected validate result: ${result.params.params.message}`);
});

case_('mrp_lifecycle', async (ctx) => {
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const name = `E2E MRP ${Date.now()}`;
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name, recipe_id: recipe.id, company_id: 1 }]]))[0];

  // original MO start dates (for the revert assertion).
  const mos0 = await ctx.rpc('mrp.production', 'search_read', [[['name', 'like', 'E2E MO']], ['id', 'name', 'date_start']], {}, { limit: 20 });
  const before = Object.fromEntries(mos0.map((m) => [m.id, m.date_start]));

  // Solve (UI) -> queued -> solved.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Solve');
  let row = await pollTo(ctx.rpc, sid, 'state', ['solved', 'failed']);
  assert(row.state === 'solved', `MRP scenario failed: ${row.jaot_error}`);
  assert(row.line_count === 4, `expected 4 lines, got ${row.line_count}`);
  assert(row.solver_status === 'optimal', `solver_status ${row.solver_status}`);
  assert(typeof row.objective_value === 'number' && row.objective_value > 0, `no objective value: ${row.objective_value}`);

  // Compare with baseline (UI): creates + submits a pinned baseline scenario.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Compare with baseline');
  const withBase = await readScenario(ctx.rpc, sid, ['baseline_scenario_id']);
  // baseline_scenario_id is a Many2one: it reads back as [id, name].
  const baseId = Array.isArray(withBase.baseline_scenario_id)
    ? withBase.baseline_scenario_id[0] : withBase.baseline_scenario_id;
  assert(baseId, 'baseline_scenario_id not set after Compare');
  const baseRow = await pollTo(ctx.rpc, baseId, 'state', ['solved', 'failed']);
  assert(baseRow.state === 'solved', `baseline scenario failed: ${baseRow.jaot_error}`);
  // A self-pinned baseline may reproduce the incumbent (zero delta), so assert the
  // comparison RAN (kpi_summary carries the baseline objectives + delta, always
  // written by _store_baseline_delta) rather than that some individual line moved.
  const mainKpi = (await readScenario(ctx.rpc, sid, ['kpi_summary'])).kpi_summary;
  assert(mainKpi && typeof mainKpi.baseline_objective === 'number',
    `baseline comparison not written to kpi_summary: ${JSON.stringify(mainKpi)}`);
  assert(typeof mainKpi.optimized_objective === 'number',
    `kpi_summary missing optimized_objective: ${JSON.stringify(mainKpi)}`);
  assert(typeof mainKpi.delta_vs_baseline === 'number',
    `kpi_summary missing delta_vs_baseline: ${JSON.stringify(mainKpi)}`);

  // What-if analysis (UI): requested -> done, rows stored.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'What-if analysis');
  const wf = await pollTo(ctx.rpc, sid, 'whatif_state', ['done', 'failed']);
  assert(wf.whatif_state === 'done', `what-if did not complete: ${wf.whatif_state}`);
  const wfLines = await ctx.rpc('jaot.scenario.whatif', 'search', [[['scenario_id', '=', sid]]]);
  assert(wfLines.length > 0, 'no what-if rows stored');

  // Apply (UI, confirmation-gated) -> applied; MO dates written + audit log.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Apply');
  await confirmOk(ctx.page);
  let after = await readScenario(ctx.rpc, sid, ['state', 'applied', 'applied_by']);
  assert(after.state === 'applied' && after.applied === true, `not applied: ${JSON.stringify(after)}`);
  const log = await ctx.rpc('jaot.apply.log', 'search_read', [[['scenario_id', '=', sid]], ['res_model', 'res_id', 'field_path', 'before_value', 'after_value']], {}, { limit: 20 });
  assert(log.length > 0, 'no apply-log rows after Apply');
  const mosAfter = Object.fromEntries((await ctx.rpc('mrp.production', 'search_read', [[['name', 'like', 'E2E MO']], ['id', 'date_start']], {}, { limit: 20 })).map((m) => [m.id, m.date_start]));
  // The apply log records the solved plan for every line. Whether a value
  // actually CHANGED is data-dependent (the MOs may already carry the
  // optimized dates across runs), so verify the records carry the applied
  // value rather than that some value moved.
  const appliedDates = log.filter((l) => l.field_path === 'date_start');
  assert(appliedDates.length > 0, 'no date_start apply-log rows after Apply');
  for (const l of appliedDates) {
    let applied; try { applied = JSON.parse(l.after_value); } catch { applied = l.after_value; }
    assert(mosAfter[l.res_id] === applied,
      `MO ${l.res_id} does not carry the applied date: expected ${applied}, got ${mosAfter[l.res_id]}`);
  }

  // Revert (UI, confirmation-gated) -> solved; MO dates restored.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Revert');
  await confirmOk(ctx.page);
  const rev = await readScenario(ctx.rpc, sid, ['state', 'applied']);
  assert(rev.state === 'solved' && rev.applied === false, `not reverted: ${JSON.stringify(rev)}`);
  const mosRestored = Object.fromEntries((await ctx.rpc('mrp.production', 'search_read', [[['name', 'like', 'E2E MO']], ['id', 'date_start']], {}, { limit: 20 })).map((m) => [m.id, m.date_start]));
  for (const [id, d] of Object.entries(before)) {
    assert(mosRestored[id] === d, `MO ${id} not restored: was ${d}, now ${mosRestored[id]}`);
  }
});

case_('mrp_infeasible', async (ctx) => {
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const capRole = (await ctx.rpc('jaot.recipe.role', 'search', [[['recipe_id', '=', recipe.id], ['name', '=', 'resource_capacity']]]))[0];
  const binding = (await ctx.rpc('jaot.binding', 'search_read', [[['recipe_id', '=', recipe.id], ['role_id', '=', capRole]], ['id', 'constant_value']]))[0];
  const origCap = binding.constant_value;
  try {
    // 500 units of demand over 2 deadline days; 80/day = 160 -> infeasible.
    await ctx.rpc('jaot.binding', 'write', [[binding.id], { constant_value: '80.0' }]);
    const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E INFEAS ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
    await ctx.rpc('jaot.scenario', 'action_submit', [[sid]]);
    const row = await pollTo(ctx.rpc, sid, 'state', ['solved', 'failed']);
    assert(row.state === 'failed', `expected infeasible/failed, got ${row.state}`);
    const infeas = await readScenario(ctx.rpc, sid, ['infeasibility', 'jaot_error']);
    assert(infeas.infeasibility || infeas.jaot_error, 'no infeasibility/error recorded for a failed scenario');
  } finally {
    await ctx.rpc('jaot.binding', 'write', [[binding.id], { constant_value: origCap }]);
  }
});

case_('mrp_cancel', async (ctx) => {
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E CANCEL ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Solve');
  // Deliberately NO reconcile here: it would advance the scenario past the
  // state the Cancel button targets. action_submit leaves it queued; the
  // one-minute cron (not run within this short window) is what would move it.
  await sleep(2000);
  await openForm(ctx.page, sid); // reload -> the queued state shows Cancel
  await clickBtn(ctx.page, 'Cancel');
  const after = await readScenario(ctx.rpc, sid, ['state']);
  assert(after.state === 'cancelled', `not cancelled: ${after.state}`);
});

case_('vrp_lifecycle', async (ctx) => {
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'vrp']], ['id']]))[0];
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E VRP ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
  const picks0 = await ctx.rpc('stock.picking', 'search_read', [[['picking_type_code', '=', 'outgoing'], ['state', 'in', ['confirmed', 'assigned']]], ['id', 'jaot_vehicle_id', 'jaot_route_sequence']], {}, { limit: 20 });
  const before = Object.fromEntries(picks0.map((p) => [p.id, [p.jaot_vehicle_id, p.jaot_route_sequence]]));

  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Solve');
  const row = await pollTo(ctx.rpc, sid, 'state', ['solved', 'failed']);
  assert(row.state === 'solved', `VRP scenario failed: ${row.jaot_error}`);
  assert(row.line_count === 4, `expected 4 VRP lines, got ${row.line_count}`);

  // Apply (confirmation-gated): vehicle + route sequence written to pickings.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Apply');
  await confirmOk(ctx.page);
  const after = await readScenario(ctx.rpc, sid, ['state', 'applied']);
  assert(after.state === 'applied', `VRP not applied: ${after.state}`);
  const picksAfter = Object.fromEntries((await ctx.rpc('stock.picking', 'search_read', [[['picking_type_code', '=', 'outgoing'], ['state', 'in', ['confirmed', 'assigned']]], ['id', 'jaot_vehicle_id', 'jaot_route_sequence']], {}, { limit: 20 })).map((p) => [p.id, [p.jaot_vehicle_id, p.jaot_route_sequence]]));
  const changed = Object.keys(before).some((id) => JSON.stringify(before[id]) !== JSON.stringify(picksAfter[id]));
  assert(changed, 'no picking changed after VRP Apply');

  // Revert (confirmation-gated): pickings restored.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Revert');
  await confirmOk(ctx.page);
  const rev = await readScenario(ctx.rpc, sid, ['state', 'applied']);
  assert(rev.state === 'solved', `VRP not reverted: ${rev.state}`);
  const picksRestored = Object.fromEntries((await ctx.rpc('stock.picking', 'search_read', [[['picking_type_code', '=', 'outgoing'], ['state', 'in', ['confirmed', 'assigned']]], ['id', 'jaot_vehicle_id', 'jaot_route_sequence']], {}, { limit: 20 })).map((p) => [p.id, [p.jaot_vehicle_id, p.jaot_route_sequence]]));
  for (const [id, vals] of Object.entries(before)) {
    assert(JSON.stringify(picksRestored[id]) === JSON.stringify(vals), `picking ${id} not restored`);
  }
});

case_('staleness_detection', async (ctx) => {
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E STALE ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
  const [mo] = await ctx.rpc('mrp.production', 'search_read', [[['name', '=', 'E2E MO 2']], ['id', 'date_start']]);
  const orig = mo.date_start;
  try {
    await ctx.rpc('jaot.scenario', 'action_submit', [[sid]]);
    await pollTo(ctx.rpc, sid, 'state', ['solved', 'failed']);
    // mutate a source record after extraction -> the snapshot hash must change.
    await ctx.rpc('mrp.production', 'write', [[mo.id], { date_start: '2026-10-09 06:00:00' }]);
    await openForm(ctx.page, sid);
    await clickBtn(ctx.page, 'Check staleness');
    const row = await readScenario(ctx.rpc, sid, ['data_stale']);
    assert(row.data_stale === true, 'data_stale not flagged after mutating the source MO');
    // The banner is bound to data_stale; reload so the form re-renders it.
    await openForm(ctx.page, sid);
    const banner = ctx.page.locator('.o_form_view .alert.alert-warning');
    assert(await banner.count() > 0, 'staleness warning banner not rendered');
  } finally {
    await ctx.rpc('mrp.production', 'write', [[mo.id], { date_start: orig }]);
  }
});

case_('security_viewer', async (ctx) => {
  // prepare a solved scenario as the manager, then inspect it as the viewer.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E VIEW ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
  await ctx.rpc('jaot.scenario', 'action_submit', [[sid]]);
  const row = await pollTo(ctx.rpc, sid, 'state', ['solved', 'failed']);
  assert(row.state === 'solved', `prep scenario failed: ${row.jaot_error}`);

  const vctx = await ctx.browser.newContext();
  const vpage = await vctx.newPage();
  try {
    await login(vpage, VIEW);
    // the viewer can READ the scenario form (group user).
    await openForm(vpage, sid);
    const formText = await vpage.locator('.o_form_view').innerText();
    assert(formText.includes('E2E VIEW'), 'viewer could not read the scenario form');

    // none of the manager action buttons may be visible to the viewer.
    for (const btn of ['Solve', 'Apply', 'Revert', 'Cancel', 'Compare with baseline', 'What-if analysis', 'Check staleness']) {
      assert(await vpage.getByRole('button', { name: btn }).count() === 0, `viewer sees manager button "${btn}"`);
    }

    // the group_system-only "expression" column must be hidden in bindings.
    await gotoAction(vpage, A.bindings);
    const headers = await vpage.locator('.o_list_view thead th, .o_list_table thead th').allInnerTexts();
    assert(!headers.some((h) => /expression/i.test(h)), `viewer sees the expression column: ${JSON.stringify(headers)}`);
  } finally {
    await vctx.close();
  }
});

case_('apply_log_view', async (ctx) => {
  // the MRP lifecycle produced reverted audit-log rows; they must be listed.
  const log = await ctx.rpc('jaot.apply.log', 'search_read', [[['state', '=', 'reverted']], ['id', 'scenario_id', 'res_model', 'field_path']], {}, { limit: 50 });
  assert(log.length > 0, 'no reverted apply-log rows found (MRP lifecycle should have produced them)');
  await gotoAction(ctx.page, A.applyLog);
  const rows = await ctx.page.locator('.o_list_view tbody tr').count();
  assert(rows > 0, 'apply log list rendered no rows');
});

// ----------------------------------------------------------------------
// runner
// ----------------------------------------------------------------------
async function main() {
  const browser = await chromium.launch();
  const ctxPage = await browser.newPage();
  const rpc = makeRpc(ctxPage);
  await login(ctxPage, MGR);
  const ctx = { browser, page: ctxPage, rpc };

  const results = [];
  for (const c of cases) {
    const t0 = Date.now();
    try {
      await c.run(ctx);
      results.push({ name: c.name, ok: true, ms: Date.now() - t0 });
      console.log(`PASS  ${c.name}  (${Date.now() - t0}ms)`);
    } catch (e) {
      const shotPath = await shot(ctx.page, c.name);
      results.push({ name: c.name, ok: false, ms: Date.now() - t0, error: e.message, screenshot: shotPath });
      console.log(`FAIL  ${c.name}  (${Date.now() - t0}ms)  ${e.message}`);
    }
  }

  const out = path.join(RESULTS, 'e2e_results.json');
  const passed = results.filter((r) => r.ok).length;
  const summary = { total: results.length, passed, failed: results.length - passed, results };
  fs.writeFileSync(out, JSON.stringify(summary, null, 2));
  console.log(`\n=== ${passed}/${results.length} cases passed -> ${out} ===`);
  await browser.close();
  process.exit(results.some((r) => !r.ok) ? 1 : 0);
}

main().catch((e) => { console.error('SUITE FATAL:', e); process.exit(2); });
