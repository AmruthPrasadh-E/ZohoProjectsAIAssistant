"""
agent/agent.py — LangChain tool-calling agent powered by Ollama.

WHY tool-calling agent instead of ReAct
========================================
ReAct agents use text parsing: they look for exact strings like
  "Action: tool_name"
  "Action Input: {...}"
in the LLM's raw output. This breaks badly when the model:
  - Uses markdown bold: **Action:** instead of Action:
  - Outputs JSON format instead of ReAct format
  - Hallucinates fake "Observation:" blocks before calling any tool

create_tool_calling_agent uses the model's native function-calling API
(tool_calls in the response object) instead of text parsing. The model
returns a structured tool invocation, not a text block — no parsing
required, no format errors, no hallucinated observations.

Requirement: the Ollama model must support tool calling.
Recommended models: qwen2.5:7b, qwen2.5:14b, llama3.1:8b, mistral-nemo
Check: ollama show <model> | grep tools

All logs → logs/app.log  (single file for the whole application)
"""

from __future__ import annotations
import json
import logging
import logging.handlers
import os
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate

import config
from api.zoho_client import ZohoClient
from tools.project_tools import make_project_tools
from tools.task_tools import make_task_tools
from tools.user_tools import make_user_tools
from tools.timesheet_tools import make_timesheet_tools

# ── Shared app logger (single log file for everything) ───────────────────────
LOG_DIR  = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

def get_app_logger(name: str) -> logging.Logger:
    """
    Return a logger that writes to logs/app.log (shared across all modules)
    plus the console at INFO level.
    All loggers created here share the same file handler.
    """
    log = logging.getLogger(name)
    if log.handlers:
        return log

    log.setLevel(logging.DEBUG)

    # Console — INFO by default, DEBUG if LOG_LEVEL=DEBUG
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)-14s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    log.addHandler(ch)

    # File — always DEBUG, shared app.log
    # Only add the file handler once (on the root "app" logger)
    root_log = logging.getLogger("app")
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root_log.handlers):
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)-14s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root_log.addHandler(fh)
        root_log.setLevel(logging.DEBUG)

    # Propagate to root "app" logger so file handler picks it up
    log.propagate = True
    return log


_log = get_app_logger("agent")


# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are ZohoBot, an AI assistant for Zoho Projects.

STRICT RULES:
1. ALWAYS call a tool. Never answer from memory or invent names/IDs.
2. Present ONLY data returned by tools. Empty = "no results found".

CREATE PROJECT:
  Use create_project(name, description, start_date, end_date, owner_id).
  Dates in MM-DD-YYYY. owner_id from list_portal_users() if needed.
  Example: create_project(name="Mobile App", start_date="04-01-2026", end_date="06-30-2026")

TASK STATUS UPDATES:
  update_task_status() tries multiple strategies automatically and verifies the change.
  You only need to call it ONCE with either:
    a) The display name: update_task_status(project_id, task_id, status_name_or_id="In Progress")
    b) A status_id from list_tasks() output: update_task_status(..., status_name_or_id="430209000000013001")
  The tool will report "success: true" with "applied_via" only when the status ACTUALLY changed.
  If it fails, it returns "success: false" with a hint — report that to the user.

TASK FIELDS (due date, name, priority):
  update_task_fields(project_id, task_id, due_date="MM-DD-YYYY")
  Also handles: start_date, name, priority, description, percent.
  Compute relative dates ("20 days from today") yourself before calling.

ASSIGN TASK:
  Step 1: list_project_users(project_id) → get user `id` (NOT zpuid).
  Step 2: assign_task(project_id, task_id, user_id=<id>).

SUBTASKS:
  list_subtasks / create_subtask / update_subtask — all need parent_task_id.

DELETE: delete_task(project_id, task_id)
DATES:  always MM-DD-YYYY format.
"""


# ── Agent builder ─────────────────────────────────────────────────────────────

def build_agent(client: ZohoClient, portal_id: str) -> AgentExecutor:
    """
    Build a tool-calling AgentExecutor.

    Uses create_tool_calling_agent (not create_react_agent) so the model
    invokes tools via its native function-calling API rather than text parsing.
    This eliminates all "Invalid Format: Missing 'Action:'" errors.
    """
    _log.info("build_agent(portal_id=%s, model=%s, ollama=%s)",
              portal_id, config.OLLAMA_MODEL, config.OLLAMA_BASE_URL)

    llm = ChatOllama(
        base_url=config.OLLAMA_BASE_URL,
        model=config.OLLAMA_MODEL,
        temperature=0,
    )

    tools = (
        make_project_tools(client, portal_id)
        + make_task_tools(client, portal_id)
        + make_user_tools(client, portal_id)
        + make_timesheet_tools(client, portal_id)
    )
    _log.info("  registered %d tool(s): %s", len(tools), [t.name for t in tools])

    # Tool-calling agent prompt — no ReAct format needed
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent    = create_tool_calling_agent(llm, tools, prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=8,
        return_intermediate_steps=True,
    )
    _log.info("  AgentExecutor ready (tool-calling mode)")
    return executor


# ── run_agent ─────────────────────────────────────────────────────────────────

def run_agent(
    executor: AgentExecutor,
    user_message: str,
    history: list[dict],
) -> dict:
    """
    Invoke the agent.

    Returns:
        {
            "answer":     str,
            "tool_calls": [{"tool": str, "input": any, "output": str}]
        }
    """
    _log.info("=" * 60)
    _log.info("USER: %s", user_message)

    # Build LangChain message history
    from langchain_core.messages import HumanMessage, AIMessage
    lc_history = []
    for msg in history[:-1]:   # exclude current message (it's in {input})
        if msg["role"] == "user":
            lc_history.append(HumanMessage(content=msg["content"]))
        else:
            lc_history.append(AIMessage(content=msg["content"]))

    try:
        result = executor.invoke({
            "input":        user_message,
            "chat_history": lc_history,
        })
    except Exception as e:
        _log.error("Agent execution failed: %s", e, exc_info=True)
        return {
            "answer":     f"I encountered an error: {e}. Please try again.",
            "tool_calls": [],
        }

    # Log and collect intermediate steps
    tool_calls = []
    for i, (action, observation) in enumerate(result.get("intermediate_steps", []), 1):
        tool_name = getattr(action, "tool", str(action))
        tool_in   = getattr(action, "tool_input", "")
        obs_str   = str(observation)

        _log.info("  STEP %d  tool=%r  input=%s", i, tool_name, tool_in)
        _log.info("          output(preview)=%s", obs_str[:400])

        # Flag if the tool itself returned an error
        try:
            obs_data = json.loads(obs_str)
            if isinstance(obs_data, dict) and "error" in obs_data:
                _log.warning("  ⚠️  tool %r returned error: %s", tool_name, obs_data["error"])
        except Exception:
            pass

        tool_calls.append({"tool": tool_name, "input": tool_in, "output": obs_str})

    final = result.get("output", "No response generated.")
    _log.info("ANSWER: %s", final[:500])
    _log.info("=" * 60)

    return {"answer": final, "tool_calls": tool_calls}