"""
api/zoho_client.py — Zoho Projects REST API client.

ROOT CAUSE FIXES IN THIS VERSION
=================================

FIX A — update_task_status() silently fails
--------------------------------------------
Symptom: API returns {"success": true} but status stays "Open" in Zoho UI.
Root cause: Zoho Projects does NOT accept the status *display name* (e.g. "In Progress")
  as the `status` parameter. It requires the status *ID* — a numeric string like "4".
  The name-based POST returns HTTP 200 but applies no change.
Fix:
  1. New method get_task_statuses() fetches all statuses for a project with their IDs.
  2. update_task_status() calls get_task_statuses(), finds the matching ID by name
     (case-insensitive), then POSTs with status=<id>.

FIX B — No due-date update capability
---------------------------------------
Symptom: Agent correctly says "no API method for due date".
Root cause: update_task() existed but was only called internally for assign/status.
  There was no tool or method that sent end_date / start_date via POST.
Fix: New method update_task_fields() sends any combination of:
  end_date, start_date, name, priority, description — all via POST to the task endpoint.

FIX C — assign_task() silently fails
--------------------------------------
Symptom: Assignment posted but task remains unassigned.
Root cause: Two issues:
  1. Using `zpuid` (Zoho Platform UID) — Zoho Projects API requires the Projects-level
     numeric user id (the `id` field from get_portal_users), NOT zpuid.
  2. The multi-value field encoding must be exactly:
       person_responsible[0]=<user_numeric_id>
     sent as application/x-www-form-urlencoded. The previous implementation
     used httpx's `content=` which does not set Content-Type automatically.
Fix: Use httpx `data=` dict with the key literally set to "person_responsible[0]".
  Also expose the `id` field correctly from _normalize_user().
"""

from __future__ import annotations
import json
import logging
import logging.handlers
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import config


# ── Logger ────────────────────────────────────────────────────────────────────
def _get_log():
    try:
        from agent.agent import get_app_logger
        return get_app_logger("zoho_client")
    except ImportError:
        from pathlib import Path as _P
        _ld = _P(__file__).parent.parent / "logs"
        _ld.mkdir(exist_ok=True)
        log = logging.getLogger("zoho_client")
        if not log.handlers:
            log.setLevel(logging.DEBUG)
            ch = logging.StreamHandler()
            ch.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
            ch.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)-8s] zoho_client | %(message)s",
                datefmt="%H:%M:%S"))
            log.addHandler(ch)
            fh = logging.handlers.RotatingFileHandler(
                _ld / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)-8s] %(name)-14s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"))
            log.addHandler(fh)
        return log

_log = _get_log()


# ── Helpers ───────────────────────────────────────────────────────────────────
def api_base_from_accounts_server(accounts_server: str) -> str:
    base     = accounts_server.rstrip("/")
    api_host = base.replace("accounts.zoho", "projectsapi.zoho")
    return f"{api_host}/restapi"

def _validate_id(value: str, name: str = "id") -> str:
    if not value or not re.match(r"^[\w\-]+$", str(value)):
        raise ValueError(f"Invalid {name}: {value!r}")
    return str(value)

def _month_range() -> tuple[str, str]:
    today = datetime.now()
    return today.replace(day=1).strftime("%m-%d-%Y"), today.strftime("%m-%d-%Y")


