#!/usr/bin/env python3
"""
test_zoho_client.py — Standalone Zoho API tester (no agent, no Streamlit).

USAGE
=====
  python test_zoho_client.py              # run all tests
  python test_zoho_client.py portals
  python test_zoho_client.py projects
  python test_zoho_client.py tasks
  python test_zoho_client.py users
  python test_zoho_client.py timesheets

  LOG_LEVEL=DEBUG python test_zoho_client.py   # full HTTP trace

GETTING YOUR TOKEN
==================
  Option A (easiest): Add ZOHO_DEBUG=1 to .env, open the Streamlit app,
    log in, then copy the token from the sidebar Debug panel.
  Option B: Add directly to .env:
    ZOHO_ACCESS_TOKEN=1000.xxxx
    ZOHO_ACCOUNTS_SERVER=https://accounts.zoho.in
"""

import json, os, sys, textwrap
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN    = os.getenv("ZOHO_ACCESS_TOKEN",    "").strip().strip('"').strip("'")
ACCOUNTS_SERVER = os.getenv("ZOHO_ACCOUNTS_SERVER", "").strip().strip('"').strip("'")

# ── Terminal colours ──────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"
def ok(m):     print(f"  {G}✓{X}  {m}")
def fail(m):   print(f"  {R}✗{X}  {m}")
def info(m):   print(f"  {C}i{X}  {m}")
def warn(m):   print(f"  {Y}!{X}  {m}")
def hdr(m):    print(f"\n{B}{C}{'─'*60}{X}\n{B}{C}  {m}{X}\n{'─'*60}")
def pprint(label, data):
    print(f"  {C}{label}:{X}\n" + textwrap.indent(json.dumps(data, indent=2, default=str), "    "))

PASS = FAIL = 0

def run(name, fn):
    global PASS, FAIL
    print(f"\n  {B}TEST:{X} {name}")
    try:
        r = fn()
        ok(f"PASSED — {type(r).__name__}")
        PASS += 1
        return r
    except Exception as e:
        fail(f"FAILED — {type(e).__name__}: {e}")
        FAIL += 1
        return None


