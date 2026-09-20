// JAOM end-to-end suite (Playwright) — drives the real Odoo web client and
// asserts behaviour through JSON-RPC. See dev/e2e/README.md.
//
//   node e2e.mjs
//
// Reads the JAOT API key from a file kept OUTSIDE the repo (never committed):
//   JAOT_E2E_KEY_FILE  (default: C:\Users\vall-\.qwen\tmp\jaom\e2e_key.txt)
//
// Case groups:
//   connection_*   connection lifecycle, key storage, failure paths, UI save
//   binding_*, recipe_*  recipe/binding authoring validation
//   scenario_*, lifecycle_*, mrp_*, vrp_*  the full scenario lifecycles
//   security_*     role/ACL positive and negative controls
//   chatter_audit, apply_log_view, scenario_list_view  audit + rendering
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';

const ROOT = 'C:\\Users\\vall-\\Desktop\\projectes\\jaom';
const RESULTS = path.join(ROOT, 'dev', 'e2e', 'results');
fs.mkdirSync(RESULTS, { recursive: true });

const BASE = process.env.JAOT_E2E_BASE || 'http://127.0.0.1:8069';
const DB = 'e2e';
const MGR = { login: 'jaotmgr', password: 'JaotE2e-1!' };
const VIEW = { login: 'jaotview', password: 'JaotE2e-1!' };
const ADMIN = { login: 'e2eadmin', password: 'JaotE2e-1!' };
const KEY_FILE = process.env.JAOT_E2E_KEY_FILE || 'C:\\Users\\vall-\\.qwen\\tmp\\jaom\\e2e_key.txt';
const ENDPOINT = 'http://host.docker.internal:8001';
const BAD_ENDPOINT = 'http://127.0.0.1:1';
const API_KEY = fs.readFileSync(KEY_FILE, 'utf8').trim();
const BAD_KEY = 'ok_live_invalid_e2e_0000000';

