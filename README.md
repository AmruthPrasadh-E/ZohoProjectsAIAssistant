# Zoho Projects AI Assistant

A Streamlit chatbot that connects to your Zoho Projects workspace and lets you
query, manage, and act on project data using plain English — powered by a local
Ollama LLM and a LangChain tool-calling agent.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture Overview](#architecture-overview)
3. [How the AI Agent Works](#how-the-ai-agent-works)
4. [Tool Catalogue](#tool-catalogue)
5. [Decision-Making Walkthrough — Real Examples](#decision-making-walkthrough--real-examples)
6. [Verification and Anti-Hallucination](#verification-and-anti-hallucination)
7. [Project Structure](#project-structure)
8. [Quick Start](#quick-start)

---

## What It Does

| Capability | Example Commands |
|---|---|
| **Query projects** | "List all active projects", "Show details of Information Management" |
| **Create projects** | "Create a project called Mobile App, due June 30th" |
| **Query tasks** | "Show all open tasks in Software Development" |
| **Create tasks** | "Create a task called Write unit tests in project Backend" |
| **Update status** | "Set Setup CI to In Progress" |
| **Set due dates** | "Set the due date of Task X to 20 days from today" |
| **Assign tasks** | "Assign Requirement Gathering to Amruth Prasadh.E" |
| **Subtasks** | "List subtasks of Requirement Specification", "Add a subtask called Review under Task X" |
| **Delete tasks** | "Delete the task called Old Spike" |
| **Team utilization** | "Show me the team's logged hours this month" |
| **Log time** | "Log 2.5 hours on Setup CI for today" |
| **Add comments** | "Add comment 'Reviewed and approved' to task X" |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit UI  (app.py)                  │
│  ┌──────────────┐  ┌───────────────────────────────────┐   │
│  │   Sidebar    │  │         Chat Interface             │   │
│  │  Log Viewer  │  │  User message → Agent → Response  │   │
│  │  Quick Prompts│ │  Tool results → Rich UI tables    │   │
│  └──────────────┘  └───────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    Agent  (agent/agent.py)                   │
│                                                              │
│  LangChain AgentExecutor (tool-calling mode)                 │
│  └── ChatOllama (qwen2.5:7b via Ollama)                     │
│  └── 19 registered tools                                    │
└──────────┬───────────────────────────────────────────────────┘
           │  tool call (structured JSON)
           ▼
┌──────────────────────────────────────────────────────────────┐
│                   Tools  (tools/*.py)                        │
│  project_tools   task_tools   user_tools   timesheet_tools  │
└──────────┬───────────────────────────────────────────────────┘
           │  Python method call
           ▼
┌──────────────────────────────────────────────────────────────┐
│               Zoho Client  (api/zoho_client.py)              │
│  HTTP POST/GET/DELETE → projectsapi.zoho.in/restapi          │
│  Token auto-refresh · ID validation · Response logging       │
└──────────────────────────────────────────────────────────────┘
```

**Authentication layer** (`auth/oauth.py`): OAuth 2.0 Authorization Code flow.
Tokens live only in `st.session_state` — never on disk. CSRF protection via
a file-based state store that survives Streamlit's cross-redirect session reset.

---

## How the AI Agent Works

### The Tool-Calling Agent (not ReAct)

The agent uses **`create_tool_calling_agent`** from LangChain, NOT the classic
ReAct pattern. This distinction is important.

**ReAct agents** parse the model's text output looking for exact strings like
`Action: tool_name` and `Action Input: {...}`. Any deviation — markdown bold,
JSON format, extra whitespace — breaks the parser. Many modern models do not
produce clean ReAct output and hallucinate fake "Observation:" blocks.

**Tool-calling agents** use the model's native function-calling API. The model
returns a structured `tool_calls` object in the response, not free-form text.
The framework extracts the tool name and arguments from that object and executes
the real API call. There is no text parsing, no format errors, and no
opportunity to hallucinate a fake API response.

```
User message
    │
    ▼
LLM decides which tool(s) to call
    │  (returns tool_calls object, not text)
    ▼
Framework extracts: tool_name + arguments
    │
    ▼
Tool function runs → calls Zoho API → returns real JSON
    │
    ▼
Framework feeds result back to LLM
    │
    ▼
LLM formulates final answer using only the real data
```

### The Agentic Loop

A single user message can trigger multiple tool calls in sequence. The
`AgentExecutor` runs an internal loop — the model can call tools, receive
results, call more tools based on those results, and only produce a final
answer when it has all the information it needs.

```
User: "Assign the task Setup CI to Amruth and set it to In Progress"
│
├─ Tool call 1: list_projects()             → finds project ID
├─ Tool call 2: list_tasks(project_id)      → finds task ID + status_id map
├─ Tool call 3: list_project_users()        → finds user's zpuid
├─ Tool call 4: assign_task(task_id, zpuid) → assigns (verified by re-read)
├─ Tool call 5: update_task_status(task_id, "In Progress") → updates (verified)
└─ Final answer: "Done — Setup CI is now In Progress, assigned to Amruth"
```

The loop is capped at 8 iterations to prevent runaway chains.

---

## Tool Catalogue

All 19 tools are defined in `tools/` and bound to the authenticated
`ZohoClient` instance and `portal_id` at agent startup.

### Project Tools (`tools/project_tools.py`)

| Tool | What it does | Key parameters |
|---|---|---|
| `list_projects` | List all projects by status | `status`: active / archived / all |
| `get_project_details` | Full details of one project | `project_id` |
| `create_project` | Create a new project | `name`, `description`, `start_date`, `end_date`, `owner_id` |

### Task Tools (`tools/task_tools.py`)

| Tool | What it does | Key parameters |
|---|---|---|
| `list_tasks` | List tasks in a project | `project_id`, `status`, `owner` |
| `get_task_detail` | Full detail + subtasks of one task | `project_id`, `task_id` |
| `get_task_statuses` | List all valid status names for a project | `project_id` |
| `create_task` | Create a new task | `project_id`, `name`, `due_date`, `priority` |
| `update_task_status` | Change task status (verified) | `project_id`, `task_id`, `status_name_or_id` |
| `update_task_fields` | Edit due date, name, priority, etc. | `project_id`, `task_id`, `due_date`, `start_date`, `name`, `priority` |
| `assign_task` | Assign task to a user (verified) | `project_id`, `task_id`, `user_id` |
| `delete_task` | Permanently delete a task | `project_id`, `task_id` |
| `add_comment` | Post a comment on a task | `project_id`, `task_id`, `comment` |
| `list_subtasks` | List subtasks of a parent task | `project_id`, `task_id` |
| `create_subtask` | Create a subtask under a parent | `project_id`, `parent_task_id`, `name` |
| `update_subtask` | Edit a subtask's fields | `project_id`, `parent_task_id`, `subtask_id` |

### User Tools (`tools/user_tools.py`)

| Tool | What it does | Key parameters |
|---|---|---|
| `list_portal_users` | All users in the portal | — |
| `list_project_users` | Users on a specific project | `project_id` |
| `get_user_utilization` | Logged hours per team member | `from_date`, `to_date` |

### Timesheet Tools (`tools/timesheet_tools.py`)

| Tool | What it does | Key parameters |
|---|---|---|
| `log_work_hours` | Log time against a task | `project_id`, `task_id`, `date`, `hours`, `billable` |
| `get_task_logs` | View time entries on a task | `project_id`, `task_id` |

---

## Decision-Making Walkthrough — Real Examples

The following examples show exactly how the agent reasons and which tools it
invokes for a given user query. Each step is visible in the chat UI as an
expandable `🔧 tool_name — view data` panel, and logged in `logs/app.log`.

---

### Example 1 — Simple Query

**User:** `"List all projects"`

```
Agent thinking:
  The user wants to see all projects. I need to call list_projects
  with no filters to get the active projects.

Step 1 → list_projects(status="active")
         ← API returns 3 projects with IDs, names, owners, dates

Final answer: "Here are your 3 active projects: ..."
UI renders: sortable table with progress bars
```

No ambiguity → single tool call → immediate answer.

---

### Example 2 — Multi-Step Action

**User:** `"Assign the Requirement Gathering task to Amruth Prasadh.E"`

```
Agent thinking:
  I need to find the task ID and the user's ID before I can assign.
  Start by listing projects to find the right one.

Step 1 → list_projects(status="active")
         ← Returns: [{id: "430209000000075007", name: "Adboy.ai"}, ...]

Agent thinking:
  I see multiple projects. "Requirement Gathering" could be in any.
  Search the most likely one first.

Step 2 → list_tasks(project_id="430209000000075007")
         ← Returns: [{id: "430209000000075171", name: "Requirement gathering",
                      assignees: ["Unassigned"]}]

Agent thinking:
  Found the task. Now I need the user's ID — must not guess it.

Step 3 → list_project_users(project_id="430209000000075007")
         ← Returns: [{id: "60068246602", zpuid: "430209000000063003",
                      name: "Amruth Prasadh.E"}]

Agent thinking:
  I have both the task ID and the user's zpuid. Call assign_task.

Step 4 → assign_task(project_id="430209000000075007",
                     task_id="430209000000075171",
                     user_id="60068246602")

         [zoho_client internally tries person_responsible=<zpuid> first]
         ← API call: POST person_responsible=430209000000063003
         ← Read-back: assignees=["Amruth Prasadh.E"]  ✓ VERIFIED

Final answer: "Done — Requirement Gathering is now assigned to Amruth Prasadh.E ✅ (verified)"
```

The agent **never guesses** the user ID or task ID — it fetches them first.
The client verifies the assignment by re-reading the task after the POST.

---

### Example 3 — Status Update with Resolution

**User:** `"Set Setup CI to In Progress"`

```
Step 1 → list_projects(status="active")
         ← Finds project "Information Management" (id: 430209000000067125)

Step 2 → list_tasks(project_id="430209000000067125")
         ← Returns tasks including:
            {id: "430209000000071007", name: "Setup CI", status: "Open",
             status_id: "430209000000000185"}
            {id: "430209000000067293", name: "Requirement Specification",
             status: "In Progress", status_id: "430209000000013001"}

Agent thinking:
  I can see "In Progress" has status_id "430209000000013001" from
  another task. I'll pass "In Progress" to update_task_status and
  the client will resolve it using the portal-wide scan.

Step 3 → update_task_status(project_id="430209000000067125",
                            task_id="430209000000071007",
                            status_name_or_id="In Progress")

         [zoho_client internally:]
         [1. Portal-wide scan finds "In Progress" → id="430209000000013001"]
         [2. Try POST custom_status=430209000000013001]
         [3. Read-back: status="In Progress"  ✓ VERIFIED]

Final answer: "Done — Setup CI is now In Progress ✅ (verified)"
```

The `custom_status` parameter (not `status`) is what Zoho Projects requires
for custom status IDs — discovered via `debug_status_probe.py`.

---

### Example 4 — Create with Computed Date

**User:** `"Create a task called Deploy to Staging in Information Management, due 20 days from today"`

```
Agent thinking:
  Today is 2026-03-30. 20 days from today = 2026-04-19 = 04-19-2026
  I need the project_id first, then I can create the task.

Step 1 → list_projects(status="active")
         ← Finds "Information Management" id="430209000000067125"

Step 2 → create_task(project_id="430209000000067125",
                     name="Deploy to Staging",
                     due_date="04-19-2026")
         ← API returns new task with id="430209000000081234"

Final answer: "Done — task 'Deploy to Staging' created with due date April 19, 2026"
UI renders: success banner with task ID
```

The agent computes the date itself — it is not passed to any tool. Tool parameters
only ever contain values the agent has computed or retrieved from prior tool calls.

---

### Example 5 — Multi-Project Aggregation

**User:** `"Show team utilization for this month"`

```
Agent thinking:
  Utilization = logged hours per user across all projects.
  get_user_utilization handles this natively.

Step 1 → get_user_utilization(from_date="03-01-2026", to_date="03-30-2026")

         [zoho_client internally iterates all projects,
          calls get_project_logs() for each, aggregates by user]

         ← Returns: [{user: "Amruth Prasadh.E",
                      total_hours: 24.5,
                      billable_hours: 18.0,
                      utilization_pct: 73.5,
                      active_projects: ["Information Management", "Adboy.ai"]}]

Final answer: "Amruth has logged 24.5 hours this month (73.5% billable)"
UI renders: horizontal bar chart + billable/non-billable donut chart
```

---

### Example 6 — Subtask Workflow

**User:** `"Add a subtask called 'Write unit tests' under the Requirement Specification task"`

```
Step 1 → list_projects()
         ← Finds "Information Management"

Step 2 → list_tasks(project_id="430209000000067125")
         ← Finds "Requirement Specification" id="430209000000067293"
            has_subtasks: true

Step 3 → create_subtask(project_id="430209000000067125",
                        parent_task_id="430209000000067293",
                        name="Write unit tests")
         ← API returns new subtask id="430209000000090011"

Final answer: "Done — subtask 'Write unit tests' added under Requirement Specification"
```

---

## Verification and Anti-Hallucination

### The Silent-Success Problem

Zoho Projects returns HTTP 200 for many write operations even when the change
was **not** applied — for example, sending a status name where an ID was
expected, or sending a user's portal-membership ID instead of their platform
UID. Without verification, the agent would report success while the data in
Zoho remained unchanged.

### How Verification Works

Both `update_task_status()` and `assign_task()` implement a
**try → verify → retry** loop:

```
For each attempt (in priority order):
    1. POST the change to Zoho
    2. Immediately re-GET the task from the API
    3. Compare the field value before and after
    4. If changed → return success=True with applied_via field
    5. If unchanged → try next attempt format
If all attempts fail → return success=False with a human-readable hint
```

The UI only shows `✅ Done — status set to "In Progress" *(verified)*` when
the re-read confirms the change. If all attempts fail, the UI shows the error
message and a specific hint (e.g. "Run debug_status_probe.py").

### Anti-Hallucination Prompt Rules

The agent system prompt enforces strict rules:

```
1. ALWAYS call a tool. Never answer from memory or invent names/IDs.
2. Present ONLY data returned by tools.
3. Empty result → say "no results found". Do NOT invent data.
4. For status updates: pass the display name — the client resolves to ID.
5. For assignment: pass either id or zpuid — the client tries both.
```

These rules prevent the LLM from inventing project names, user names, task IDs,
or fabricating API responses — the failure mode observed with ReAct agents when
tool calls fail to parse.

---

## Project Structure

```
zoho_projects/
│
├── app.py                      # Streamlit UI, OAuth callback, chat loop
├── config.py                   # Central config from .env
├── requirements.txt
├── .env.example
├── SETUP_GUIDE.md              # This setup guide
├── README.md                   # This file
│
├── auth/
│   └── oauth.py                # OAuth 2.0: auth URL, code exchange,
│                               # token refresh, file-based CSRF state
│
├── api/
│   └── zoho_client.py          # Zoho REST API client
│                               # All HTTP calls, ID validation, logging,
│                               # verify-and-retry for writes
│
├── tools/
│   ├── project_tools.py        # list_projects, create_project, get_project_details
│   ├── task_tools.py           # 12 task + subtask tools
│   ├── user_tools.py           # list_users, get_user_utilization
│   └── timesheet_tools.py      # log_work_hours, get_task_logs
│
├── agent/
│   └── agent.py                # build_agent() → AgentExecutor
│                               # run_agent() → answer + tool_call log
│                               # Shared app logger
│
├── ui/
│   └── components.py           # Streamlit renderers:
│                               # tables, charts, cards, action banners
│
├── logs/
│   └── app.log                 # All logs from all modules (rotating, 2 MB)
│
└── debug tools/
    ├── test_zoho_client.py     # Standalone API tester (no agent)
    ├── debug_status_probe.py   # Finds working status update format
    └── debug_assign_probe.py   # Finds working assignment format
```

---

## Quick Start

```bash
# 1. Install Ollama and pull a model
ollama pull qwen2.5:7b && ollama serve

# 2. Register a Zoho Server-based Application at https://api-console.zoho.com/
#    Redirect URI: http://localhost:8501/

# 3. Configure
cp .env.example .env
# Edit .env with your ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_DC

# 4. Install and run
pip install -r requirements.txt
streamlit run app.py

# 5. Click "Connect to Zoho Projects" and authorize
# 6. Start chatting
```

See **SETUP_GUIDE.md** for the complete setup walkthrough including
troubleshooting for every known error.

---

## Zoho API References

| Resource | URL |
|---|---|
| Zoho Projects REST API | https://www.zoho.com/projects/help/rest-api/projects-api.html |
| Zoho Projects V3 API | https://projects.zoho.com/api-docs |
| Zoho OAuth 2.0 Protocol | https://www.zoho.com/accounts/protocol/oauth.html |
| Zoho API Console | https://api-console.zoho.com/ |
| Ollama Model Library | https://ollama.com/library |
| LangChain Tool Calling | https://python.langchain.com/docs/how_to/tool_calling/ |
