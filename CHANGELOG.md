# Changelog

All user-facing changes, newest first. One to three lines per entry.

## Unreleased

- Fix: the scenario actions (Solve, Apply, Revert, baseline, what-if,
  staleness check) are now access-checked at the API level, so a
  read-only user cannot trigger them — before, the denial depended on a
  downstream write failing.
- Fix: the plain-language presentation never leaks a referenced record's
  database id — a viewer without access to that record (e.g. the delivery
  vehicle) or a deleted one now sees a safe generic label instead of a raw
  id.
- Scenarios now read like a plan, not data: each line names the record and
  its decision in plain language (e.g. "Van 1 · stop 3", "Start 2026-10-05"),
  previews the exact before → after change before you apply, and a result
  banner states the improvement in your currency (or kilometres) versus your
  current plan.
- Fix: a what-if analysis that comes back in a malformed shape no longer
  wedges the scenario stuck in "requested" (re-polled and re-crashed on
  every cron run) — the bad rows are skipped and the analysis reaches a
  terminal state instead.
- Fix: applying a scenario whose decision writes through a dotted field
  path no longer silently drops the write (and logs it as if it
  succeeded) when an intermediate record is missing — it now fails with
  a clear error and rolls the whole apply back.
- Fix: saving a recipe binding now rejects a parameter constant that is
  not a number (a clear error at save time), instead of letting it through
  and crashing later when a scenario is submitted.
- Fix: applying and reverting a scenario are now all-or-nothing. A write
  failure part-way rolls back the whole operation (no partial plan left
  behind), and applying when none of the plan's target records still exist
  does not mark the scenario applied.
- Fix: the background reconcile job that polls submitted scenarios now
  actually fires — it was silently erroring on every run, so a queued
  solve only got picked up when reconciled by hand.
- Solved scenarios now carry a manager-readable explanation (new form
  section): the objective decomposed into named terms, the tight
  constraints in plain language; infeasible solves get a plain-language
  summary of the conflicting requirements.
- Fix: the JAOT connection form now works for a manager without
  system-admin rights — saving, testing, and clearing the API key,
  recipe validation, and scenario solving no longer fail on the
  manager role.
- Apply and Revert now ask for confirmation before writing or
  restoring records.
- Fix: applying a scenario now stamps the affected records with the
  scenario that produced them (the link follows reverts and
  re-applies), and the link write is part of the apply audit trail.
- Fix: a binding domain that parses but is not a list of conditions
  is now rejected when the binding is authored, instead of crashing
  the data extraction.

## 1.0.0 (2026-09-20)

First public release.

- Delivery routing: solve a vehicle-routing scenario over your confirmed
  outgoing pickings, compare it against your current plan, explore
  what-ifs, and apply (or revert) the optimized vehicle assignments —
  every write audited.
- Production scheduling: schedule confirmed production orders with
  deadlines under a daily capacity, trading setup cost against
  inventory holding cost, and apply the start dates back to the orders.
- Per-company JAOT connection with a masked API key, a connection test,
  and an idempotent polling job; infeasible datasets surface the solver's
  infeasibility analysis instead of failing silently.