// ir.ui.action ids for the `e2e` db (verified).
const A = { config: 184, recipes: 182, bindings: 183, scenarios: 185, applyLog: 186, toy: 187, mrp: 501, vrp: 435 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function assert(cond, msg) { if (!cond) throw new Error(msg); }

// psql inside the odoo container (repo root is RO-mounted there; the db host
// is `db`, superuser `odoo`). Used only to bypass the ORM on purpose
// (recipe_validate_invalid) — every other case goes through the API.
function execSql(sql) {
  const out = execFileSync('docker', [
    'exec', '-e', 'PGPASSWORD=odoo', 'jaom_odoo',
    'psql', '-h', 'db', '-U', 'odoo', '-d', DB, '-t', '-A', '-c', sql,
  ], { encoding: 'utf8' });
  return out.trim();
}

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

async function openRecord(page, actionId, id) {
  await page.goto(`${BASE}/odoo/action-${actionId}/${id}`, { waitUntil: 'domcontentloaded' });
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

// Run `fn` and assert it raises with a message matching `re`.
async function expectError(re, fn) {
  let failed = false, msg = '';
  try {
    await fn();
  } catch (e) { failed = true; msg = e.message; }
  assert(failed, `expected an error matching ${re}, but the call succeeded`);
  assert(re.test(msg), `error message "${msg}" does not match ${re}`);
  return msg;
}

function findConfig(rpc, company) {
  return rpc('jaot.config', 'search_read', [[['company_id', '=', company]], ['id', 'endpoint_url', 'api_key_set', 'api_key_masked', 'default_solver']]).then((rows) => rows[0]);
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
  ctx.cfgMain = cfg;
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

case_('connection_bad_key', async (ctx) => {
  // reachable endpoint + wrong key: JAOT answers 401 and the action must
  // surface it, not hang or pretend success.
  const c8 = await findConfig(ctx.rpc, 8);
  assert(c8, 'company-8 connection not found');
  try {
    await ctx.rpc('jaot.config', 'write', [[c8.id], { endpoint_url: ENDPOINT, api_key_input: BAD_KEY }]);
    await expectError(/401|unauthorized|invalid|key/i,
      () => ctx.rpc('jaot.config', 'action_test_connection', [[c8.id]]));
  } finally {
    // restore the canonical state (bad endpoint, real key) for the other cases
    await ctx.rpc('jaot.config', 'write', [[c8.id], { endpoint_url: BAD_ENDPOINT, api_key_input: API_KEY }]);
  }
});

case_('connection_solver_warning', async (ctx) => {
  // a default solver that is not in the live list must downgrade the
  // success notification to a WARNING that names the solver.
  const c1 = await findConfig(ctx.rpc, 1);
  assert(c1, 'company-1 connection not found');
  const orig = c1.default_solver || null;
  try {
    await ctx.rpc('jaot.config', 'write', [[c1.id], { default_solver: 'nope_missing_solver' }]);
    const test = await ctx.rpc('jaot.config', 'action_test_connection', [[c1.id]]);
    assert(test?.params?.params?.type === 'warning', `expected a warning notification, got: ${JSON.stringify(test)}`);
    assert(/WARNING/.test(test.params.params.message) && /nope_missing_solver/.test(test.params.params.message),
      `warning does not name the bad solver: ${test.params.params.message}`);
  } finally {
    await ctx.rpc('jaot.config', 'write', [[c1.id], { default_solver: orig }]);
  }
});

case_('connection_clear_key', async (ctx) => {
  // manager UI "Remove key": the key leaves ir.config_parameter, the masked
  // field clears, Test connection fails with a clear message; then restore.
  const c1 = await findConfig(ctx.rpc, 1);
  assert(c1, 'company-1 connection not found');
  await openRecord(ctx.page, A.config, c1.id);
  await clickBtn(ctx.page, 'Remove key');
  const cleared = (await ctx.rpc('jaot.config', 'read', [[c1.id], ['api_key_set', 'api_key_masked']]))[0];
  assert(cleared.api_key_set === false, `api_key_set still true after Remove key: ${JSON.stringify(cleared)}`);
  assert(!cleared.api_key_masked, `masked key still shown after Remove key: ${cleared.api_key_masked}`);
  await expectError(/No API key stored/i,
    () => ctx.rpc('jaot.config', 'action_test_connection', [[c1.id]]));
  // restore + verify the connection works again
  await ctx.rpc('jaot.config', 'write', [[c1.id], { api_key_input: API_KEY }]);
  const restored = (await ctx.rpc('jaot.config', 'read', [[c1.id], ['api_key_set']]))[0];
  assert(restored.api_key_set === true, 'key not restored');
  const test = await ctx.rpc('jaot.config', 'action_test_connection', [[c1.id]]);
  assert(test?.params?.params?.type === 'success', `test connection broken after restore: ${JSON.stringify(test)}`);
  // the chatter must carry both audit messages
  const msgs = await ctx.rpc('mail.message', 'search_read',
    [[['model', '=', 'jaot.config'], ['res_id', '=', c1.id]], ['body']]);
  const bodies = msgs.map((m) => m.body || '').join(' ');
  assert(/API key removed\./.test(bodies), 'chatter missing "API key removed."');
  assert(/API key stored\./.test(bodies), 'chatter missing "API key stored."');
});

case_('connection_save_key_via_ui', async (ctx) => {
  // manager pastes a new key into the form field and saves: the key lands
  // in ir.config_parameter (never on the record) and the mask updates.
  const c1 = await findConfig(ctx.rpc, 1);
  assert(c1, 'company-1 connection not found');
  await openRecord(ctx.page, A.config, c1.id);
  // Odoo 19 renders form fields as <div name="field"> wrappers around the
  // actual input; select the input inside the wrapper.
  const keyInput = ctx.page.locator('.o_form_view div[name="api_key_input"] input');
  assert(await keyInput.count() > 0, 'api_key_input field not visible to the manager');
  await keyInput.fill(API_KEY);
  await ctx.page.locator('.o_form_button_save').first().click();
  await ctx.page.waitForTimeout(1500);
  const row = (await ctx.rpc('jaot.config', 'read', [[c1.id], ['api_key_set', 'api_key_masked']]))[0];
  assert(row.api_key_set === true, `key not stored via the form: ${JSON.stringify(row)}`);
  assert(/.{4}.{1,}.{4}/.test(row.api_key_masked || ''), `masked key wrong after form save: ${row.api_key_masked}`);
  const bodyText = await ctx.page.locator('.o_form_view').innerText();
  assert(bodyText.includes(row.api_key_masked), 'form does not show the updated mask');
});

case_('uniqueness_constraints', async (ctx) => {
  // one connection per company, one recipe code per company.
  await expectError(/One JAOT connection per company/i,
    () => ctx.rpc('jaot.config', 'create', [[{ company_id: 1, endpoint_url: 'http://dup.example' }]]));
  await expectError(/recipe code must be unique per company/i,
    () => ctx.rpc('jaot.recipe', 'create', [[{ name: 'Dup', code: 'mrp', domain: 'mrp', company_id: 1 }]]));
});

case_('binding_validation', async (ctx) => {
  // the binding create/write guards (SPECS 5.4): expression/domain syntax,
  // source model, constant value, and a domain that is not a list.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const qtyRole = (await ctx.rpc('jaot.recipe.role', 'search', [[['recipe_id', '=', recipe.id], ['name', '=', 'order_qty']]]))[0];
  const capRole = (await ctx.rpc('jaot.recipe.role', 'search', [[['recipe_id', '=', recipe.id], ['name', '=', 'resource_capacity']]]))[0];
  await expectError(/source model/i,
    () => ctx.rpc('jaot.binding', 'create', [[{ recipe_id: recipe.id, role_id: qtyRole, company_id: 1 }]]));
  await expectError(/Invalid expression/i,
    () => ctx.rpc('jaot.binding', 'create', [[{ recipe_id: recipe.id, role_id: qtyRole, res_model: 'mrp.production', expression: 'qty *', company_id: 1 }]]));
  await expectError(/Invalid domain/i,
    () => ctx.rpc('jaot.binding', 'create', [[{ recipe_id: recipe.id, role_id: qtyRole, res_model: 'mrp.production', domain: '["broken"', company_id: 1 }]]));
  await expectError(/constant value/i,
    () => ctx.rpc('jaot.binding', 'create', [[{ recipe_id: recipe.id, role_id: capRole, company_id: 1 }]]));
  // A domain that evaluates to a non-list (e.g. the literal 5) passes no
  // useful interpretation and must be rejected at authoring time, not crash
  // the extraction later.
  let stray = null;
  try {
    stray = (await ctx.rpc('jaot.binding', 'create', [[{
      recipe_id: recipe.id, role_id: qtyRole, res_model: 'mrp.production',
      field_path: 'product_qty', domain: '5', company_id: 1,
    }]]))[0];
    throw new Error(`non-list domain "5" was accepted (binding ${stray}) — expected rejection`);
  } catch (e) {
    assert(/Invalid domain/i.test(e.message), `unexpected error for non-list domain: ${e.message}`);
  } finally {
    if (stray) await ctx.rpc('jaot.binding', 'unlink', [[stray]]).catch(() => {});
  }
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

case_('recipe_validate_invalid', async (ctx) => {
  // Bypass the ORM (direct SQL) to plant a syntactically invalid expression,
  // then the Validate button must catch it — it is the audit re-check, not
  // just a rubber stamp.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const binding = (await ctx.rpc('jaot.binding', 'search_read',
    [[['recipe_id', '=', recipe.id], ['role_id', '=', (await ctx.rpc('jaot.recipe.role', 'search', [[['recipe_id', '=', recipe.id], ['name', '=', 'order_qty']]]))[0]]], ['id']]))[0];
  assert(binding, 'order_qty binding not found');
  execSql(`UPDATE jaot_binding SET expression = '1 +' WHERE id = ${binding.id}`);
  try {
    await expectError(/Invalid expression/i,
      () => ctx.rpc('jaot.recipe', 'action_validate', [[recipe.id]]));
  } finally {
    execSql(`UPDATE jaot_binding SET expression = NULL WHERE id = ${binding.id}`);
  }
});

case_('scenario_create_via_ui', async (ctx) => {
  // the plain user flow: Scenarios > New > name + recipe > Save.
  await gotoAction(ctx.page, A.scenarios);
  assert(await ctx.page.locator('.o_list_view').count() > 0, 'scenario list did not render');
  await ctx.page.locator('button.o_list_button_add').first().click();
  await ctx.page.waitForSelector('.o_form_view', { timeout: 15000 });
  const name = `E2E UI ${Date.now()}`;
  await ctx.page.fill('.o_form_view div[name="name"] input', name);
  const recipeInput = ctx.page.locator('.o_form_view div[name="recipe_id"] input');
  await recipeInput.scrollIntoViewIfNeeded();
  await recipeInput.click();
  await recipeInput.fill('Production scheduling');
  // Odoo 19's many2one autocomplete renders items as
  // .o-autocomplete--dropdown-item (the legacy .o_dropdown_item is gone).
  const item = ctx.page.locator('.o-autocomplete--dropdown-item').first();
  await item.waitFor({ state: 'visible', timeout: 8000 });
  await item.click();
  await ctx.page.locator('.o_form_button_save').first().click();
  await ctx.page.waitForTimeout(1500);
  const rows = await ctx.rpc('jaot.scenario', 'search_read', [[['name', '=', name]], ['id', 'state', 'recipe_id']]);
  assert(rows.length === 1, `scenario not created via the UI: ${JSON.stringify(rows)}`);
  assert(rows[0].state === 'draft', `new UI scenario not draft: ${rows[0].state}`);
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
  assert(after.applied_by && after.applied_by[0] > 0, `applied_by not recorded: ${JSON.stringify(after.applied_by)}`);
  const log = await ctx.rpc('jaot.apply.log', 'search_read', [[['scenario_id', '=', sid]], ['res_model', 'res_id', 'field_path', 'before_value', 'after_value']], {}, { limit: 40 });
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
  // keep the solved scenario for the follow-up cases
  ctx.mrpSolvedId = sid;
});

case_('mrp_reapply_after_revert', async (ctx) => {
  // the full second round: Apply again on the reverted scenario, then
  // Revert again; and the jaot_scenario_id link on the MOs must follow the
  // scenario (set by Apply, restored by Revert) and be audit-logged.
  const sid = ctx.mrpSolvedId;
  assert(sid, 'no solved MRP scenario from the lifecycle case');
  const mos0 = await ctx.rpc('mrp.production', 'search_read',
    [[['name', 'like', 'E2E MO']], ['id', 'date_start', 'jaot_scenario_id']], {}, { limit: 20 });
  const prevLink = Object.fromEntries(mos0.map((m) => [m.id, m.jaot_scenario_id ? m.jaot_scenario_id[0] : null]));
  const before = Object.fromEntries(mos0.map((m) => [m.id, m.date_start]));

  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Apply');
  await confirmOk(ctx.page);
  const after = await readScenario(ctx.rpc, sid, ['state', 'applied']);
  assert(after.state === 'applied', `second Apply did not reach applied: ${after.state}`);
  const mosLink = await ctx.rpc('mrp.production', 'search_read',
    [[['name', 'like', 'E2E MO']], ['id', 'jaot_scenario_id']], {}, { limit: 20 });
  for (const m of mosLink) {
    const link = m.jaot_scenario_id ? m.jaot_scenario_id[0] : null;
    assert(link === sid, `MO ${m.id} jaot_scenario_id is ${link}, expected scenario ${sid} after Apply`);
  }
  const log = await ctx.rpc('jaot.apply.log', 'search_read',
    [[['scenario_id', '=', sid], ['state', '=', 'applied']], ['field_path']], {}, { limit: 40 });
  assert(log.some((l) => l.field_path === 'jaot_scenario_id'),
    'jaot_scenario_id link not audit-logged by Apply');

  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Revert');
  await confirmOk(ctx.page);
  const rev = await readScenario(ctx.rpc, sid, ['state', 'applied']);
  assert(rev.state === 'solved' && rev.applied === false, `second Revert failed: ${JSON.stringify(rev)}`);
  const mosFinal = await ctx.rpc('mrp.production', 'search_read',
    [[['name', 'like', 'E2E MO']], ['id', 'date_start', 'jaot_scenario_id']], {}, { limit: 20 });
  for (const m of mosFinal) {
    const link = m.jaot_scenario_id ? m.jaot_scenario_id[0] : null;
    assert(link === prevLink[m.id], `MO ${m.id} jaot_scenario_id not restored: ${link} != ${prevLink[m.id]}`);
    assert(m.date_start === before[m.id], `MO ${m.id} date not restored on second revert: ${m.date_start} != ${before[m.id]}`);
  }
});

case_('lifecycle_guards', async (ctx) => {
  // every state-machine guard: the actions refuse the wrong state with a
  // clear message instead of corrupting data.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const draft = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E GUARD ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
  const solved = ctx.mrpSolvedId;
  assert(solved, 'no solved scenario available');
  // the earlier lifecycle cases may leave the scenario applied; the
  // guards below need it in solved state.
  const st = (await readScenario(ctx.rpc, solved, ['state'])).state;
  if (st === 'applied') {
    await ctx.rpc('jaot.scenario', 'action_revert', [[solved]]);
  }
  assert((await readScenario(ctx.rpc, solved, ['state'])).state === 'solved',
    `scenario ${solved} is not in solved state for the guard checks`);
  await expectError(/Only draft scenarios can be submitted/i,
    () => ctx.rpc('jaot.scenario', 'action_submit', [[solved]]));
  await expectError(/Only queued or solving scenarios can be cancelled/i,
    () => ctx.rpc('jaot.scenario', 'action_cancel', [[solved]]));
  await expectError(/Only solved scenarios can be applied/i,
    () => ctx.rpc('jaot.scenario', 'action_apply', [[draft]]));
  await expectError(/Only applied scenarios can be reverted/i,
    () => ctx.rpc('jaot.scenario', 'action_revert', [[solved]]));
  await expectError(/Only a solved scenario can be baselined/i,
    () => ctx.rpc('jaot.scenario', 'action_compare_baseline', [[draft]]));
  await expectError(/Only a solved scenario can be analyzed/i,
    () => ctx.rpc('jaot.scenario', 'action_run_whatif', [[draft]]));
});

case_('staleness_negative', async (ctx) => {
  // untouched source data: Check staleness must report current, not stale.
  const sid = ctx.mrpSolvedId;
  assert(sid, 'no solved MRP scenario');
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Check staleness');
  const row = await readScenario(ctx.rpc, sid, ['data_stale']);
  assert(row.data_stale === false, `data_stale true on untouched data: ${JSON.stringify(row)}`);
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

case_('orphan_queued_timeout', async (ctx) => {
  // a scenario stuck in queued without a JAOT task id (submit crashed) must
  // be failed by the reconcile backstop, not poll forever.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E ORPHAN ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
  await ctx.rpc('jaot.scenario', 'write', [[sid], { state: 'queued' }]);
  // the backstop compares write_date < now() at second precision: give it a
  // full second so the orphan is unambiguously older than "now".
  await sleep(1500);
  await ctx.rpc('jaot.scenario', 'reconcile_jaot_scenarios', []);
  const row = await readScenario(ctx.rpc, sid, ['state', 'jaot_error']);
  assert(row.state === 'failed', `orphan not failed by the reconcile backstop: ${row.state}`);
  assert(/Timed out before a JAOT task/i.test(row.jaot_error || ''), `no timeout error recorded: ${row.jaot_error}`);
});

case_('apply_missing_record', async (ctx) => {
  // a source record deleted between Solve and Apply: the apply must skip it
  // and write the rest, not abort. The MO is restored afterwards.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'mrp']], ['id']]))[0];
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E DEL ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
  await ctx.rpc('jaot.scenario', 'action_submit', [[sid]]);
  const row = await pollTo(ctx.rpc, sid, 'state', ['solved', 'failed']);
  assert(row.state === 'solved', `scenario failed: ${row.jaot_error}`);
  const [mo] = await ctx.rpc('mrp.production', 'search_read', [[['name', '=', 'E2E MO 1']], ['id', 'product_qty']]);
  const product = (await ctx.rpc('product.product', 'search_read', [[['name', '=', 'E2E Widget']], ['id']]))[0];
  const wh = (await ctx.rpc('stock.warehouse', 'search_read', [[['code', '=', 'WH']], ['id']]))[0];
  try {
    await ctx.rpc('mrp.production', 'unlink', [[mo.id]]);
    await openForm(ctx.page, sid);
    await clickBtn(ctx.page, 'Apply');
    await confirmOk(ctx.page);
    const after = await readScenario(ctx.rpc, sid, ['state']);
    assert(after.state === 'applied', `apply with a deleted record did not reach applied: ${after.state}`);
    const log = await ctx.rpc('jaot.apply.log', 'search_read',
      [[['scenario_id', '=', sid]], ['res_id', 'field_path', 'after_value']], {}, { limit: 40 });
    assert(log.length > 0, 'no apply-log rows');
    assert(!log.some((l) => l.res_id === mo.id), 'log rows written for the deleted MO');
    const touched = new Set(log.filter((l) => l.field_path === 'date_start').map((l) => l.res_id));
    assert(touched.size === 3, `expected 3 surviving MOs written, got ${touched.size}`);
    for (const [id, d] of Object.entries(Object.fromEntries(
      (await ctx.rpc('mrp.production', 'search_read', [[['name', 'like', 'E2E MO']], ['id', 'date_start']], {}, { limit: 20 }))
      .map((m) => [m.id, m.date_start])))) {
      if (touched.has(Number(id))) {
        const l = log.find((x) => x.res_id === Number(id) && x.field_path === 'date_start');
        let applied; try { applied = JSON.parse(l.after_value); } catch { applied = l.after_value; }
        assert(d === applied, `MO ${id} missing the applied date: ${d} != ${applied}`);
      }
    }
    // revert so the surviving MOs carry their pre-apply dates again
    await openForm(ctx.page, sid);
    await clickBtn(ctx.page, 'Revert');
    await confirmOk(ctx.page);
    const rev = await readScenario(ctx.rpc, sid, ['state']);
    assert(rev.state === 'solved', `revert after missing-record apply failed: ${rev.state}`);
  } finally {
    // recreate E2E MO 1 with the seed's specs so later cases see 4 MOs again
    const newMo = (await ctx.rpc('mrp.production', 'create', [[{
      name: 'E2E MO 1', product_id: product.id, product_qty: mo.product_qty, warehouse_id: wh.id,
    }]]))[0];
    await ctx.rpc('mrp.production', 'action_confirm', [[newMo]]);
    const mid = (await ctx.rpc('mrp.production', 'read', [[newMo], ['move_finished_ids']]))[0].move_finished_ids[0];
    // Odoo 19: move_finished_ids is a One2many to stock.move.
    await ctx.rpc('stock.move', 'write', [[mid], { date_deadline: '2026-10-05' }]);
    await ctx.rpc('mrp.production', 'write', [[newMo], { date_start: '2026-10-05 06:00:00' }]);
  }
});

case_('vrp_lifecycle', async (ctx) => {
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'vrp']], ['id']]))[0];
  const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E VRP ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];

  // Plant a KNOWN suboptimal incumbent: split the four pickings across both
  // vehicles (alternating, position 1/2). The optimum serves everything with
  // a single tour (800 kg total < one vehicle's 1600 kg), so Apply is
  // guaranteed to change every picking and Revert is guaranteed to restore
  // exactly this split. Without this the incumbent would often already be
  // the optimum (from an earlier Apply) and "no picking changed" would be a
  // false pass.
  const vehicles = (await ctx.rpc('fleet.vehicle', 'search_read', [[['active', '=', true]], ['id']], {}, { order: 'id' }));
  const [va, vb] = [vehicles[0].id, vehicles[1].id];
  assert(va && vb, `expected two active vehicles, got ${JSON.stringify(vehicles)}`);
  const picks0 = await ctx.rpc('stock.picking', 'search_read', [[['picking_type_code', '=', 'outgoing'], ['state', 'in', ['confirmed', 'assigned']]], ['id']], {}, { limit: 20 });
  assert(picks0.length === 4, `expected 4 outgoing pickings, got ${picks0.length}`);
  for (let i = 0; i < picks0.length; i++) {
    await ctx.rpc('stock.picking', 'write', [[picks0[i].id], { jaot_vehicle_id: i % 2 ? vb : va, jaot_route_sequence: (i % 2) + 1, jaot_scenario_id: false }]);
  }
  const planted = await ctx.rpc('stock.picking', 'search_read', [[['id', 'in', picks0.map((p) => p.id)]], ['id', 'jaot_vehicle_id', 'jaot_route_sequence', 'jaot_scenario_id']], {}, { limit: 20 });
  const before = Object.fromEntries(planted.map((p) => [p.id, [p.jaot_vehicle_id, p.jaot_route_sequence, p.jaot_scenario_id ? p.jaot_scenario_id[0] : null]]));

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
  const picksAfter = await ctx.rpc('stock.picking', 'search_read', [[['picking_type_code', '=', 'outgoing'], ['state', 'in', ['confirmed', 'assigned']]], ['id', 'jaot_vehicle_id', 'jaot_route_sequence', 'jaot_scenario_id']], {}, { limit: 20 });
  const pickMap = Object.fromEntries(picksAfter.map((p) => [p.id, [p.jaot_vehicle_id, p.jaot_route_sequence]]));
  const changed = Object.keys(before).some((id) => JSON.stringify(before[id].slice(0, 2)) !== JSON.stringify(pickMap[id]));
  assert(changed, 'no picking changed after VRP Apply');
  for (const p of picksAfter) {
    const link = p.jaot_scenario_id ? p.jaot_scenario_id[0] : null;
    assert(link === sid, `picking ${p.id} jaot_scenario_id is ${link}, expected scenario ${sid} after Apply`);
  }

  // Revert (confirmation-gated): pickings restored.
  await openForm(ctx.page, sid);
  await clickBtn(ctx.page, 'Revert');
  await confirmOk(ctx.page);
  const rev = await readScenario(ctx.rpc, sid, ['state', 'applied']);
  assert(rev.state === 'solved', `VRP not reverted: ${rev.state}`);
  const picksRestored = await ctx.rpc('stock.picking', 'search_read', [[['picking_type_code', '=', 'outgoing'], ['state', 'in', ['confirmed', 'assigned']]], ['id', 'jaot_vehicle_id', 'jaot_route_sequence', 'jaot_scenario_id']], {}, { limit: 20 });
  for (const p of picksRestored) {
    const prev = before[p.id];
    const now = [p.jaot_vehicle_id, p.jaot_route_sequence, p.jaot_scenario_id ? p.jaot_scenario_id[0] : null];
    assert(JSON.stringify(now) === JSON.stringify(prev), `picking ${p.id} not restored: ${JSON.stringify(now)} != ${JSON.stringify(prev)}`);
  }
});

