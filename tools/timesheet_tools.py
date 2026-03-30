"""
tools/timesheet_tools.py — LangChain @tool definitions for timesheet operations.
"""

import json
from langchain_core.tools import tool
from api.zoho_client import ZohoClient


def make_timesheet_tools(client: ZohoClient, portal_id: str) -> list:
    """Return timesheet-related LangChain tools bound to client + portal."""

    @tool
    def log_work_hours(
        project_id: str,
        task_id: str,
        date: str,
        hours: float,
        notes: str = "",
        billable: bool = False,
    ) -> str:
        """
        Log work hours against a specific task.

        Args:
            project_id: The Zoho project ID.
            task_id:    The Zoho task ID.
            date:       Date of work in MM-DD-YYYY format (e.g. "03-15-2025").
            hours:      Number of hours to log (decimals supported, e.g. 1.5).
            notes:      Optional notes about the work done.
            billable:   Whether the hours are billable (default: False).

        Returns:
            JSON confirmation or error.
        """
        try:
            bill_status = "Billable" if billable else "Non Billable"
            result = client.log_hours(
                portal_id, project_id, task_id,
                date=date, hours=hours, notes=notes, bill_status=bill_status
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def get_task_logs(project_id: str, task_id: str) -> str:
        """
        Get all timesheet entries logged against a specific task.

        Args:
            project_id: The Zoho project ID.
            task_id:    The Zoho task ID.

        Returns:
            JSON list of timesheet entries with user, date, hours, and notes.
        """
        try:
            logs = client.get_task_logs(portal_id, project_id, task_id)
            if not logs:
                return json.dumps({"message": "No time logs found for this task.", "logs": []})
            total = sum(l["hours"] for l in logs)
            return json.dumps({"total_hours": round(total, 2), "count": len(logs), "logs": logs})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return [log_work_hours, get_task_logs]
