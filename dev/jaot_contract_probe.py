#!/usr/bin/env python3
"""JAOT contract probe — PLAN P1.3.

Verifies the SPECS §6 integration contract end-to-end against a LIVE JAOT
instance with real calls, and prints the exact response field names (frozen
in docs/research/C-jaot-contract.md, later pinned by the CI contract smoke
test, SPECS §6.4).

Stdlib only. Configuration via environment:
  JAOT_API_KEY   required — Bearer key from POST /api/v2/keys/ (never in the repo)
  JAOT_BASE      optional — default http://127.0.0.1:8001

Run:  python dev/jaot_contract_probe.py
Exit 0 = every contract step verified.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("JAOT_BASE", "http://127.0.0.1:8001").rstrip("/")
API = BASE + "/api/v2"
KEY = os.environ.get("JAOT_API_KEY", "")

RESULTS = []


def req(method, path, body=None, timeout=60):
    """One authenticated call -> (status, json). Raises on HTTP error."""
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {}), time.time() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), time.time() - t0
        except Exception:
            raise RuntimeError(
                f"{method} {path} -> HTTP {e.code}: {raw[:300]!r}") from e


def step(name, fn):
    """Run one contract step; record PASS/FAIL; keep going on failure."""
    try:
        fn()
        RESULTS.append((name, "PASS", ""))
        print(f"[PASS] {name}")
    except Exception as e:  # noqa: BLE001 - probe records, does not abort
        RESULTS.append((name, "FAIL", str(e)[:200]))
        print(f"[FAIL] {name}: {str(e)[:200]}")


def deep_keys(obj, prefix="", out=None, depth=4):
    """Observed key paths of a JSON response (evidence for the freeze)."""
    if out is None:
        out = []
    if isinstance(obj, dict) and depth > 0:
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            out.append(p)
            deep_keys(v, p, out, depth - 1)
    elif isinstance(obj, list) and obj and depth > 0:
        deep_keys(obj[0], prefix + "[]", out, depth - 1)
    return out


def show(label, obj, depth=4):
    txt = json.dumps(obj, indent=1, default=str)
    print(f"--- {label} ---")
    print(txt[:2500] + ("  ... [truncated]" if len(txt) > 2500 else ""))


# ---------------------------------------------------------------- toym problems
# 1) feasible mini-assignment (gives exact-analysis something binding):
#    min 2*x1 + 3*x2 + 5*x3  s.t.  x1+x2+x3 >= 2   (coverage)
#                                      x1+x3   <= 1   (conflict)
#    optimum: x1=x2=1, x3=0, objective 5; coverage binding, conflict slack.
TOY_FEASIBLE = {
    "name": "jaom_p13_toy_feasible",
    "description": "P1.3 contract probe — feasible toy (2/3 cover, conflict)",
    "variables": [
        {"name": "x1", "type": "binary", "lower_bound": 0, "upper_bound": 1},
        {"name": "x2", "type": "binary", "lower_bound": 0, "upper_bound": 1},
        {"name": "x3", "type": "binary", "lower_bound": 0, "upper_bound": 1},
    ],
    "objective": {"sense": "minimize", "expression": "2*x1 + 3*x2 + 5*x3"},
    "constraints": [
        {"name": "coverage", "expression": "x1 + x2 + x3 >= 2"},
        {"name": "conflict", "expression": "x1 + x3 <= 1"},
    ],
    "options": {"time_limit_seconds": 60, "gap_tolerance": 0.01},
}

# 2) infeasible twin (IIS check): max sum of two binaries is 2 < 3.
TOY_INFEASIBLE = {
    "name": "jaom_p13_toy_infeasible",
    "description": "P1.3 contract probe — infeasible toy (IIS check)",
    "variables": [
        {"name": "x1", "type": "binary", "lower_bound": 0, "upper_bound": 1},
        {"name": "x2", "type": "binary", "lower_bound": 0, "upper_bound": 1},
    ],
    "objective": {"sense": "minimize", "expression": "x1 + x2"},
    "constraints": [
        {"name": "impossible", "expression": "x1 + x2 >= 3"},
    ],
    "options": {"time_limit_seconds": 60, "gap_tolerance": 0.01},
}

TERMINAL = {"completed", "failed", "infeasible", "cancelled", "error"}


def poll_task(task_id, cap_seconds=240, interval=3):
    """Poll GET /solve/async/{task_id} until terminal; return final payload."""
    t0 = time.time()
    while time.time() - t0 < cap_seconds:
        status, payload, _ = req("GET", f"/solve/async/{task_id}")
        if status != 200:
            raise RuntimeError(f"poll {task_id} -> HTTP {status}: {payload}")
        st = payload.get("status")
        if st in TERMINAL:
            return payload
        time.sleep(interval)
    raise TimeoutError(f"task {task_id} not terminal in {cap_seconds}s")


def main():
    if not KEY:
        sys.exit("JAOT_API_KEY env var is required (POST /api/v2/keys/)")
    state = {}

    # -- 1. health/status -------------------------------------------------
    def s_health():
        status, body, dt = req("GET", "/health/status")
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body}")
        state["version"] = body.get("version")
        show("GET /health/status", body, 3)
        print(f"   version={body.get('version')} "
              f"checks={body.get('checks_passed')}/{body.get('checks_total')} "
              f"({dt*1000:.0f} ms)")

    # -- 2. solvers/available ----------------------------------------------
    def s_solvers():
        status, body, dt = req("GET", "/solvers/available")
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body}")
        solvers = body.get("solvers", [])
        if not solvers:
            raise RuntimeError("no solvers reported")
        state["solver"] = next(
            (s["name"] for s in solvers if s.get("available")), None)
        for s in solvers:
            print(f"   solver {s['name']}: available={s['available']} "
                  f"v={s.get('version')}")
        print(f"   ({dt*1000:.0f} ms)")

    # -- 3. templates list ---------------------------------------------------
    def s_templates():
        tpls, page, total = [], 1, None
        while total is None or len(tpls) < total:
            status, body, dt = req(
                "GET", f"/solve/templates?page_size=100&page={page}")
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {body}")
            tpls += body.get("templates", [])
            total = body.get("total")
            page += 1
            if len(body.get("templates", [])) == 0:
                break
        state["templates"] = tpls
        print(f"   total={total} fetched={len(tpls)} ({dt*1000:.0f} ms)")
        candidates = []
        for t in tpls:
            hay = (t.get("name", "") + " " +
                   " ".join(t.get("tags", []))).lower()
            is_routing = (t.get("generator_type") == "routing"
                          or any(k in hay for k in ("vrp", "cvrp")))
            mark = ""
            if is_routing:
                candidates.append(t)
                mark = "  <-- routing candidate"
            if is_routing or t.get("category") == "routing":
                print(f"   {t['id']}: {t['name']} [{t['category']}] "
                      f"gen={t.get('generator_type')}{mark}")
        if not candidates:
            raise RuntimeError("no routing template found in catalog")
        state["routing_template"] = candidates[0]["id"]
        print(f"   previewing: {state['routing_template']}")

    # -- 4. routing template preview (POST with user input; live 3.9.0) ------
    def s_preview():
        tid = state["routing_template"]
        status, body, dt = req("POST", f"/solve/templates/{tid}/preview", {})
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body}")
        print(f"   template {tid} preview ({dt*1000:.0f} ms)")
        show(f"POST /solve/templates/{tid}/preview", body, 4)

    # -- 5. async solve (feasible) ------------------------------------------
    def s_solve():
        status, body, dt = req("POST", "/solve/async", TOY_FEASIBLE)
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body}")
        for f in ("task_id", "execution_id", "status", "message",
                  "ws_url", "poll_url"):
            if f not in body:
                raise RuntimeError(f"envelope missing field: {f}")
        state["task"], state["exec"] = body["task_id"], body["execution_id"]
        print(f"   envelope: task={body['task_id'][:12]}… "
              f"exec={body['execution_id'][:12]}… status={body['status']} "
              f"({dt*1000:.0f} ms)")

    # -- 6. poll to terminal ---------------------------------------------------
    def s_poll():
        payload = poll_task(state["task"])
        state["poll"] = payload
        show("GET /solve/async/{task_id} (terminal)", payload, 4)

    # -- 7. execution detail ---------------------------------------------------
    def s_exec():
        status, body, dt = req("GET", f"/models/executions/{state['exec']}")
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body}")
        state["exec_body"] = body
        print(f"   status={body.get('status')} "
              f"solver={body.get('solver_name')} "
              f"objective={body.get('objective_value')} "
              f"time_ms={body.get('execution_time_ms')} ({dt*1000:.0f} ms)")
        show("GET /models/executions/{id} (deep keys)", body, 4)

    # -- 8. exact-analysis -------------------------------------------------------
    def s_exact():
        status, body, dt = req(
            "GET", f"/models/executions/{state['exec']}/exact-analysis")
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body}")
        state["exact"] = body
        print(f"   binding_count={body.get('binding_count')} "
              f"of {body.get('total_constraints')} ({dt*1000:.0f} ms)")
        for c in body.get("constraints", []):
            print(f"   {c['name']}: activity={c['activity']} "
                  f"rhs={c['rhs']} slack={c['slack']} "
                  f"binding={c['is_binding']}")
        show("GET …/exact-analysis (deep keys)", body, 3)

    # -- 9. scenario-analysis (no body; auto what-if batch) ---------------------
    def s_scenario():
        status, body, dt = req(
            "POST", f"/models/executions/{state['exec']}/scenario-analysis")
        if status not in (200, 202):
            raise RuntimeError(f"HTTP {status}: {body}")
        print(f"   job status={body.get('status')} ({dt*1000:.0f} ms)")
        t0 = time.time()
        while body.get("status") == "running" and time.time() - t0 < 300:
            time.sleep(3)
            status, body, _ = req(
                "GET", f"/models/executions/{state['exec']}/scenario-analysis")
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {body}")
        if body.get("status") != "completed":
            raise RuntimeError(f"scenario batch did not complete: {body}")
        state["scenario"] = body
        a = body.get("analysis", {})
        print(f"   batch: {a.get('resolves_used')}/{a.get('resolves_planned')} "
              f"resolves, base_objective={a.get('base_objective')}, "
              f"partial={a.get('partial')}")
        for k in ("rhs_scenarios", "decision_scenarios"):
            for row in a.get(k, [])[:3]:
                print(f"   {k}: {json.dumps(row, default=str)[:200]}")
        show("GET …/scenario-analysis (deep keys)", body, 4)

    # -- 10. infeasibility-analysis ---------------------------------------------
    def s_infeasible():
        status, body, dt = req("POST", "/solve/async", TOY_INFEASIBLE)
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body}")
        payload = poll_task(body["task_id"])
        ex = body["execution_id"]
        print(f"   infeasible toy terminal: status={payload.get('status')} "
              f"error={str(payload.get('error'))[:120]} "
              f"({dt*1000:.0f} ms enqueue)")
        st2, body2, dt2 = req(
            "POST", f"/solve/{ex}/infeasibility-analysis")
        if st2 != 200:
            raise RuntimeError(f"HTTP {st2}: {body2}")
        state["iis"] = body2
        print(f"   iis_constraints={body2.get('iis_constraints')} "
              f"conflict_type={body2.get('conflict_type')} "
              f"method={body2.get('method')} ({dt2*1000:.0f} ms)")
        show("POST /solve/{id}/infeasibility-analysis", body2, 3)

    step("1 health/status", s_health)
    step("2 solvers/available", s_solvers)
    step("3 solve/templates (routing catalog)", s_templates)
    step("4 routing template preview", s_preview)
    step("5 solve/async (envelope)", s_solve)
    step("6 solve/async/{task} poll -> terminal", s_poll)
    step("7 models/executions/{id} (solution)", s_exec)
    step("8 executions/{id}/exact-analysis", s_exact)
    step("9 executions/{id}/scenario-analysis (what-if batch)", s_scenario)
    step("10 solve/{id}/infeasibility-analysis (IIS)", s_infeasible)

    # -- summary -------------------------------------------------------------
    print("\n=== FROZEN FIELD NAMES (observed keys) ===")
    for label in ("exec_body", "exact", "scenario"):
        if label in state:
            keys = sorted(set(deep_keys(state[label])))
            print(f"\n[{label}] {len(keys)} keys:\n  "
                  + "\n  ".join(keys[:80]))
    if "iis" in state:
        keys = sorted(set(deep_keys(state["iis"])))
        print(f"\n[iis] {len(keys)} keys:\n  " + "\n  ".join(keys))

    fails = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} steps passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
