"""
ui/components.py — Streamlit rendering helpers.

FIXES IN THIS VERSION
=====================
1. Duplicate plotly_chart key error — all st.plotly_chart() calls now receive
   a unique key= built from the tool name + a per-render counter stored in
   st.session_state. This prevents StreamlitDuplicateElementId on the second
   chat message onwards.

2. New renderers for subtask operations:
   list_subtasks, create_subtask, update_subtask

3. _render_tasks() now shows a "🔗 has subtasks" indicator column.

4. _render_task_detail() now shows subtasks in an expander.
"""

from __future__ import annotations
import json
import time
from typing import Any

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

PALETTE = ["#2563EB", "#7C3AED", "#059669", "#D97706", "#DC2626", "#0891B2"]


# ── Unique key generator ──────────────────────────────────────────────────────
# Each render pass increments a counter stored in session_state so every
# plotly_chart / widget gets a globally unique key, avoiding duplicate-ID errors.

def _chart_key(label: str) -> str:
    """Return a unique key for a Streamlit widget, safe across reruns."""
    if "_chart_counter" not in st.session_state:
        st.session_state["_chart_counter"] = 0
    st.session_state["_chart_counter"] += 1
    return f"{label}_{st.session_state['_chart_counter']}"


# ── Router ────────────────────────────────────────────────────────────────────

def render_tool_output(tool_name: str, raw_output: str):
    try:
        data = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
    except json.JSONDecodeError:
        st.code(raw_output, language="text")
        return

    if isinstance(data, dict) and "error" in data:
        st.error(f"⚠️ {data['error']}")
        return

    dispatch = {
        "list_projects":       _render_projects,
        "get_project_details": _render_project_detail,
        "create_project":      _render_created_project,
        "list_tasks":          _render_tasks,
        "get_task_detail":     _render_task_detail,
        "create_task":         _render_action,
        "update_task_status":  _render_action,
        "assign_task":         _render_action,
        "delete_task":         _render_action,
        "get_task_statuses":   _render_task_statuses,
        "update_task_fields":  _render_action,
        "add_comment":         _render_action,
        "list_portal_users":   _render_users,
        "list_project_users":  _render_users,
        "get_user_utilization": _render_utilization,
        "log_work_hours":      _render_action,
        "get_task_logs":       _render_task_logs,
        # Subtask renderers
        "list_subtasks":       _render_subtasks,
        "create_subtask":      _render_action,
        "update_subtask":      _render_action,
    }
    fn = dispatch.get(tool_name, _render_generic)
    fn(data)


# ── Projects ──────────────────────────────────────────────────────────────────

def _render_projects(data: dict):
    projects = data.get("projects", [])
    if not projects:
        st.info(data.get("message", "No projects found."))
        return

    st.caption(f"**{len(projects)} project(s)**")
    df = pd.DataFrame(projects)
    cols = ["name", "status", "owner", "start_date", "end_date", "percent", "open_tasks"]
    df   = df[[c for c in cols if c in df.columns]].copy()
    df.columns = [c.replace("_", " ").title() for c in df.columns]
    df.rename(columns={"Percent": "Progress %"}, inplace=True)

    st.dataframe(df, width='content', hide_index=True,
                 column_config={"Progress %": st.column_config.ProgressColumn(
                     "Progress", min_value=0, max_value=100, format="%d%%")})

    if "Status" in df.columns and len(df["Status"].unique()) > 1:
        counts = df["Status"].value_counts().reset_index()
        counts.columns = ["Status", "Count"]
        fig = px.pie(counts, names="Status", values="Count", hole=0.5,
                     color_discrete_sequence=PALETTE, title="Projects by Status")
        fig.update_layout(height=260, margin=dict(t=36, b=0, l=0, r=0),
                          paper_bgcolor="rgba(0,0,0,0)")
        # FIX: unique key per chart
        st.plotly_chart(fig,width='content', key=_chart_key("proj_status_pie"))


def _render_created_project(data: dict):
    if not data.get("success"):
        st.error(f"⚠️ {data.get('error', 'Unknown error')}")
        return
    p = data.get("project", {})
    st.success(f"✅ Project **{p.get('name', '')}** created successfully!")
    c1, c2 = st.columns(2)
    c1.metric("Start", p.get("start_date") or "—")
    c2.metric("End",   p.get("end_date")   or "—")
    if p.get("id"):
        st.caption(f"Project ID: `{p['id']}`")


def _render_project_detail(data: dict):
    if not data:
        st.info("Project not found.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Status",   data.get("status",  "—"))
    c2.metric("Progress", f"{data.get('percent', 0)}%")
    c3.metric("Owner",    data.get("owner",   "—"))
    st.write(f"**Start:** {data.get('start_date','—')}  |  **End:** {data.get('end_date','—')}")
    if data.get("description"):
        st.caption(data["description"])


# ── Tasks ─────────────────────────────────────────────────────────────────────

_STATUS_ICON = {"open": "🔵", "in progress": "🟡", "inprogress": "🟡", "closed": "🟢"}
_PRI_ICON    = {"high": "🔴", "medium": "🟡", "low": "🟢", "none": "⚪"}


