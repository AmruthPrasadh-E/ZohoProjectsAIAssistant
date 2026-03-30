"""
tools/user_tools.py — LangChain @tool definitions for users and utilization.
"""

import json
from langchain_core.tools import tool
from api.zoho_client import ZohoClient


def make_user_tools(client: ZohoClient, portal_id: str) -> list:
    """Return user-related LangChain tools bound to client + portal."""

    @tool
    def list_portal_users() -> str:
        """
        List all users in the current Zoho Projects portal.

        Returns a JSON list of users with their ID, name, email, and role.
        Use the user IDs returned here when calling assign_task.
        """
        try:
            users = client.get_portal_users(portal_id)
            if not users:
                return json.dumps({"message": "No users found.", "users": []})
            return json.dumps({"count": len(users), "users": users})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def list_project_users(project_id: str) -> str:
        """
        List all users assigned to a specific project.

        Args:
            project_id: The Zoho project ID.

        Returns:
            JSON list of users with ID, name, email, and role.
        """
        try:
            users = client.get_project_users(portal_id, project_id)
            if not users:
                return json.dumps({"message": "No users found for this project.", "users": []})
            return json.dumps({"count": len(users), "users": users})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def get_user_utilization(from_date: str = "", to_date: str = "") -> str:
        """
        Get a utilization breakdown: total hours logged per team member across all projects.

        Args:
            from_date: Optional start date in MM-DD-YYYY format.
            to_date:   Optional end date in MM-DD-YYYY format.

        Returns:
            JSON with per-user hour totals, billable hours, and utilization percentage.
        """
        try:
            projects = client.get_projects(portal_id)
            utilization: dict[str, dict] = {}

            for project in projects:
                try:
                    logs = client.get_project_logs(
                        portal_id,
                        project["id"],
                        from_date=from_date or None,
                        to_date=to_date or None,
                    )
                except Exception:
                    continue

                for log in logs:
                    user = log["user"] or "Unassigned"
                    if user not in utilization:
                        utilization[user] = {
                            "user": user,
                            "total_hours": 0.0,
                            "billable_hours": 0.0,
                            "projects": set(),
                        }
                    utilization[user]["total_hours"] += log["hours"]
                    if log["billable"]:
                        utilization[user]["billable_hours"] += log["hours"]
                    utilization[user]["projects"].add(project["name"])

            result = []
            for u in utilization.values():
                total = u["total_hours"]
                bill = u["billable_hours"]
                result.append(
                    {
                        "user": u["user"],
                        "total_hours": round(total, 2),
                        "billable_hours": round(bill, 2),
                        "non_billable_hours": round(total - bill, 2),
                        "utilization_pct": round(bill / total * 100, 1) if total > 0 else 0.0,
                        "active_projects": list(u["projects"]),
                    }
                )

            result.sort(key=lambda x: x["total_hours"], reverse=True)

            if not result:
                return json.dumps({"message": "No timesheet data found for the selected period.", "utilization": []})
            return json.dumps({"count": len(result), "utilization": result})

        except Exception as e:
            return json.dumps({"error": str(e)})

    return [list_portal_users, list_project_users, get_user_utilization]
