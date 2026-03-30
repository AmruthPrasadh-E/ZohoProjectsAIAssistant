"""
tools/project_tools.py — LangChain tools for project operations.
"""

import json
from langchain_core.tools import tool
from api.zoho_client import ZohoClient


def make_project_tools(client: ZohoClient, portal_id: str) -> list:

    @tool
    def list_projects(status: str = "active") -> str:
        """
        List Zoho Projects in the portal.

        Args:
            status: active | archived | all  (default: active)
        """
        try:
            projects = client.get_projects(portal_id, status=status)
            if not projects:
                return json.dumps({"message": f"No {status} projects found.", "projects": []})
            return json.dumps({"count": len(projects), "projects": projects})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def get_project_details(project_id: str) -> str:
        """
        Get full details of a specific project.

        Args:
            project_id: Zoho project ID.
        """
        try:
            return json.dumps(client.get_project_details(portal_id, project_id))
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def create_project(
        name:        str,
        description: str = "",
        start_date:  str = "",
        end_date:    str = "",
        owner_id:    str = "",
    ) -> str:
        """
        Create a new project in the Zoho Projects portal.

        Args:
            name:        Project name (required).
            description: Optional description.
            start_date:  Optional start date in MM-DD-YYYY format.
            end_date:    Optional end/due date in MM-DD-YYYY format.
            owner_id:    Optional user `id` to assign as project owner.
                         Call list_portal_users() first to find the id.

        Returns:
            JSON with the created project's id, name, and details.

        Example:
            create_project(name="Mobile App", start_date="04-01-2026", end_date="06-30-2026")
        """
        try:
            project = client.create_project(
                portal_id,
                name        = name,
                description = description,
                start_date  = start_date,
                end_date    = end_date,
                owner_id    = owner_id,
            )
            return json.dumps({"success": True, "project": project})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return [list_projects, get_project_details, create_project]