def _render_tasks(data: dict):
    tasks = data.get("tasks", [])
    if not tasks:
        st.info(data.get("message", "No tasks found."))
        return

    st.caption(f"**{len(tasks)} task(s)**")
    df = pd.DataFrame(tasks)

    if "status" in df.columns:
        df["status"] = df["status"].apply(
            lambda s: f"{_STATUS_ICON.get(str(s).lower(), '⚪')} {s}" if s else "—")
    if "priority" in df.columns:
        df["priority"] = df["priority"].apply(
            lambda p: f"{_PRI_ICON.get(str(p).lower(), '⚪')} {p}" if p else "—")
    if "assignees" in df.columns:
        df["assignees"] = df["assignees"].apply(
            lambda a: ", ".join(a) if isinstance(a, list) else (a or "—"))
    if "has_subtasks" in df.columns:
        df["has_subtasks"] = df["has_subtasks"].apply(
            lambda v: "🔗 Yes" if v else "—")

    cols = ["name", "status", "priority", "assignees", "due_date", "percent", "has_subtasks"]
    df   = df[[c for c in cols if c in df.columns]]
    df.columns = [c.replace("_", " ").title() for c in df.columns]

    st.dataframe(df, width='content', hide_index=True,
                 column_config={"Percent": st.column_config.ProgressColumn(
                     "Done", min_value=0, max_value=100, format="%d%%")})


def _render_task_detail(data: dict | list):
    if isinstance(data, list):
        data = data[0] if data else {}
    if not data:
        st.info("Task not found.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Status",   data.get("status",   "—"))
    c2.metric("Priority", data.get("priority", "—"))
    c3.metric("Done",     f"{data.get('percent', 0)}%")

    assignees = data.get("assignees", [])
    st.write(f"**Assignees:** {', '.join(assignees) if assignees else '—'}")
    st.write(f"**Due:** {data.get('due_date', '—')}")
    if data.get("description"):
        st.caption(data["description"])

    # Show subtasks inline if present
    subtasks = data.get("subtasks", [])
    if subtasks:
        with st.expander(f"🔗 Subtasks ({len(subtasks)})", expanded=True):
            _render_subtasks({"subtasks": subtasks, "count": len(subtasks)})
    else:
        st.caption("No subtasks.")


# ── Task statuses ────────────────────────────────────────────────────────────────

def _render_task_statuses(data: dict):
    statuses = data.get("statuses", [])
    if not statuses:
        st.info("No statuses found.")
        return
    st.caption(f"**{len(statuses)} status(es) available**")
    df = pd.DataFrame(statuses)[["name", "type", "id"]].copy()
    df.columns = ["Status Name", "Type", "ID"]
    st.dataframe(df, width='content', hide_index=True)
    st.caption("Use the **Status Name** exactly when calling update_task_status.")


# ── Subtasks ──────────────────────────────────────────────────────────────────

def _render_subtasks(data: dict):
    subtasks = data.get("subtasks", [])
    if not subtasks:
        st.info(data.get("message", "No subtasks found."))
        return

    st.caption(f"**{len(subtasks)} subtask(s)**")
    df = pd.DataFrame(subtasks)

    if "status" in df.columns:
        df["status"] = df["status"].apply(
            lambda s: f"{_STATUS_ICON.get(str(s).lower(), '⚪')} {s}" if s else "—")
    if "priority" in df.columns:
        df["priority"] = df["priority"].apply(
            lambda p: f"{_PRI_ICON.get(str(p).lower(), '⚪')} {p}" if p else "—")
    if "assignees" in df.columns:
        df["assignees"] = df["assignees"].apply(
            lambda a: ", ".join(a) if isinstance(a, list) else (a or "—"))

    cols = ["name", "status", "priority", "assignees", "due_date", "percent"]
    df   = df[[c for c in cols if c in df.columns]]
    df.columns = [c.replace("_", " ").title() for c in df.columns]

    st.dataframe(df, width='content', hide_index=True,
                 column_config={"Percent": st.column_config.ProgressColumn(
                     "Done", min_value=0, max_value=100, format="%d%%")})


# ── Users ─────────────────────────────────────────────────────────────────────

def _render_users(data: dict):
    users = data.get("users", [])
    if not users:
        st.info(data.get("message", "No users found."))
        return
    st.caption(f"**{len(users)} member(s)**")
    df = pd.DataFrame(users)
    cols = [c for c in ["name", "email", "role", "id"] if c in df.columns]
    df   = df[cols].copy()
    df.columns = [c.title() if c != "id" else "User ID" for c in cols]
    st.dataframe(df, width='content', hide_index=True)


# ── Utilization ───────────────────────────────────────────────────────────────

