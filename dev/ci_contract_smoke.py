#!/usr/bin/env python3
"""CI contract smoke test — SPECS §6.4, PLAN P5.6.

One async solve -> poll -> execution -> exact-analysis round-trip on a toy
problem, run against the pinned JAOT image, pinning the frozen response field
names (docs/research/C-jaot-contract.md §4). Stdlib only, so it runs in CI
without a venv. A failure here is a release-blocking API-drift event
(SPECS §6.4), not a silent workaround.

Configuration via environment:
  JAOT_API_KEY   required — Bearer key (POST /api/v2/keys/), never in the repo
  JAOT_BASE      optional — default http://127.0.0.1:8001

Run:  python dev/ci_contract_smoke.py
Exit 0 = round-trip succeeded and every pinned field is present.
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
TERMINAL = {"completed", "failed", "infeasible", "cancelled", "error"}

# toy feasible MIP (same shape as the P1.3 probe): optimum 5.0 at
# x1=x2=1, x3=0; coverage binding, conflict at its limit.
TOY = {
    "name": "jaom_ci_smoke_toy",
    "description": "SPECS 6.4 CI smoke — feasible toy (coverage + conflict)",
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

FAILURES = []


def req(method, path, body=None, timeout=60):
    """One authenticated call -> (status, json). Raises on HTTP error."""
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            raise RuntimeError(
                f"{method} {path} -> HTTP {e.code}: {raw[:300]!r}") from e


def has(obj, dotted):
    """True if the dotted path exists on obj (dict descent)."""
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return False
        obj = obj[part]
    return True


def pin(label, obj, fields):
    """Record PASS/FAIL for each pinned field name (contract governance)."""
    for f in fields:
        if has(obj, f):
            print(f"[OK]   {label} {f}")
        else:
            FAILURES.append(f"{label}: missing pinned field {f}")
            print(f"[MISS] {label} {f}")


def poll_task(task_id, cap_seconds=240, interval=3):
    t0 = time.time()
    while time.time() - t0 < cap_seconds:
        status, payload = req("GET", f"/solve/async/{task_id}")
        if status != 200:
            raise RuntimeError(f"poll {task_id} -> HTTP {status}: {payload}")
        if payload.get("status") in TERMINAL:
            return payload
        time.sleep(interval)
    raise TimeoutError(f"task {task_id} not terminal in {cap_seconds}s")


def main():
    if not KEY:
        sys.exit("JAOT_API_KEY env var is required (POST /api/v2/keys/)")
    state = {}

    # 1. health (auth + pinned version) -------------------------------
    status, body = req("GET", "/health/status")
    if status != 200:
        sys.exit(f"health/status -> HTTP {status}: {body}")
    state["version"] = body.get("version")
    print(f"health: status={body.get('status')} version={state['version']}")
    pin("DetailedStatusResponse", body, ["status", "version"])

    # 2. async solve envelope ----------------------------------------
    status, body = req("POST", "/solve/async", TOY)
    if status != 200:
        sys.exit(f"solve/async -> HTTP {status}: {body}")
    state["task"], state["exec"] = body["task_id"], body["execution_id"]
    print(f"solve/async: task={body['task_id'][:12]}… exec={body['execution_id'][:12]}… "
          f"status={body.get('status')}")
    pin("AsyncSolveEnvelope", body,
        ["task_id", "execution_id", "status", "message", "ws_url", "poll_url"])

    # 3. poll to terminal ---------------------------------------------
    poll = poll_task(state["task"])
    print(f"poll terminal: status={poll.get('status')} "
          f"result.status={poll.get('result', {}).get('status')}")
    # the poll's terminal payload nests the solution under result.result
    # (frozen shape, C-jaot-contract.md 4): outer result has status/task_id,
    # inner result.result has the solution fields.
    outer_result = poll.get("result", {})
    pin("AsyncSolveStatusResponse", poll,
        ["task_id", "status", "result", "solver_used"])
    pin("AsyncSolveStatusResponse.result", outer_result,
        ["status", "task_id"])
    pin("AsyncSolveStatusResponse.result.result", outer_result.get("result", {}),
        ["status", "execution_id", "objective_value", "variables"])

    # 4. execution detail ---------------------------------------------
    status, body = req("GET", f"/models/executions/{state['exec']}")
    if status != 200:
        sys.exit(f"models/executions -> HTTP {status}: {body}")
    print(f"execution: status={body.get('status')} solver={body.get('solver_name')} "
          f"objective={body.get('objective_value')}")
    pin("ModelExecutionResponse", body,
        ["id", "status", "solver_status", "objective_value",
         "execution_time_ms", "result_data"])
    pin("ModelExecutionResponse.result_data", body.get("result_data", {}),
        ["model", "variables", "solver_status", "objective_value"])

    # 5. exact-analysis -----------------------------------------------
    status, body = req("GET", f"/models/executions/{state['exec']}/exact-analysis")
    if status != 200:
        sys.exit(f"exact-analysis -> HTTP {status}: {body}")
    print(f"exact-analysis: {body.get('binding_count')}/"
          f"{body.get('total_constraints')} binding")
    pin("ExactAnalysis", body,
        ["objective_value", "total_constraints", "binding_count", "constraints"])
    pin("ExactAnalysis.constraints[]", body.get("constraints", [{}])[0],
        ["name", "activity", "rhs", "is_binding"])

    # summary ---------------------------------------------------------
    print(f"\n{len(FAILURES) and 'FAIL' or 'PASS'}: "
          f"{'' if not FAILURES else str(len(FAILURES)) + ' pinned field(s) missing'}")
    for f in FAILURES:
        print("  " + f)
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