def main():
    global ACCESS_TOKEN, ACCOUNTS_SERVER
    hdr("Zoho Projects API — Standalone Client Tester")

    # ── Token ─────────────────────────────────────────────────────────────────
    if not ACCESS_TOKEN:
        print(f"\n{Y}No ZOHO_ACCESS_TOKEN in .env.{X}")
        print("Add ZOHO_DEBUG=1 to .env, open the Streamlit app → sidebar Debug panel.\n")
        ACCESS_TOKEN = input("Paste access token: ").strip()
        if not ACCESS_TOKEN:
            print(f"{R}No token. Exiting.{X}"); sys.exit(1)

    if not ACCOUNTS_SERVER:
        print(f"\n{Y}No ZOHO_ACCOUNTS_SERVER in .env.{X}")
        print("Example: https://accounts.zoho.in\n")
        ACCOUNTS_SERVER = input("Paste accounts-server URL (Enter = skip): ").strip()

    import config
    from api.zoho_client import ZohoClient, api_base_from_accounts_server

    api_base = api_base_from_accounts_server(ACCOUNTS_SERVER) if ACCOUNTS_SERVER else config.ZOHO_API_BASE
    info(f"accounts_server : {ACCOUNTS_SERVER or '(using .env DC)'}")
    info(f"api_base        : {api_base}")
    info(f"token prefix    : {ACCESS_TOKEN[:20]}...")

    client = ZohoClient(ACCESS_TOKEN, api_base=api_base)
    mode   = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    run_all = (mode == "all")

    # ── 1: Portals ────────────────────────────────────────────────────────────
    portal_id = None
    if run_all or mode == "portals":
        hdr("1 · Portals")
        portals = run("get_portals()", client.get_portals)
        if portals:
            pprint("portals", portals)
            portal_id = portals[0]["id"]
            ok(f"Using portal: {portals[0]['name']!r}  id={portal_id}")

    if portal_id is None:
        portals = client.get_portals()
        if not portals:
            fail("No portals found — cannot continue."); sys.exit(1)
        portal_id = portals[0]["id"]

    # ── 2: Projects ───────────────────────────────────────────────────────────
    project_id = None
    if run_all or mode == "projects":
        hdr("2 · Projects")

        active = run("get_projects(status='active')",
                     lambda: client.get_projects(portal_id, "active"))
        if active:
            pprint("active projects", active)
            project_id = active[0]["id"]
            ok(f"Active project count from API: {len(active)}")
            warn("VERIFY ↑ matches Zoho web UI active project count")

        archived = run("get_projects(status='archived')",
                       lambda: client.get_projects(portal_id, "archived"))
        if archived is not None:
            ok(f"Archived project count: {len(archived)}")

        # Test the merged 'all' path
        all_p = run("get_projects(status='all')  [merged active+archived]",
                    lambda: client.get_projects(portal_id, "all"))
        if all_p is not None:
            ok(f"Total merged count: {len(all_p)}")

        if project_id:
            run(f"get_project_details({project_id!r})",
                lambda: client.get_project_details(portal_id, project_id))

    # ── 3: Tasks ──────────────────────────────────────────────────────────────
    task_id = None
    if run_all or mode == "tasks":
        hdr("3 · Tasks")

        if project_id is None:
            ps = client.get_projects(portal_id)
            if ps: project_id = ps[0]["id"]; info(f"Using project {ps[0]['name']!r}")

        if project_id:
            tasks = run("get_tasks() — all tasks (action=all, no status filter)",
                        lambda: client.get_tasks(portal_id, project_id))
            if tasks:
                pprint("tasks", tasks)
                task_id = tasks[0]["id"]
                ok(f"Task count: {len(tasks)}")
                warn("VERIFY ↑ matches Zoho web UI task count for this project")

            # FIX 2 verified: status filter without action=all
            run("get_tasks(filters={'status': 'open'})  [no action param]",
                lambda: client.get_tasks(portal_id, project_id, {"status": "open"}))

            run("get_tasks(filters={'status': 'closed'})",
                lambda: client.get_tasks(portal_id, project_id, {"status": "closed"}))

            if task_id:
                run(f"get_task_detail({task_id!r})",
                    lambda: client.get_task_detail(portal_id, project_id, task_id))

    # ── 4: Users ──────────────────────────────────────────────────────────────
    if run_all or mode == "users":
        hdr("4 · Users")

        users = run("get_portal_users()", lambda: client.get_portal_users(portal_id))
        if users:
            pprint("portal users", users)
            ok(f"Portal user count: {len(users)}")
            warn("VERIFY ↑ — if agent ever shows Alice/Bob/David, it is hallucinating")

        if project_id:
            run("get_project_users()", lambda: client.get_project_users(portal_id, project_id))

    # ── 5: Timesheets ─────────────────────────────────────────────────────────
    if run_all or mode == "timesheets":
        hdr("5 · Timesheets")

        if project_id is None:
            ps = client.get_projects(portal_id)
            if ps: project_id = ps[0]["id"]
        if project_id and task_id is None:
            ts = client.get_tasks(portal_id, project_id)
            if ts: task_id = ts[0]["id"]

        now   = datetime.now()
        start = now.replace(day=1).strftime("%m-%d-%Y")
        end   = now.strftime("%m-%d-%Y")

        if project_id:
            # FIX 3 verified: date range always supplied
            r = run(f"get_project_logs(default month: {start} → {end})",
                    lambda: client.get_project_logs(portal_id, project_id))
            if r is not None:
                ok(f"Log entries: {len(r)}")
                if r: pprint("logs", r[:3])

            # Explicit date range
            run(f"get_project_logs(explicit {start} → {end})",
                lambda: client.get_project_logs(portal_id, project_id, start, end))

        if project_id and task_id:
            # FIX 4 verified: empty body handled gracefully
            r = run(f"get_task_logs({task_id!r})  [graceful empty body]",
                    lambda: client.get_task_logs(portal_id, project_id, task_id))
            if r is not None:
                ok(f"Task log entries: {len(r)} (0 is valid — no logs yet)")

    # ── 6: Subtasks ───────────────────────────────────────────────────────────
    if run_all or mode == "subtasks":
        hdr("6 · Subtasks")

        if project_id is None:
            ps = client.get_projects(portal_id)
            if ps: project_id = ps[0]["id"]
        if project_id and task_id is None:
            ts = client.get_tasks(portal_id, project_id)
            if ts: task_id = ts[0]["id"]

        if project_id and task_id:
            subtasks = run("get_subtasks()",
                           lambda: client.get_subtasks(portal_id, project_id, task_id))
            if subtasks is not None:
                ok(f"Subtask count: {len(subtasks)} (0 is valid — none created yet)")
                if subtasks: pprint("subtasks", subtasks[:2])

            # Create a test subtask
            created = run("create_subtask(name='Test Subtask')",
                          lambda: client.create_subtask(
                              portal_id, project_id, task_id,
                              name="Test Subtask [auto-created by test_zoho_client.py]",
                              priority="low"))
            if created and created.get("id"):
                subtask_id = created["id"]
                ok(f"Created subtask id={subtask_id}")

                run("update_subtask(status='Closed')",
                    lambda: client.update_subtask(
                        portal_id, project_id, task_id, subtask_id, {"status": "Closed"}))

        else:
            warn("Skipping subtask tests — need a project and task ID")

    # ── 7: Assign + Status ────────────────────────────────────────────────────
    if run_all or mode == "assign":
        hdr("7 · Assign Task + Update Status")

        if project_id is None:
            ps = client.get_projects(portal_id)
            if ps: project_id = ps[0]["id"]
        if project_id and task_id is None:
            ts = client.get_tasks(portal_id, project_id)
            if ts: task_id = ts[0]["id"]

        users = client.get_portal_users(portal_id)
        if users and project_id and task_id:
            user_id = users[0]["id"]
            info(f"Assigning task {task_id} to user {users[0]['name']!r} (id={user_id})")

            run("assign_task()",
                lambda: client.assign_task(portal_id, project_id, task_id, user_id))

            run("update_task_status(status='In Progress')",
                lambda: client.update_task_status(
                    portal_id, project_id, task_id, "In Progress"))

            run("update_task_status(status='Open')  [reset]",
                lambda: client.update_task_status(
                    portal_id, project_id, task_id, "Open"))
        else:
            warn("Skipping — need project, task, and at least one user")

    # ── Summary ───────────────────────────────────────────────────────────────
    hdr("Test Summary")
    total = PASS + FAIL
    print(f"  {G}{PASS}/{total} passed{X}  |  {R}{FAIL}/{total} failed{X}\n")

    if FAIL == 0:
        print(f"  {G}{B}All tests passed.{X}")
        print("  → API is working correctly.")
        print("  → If the Streamlit agent shows wrong data, it is the LLM hallucinating.")
        print("  → Check logs/agent.log to see exactly what tools were called and what they returned.")
    else:
        print(f"  {R}{B}Some tests failed.{X}")
        print("  → Run:  LOG_LEVEL=DEBUG python test_zoho_client.py")
        print("  → Check: logs/zoho_client.log for full HTTP trace")
        print("  → Common causes:")
        print("     401 → Wrong DC or expired token")
        print("     403 → Missing OAuth scope")
        print("     400 → Wrong parameter value (check log for details)")
        print("     404 → Wrong portal/project ID")

    print(f"\n  HTTP log: logs/zoho_client.log")
    print(f"  Agent log: logs/agent.log  (set LOG_LEVEL=DEBUG for verbose output)\n")


if __name__ == "__main__":
    main()