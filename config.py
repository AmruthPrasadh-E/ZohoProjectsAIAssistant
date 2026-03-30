"""
config.py — Centralised configuration loaded from environment / .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

def _env(key: str, default: str = "") -> str:
    """Get env var and strip any surrounding quotes (common .env mistake)."""
    val = os.getenv(key, default)
    return val.strip().strip('"').strip("'")

# ── Zoho OAuth ───────────────────────────────────────────────────────────────
ZOHO_CLIENT_ID:     str = _env("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET: str = _env("ZOHO_CLIENT_SECRET")
ZOHO_REDIRECT_URI:  str = _env("ZOHO_REDIRECT_URI", "http://localhost:8501/")
ZOHO_DC:            str = _env("ZOHO_DC", "com")

# NOTE: ZOHO_ACCOUNTS_URL is used only to BUILD the authorization URL.
# The token exchange ALWAYS uses the `accounts-server` param that Zoho
# returns in its redirect callback — see auth/oauth.py for details.
_ACCOUNTS_URLS = {
    "com":    "https://accounts.zoho.com",
    "eu":     "https://accounts.zoho.eu",
    "in":     "https://accounts.zoho.in",
    "com.au": "https://accounts.zoho.com.au",
    "jp":     "https://accounts.zoho.jp",
}
_API_URLS = {
    "com":    "https://projectsapi.zoho.com",
    "eu":     "https://projectsapi.zoho.eu",
    "in":     "https://projectsapi.zoho.in",
    "com.au": "https://projectsapi.zoho.com.au",
    "jp":     "https://projectsapi.zoho.jp",
}

ZOHO_ACCOUNTS_URL: str = _ACCOUNTS_URLS.get(ZOHO_DC, _ACCOUNTS_URLS["com"])
ZOHO_API_BASE:     str = _API_URLS.get(ZOHO_DC, _API_URLS["com"]) + "/restapi"

ZOHO_SCOPES = [
    "ZohoProjects.portals.ALL",
    "ZohoProjects.projects.ALL",
    "ZohoProjects.tasks.ALL",
    "ZohoProjects.users.READ",
    "ZohoProjects.timesheets.ALL",
]

# ── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL: str = _env("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL:    str = _env("OLLAMA_MODEL", "qwen3:4b")


def validate() -> list[str]:
    missing = []
    if not ZOHO_CLIENT_ID:
        missing.append("ZOHO_CLIENT_ID")
    if not ZOHO_CLIENT_SECRET:
        missing.append("ZOHO_CLIENT_SECRET")
    return missing