case_('vrp_baseline_whatif', async (ctx) => {
  // the VRP versions of Compare-with-baseline and What-if. The baseline is
  // only available in the solved state and pins the pickings' CURRENT plan,
  // so scenario A is applied first to give the pickings an incumbent tour;
  // scenario B is then solved and baselined against A's plan.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'vrp']], ['id']]))[0];
  const make = () => ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E VRP BW ${Date.now()} ${Math.floor(Math.random() * 1e6)}`, recipe_id: recipe.id, company_id: 1 }]]).then((r) => r[0]);
  const a = await make();
  await openForm(ctx.page, a);
  await clickBtn(ctx.page, 'Solve');
  const ra = await pollTo(ctx.rpc, a, 'state', ['solved', 'failed']);
  assert(ra.state === 'solved', `VRP A failed: ${ra.jaot_error}`);
  await openForm(ctx.page, a);
  await clickBtn(ctx.page, 'Apply');
  await confirmOk(ctx.page);
  const appliedA = await readScenario(ctx.rpc, a, ['state']);
  assert(appliedA.state === 'applied', `VRP A apply failed: ${appliedA.state}`);

  // scenario B, solved, then baselined against A's now-current plan.
  const b = await make();
  await openForm(ctx.page, b);
  await clickBtn(ctx.page, 'Solve');
  const rb = await pollTo(ctx.rpc, b, 'state', ['solved', 'failed']);
  assert(rb.state === 'solved', `VRP B failed: ${rb.jaot_error}`);
  await openForm(ctx.page, b);
  await clickBtn(ctx.page, 'Compare with baseline');
  const withBase = await readScenario(ctx.rpc, b, ['baseline_scenario_id']);
  const baseId = Array.isArray(withBase.baseline_scenario_id)
    ? withBase.baseline_scenario_id[0] : withBase.baseline_scenario_id;
  assert(baseId, 'baseline_scenario_id not set after Compare');
  const baseRow = await pollTo(ctx.rpc, baseId, 'state', ['solved', 'failed']);
  assert(baseRow.state === 'solved', `VRP baseline failed: ${baseRow.jaot_error}`);
  const kpi = (await readScenario(ctx.rpc, b, ['kpi_summary'])).kpi_summary;
  assert(kpi && typeof kpi.baseline_objective === 'number'
    && typeof kpi.optimized_objective === 'number'
    && typeof kpi.delta_vs_baseline === 'number',
    `VRP baseline delta not written: ${JSON.stringify(kpi)}`);

  // what-if on an APPLIED scenario (allowed state): rows stored.
  await openForm(ctx.page, b);
  await clickBtn(ctx.page, 'Apply');
  await confirmOk(ctx.page);
  const appliedB = await readScenario(ctx.rpc, b, ['state']);
  assert(appliedB.state === 'applied', `VRP B apply failed: ${appliedB.state}`);
  await openForm(ctx.page, b);
  await clickBtn(ctx.page, 'What-if analysis');
  const wf = await pollTo(ctx.rpc, b, 'whatif_state', ['done', 'failed']);
  assert(wf.whatif_state === 'done', `VRP what-if did not complete: ${wf.whatif_state}`);
  const wfLines = await ctx.rpc('jaot.scenario.whatif', 'search', [[['scenario_id', '=', b]]]);
  assert(wfLines.length > 0, 'no VRP what-if rows stored');

  // leave the picking data clean: revert B (restores A's plan), then A.
  await openForm(ctx.page, b);
  await clickBtn(ctx.page, 'Revert');
  await confirmOk(ctx.page);
  const revB = await readScenario(ctx.rpc, b, ['state']);
  assert(revB.state === 'solved', `VRP B revert failed: ${revB.state}`);
  await openForm(ctx.page, a);
  await clickBtn(ctx.page, 'Revert');
  await confirmOk(ctx.page);
  const revA = await readScenario(ctx.rpc, a, ['state']);
  assert(revA.state === 'solved', `VRP A revert failed: ${revA.state}`);
});

case_('vrp_infeasible', async (ctx) => {
  // vehicle capacity below a single picking's demand -> infeasible.
  const recipe = (await ctx.rpc('jaot.recipe', 'search_read', [[['code', '=', 'vrp']], ['id']]))[0];
  const capRole = (await ctx.rpc('jaot.recipe.role', 'search', [[['recipe_id', '=', recipe.id], ['name', '=', 'vehicle_capacity']]]))[0];
  const binding = (await ctx.rpc('jaot.binding', 'search_read', [[['recipe_id', '=', recipe.id], ['role_id', '=', capRole]], ['id', 'constant_value']]))[0];
  const origCap = binding.constant_value;
  try {
    // each E2E picking carries 200 kg; 150 kg per vehicle cannot serve any.
    await ctx.rpc('jaot.binding', 'write', [[binding.id], { constant_value: '150.0' }]);
    const sid = (await ctx.rpc('jaot.scenario', 'create', [[{ name: `E2E VRP INFEAS ${Date.now()}`, recipe_id: recipe.id, company_id: 1 }]]))[0];
    await ctx.rpc('jaot.scenario', 'action_submit', [[sid]]);
    const row = await pollTo(ctx.rpc, sid, 'state', ['solved', 'failed']);
    assert(row.state === 'failed', `expected infeasible/failed, got ${row.state}`);
    const infeas = await readScenario(ctx.rpc, sid, ['infeasibility', 'jaot_error']);
    assert(infeas.infeasibility || infeas.jaot_error, 'no infeasibility/error recorded for a failed VRP scenario');
  } finally {
    await ctx.rpc('jaot.binding', 'write', [[binding.id], { constant_value: origCap }]);
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

case_('security_viewer_write_denied', async (ctx) => {
  // the viewer is read-only end-to-end: no create, no apply, no key fields —
  // but the un-gated Test connection still works (it is read-only).
  const sid = ctx.mrpSolvedId;
  assert(sid, 'no solved scenario');
  const c1 = await findConfig(ctx.rpc, 1);
  const vctx = await ctx.browser.newContext();
  const vpage = await vctx.newPage();
  const vrpc = makeRpc(vpage);
  try {
    await login(vpage, VIEW);
    await expectError(/Access Error|not allowed|ACL|missing/i,
      () => vrpc('jaot.scenario', 'create', [[{ name: 'E2E VIEW CREATE', recipe_id: 1, company_id: 1 }]]));
    await expectError(/Access Error|not allowed|ACL|missing/i,
      () => vrpc('jaot.scenario', 'action_apply', [[sid]]));
    // read access to the audit trail is allowed
    const log = await vrpc('jaot.apply.log', 'search_read', [[['state', '=', 'reverted']], ['id']], {}, { limit: 10 });
    assert(Array.isArray(log), 'viewer could not even query the apply log');
    // the key input field and the Remove key button are manager-only
    await openRecord(vpage, A.config, c1.id);
    assert(await vpage.locator('.o_form_view div[name="api_key_input"]').count() === 0,
      'viewer sees the api_key_input field');
    assert(await vpage.getByRole('button', { name: 'Remove key' }).count() === 0,
      'viewer sees the Remove key button');
    // Test connection is not gated: it must still succeed for the viewer
    const test = await vrpc('jaot.config', 'action_test_connection', [[c1.id]]);
    assert(test?.params?.params?.type === 'success', `viewer test connection failed: ${JSON.stringify(test)}`);
  } finally {
    await vctx.close();
  }
});

case_('security_manager_expr_hidden', async (ctx) => {
  // the manager (not a system admin) must NOT see group_system-only data:
  // the expression column and the JAOT identifiers block.
  await gotoAction(ctx.page, A.bindings);
  const headers = await ctx.page.locator('.o_list_view thead th, .o_list_table thead th').allInnerTexts();
  assert(!headers.some((h) => /expression/i.test(h)),
    `manager sees the expression column: ${JSON.stringify(headers)}`);
  const sid = ctx.mrpSolvedId;
  assert(sid, 'no solved scenario');
  await openForm(ctx.page, sid);
  const formText = await ctx.page.locator('.o_form_view').innerText();
  // the group header renders upper-cased by CSS, so match case-insensitively
  assert(!/JAOT identifiers/i.test(formText), 'manager sees the group_system JAOT identifiers block');
});

case_('security_admin_sees_expression', async (ctx) => {
  // positive control: the system admin sees exactly what the manager does
  // not — the expression column and the group_system-only blocks.
  const actx = await ctx.browser.newContext();
  const apage = await actx.newPage();
  try {
    await login(apage, ADMIN);
    await gotoAction(apage, A.bindings);
    const headers = await apage.locator('.o_list_view thead th, .o_list_table thead th').allInnerTexts();
    assert(headers.some((h) => /expression/i.test(h)),
      `admin does not see the expression column: ${JSON.stringify(headers)}`);
    const sid = ctx.mrpSolvedId;
    assert(sid, 'no solved scenario');
    await openForm(apage, sid);
    const formText = await apage.locator('.o_form_view').innerText();
    assert(/JAOT identifiers/i.test(formText), 'admin does not see the JAOT identifiers block');
  } finally {
    await actx.close();
  }
});

case_('scenario_list_view', async (ctx) => {
  // the scenario list renders the accumulated rows with their states.
  await gotoAction(ctx.page, A.scenarios);
  const rows = await ctx.page.locator('.o_list_view tbody tr').count();
  assert(rows > 0, 'scenario list rendered no rows');
  const text = await ctx.page.locator('.o_list_view').innerText();
  assert(/E2E MRP/.test(text), 'scenario list does not show the MRP lifecycle scenario');
  assert(/Solved|Applied|Failed|Cancelled/.test(text), 'scenario list shows no states');
});

case_('chatter_audit', async (ctx) => {
  // the audit trail: the scenario chatter carries the lifecycle events and
  // the config chatter carries the key storage/removal events.
  const sid = ctx.mrpSolvedId;
  assert(sid, 'no solved scenario');
  const msgs = await ctx.rpc('mail.message', 'search_read',
    [[['model', '=', 'jaot.scenario'], ['res_id', '=', sid]], ['body']]);
  const bodies = msgs.map((m) => m.body || '').join(' ');
  assert(/Submitted to JAOT/i.test(bodies), 'scenario chatter missing the submission event');
  assert(/Solved:/i.test(bodies), 'scenario chatter missing the solved event');
  assert(/Applied \d+ line/i.test(bodies), 'scenario chatter missing the apply event');
  assert(/Reverted \d+ change/i.test(bodies), 'scenario chatter missing the revert event');
  const c1 = await findConfig(ctx.rpc, 1);
  const cmsgs = await ctx.rpc('mail.message', 'search_read',
    [[['model', '=', 'jaot.config'], ['res_id', '=', c1.id]], ['body']]);
  const cbodies = cmsgs.map((m) => m.body || '').join(' ');
  assert(/API key stored\./.test(cbodies), 'config chatter missing "API key stored."');
  assert(/API key removed\./.test(cbodies), 'config chatter missing "API key removed."');
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
