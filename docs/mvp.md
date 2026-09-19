# MVP acceptance runbook (PLAN P3.8)

This is the runbook for the **P3.8 MVP gate**: the SPECS §11.1 acceptance flow
run on a fresh Odoo 19 + JAOT. It is a *runbook* for the maintainer to execute
and fill with screenshots. A run is only "done" when the maintainer has
performed it end to end and recorded the screenshots below. Nothing here is a
claim that the gate has passed.

**What it covers today (P3.1–P3.7):** the core routing flow on a real
stock/fleet dataset. The **baseline comparison** ("diff vs baseline") in
SPECS §11.1 step 1 is a **Phase 4** feature (P4.1/P4.2), so this run shows the
routing decision lines, not a baseline delta yet. See the open question at the
bottom before treating §11.1 as fully satisfied.

## Prerequisites

- Fresh Odoo 19 Community database with `stock`, `fleet`, `jaot_base` and
  `jaot_stock` installed (`jaot_stock` auto-installs when `stock`+`fleet` are
  present).
- A reachable JAOT instance (pinned v3.x) and an API key.
- The dev setup (`dev/docker-compose.yml` + `dev/.env`) or an equivalent.

## Setup (one time)

1. **Configure JAOT.** *JAOT → Configuration → JAOT connection* (per company):
   set the endpoint URL and the API key. Save. (The key is stored masked.)
   Screenshot: the connection form + a successful connection test.
2. **Confirm the recipe.** The install created the `vrp` recipe with its
   default bindings for this company. *JAOT → Configuration → Recipes*: open
   it. The bindings read the depot geo from `stock.warehouse`, order geo +
   weight from outgoing `stock.picking`, the fleet from `fleet.vehicle`, and a
   constant capacity parameter. Screenshot: the recipe + its roles + bindings.

## The acceptance flow (SPECS §11.1, core)

3. **Seed a route.** Create a few confirmed/assigned **outgoing** pickings
   (each with a destination partner that has coordinates and a shipping
   weight), make sure the warehouse contact has coordinates, and create at
   least one active `fleet.vehicle`. Screenshot: the pickings.
4. **Open a scenario.** *Inventory → Operations → Routing scenarios* (or the
   JAOT app) → create a scenario on the `vrp` recipe. Screenshot: the
   scenario list with states.
5. **Solve.** Press **Submit**; the scenario goes to `queued`. Let the
   reconciliation cron (or a manual reconcile) run; it goes to `solved`.
   Screenshot: the scenario `solved`, with the solver status and objective.
6. **Review the decision.** The scenario's line view shows one line per
   picking with the assigned vehicle and route position. Screenshot: the line
   view (this is the "diff view" that is the product).
7. **Apply.** Press **Apply** (manager only, with confirmation). Each picking
   is written with its vehicle and route position. Screenshot: a picking form
   showing the JAOT routing fields.
8. **Audit.** *JAOT → apply log*: one row per written field, before/after.
   Screenshot: the apply log.
9. **Revert.** Press **Revert**. The picking fields return to their
   before-state. Screenshot: the picking restored + the reverted log rows.

## Optional (SPECS §11.1 step 2)

10. **Re-binding, no code.** Remap one binding to a custom/OCA source for this
    company (e.g. a different geo or weight field) and re-solve. No code
    changes; the scenario picks up the new data. Screenshot: the edited
    binding + the re-solved scenario.

## Open question for the maintainer

SPECS §11.1 step 1 says "the scenario shows the **diff vs baseline**," but
baseline capture is implemented in Phase 4 (P4.1/P4.2). Two readings:

- (a) The P3.8 MVP gate covers the core flow above (solve → decision lines →
  apply → audit → revert), and the baseline delta is verified when Phase 4
  lands.
- (b) The MVP gate requires the baseline delta, so Phase 4 must precede it.

Please confirm which reading stands so the gate scope is fixed. Until then the
gate is treated as the **core flow** (reading a).
