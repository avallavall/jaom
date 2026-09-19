# -*- coding: utf-8 -*-
# License LGPL-3
"""HTTP client for the JAOT v2 API (thin client, SPECS §6).

Framework-free on purpose: no Odoo imports, so the unit tests can drive it
with a fake transport and the contract smoke test can reuse it verbatim.
Response field names are the ones frozen in
docs/research/C-jaot-contract.md §4 (live JAOT v3.9.0).
"""
import logging
import time

import requests

_logger = logging.getLogger(__name__)

# Default per-call budget (SPECS §10.1: no long work in a request; the solve
# itself is async, every call here is a fast control-plane call).
DEFAULT_TIMEOUT = 30


class JaotAPIError(Exception):
    """A JAOT HTTP error, carrying the status and the machine-readable code.

    ``code`` comes from the JSON body when JAOT provides one
    (``error`` / ``code`` / ``detail`` keys), otherwise it is the HTTP
    status as a string. ``detail`` is the raw JSON body (dict) for the
    scenario's error surfacing (SPECS §4.4: "JAOT error surfaced with its
    code").
    """

    def __init__(self, status, code, message, detail=None, latency_ms=None):
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.latency_ms = latency_ms
        super().__init__(f"JAOT HTTP {status} ({code}): {message}")


class JaotClient:
    """One JAOT instance per company (SPECS §6.1, DECIDED Q2)."""

    def __init__(self, base_url, api_key, timeout=DEFAULT_TIMEOUT,
                 transport=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        # ``transport`` overrides requests.request — the fake-client
        # seam for unit tests (SPECS §10.3).
        self._transport = transport or requests.request

    # ------------------------------------------------------------------
    # low level
    # ------------------------------------------------------------------
    def _request(self, method, path, body=None):
        url = f"{self.base_url}/api/v2{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        t0 = time.perf_counter()
        try:
            resp = self._transport(
                method, url, headers=headers,
                json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            _logger.error("JAOT %s %s transport error: %s (%.0f ms)",
                          method, path, exc, latency_ms)
            raise JaotAPIError(0, "transport_error", str(exc),
                               latency_ms=latency_ms) from exc
        latency_ms = (time.perf_counter() - t0) * 1000
        _logger.info("JAOT %s %s -> %d in %.0f ms", method, path,
                     resp.status_code, latency_ms)
        if resp.status_code >= 400:
            detail = {}
            try:
                detail = resp.json()
            except ValueError:
                detail = {"raw": resp.text[:2000]}
            code, message = self._extract_error(detail, resp.status_code)
            raise JaotAPIError(resp.status_code, code, message,
                               detail=detail, latency_ms=latency_ms)
        try:
            return resp.json()
        except ValueError:
            return {}

    @staticmethod
    def _extract_error(detail, status):
        if isinstance(detail, dict):
            for key in ("error", "code"):
                if detail.get(key):
                    return str(detail[key]), str(detail.get("message")
                                                  or detail.get("detail")
                                                  or status)
            if detail.get("detail"):
                detail_v = detail["detail"]
                if isinstance(detail_v, str):
                    return str(status), detail_v
                if isinstance(detail_v, dict):
                    return str(detail_v.get("code") or status), \
                        str(detail_v.get("message") or detail_v)
        return str(status), "JAOT request failed"

    # ------------------------------------------------------------------
    # contract endpoints (SPECS §6.2, field names frozen in note C §4)
    # ------------------------------------------------------------------
    def health_status(self):
        """Connectivity check (SPECS §6.1): status + version + checks."""
        return self._request("GET", "/health/status")

    def solvers_available(self):
        """Live solver catalog for default_solver validation."""
        return self._request("GET", "/solvers/available")

    def solve_async(self, problem, solver_name=None, wait=False):
        """POST /solve/async — the only submit path (sync POST /solve is
        never used, SPECS §6.2). Returns the AsyncSolveEnvelope
        {task_id, execution_id, status, message, ws_url, poll_url}."""
        query = ""
        if solver_name:
            query = f"?solver_name={requests.utils.quote(solver_name)}"
        if wait:
            query = (query + "&" if query else "?") + "wait=true"
        return self._request("POST", f"/solve/async{query}", body=problem)

    def poll_task(self, task_id):
        """GET /solve/async/{task_id} — poll until terminal (D5: ir.cron,
        never inside a user request)."""
        return self._request("GET", f"/solve/async/{task_id}")

    def cancel_task(self, task_id):
        """POST /solve/async/{task_id}/cancel (SPECS §4.4 cancelled)."""
        return self._request("POST", f"/solve/async/{task_id}/cancel")

    def execution(self, execution_id):
        """GET /models/executions/{id} — solution values, objective, gap,
        solver, time (SPECS §6.2 step 3; delta D3: infeasibility is read
        from solver_status here, never from the task status alone)."""
        return self._request("GET", f"/models/executions/{execution_id}")

    def exact_analysis(self, execution_id):
        """GET …/executions/{id}/exact-analysis (SPECS §6.2 step 4)."""
        return self._request("GET",
                             f"/models/executions/{execution_id}/exact-analysis")

    def scenario_analysis(self, execution_id):
        """POST …/executions/{id}/scenario-analysis — no request body
        (delta D2); returns the ScenarioAnalysisJob."""
        return self._request("POST",
                             f"/models/executions/{execution_id}/scenario-analysis")

    def scenario_analysis_get(self, execution_id):
        """GET …/executions/{id}/scenario-analysis — poll the job until it
        leaves ``running``."""
        return self._request("GET",
                             f"/models/executions/{execution_id}/scenario-analysis")

    def infeasibility_analysis(self, execution_id):
        """POST /solve/{execution_id}/infeasibility-analysis (SPECS
        §6.2 step 6): minimal conflicting constraint set when infeasible."""
        return self._request("POST",
                             f"/solve/{execution_id}/infeasibility-analysis")
