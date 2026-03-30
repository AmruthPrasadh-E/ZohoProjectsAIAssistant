#!/usr/bin/env python3
"""
debug_assign_probe.py — Find which field/ID combination Zoho accepts for task assignment.

Run this when assign_task returns success but the task stays "Unassigned".

Usage:
    python debug_assign_probe.py
"""
import os, json, sys
from dotenv import load_dotenv
load_dotenv()

import httpx

TOKEN  = os.getenv("ZOHO_ACCESS_TOKEN", "").strip().strip('"\'')
SERVER = os.getenv("ZOHO_ACCOUNTS_SERVER", "").strip().strip('"\'')
if not TOKEN:  TOKEN  = input("Access token: ").strip()
if not SERVER: SERVER = input("Accounts server (e.g. https://accounts.zoho.in): ").strip()

import config
from api.zoho_client import ZohoClient, api_base_from_accounts_server

api_base = api_base_from_accounts_server(SERVER) if SERVER else config.ZOHO_API_BASE
client   = ZohoClient(TOKEN, api_base=api_base)
headers  = {"Authorization": f"Zoho-oauthtoken {TOKEN}"}

# ── Discover IDs ──────────────────────────────────────────────────────────────
portals  = client.get_portals()
pid      = portals[0]["id"]
projects = client.get_projects(pid)
prid     = projects[0]["id"]
pname    = projects[0]["name"]

tasks = client.get_tasks(pid, prid)
target = tasks[0]
tid    = target["id"]
tname  = target["name"]

users  = client.get_project_users(pid, prid)
user   = users[0]
uid    = user["id"]
zpuid  = user["zpuid"]
uname  = user["name"]

print(f"\nProject : {pname!r}  (pid={prid})")
print(f"Task    : {tname!r}  (tid={tid})")
print(f"User    : {uname!r}")
print(f"  id    = {uid!r}   ← portal numeric id")
print(f"  zpuid = {zpuid!r} ← Zoho platform uid\n")

task_url = client._url(f"/portal/{pid}/projects/{prid}/tasks/{tid}/")

def read_assignees() -> str:
    with httpx.Client(headers=headers, timeout=10) as h:
        r = h.get(task_url)
    try:
        t   = r.json().get("tasks", [{}])[0]
        raw = t.get("details", {}).get("owners", [])
        names = [o.get("name","") for o in raw if o.get("name","").lower() != "unassigned"]
        return names or ["Unassigned"]
    except Exception:
        return ["(read error)"]

def probe(label, data):
    print(f"─── {label} ───")
    print(f"  data = {data}")
    with httpx.Client(headers=headers, timeout=10) as h:
        resp = h.post(task_url, data=data)
    print(f"  HTTP {resp.status_code}")
    after = read_assignees()
    print(f"  assignees after: {after}")
    changed = "Unassigned" not in after and after != ["(read error)"]
    if changed:
        print(f"  ✅ ASSIGNED!")
    else:
        print(f"  ✗  unchanged")
    print()
    return changed

combos = [
    ("person_responsible[0]=zpuid",  {"person_responsible[0]": zpuid}),
    ("person_responsible[0]=id",     {"person_responsible[0]": uid}),
    ("owners[0]=zpuid",              {"owners[0]":             zpuid}),
    ("owners[0]=id",                 {"owners[0]":             uid}),
    ("person_responsible=zpuid",     {"person_responsible":    zpuid}),
    ("person_responsible=id",        {"person_responsible":    uid}),
]

print(f"Initial assignees: {read_assignees()}\n")
for label, data in combos:
    if probe(label, data):
        print(f"✅ WINNING COMBO: {label}  data={data}")
        print("Add this to zoho_client.py assign_task() as the first attempt.")
        break
else:
    print("✗ None of the combos worked.")
    print("Check logs/app.log and share with support.")