# ═══════════════════════════════════════════════════════════════════════════════
class ZohoClient:
    def __init__(self, access_token: str, api_base: Optional[str] = None):
        if not access_token:
            raise ValueError("access_token must not be empty.")
        self._api_base = (api_base or config.ZOHO_API_BASE).rstrip("/")
        self._http     = httpx.Client(
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=20,
        )
        _log.info("ZohoClient initialised | api_base=%s", self._api_base)

    def close(self): self._http.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    # ── Internal HTTP helpers ─────────────────────────────────────────────────
    def _url(self, path: str) -> str:
        return f"{self._api_base}{path}"

    def _get(self, path: str, params: dict | None = None) -> Any:
        url  = self._url(path)
        _log.debug("GET %s params=%s", url, params)
        resp = self._http.get(url, params=params or {})
        self._log_resp(resp)
        resp.raise_for_status()
        return resp.json()

    def _get_safe(self, path: str, params: dict | None = None) -> Any:
        url  = self._url(path)
        _log.debug("GET %s params=%s", url, params)
        resp = self._http.get(url, params=params or {})
        self._log_resp(resp)
        resp.raise_for_status()
        if not resp.content.strip():
            return None
        try:
            return resp.json()
        except Exception:
            _log.warning("non-JSON body: %r", resp.text[:200])
            return None

    def _post(self, path: str, data: dict) -> Any:
        url  = self._url(path)
        _log.debug("POST %s data=%s", url, data)
        resp = self._http.post(url, data=data)
        self._log_resp(resp)
        resp.raise_for_status()
        return resp.json()

    def _post_safe(self, path: str, data: dict) -> Any:
        url  = self._url(path)
        _log.debug("POST %s data=%s", url, data)
        resp = self._http.post(url, data=data)
        self._log_resp(resp)
        resp.raise_for_status()
        if not resp.content.strip():
            return None
        try:
            return resp.json()
        except Exception:
            return None

    def _delete(self, path: str) -> bool:
        url  = self._url(path)
        _log.debug("DELETE %s", url)
        resp = self._http.delete(url)
        self._log_resp(resp)
        resp.raise_for_status()
        return True

    def _log_resp(self, resp: httpx.Response):
        try:
            body = json.dumps(resp.json(), indent=2)[:2000]
        except Exception:
            body = resp.text[:500]
        level = logging.DEBUG if resp.is_success else logging.WARNING
        _log.log(level, "← %s %s | %d | %s",
                 resp.request.method, resp.request.url, resp.status_code, body)

    # ── Portal ────────────────────────────────────────────────────────────────
    def get_portals(self) -> list[dict]:
        _log.info("get_portals()")
        data    = self._get("/portals/")
        portals = data.get("portals", [])
        _log.info("  → %d portal(s)", len(portals))
        return [{"id": p["id_string"], "name": p.get("name", ""),
                 "company": p.get("company_name", ""), "plan": p.get("plan", ""),
                 "role": p.get("role", "")} for p in portals]

    # ── Projects ──────────────────────────────────────────────────────────────
    def get_projects(self, portal_id: str, status: str = "active") -> list[dict]:
        pid = _validate_id(portal_id, "portal_id")
        _log.info("get_projects(portal=%s, status=%r)", pid, status)
        if status == "all":
            active   = self._fetch_projects(pid, "active")
            archived = self._fetch_projects(pid, "archived")
            return active + archived
        return self._fetch_projects(pid, status)

    def _fetch_projects(self, pid: str, status: str) -> list[dict]:
        # Use _get_safe: Zoho returns empty body for archived when none exist
        data     = self._get_safe(f"/portal/{pid}/projects/", params={"status": status})
        if data is None:
            _log.info("  → 0 project(s) [%r] (empty response)", status)
            return []
        projects = data.get("projects", [])
        _log.info("  → %d project(s) [%r]", len(projects), status)
        return [{"id": p["id_string"], "name": p["name"], "status": p.get("status"),
                 "owner": p.get("owner_name", ""), "start_date": p.get("start_date", ""),
                 "end_date": p.get("end_date", ""), "percent": p.get("percent", 0),
                 "open_tasks": p.get("task_count_open", 0),
                 "description": p.get("description", "")} for p in projects]

    def get_project_details(self, portal_id: str, project_id: str) -> dict:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        data = self._get(f"/portal/{pid}/projects/{prid}/")
        p    = data.get("projects", [{}])[0]
        return {"id": p.get("id_string"), "name": p.get("name"), "status": p.get("status"),
                "owner": p.get("owner_name", ""), "start_date": p.get("start_date", ""),
                "end_date": p.get("end_date", ""), "percent": p.get("percent", 0),
                "budget": p.get("budget"), "description": p.get("description", "")}

    def create_project(
        self,
        portal_id:   str,
        name:        str,
        description: str = "",
        start_date:  str = "",
        end_date:    str = "",
        owner_id:    str = "",
    ) -> dict:
        """
        Create a new project in the portal.
        Endpoint: POST /portal/{pid}/projects/
        Required: name
        Optional: description, start_date (MM-DD-YYYY), end_date (MM-DD-YYYY), owner_id
        """
        pid = _validate_id(portal_id, "portal_id")
        _log.info("create_project(portal=%s name=%r)", pid, name)
        payload: dict = {"name": name}
        if description: payload["description"] = description
        if start_date:  payload["start_date"]  = start_date
        if end_date:    payload["end_date"]     = end_date
        if owner_id:    payload["owner"]        = owner_id
        data = self._post(f"/portal/{pid}/projects/", payload)
        projects = data.get("projects", [{}])
        p = projects[0] if projects else {}
        result = {
            "id":          p.get("id_string", ""),
            "name":        p.get("name", name),
            "status":      p.get("status", "active"),
            "owner":       p.get("owner_name", ""),
            "start_date":  p.get("start_date", start_date),
            "end_date":    p.get("end_date",   end_date),
            "description": p.get("description", description),
        }
        _log.info("  → created project id=%s name=%r", result["id"], result["name"])
        return result

    # ── Task statuses ─────────────────────────────────────────────────────────
    def get_task_statuses(self, portal_id: str, project_id: str) -> list[dict]:
        """
        Fetch custom task statuses for a project.
        Correct endpoint: GET .../tasks/statuses/
        Returns: [{"id": "4", "name": "In Progress", "type": "inprogress"}, ...]
        The numeric `id` is what Zoho requires when POSTing a status change.
        """
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        _log.info("get_task_statuses(portal=%s project=%s)", pid, prid)
        data     = self._get(f"/portal/{pid}/projects/{prid}/tasks/statuses/")
        statuses = data.get("statuses", [])
        _log.info("  → %d status(es): %s",
                  len(statuses), [(s.get("name"), s.get("id")) for s in statuses])
        return [{"id":   str(s.get("id", "")),
                 "name": s.get("name", ""),
                 "type": s.get("type", "")} for s in statuses]

    def _resolve_status_id(self, portal_id: str, project_id: str,
                           status_name: str) -> Optional[str]:
        """
        Resolve a status display name → custom status ID.

        Zoho Projects uses portal-wide custom status IDs (18-digit numbers).
        The /taskstatuses/ and /tasks/statuses/ endpoints return 400 on most
        portals. Instead we scan tasks across ALL projects in the portal
        to build a complete {name → id} map.

        Returns None if the name cannot be resolved (caller falls back to
        sending the raw display name).

        The map is cached portal-wide on this client instance.
        """
        pid        = _validate_id(portal_id,  "portal_id")
        name_lower = status_name.strip().lower()

        # Per-instance portal-wide cache
        if not hasattr(self, "_status_cache"):
            self._status_cache: dict = {}

        cache_key = f"portal:{pid}"
        if cache_key not in self._status_cache:
            _log.info("  building portal-wide status map (portal=%s)", pid)
            seen: dict[str, str] = {}
            try:
                projects = self._get(f"/portal/{pid}/projects/",
                                     params={"status": "active"})
                for proj in projects.get("projects", []):
                    prid_scan = proj.get("id_string", "")
                    if not prid_scan:
                        continue
                    try:
                        tasks_data = self._get(
                            f"/portal/{pid}/projects/{prid_scan}/tasks/",
                            params={"action": "all"}
                        )
                        for t in tasks_data.get("tasks", []):
                            st = t.get("status", {})
                            if isinstance(st, dict) and st.get("id") and st.get("name"):
                                k = st["name"].strip().lower()
                                if k not in seen:
                                    seen[k] = str(st["id"])
                                    _log.info("  status map: %r → %s", st["name"], st["id"])
                    except Exception:
                        pass
            except Exception as e:
                _log.warning("  portal-wide scan failed: %s", e)
            _log.info("  portal status map complete: %s", seen)
            self._status_cache[cache_key] = seen

        seen = self._status_cache[cache_key]

        # Exact match
        if name_lower in seen:
            return seen[name_lower]
        # Normalised match (strip spaces: "inprogress" matches "in progress")
        for k, v in seen.items():
            if k.replace(" ", "") == name_lower.replace(" ", ""):
                return v

        _log.warning("  status %r not found in portal map %s", status_name, list(seen.keys()))
        return None   # caller handles the None

    # ── Tasks ─────────────────────────────────────────────────────────────────
    def get_tasks(self, portal_id: str, project_id: str,
                  filters: Optional[dict] = None) -> list[dict]:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        _log.info("get_tasks(portal=%s, project=%s, filters=%s)", pid, prid, filters)
        params: dict = {}
        status_filter = (filters or {}).get("status")
        if status_filter:
            params["status"] = status_filter
        else:
            params["action"] = "all"
        data  = self._get(f"/portal/{pid}/projects/{prid}/tasks/", params=params)
        tasks = data.get("tasks", [])
        _log.info("  → %d task(s)", len(tasks))
        if filters and "owner" in filters:
            f = filters["owner"].lower()
            tasks = [t for t in tasks
                     if any(f in o.get("name", "").lower()
                            for o in t.get("details", {}).get("owners", []))]
        return [_normalize_task(t) for t in tasks]

    def get_task_detail(self, portal_id: str, project_id: str, task_id: str) -> dict:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        _log.info("get_task_detail(portal=%s project=%s task=%s)", pid, prid, tid)
        data  = self._get(f"/portal/{pid}/projects/{prid}/tasks/{tid}/")
        tasks = data.get("tasks", [])
        if not tasks:
            raise ValueError(f"Task {task_id} not found.")
        task             = _normalize_task(tasks[0])
        task["subtasks"] = self.get_subtasks(portal_id, project_id, task_id)
        return task

    def create_task(self, portal_id: str, project_id: str, name: str,
                    description: str = "", due_date: str = "",
                    priority: str = "none") -> dict:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        _log.info("create_task(portal=%s project=%s name=%r)", pid, prid, name)
        payload: dict = {"name": name}
        if description: payload["description"] = description
        if due_date:    payload["end_date"]     = due_date
        if priority and priority != "none": payload["priority"] = priority
        data  = self._post(f"/portal/{pid}/projects/{prid}/tasks/", payload)
        tasks = data.get("tasks", [{}])
        result = _normalize_task(tasks[0]) if tasks else {"error": "No task returned"}
        _log.info("  → created task id=%s", result.get("id"))
        return result

    def update_task_status(self, portal_id: str, project_id: str,
                           task_id: str, status_name_or_id: str) -> dict:
        """
        Update task status with verification.

        STRATEGY ORDER (each verified by re-reading the task):
          1. POST custom_status=<portal-wide-ID>  ← primary for custom-status portals
          2. POST status=<portal-wide-ID>
          3. POST custom_status=<caller-supplied-ID>  (if caller passed a raw ID)
          4. POST status=<display-name>
          5. POST status=<lowercase-nospace>
        """
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        val  = status_name_or_id.strip()
        _log.info("update_task_status(portal=%s project=%s task=%s value=%r)",
                  pid, prid, tid, val)

        # ── Read actual status from Zoho ──────────────────────────────────────
        def _read_back() -> str:
            try:
                d = self._get_safe(f"/portal/{pid}/projects/{prid}/tasks/{tid}/")
                if d:
                    st = d.get("tasks", [{}])[0].get("status", {})
                    return (st.get("name", "") if isinstance(st, dict) else str(st)).lower()
            except Exception:
                pass
            return ""

        original = _read_back()
        _log.info("  current=%r  target=%r", original, val.lower())

        # ── Resolve status ID from portal-wide scan ───────────────────────────
        # Returns None if the name can't be found across all projects
        resolved_id = self._resolve_status_id(pid, prid, val)

        # If val looks like a raw 18-digit ID, treat it as one directly
        is_raw_id = val.isdigit() and len(val) >= 9
        raw_id    = val if is_raw_id else None

        # ── Build attempt list ────────────────────────────────────────────────
        # custom_status first — that's what Zoho uses for portal custom statuses
        attempts: list[tuple[str, str, dict]] = []

        if resolved_id:
            attempts += [
                ("POST custom_status=<resolved_id>", "post", {"custom_status": resolved_id}),
                ("POST status=<resolved_id>",         "post", {"status":        resolved_id}),
            ]
        if raw_id:
            attempts += [
                ("POST custom_status=<raw_id>",       "post", {"custom_status": raw_id}),
                ("POST status=<raw_id>",              "post", {"status":        raw_id}),
            ]
        # Always fall back to display-name forms
        attempts += [
            ("POST status=<display_name>",            "post", {"status": val}),
            ("POST status=<lowercase_nospace>",       "post", {"status": val.lower().replace(" ", "")}),
        ]

        task_url = f"/portal/{pid}/projects/{prid}/tasks/{tid}/"
        for label, verb, payload in attempts:
            _log.info("  [%s] %s", label, payload)
            try:
                resp = getattr(self._http, verb)(self._url(task_url), data=payload)
                self._log_resp(resp)
                if resp.status_code >= 400:
                    _log.warning("    HTTP %d — skip", resp.status_code)
                    continue
            except Exception as exc:
                _log.warning("    exception: %s", exc)
                continue

            new_status = _read_back()
            _log.info("    read-back: %r", new_status)
            if new_status and new_status != original:
                _log.info("  ✓ CHANGED via [%s]  %r → %r", label, original, new_status)
                self._working_status_strategy = (verb, list(payload.keys())[0])
                return {
                    "success":       True,
                    "status":        new_status,
                    "applied_via":   label,
                    "applied_value": val,
                }

        _log.error("  ✗ status unchanged %r → tried %r", original, val)
        return {
            "success":     False,
            "error":       f"Status is still '{original}' after all attempts.",
            "tried_value": val,
            "resolved_id": resolved_id,
            "hint": (
                "Run: python debug_status_probe.py — it will find the exact "
                "API format your portal accepts. "
                "Check logs/app.log for each HTTP response."
            ),
        }

    def update_task_fields(self, portal_id: str, project_id: str,
                           task_id: str, fields: dict) -> dict:
        """
        FIX B: Update any editable task fields via POST.

        Supported fields in `fields` dict:
          name        : str  — task title
          end_date    : str  — due date in MM-DD-YYYY format
          start_date  : str  — start date in MM-DD-YYYY format
          priority    : str  — none | low | medium | high
          description : str  — task description
          percent     : int  — completion percentage 0-100

        Example:
            client.update_task_fields(pid, prid, tid, {"end_date": "04-08-2026"})
        """
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        _log.info("update_task_fields(portal=%s project=%s task=%s fields=%s)",
                  pid, prid, tid, fields)
        if not fields:
            raise ValueError("No fields provided to update.")
        data  = self._post_safe(f"/portal/{pid}/projects/{prid}/tasks/{tid}/", fields)
        if data:
            tasks = data.get("tasks", [{}])
            result = _normalize_task(tasks[0]) if tasks else {"success": True}
        else:
            result = {"success": True}
        result["updated_fields"] = list(fields.keys())
        _log.info("  → update_task_fields result=%s", result)
        return result

    def assign_task(self, portal_id: str, project_id: str,
                    task_id: str, user_id: str) -> dict:
        """
        Assign a task to a user with verification.

        Zoho Projects silently accepts invalid user IDs (returns 200, no error)
        but doesn't apply the assignment. We verify by re-reading the task's
        assignees after each attempt.

        The user list returns two IDs per user:
          id    = portal-level numeric ID  (e.g. 60068246602)
          zpuid = Zoho platform UID        (e.g. 430209000000063003)

        Zoho Projects task assignment requires the ZPUID. We accept either from
        the caller and try both.

        Field variants tried (in order):
          person_responsible[0]=<zpuid>
          person_responsible[0]=<id>
          owners[0]=<zpuid>
          owners[0]=<id>
        """
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        _validate_id(user_id, "user_id")
        _log.info("assign_task(portal=%s project=%s task=%s user_id=%s)",
                  pid, prid, tid, user_id)

        task_url = self._url(f"/portal/{pid}/projects/{prid}/tasks/{tid}/")

        # ── Read current assignees ────────────────────────────────────────────
        def _read_assignees() -> list[str]:
            try:
                d = self._get_safe(f"/portal/{pid}/projects/{prid}/tasks/{tid}/")
                if d:
                    owners = d.get("tasks", [{}])[0].get("details", {}).get("owners", [])
                    names  = [o.get("name", "") for o in owners]
                    return [n for n in names if n and n.lower() != "unassigned"]
            except Exception:
                pass
            return []

        # ── Resolve both IDs: the caller may pass either one ─────────────────
        # Look up the user's zpuid from the project user list so we always
        # have both forms available regardless of which the caller passed.
        alt_id: Optional[str] = None
        try:
            users = self.get_project_users(portal_id, project_id)
            for u in users:
                if user_id in (u.get("id", ""), u.get("zpuid", "")):
                    # We have the user — collect the OTHER id form
                    alt_id = u["zpuid"] if user_id == u.get("id") else u["id"]
                    _log.info("  user found: id=%s zpuid=%s",
                              u.get("id"), u.get("zpuid"))
                    break
        except Exception as e:
            _log.warning("  could not look up alt user id: %s", e)

        # Determine zpuid and portal-id from the lookup above
        # Winning combo confirmed by debug_assign_probe.py:
        #   person_responsible=<zpuid>  (no brackets, zpuid not portal id)
        zpuid_candidate = alt_id if alt_id else user_id
        id_candidate    = user_id

        attempts = [
            ("POST person_responsible=zpuid",    {"person_responsible":    zpuid_candidate}),
            ("POST person_responsible=id",       {"person_responsible":    id_candidate}),
            ("POST person_responsible[0]=zpuid", {"person_responsible[0]": zpuid_candidate}),
            ("POST person_responsible[0]=id",    {"person_responsible[0]": id_candidate}),
            ("POST owners[0]=zpuid",             {"owners[0]":             zpuid_candidate}),
            ("POST owners[0]=id",                {"owners[0]":             id_candidate}),
        ]

        for label, form_data in attempts:
            _log.info("  [%s] %s", label, form_data)
            try:
                resp = self._http.post(task_url, data=form_data)
                self._log_resp(resp)
                if resp.status_code >= 400:
                    _log.warning("    HTTP %d — skip", resp.status_code)
                    continue
            except Exception as exc:
                _log.warning("    exception: %s", exc)
                continue

            # Verify: check assignees changed
            assigned = _read_assignees()
            _log.info("    assignees after: %s", assigned)
            if assigned:
                _log.info("  ✓ ASSIGNED via [%s]  assignees=%s", label, assigned)
                return {
                    "success":      True,
                    "assigned_via": label,
                    "assignees":    assigned,
                }

        _log.error("  ✗ assignment failed — task still unassigned")
        return {
            "success": False,
            "error":   "Task is still unassigned after all attempts.",
            "hint": (
                "Run: python debug_assign_probe.py — it will find "
                "the exact field/ID combo your portal needs. "
                "Check logs/app.log for each HTTP response."
            ),
        }

    def delete_task(self, portal_id: str, project_id: str, task_id: str) -> dict:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        _log.info("delete_task(portal=%s project=%s task=%s)", pid, prid, tid)
        self._delete(f"/portal/{pid}/projects/{prid}/tasks/{tid}/")
        return {"success": True, "deleted_task_id": task_id}

    def add_comment(self, portal_id: str, project_id: str,
                    task_id: str, comment: str) -> dict:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        _log.info("add_comment(portal=%s project=%s task=%s)", pid, prid, tid)
        self._post(f"/portal/{pid}/projects/{prid}/tasks/{tid}/comments/",
                   {"content": comment})
        return {"success": True, "comment": comment}

    # ── Subtasks ──────────────────────────────────────────────────────────────
    def get_subtasks(self, portal_id: str, project_id: str,
                     task_id: str) -> list[dict]:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        _log.info("get_subtasks(portal=%s project=%s task=%s)", pid, prid, tid)
        data = self._get_safe(f"/portal/{pid}/projects/{prid}/tasks/{tid}/subtasks/")
        if data is None:
            return []
        tasks = data.get("tasks", [])
        _log.info("  → %d subtask(s)", len(tasks))
        return [_normalize_task(t) for t in tasks]

    def create_subtask(self, portal_id: str, project_id: str,
                       parent_task_id: str, name: str, description: str = "",
                       due_date: str = "", priority: str = "none") -> dict:
        pid  = _validate_id(portal_id,     "portal_id")
        prid = _validate_id(project_id,    "project_id")
        tid  = _validate_id(parent_task_id, "parent_task_id")
        _log.info("create_subtask(portal=%s project=%s parent=%s name=%r)",
                  pid, prid, tid, name)
        payload: dict = {"name": name}
        if description: payload["description"] = description
        if due_date:    payload["end_date"]     = due_date
        if priority and priority != "none": payload["priority"] = priority
        data  = self._post(f"/portal/{pid}/projects/{prid}/tasks/{tid}/subtasks/", payload)
        tasks = data.get("tasks", [{}])
        return _normalize_task(tasks[0]) if tasks else {"error": "No subtask returned"}

    def update_subtask(self, portal_id: str, project_id: str,
                       parent_task_id: str, subtask_id: str,
                       updates: dict) -> dict:
        pid   = _validate_id(portal_id,     "portal_id")
        prid  = _validate_id(project_id,    "project_id")
        tid   = _validate_id(parent_task_id, "parent_task_id")
        stid  = _validate_id(subtask_id,    "subtask_id")
        _log.info("update_subtask(portal=%s project=%s parent=%s subtask=%s updates=%s)",
                  pid, prid, tid, stid, updates)
        # If updating status, resolve name→ID first
        if "status" in updates:
            try:
                updates["status"] = self._resolve_status_id(pid, prid, updates["status"])
            except ValueError:
                pass  # keep original value; Zoho may accept it
        data  = self._post_safe(
            f"/portal/{pid}/projects/{prid}/tasks/{tid}/subtasks/{stid}/", updates)
        if data:
            tasks = data.get("tasks", [{}])
            return _normalize_task(tasks[0]) if tasks else {"success": True}
        return {"success": True, "subtask_id": subtask_id}

    # ── Users ─────────────────────────────────────────────────────────────────
    def get_portal_users(self, portal_id: str) -> list[dict]:
        pid  = _validate_id(portal_id, "portal_id")
        _log.info("get_portal_users(portal=%s)", pid)
        data  = self._get(f"/portal/{pid}/users/")
        users = data.get("users", [])
        _log.info("  → %d user(s)", len(users))
        for u in users:
            _log.debug("  user id=%s zpuid=%s name=%r",
                       u.get("id"), u.get("zpuid"), u.get("name"))
        return [_normalize_user(u) for u in users]

    def get_project_users(self, portal_id: str, project_id: str) -> list[dict]:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        _log.info("get_project_users(portal=%s project=%s)", pid, prid)
        data  = self._get(f"/portal/{pid}/projects/{prid}/users/")
        users = data.get("users", [])
        _log.info("  → %d user(s)", len(users))
        return [_normalize_user(u) for u in users]

    # ── Timesheets ────────────────────────────────────────────────────────────
    def log_hours(self, portal_id, project_id, task_id, date, hours,
                  notes="", bill_status="Non Billable") -> dict:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        _log.info("log_hours(portal=%s project=%s task=%s date=%s hours=%.2f)",
                  pid, prid, tid, date, hours)
        h, m = int(hours), int((hours - int(hours)) * 60)
        self._post(f"/portal/{pid}/projects/{prid}/tasks/{tid}/logs/",
                   {"date": date, "hours": f"{h:02d}:{m:02d}",
                    "notes": notes, "bill_status": bill_status})
        return {"success": True, "logged_hours": hours, "date": date}

    def get_task_logs(self, portal_id, project_id, task_id) -> list[dict]:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        tid  = _validate_id(task_id,    "task_id")
        data = self._get_safe(f"/portal/{pid}/projects/{prid}/tasks/{tid}/logs/")
        if data is None:
            return []
        logs = data.get("timelogs", {})
        if isinstance(logs, dict):
            logs = logs.get("grandtotal", [])
        return [{"user": l.get("owner_name", ""), "date": l.get("log_date", ""),
                 "hours": float(l.get("hours", 0)), "notes": l.get("notes", ""),
                 "billable": l.get("bill_status") == "Billable"} for l in logs]

    def get_project_logs(self, portal_id, project_id,
                         from_date=None, to_date=None) -> list[dict]:
        pid  = _validate_id(portal_id,  "portal_id")
        prid = _validate_id(project_id, "project_id")
        ds, de = _month_range()
        params = {"bill_status": "ALL",
                  "date":        from_date or ds,
                  "end_date":    to_date   or de}
        data   = self._get_safe(f"/portal/{pid}/projects/{prid}/logs/", params=params)
        if data is None:
            return []
        logs = data.get("timelogs", {})
        if isinstance(logs, dict):
            logs = logs.get("grandtotal", [])
        return [{"user": l.get("owner_name", ""), "task": l.get("task_name", ""),
                 "date": l.get("log_date", ""), "hours": float(l.get("hours", 0)),
                 "billable": l.get("bill_status") == "Billable"} for l in logs]


