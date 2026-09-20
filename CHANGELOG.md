# Changelog

All user-facing changes, newest first. One to three lines per entry.

## Unreleased

- Fix: the JAOT connection form now works for a manager without
  system-admin rights — saving, testing, and clearing the API key,
  recipe validation, and scenario solving no longer fail on the
  manager role.
- Apply and Revert now ask for confirmation before writing or
  restoring records.

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
