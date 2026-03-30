"""
tools/task_tools.py — LangChain tools for task + subtask operations.
"""

import json
from langchain_core.tools import tool
from api.zoho_client import ZohoClient


def make_task_tools(client: ZohoClient, portal_id: str) -> list:

    @tool
    def list_tasks(project_id: str, status: str = "", owner: str = "") -> str:
        """
        List tasks in a project, with optional filters.

        Args:
            project_id: Zoho project ID.
            status:     Optional — open | closed | inprogress.
            owner:      Optional partial assignee name.
        """
        try:
            filters = {}
            if status: filters["status"] = status
            if owner:  filters["owner"]  = owner
            tasks = client.get_tasks(portal_id, project_id, filters=filters or None)
            if not tasks:
                return json.dumps({"message": "No tasks found.", "tasks": []})
            return json.dumps({"count": len(tasks), "tasks": tasks})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def get_task_detail(project_id: str, task_id: str) -> str:
        """Get full details of a task, including its subtasks."""
        try:
            return json.dumps(client.get_task_detail(portal_id, project_id, task_id))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def get_task_statuses(project_id: str) -> str:
        """
        Get all available task statuses for a project, with their IDs and names.
        Always call this before update_task_status to know valid status names.

        Args:
            project_id: Zoho project ID.

        Returns:
            JSON list of {id, name, type} objects.
        """
        try:
            statuses = client.get_task_statuses(portal_id, project_id)
            return json.dumps({"statuses": statuses})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def create_task(project_id: str, name: str, description: str = "",
                    due_date: str = "", priority: str = "none") -> str:
        """
        Create a new task.

        Args:
            project_id:  Zoho project ID.
            name:        Task title (required).
            description: Optional description.
            due_date:    Optional due date MM-DD-YYYY.
            priority:    none | low | medium | high.
        """
        try:
            task = client.create_task(portal_id, project_id, name,
                                      description=description, due_date=due_date,
                                      priority=priority)
            return json.dumps({"success": True, "task": task})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def update_task_status(project_id: str, task_id: str, status_name_or_id: str) -> str:
        """
        Update the status of a task.

        PREFERRED: Pass the numeric status_id directly from list_tasks() output.
          Each task in list_tasks() has a "status_id" field. Find a task that
          already has the target status, copy its status_id, and pass it here.
          Example: if "Requirement Specification" has status_id="430209000000013001"
                   for "In Progress", pass that ID to set another task to In Progress.

        ALTERNATIVE: Pass a display name like "In Progress" — it will be resolved
          automatically by scanning existing task statuses.

        Args:
            project_id:        Zoho project ID.
            task_id:           Zoho task ID to update.
            status_name_or_id: Numeric status_id from list_tasks(), OR a display name.
        """
        try:
            result = client.update_task_status(portal_id, project_id,
                                               task_id, status_name_or_id)
            return json.dumps({"success": True, "result": result})
        except ValueError as e:
            return json.dumps({
                "error": str(e),
                "hint": "Call list_tasks() and use the status_id from a task "
                        "that already has the desired status."
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def update_task_fields(project_id: str, task_id: str,
                           due_date: str = "", start_date: str = "",
                           name: str = "", priority: str = "",
                           description: str = "", percent: int = -1) -> str:
        """
        Update editable fields of a task — due date, start date, name,
        priority, description, or completion percentage.

        Args:
            project_id:  Zoho project ID.
            task_id:     Zoho task ID.
            due_date:    New due date in MM-DD-YYYY format.
            start_date:  New start date in MM-DD-YYYY format.
            name:        New task name.
            priority:    none | low | medium | high.
            description: New description text.
            percent:     Completion % (0–100). Pass -1 to leave unchanged.
        """
        try:
            fields: dict = {}
            if due_date:                 fields["end_date"]     = due_date
            if start_date:               fields["start_date"]   = start_date
            if name:                     fields["name"]         = name
            if priority:                 fields["priority"]     = priority
            if description:              fields["description"]  = description
            if percent is not None and percent >= 0:
                fields["percent_complete"] = str(percent)
            if not fields:
                return json.dumps({"error": "No fields to update provided."})
            result = client.update_task_fields(portal_id, project_id, task_id, fields)
            return json.dumps({"success": True, "result": result})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def assign_task(project_id: str, task_id: str, user_id: str) -> str:
        """
        Assign a task to a team member with automatic verification.

        WORKFLOW:
          1. Call list_project_users(project_id) to get users.
          2. Pass either the `id` OR `zpuid` field — the tool tries both.
          3. The tool confirms assignment by re-reading the task.
             Returns success=true only when assignees actually changed.

        Args:
            project_id: Zoho project ID.
            task_id:    Zoho task ID.
            user_id:    Either the `id` or `zpuid` from list_project_users.
        """
        try:
            result = client.assign_task(portal_id, project_id, task_id, user_id)
            if result.get("success") and result.get("assignees"):
                return json.dumps({
                    "success":      True,
                    "assigned_via": result.get("assigned_via", ""),
                    "assignees":    result.get("assignees", []),
                })
            elif not result.get("success"):
                return json.dumps(result)   # pass error + hint through
            return json.dumps({"success": True, "result": result})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def delete_task(project_id: str, task_id: str) -> str:
        """Permanently delete a task."""
        try:
            return json.dumps(client.delete_task(portal_id, project_id, task_id))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def add_comment(project_id: str, task_id: str, comment: str) -> str:
        """Add a comment to a task."""
        try:
            return json.dumps(client.add_comment(portal_id, project_id, task_id, comment))
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Subtask tools ─────────────────────────────────────────────────────────

    @tool
    def list_subtasks(project_id: str, task_id: str) -> str:
        """List all subtasks of a parent task."""
        try:
            subtasks = client.get_subtasks(portal_id, project_id, task_id)
            if not subtasks:
                return json.dumps({"message": "No subtasks.", "subtasks": []})
            return json.dumps({"count": len(subtasks), "subtasks": subtasks})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def create_subtask(project_id: str, parent_task_id: str, name: str,
                       description: str = "", due_date: str = "",
                       priority: str = "none") -> str:
        """
        Create a subtask under an existing parent task.

        Args:
            project_id:     Zoho project ID.
            parent_task_id: The parent task's ID.
            name:           Subtask title (required).
            description:    Optional description.
            due_date:       Optional due date MM-DD-YYYY.
            priority:       none | low | medium | high.
        """
        try:
            subtask = client.create_subtask(portal_id, project_id, parent_task_id,
                                            name, description=description,
                                            due_date=due_date, priority=priority)
            return json.dumps({"success": True, "subtask": subtask})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def update_subtask(project_id: str, parent_task_id: str, subtask_id: str,
                       status: str = "", name: str = "",
                       due_date: str = "", priority: str = "") -> str:
        """
        Update a subtask — change its status, name, due date, or priority.

        Args:
            project_id:     Zoho project ID.
            parent_task_id: The parent task's ID.
            subtask_id:     The subtask ID.
            status:         New status name (use get_task_statuses for valid names).
            name:           New name.
            due_date:       New due date MM-DD-YYYY.
            priority:       none | low | medium | high.
        """
        try:
            updates: dict = {}
            if status:   updates["status"]   = status
            if name:     updates["name"]      = name
            if due_date: updates["end_date"]  = due_date
            if priority: updates["priority"]  = priority
            if not updates:
                return json.dumps({"error": "Provide at least one field to update."})
            result = client.update_subtask(portal_id, project_id,
                                           parent_task_id, subtask_id, updates)
            return json.dumps({"success": True, "subtask": result})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return [
        list_tasks, get_task_detail, get_task_statuses,
        create_task, update_task_status, update_task_fields,
        assign_task, delete_task, add_comment,
        list_subtasks, create_subtask, update_subtask,
    ]