# ── Normalisers ───────────────────────────────────────────────────────────────
def _normalize_task(t: dict) -> dict:
    owners = t.get("details", {}).get("owners", [])
    status = t.get("status", {})
    # Preserve the numeric status ID — needed for update_task_status
    status_id   = status.get("id",   "") if isinstance(status, dict) else ""
    status_name = status.get("name", "") if isinstance(status, dict) else str(status)
    return {
        "id":          t.get("id_string", t.get("id", "")),
        "name":        t.get("name", ""),
        "status":      status_name,
        "status_id":   str(status_id),   # numeric ID e.g. "2", "4" — use for updates
        "priority":    t.get("priority", "none"),
        "percent":     t.get("percent", 0),
        "start_date":  t.get("start_date", ""),
        "due_date":    t.get("end_date", ""),
        "assignees":   [o.get("name", "") for o in owners],
        "description": t.get("description", ""),
        "project_id":  t.get("project_id", ""),
        "has_subtasks": t.get("subtask_count", 0) > 0 or bool(t.get("subtasks")),
    }

def _normalize_user(u: dict) -> dict:
    """
    FIX C part 2: expose BOTH id fields.
    - `id`    = Projects-level numeric ID  ← use this for assign_task()
    - `zpuid` = Zoho Platform UID          ← informational only
    The log debug above shows which field contains which value so you can verify.
    """
    return {
        "id":     str(u.get("id",    u.get("zpuid", ""))),   # Projects numeric ID
        "zpuid":  str(u.get("zpuid", u.get("id",    ""))),   # Platform UID
        "name":   u.get("name",  ""),
        "email":  u.get("email", ""),
        "role":   u.get("role",  ""),
        "active": u.get("active", True),
    }