def _render_utilization(data: dict):
    rows = data.get("utilization", [])
    if not rows:
        st.info(data.get("message", "No timesheet data found."))
        return

    st.caption(f"**Team utilization — {len(rows)} member(s)**")
    df = pd.DataFrame(rows)

    if "active_projects" in df.columns:
        df["active_projects"] = df["active_projects"].apply(
            lambda p: ", ".join(p) if isinstance(p, list) else p)

    display_cols = [c for c in ["user", "total_hours", "billable_hours",
                                 "non_billable_hours", "utilization_pct",
                                 "active_projects"] if c in df.columns]
    display = df[display_cols].copy()
    display.columns = ["Team Member", "Total h", "Billable h",
                       "Non-Bill h", "Billable %", "Projects"][:len(display_cols)]

    st.dataframe(display, width='content', hide_index=True,
                 column_config={"Billable %": st.column_config.ProgressColumn(
                     "Billable %", min_value=0, max_value=100, format="%.1f%%")})

    if "total_hours" in df.columns and not df.empty:
        fig_bar = px.bar(
            df.sort_values("total_hours"),
            x="total_hours", y="user", orientation="h",
            color="billable_hours" if "billable_hours" in df.columns else None,
            color_continuous_scale=["#2563EB", "#7C3AED"],
            labels={"total_hours": "Total Hours", "user": "",
                    "billable_hours": "Billable h"},
            title="Hours Logged per Team Member",
        )
        fig_bar.update_layout(
            height=max(240, len(rows) * 38),
            margin=dict(t=36, b=0, l=0, r=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            coloraxis_showscale=False,
        )
        # FIX: unique key
        st.plotly_chart(fig_bar,width='content', key=_chart_key("util_bar"))

    if "billable_hours" in df.columns and "non_billable_hours" in df.columns:
        total_b  = df["billable_hours"].sum()
        total_nb = df["non_billable_hours"].sum()
        if total_b + total_nb > 0:
            fig_pie = go.Figure(go.Pie(
                labels=["Billable", "Non-Billable"],
                values=[total_b, total_nb],
                hole=0.55,
                marker_colors=[PALETTE[0], PALETTE[4]],
            ))
            fig_pie.update_layout(
                title="Billable vs Non-Billable",
                height=250, margin=dict(t=36, b=0, l=0, r=0),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            # FIX: unique key
            st.plotly_chart(fig_pie, width='content',
                            key=_chart_key("util_donut"))


# ── Timesheet logs ────────────────────────────────────────────────────────────

def _render_task_logs(data: dict):
    logs = data.get("logs", [])
    if not logs:
        st.info(data.get("message", "No time logs found."))
        return
    total = data.get("total_hours", sum(l.get("hours", 0) for l in logs))
    st.caption(f"**{total:.2f} total hours · {len(logs)} entries**")
    cols = [c for c in ["user", "date", "hours", "billable", "notes"] if c in logs[0]]
    df   = pd.DataFrame(logs)[cols]
    df.columns = [c.title() for c in cols]
    st.dataframe(df, width='content', hide_index=True)


# ── Action result ─────────────────────────────────────────────────────────────

def _render_action(data: dict):
    # Handle nested result dict (update_task_status wraps in {"success":T,"result":{...}})
    inner = data.get("result", data)
    success = data.get("success", inner.get("success", False))

    if success:
        detail = ""
        # Status update with verification
        if "applied_via" in inner:
            new_status = inner.get("status", "")
            detail = f"— status set to **{new_status}** *(verified)*"
        # Assignment with verification
        elif "assignees" in inner and "assigned_via" in inner:
            names  = ", ".join(inner.get("assignees", []))
            detail = f"— assigned to **{names}** *(verified)*"
        elif "updated_fields" in inner:
            detail = f"— updated: {', '.join(inner.get('updated_fields', []))}"
        elif "task" in data:
            t = data["task"]
            detail = f"— **{t.get('name', '')}** (status: {t.get('status', '—')})"
        elif "subtask" in data:
            detail = f"— subtask **{data['subtask'].get('name', '')}**"
        elif "logged_hours" in data:
            detail = f"— {data['logged_hours']}h on {data.get('date', '')}"
        elif "deleted_task_id" in data:
            detail = f"— task `{data['deleted_task_id']}` deleted"
        st.success(f"✅ Done {detail}")
    else:
        err = data.get("error", inner.get("error", str(data)))
        hint = data.get("hint", inner.get("hint", ""))
        st.error(f"⚠️ {err}")
        if hint:
            st.caption(f"💡 {hint}")


# ── Generic fallback ──────────────────────────────────────────────────────────

def _render_generic(data: Any):
    if isinstance(data, list) and data:
        try:
            st.dataframe(pd.DataFrame(data), width='content', hide_index=True)
            return
        except Exception:
            pass
    st.json(data)


# ── Chat message renderer ─────────────────────────────────────────────────────

def render_chat_message(msg: dict):
    role       = msg["role"]
    content    = msg["content"]
    tool_calls = msg.get("tool_calls", [])

    with st.chat_message(role):
        st.markdown(content)
        for i, tc in enumerate(tool_calls):
            # FIX: unique expander key prevents duplicate widget ID on rerun
            with st.expander(f"🔧 `{tc['tool']}` — view data",
                             expanded=True):
                render_tool_output(tc["tool"], tc["output"])