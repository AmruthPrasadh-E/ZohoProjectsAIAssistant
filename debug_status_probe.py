#!/usr/bin/env python3
"""
debug_status_probe.py — Comprehensive status update probe.

This version tests custom_status parameter and portal-wide status ID scan.
Reads ZOHO_ACCESS_TOKEN, ZOHO_ACCOUNTS_SERVER from .env
"""

import os, json, sys
from dotenv import load_dotenv
load_dotenv()

import httpx

TOKEN  = os.getenv("ZOHO_ACCESS_TOKEN",    "").strip().strip('"').strip("'")
SERVER = os.getenv("ZOHO_ACCOUNTS_SERVER", "").strip().strip('"').strip("'")

if not TOKEN:
    TOKEN  = input("Access token: ").strip()
if not SERVER:
    SERVER = input("Accounts server (e.g. https://accounts.zoho.in): ").strip()

import config
from api.zoho_client import ZohoClient, api_base_from_accounts_server

api_base = api_base_from_accounts_server(SERVER) if SERVER else config.ZOHO_API_BASE
client   = ZohoClient(TOKEN, api_base=api_base)
headers  = {"Authorization": f"Zoho-oauthtoken {TOKEN}"}

# ── Discover portal / project / task ─────────────────────────────────────────
portals  = client.get_portals()
pid      = portals[0]["id"]
projects = client.get_projects(pid)
if not projects:
    print("No projects"); sys.exit(1)

prid  = projects[0]["id"]
pname = projects[0]["name"]
tasks = client.get_tasks(pid, prid)
if not tasks:
    print("No tasks"); sys.exit(1)

open_tasks = [t for t in tasks if t["status"].lower() == "open"] or tasks
target    = open_tasks[0]
tid       = target["id"]
tname     = target["name"]
cur_status = target["status"]
cur_sid    = target["status_id"]

print(f"\nTarget  : {tname!r}  id={tid}")
print(f"Status  : {cur_status!r}  status_id={cur_sid!r}")
print(f"Project : {pname!r}  pid={prid}\n")

# ── Collect all status IDs portal-wide across all projects ───────────────────
print("═══ Scanning ALL projects for status IDs ═══")
status_map: dict[str, str] = {}   # {name_lower: id}
for proj in projects:
    try:
        all_tasks = client.get_tasks(pid, proj["id"])
        for t in all_tasks:
            raw_t = client._http.get(
                client._url(f"/portal/{pid}/projects/{proj['id']}/tasks/"),
                params={"action": "all"}
            ).json()
            for rt in raw_t.get("tasks", []):
                st = rt.get("status", {})
                if isinstance(st, dict) and st.get("id") and st.get("name"):
                    k = st["name"].strip().lower()
                    if k not in status_map:
                        status_map[k] = str(st["id"])
                        print(f"  Found: {st['name']!r} → id={st['id']}")
    except Exception as e:
        print(f"  Error scanning {proj['name']}: {e}")

print(f"\nFull status map: {status_map}\n")

inprogress_id = (status_map.get("in progress")
                 or status_map.get("inprogress")
                 or None)
print(f"In Progress ID: {inprogress_id!r}\n")

# ── Helper probes ─────────────────────────────────────────────────────────────
base_url = client._url(f"/portal/{pid}/projects/{prid}/tasks/{tid}/")

def probe(label, method, url, **kwargs):
    print(f"─── {label} ───")
    if "data" in kwargs:   print(f"  data  ={kwargs['data']}")
    if "json" in kwargs:   print(f"  json  ={kwargs['json']}")
    with httpx.Client(headers=headers, timeout=15) as http:
        resp = getattr(http, method.lower())(url, **kwargs)
    # Parse and show the status field specifically
    try:
        body  = resp.json()
        tasks = body.get("tasks", [{}])
        st    = tasks[0].get("status", "N/A") if tasks else "N/A"
        print(f"  → HTTP {resp.status_code}")
        print(f"  → status in response: {st}")
    except Exception:
        print(f"  → HTTP {resp.status_code}")
        print(f"  → body: {resp.text[:300]}")

    # Read back from API
    try:
        rb = client._http.get(base_url).json()
        rb_t  = rb.get("tasks", [{}])[0]
        rb_st = rb_t.get("status", {})
        rb_name = rb_st.get("name","?") if isinstance(rb_st, dict) else str(rb_st)
        rb_id   = rb_st.get("id",  "?") if isinstance(rb_st, dict) else "?"
        print(f"  → READ-BACK status: {rb_name!r}  id={rb_id!r}")
        changed = rb_name.lower() != cur_status.lower()
        if changed:
            print(f"  ✅ STATUS CHANGED!  {cur_status!r} → {rb_name!r}")
        else:
            print(f"  ✗  unchanged ({rb_name!r})")
    except Exception as e:
        print(f"  → read-back error: {e}")
    print()
    return resp

# ── Probes ────────────────────────────────────────────────────────────────────
probe("1. POST status='In Progress'",  "POST", base_url, data={"status": "In Progress"})
probe("2. POST status='inprogress'",   "POST", base_url, data={"status": "inprogress"})
probe("3. POST status='open'  (reset)","POST", base_url, data={"status": "open"})

if inprogress_id:
    probe(f"4. POST custom_status={inprogress_id!r}",
          "POST", base_url, data={"custom_status": inprogress_id})
    probe(f"5. POST status={inprogress_id!r} (ID as status)",
          "POST", base_url, data={"status": inprogress_id})
    probe(f"6. POST json custom_status={inprogress_id!r}",
          "POST", base_url,
          headers={**headers, "Content-Type": "application/json"},
          content=json.dumps({"custom_status": inprogress_id}).encode())

# Try portal-level statuses endpoints
print("═══ Portal-level status endpoints ═══")
for ep in [
    f"/portal/{pid}/taskstatuses/",
    f"/portal/{pid}/tasks/statuses/",
    f"/portal/{pid}/projects/{prid}/taskstatuses/",
]:
    url = client._url(ep)
    try:
        with httpx.Client(headers=headers, timeout=10) as h:
            r = h.get(url)
        print(f"  GET {ep} → {r.status_code}")
        if r.status_code == 200:
            print(f"  body={r.text[:400]}")
    except Exception as e:
        print(f"  GET {ep} → error: {e}")

print("\n═══ Summary ═══")
print(f"status_map = {json.dumps(status_map, indent=2)}")