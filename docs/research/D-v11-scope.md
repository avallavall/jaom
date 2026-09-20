# D — v1.1 scope research (2026-09-20)

Selection basis for SPECS §13 / PLAN Phase 9. Two research tracks ran on
2026-09-20 (a full academic pass by a research agent; a focused market pass
in-session). Only sources actually fetched are cited; unverified items are
marked.

## 1. Market

| Source | Verified finding |
|---|---|
| Locus (locus.sh) | Enterprise "agentic TMS": 360+ clients, 30+ countries, backed by Ingka Group (IKEA). **Price not public.** Enterprise tier is crowded and well-funded — not this product's segment. |
| Routific (routific.com) | SME route optimization, usage-based: free to 100 orders/month; $150/mo for 101–1,000; then $0.15 → $0.03 per extra order (tiers to 50 k); unlimited drivers/dispatchers. The SME routing price anchor. |
| Odoo App Store — "delivery optimization" | No credible incumbent: the closest app (€30.73) has 2 downloads; the rest are €7–145 report/checkbox modules. |
| Odoo App Store — "production planning" | No credible incumbent: €38–155 one-time apps with 1–3 downloads (e.g. "MPS Forecast Demand" €154.96). |
| Odoo App Store — "forecast" | Demand exists, no strong player: €175–749 one-time, single-digit to low-double downloads ("Advance Reordering" €749 / 10 downloads; "Odoo AI Assistant" €228 / 9). |
| OptiMyte, oRACLe | **Unverified** — DNS failures at fetch time; excluded from the decision. |
| Kinaxis (via research agent) | Vendor marketing treats "assess the impact of many planning scenarios" as table stakes — scenario comparison is expected, not a differentiator; the differentiator is running it on a real optimizer. |

**Read:** don't fight the enterprise tier head-on; the SME tier is
price-anchored around ~$150/mo usage-based; the Odoo ecosystem itself is
empty of real optimization — every "optimization" app is a small report
module. The differentiator is the spec's core claim: a real solver living
inside Odoo, native records, no ETL, per-company, apply/revert onto real
orders.

## 2. Academic (verified sources, 2020–2026 where noted)

- **Forecasting for MRP:** Croston (1972, OR Quarterly 23(3):289–304, verified
  via ar5iv full text of arXiv:1307.6102); SBA/SY defined in the same
  prestwich paper (arXiv:1307.6102); ETS canonical treatment: Hyndman &
  Athanasopoulos, *Forecasting: Principles and Practice* 3rd ed., ch. 8
  (otexts.com/fpp3); forecast accuracy ≠ inventory performance — use
  cost-oriented error metrics (arXiv:2004.10537); probabilistic forecasts
  bridging accuracy and inventory utility (arXiv:2304.03092). **Cheap to
  build credibly:** ETS + Croston/SBA with ADI/ABC routing + safety-stock
  quantiles. Deep probabilistic/ML models: do not ship.
- **Planning method vs buffers:** scenario-based stochastic programming in a
  rolling horizon vs MRP: optimization consistently outperforms MRP,
  stochastic optimization cut cost up to 68% in congested shops, and
  explicit safety stocks change which method wins (arXiv:2402.14506).
  (Marketing number — cite carefully in docs.)
- **Lot-sizing:** exact MIP with warm starts is the defensible mid-market
  default; heuristics only at scale (arXiv:2112.03965, arXiv:1610.02056);
  multi-plant NP-hard even in restricted cases (arXiv:2003.04438);
  robust/fuzzy demand in lot-sizing (arXiv:1210.5386); robustification via
  budgeted uncertainty sized from data (arXiv:1401.0212, arXiv:1408.4445).
- **VRP:** cost objective separate from the time dimension (OR-Tools routing
  guide, developers.google.com/optimization/routing); PDPTW: MIP practical
  to ~12 request pairs, heuristic beyond (arXiv:2511.07681); dynamic
  re-optimization / re-routing after disruptions (arXiv:1908.07827,
  arXiv:2304.00789); driver-shift full-truckload routing (arXiv:2012.06538).
- **Explainable optimization:** practical toolbox = objective decomposition
  + binding-constraint/slack reports + LP-relaxation ranging (HiGHS exposes
  cost/bound/RHS/basic-solution ranging natively — ERGO-Code/HiGHS README) +
  IIS; contrastive "why not" explanations from IIS (arXiv:2507.13007);
  explainable optimization is now an explicit research area
  (arXiv:2606.08675).
- **What-if / scenario simulation in ERP:** planners simulate demand
  volatility + shop-floor friction under rolling horizons with buffer
  policies (arXiv:2402.14506); discrete-event what-if simulation is now
  commodity open tooling (SupplyNetPy, arXiv:2607.09745); digital-twin
  framing (arXiv:2103.12854).
- **ML+OR hybrids (pilot-grade only):** prediction-then-optimization
  (arXiv:1710.08005, PyEPO arXiv:2206.14234); interpretable SPOTs
  (arXiv:2003.00360); GNN-aided fix-and-optimize for lot sizing
  (arXiv:2605.27339); a GBM surrogate trained on own solve history is the
  only small-team-shipable variant (pilot, not v1.1).

## 3. Selection

- **P9.1 explanation** — highest-ROI trust feature; pure post-processing +
  existing exact-analysis/IIS.
- **P9.2 named scenarios** — productizes the what-if on real solves; vendor
  table stakes + our differentiator.
- **P9.3 es translation** — day-one promise (§10.5) still open; near-zero
  cost; unblocks the Spanish-speaking market.
- **P9.4 intraday re-optimization** — concrete daily pain; reuses baseline
  fix-all + staleness machinery.
- **P9.5 forecast + safety stock** — credible cheap statistics (no solver);
  fills the forecast/MPS demand visible in the app store; feeds the MRP
  bridge through the standard role machinery.
- **Deferred (v2 / demand-gated):** multi-machine lot-sizing, cost-objective
  routing with driver shifts, PDPTW, sequence-dependent setups, ML
  surrogates (pilot), `jaot_hr`/`jaot_purchase`/`jaot_account` (ordered by
  customer demand), LLM opportunity scan (D4), `jaot_local_solver` (gated on
  Q3), webhook triggers, payload archival, evaluate-only adoption (JAOT
  issue avallavall/jaot#3), WebSocket progress.
