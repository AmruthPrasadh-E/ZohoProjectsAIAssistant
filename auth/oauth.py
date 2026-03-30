"""
auth/oauth.py — Zoho OAuth 2.0 Authorization Code flow, Streamlit-safe.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import httpx
import streamlit as st

import config

# File-based CSRF state store — survives Streamlit's session reset on redirect
_STATE_FILE = Path(__file__).parent / ".oauth_state_store.json"
_STATE_TTL  = 600   # 10 minutes

_SCOPE = ",".join(config.ZOHO_SCOPES)


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def get_authorization_url() -> str:
    """
    Build and return the Zoho OAuth authorization URL.
    Persists a CSRF state token to disk (not session_state).
    """
    state = secrets.token_urlsafe(24)
    _save_state(state)
    params = (
        f"?scope={_SCOPE}"
        f"&client_id={config.ZOHO_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={config.ZOHO_REDIRECT_URI}"
        f"&access_type=offline"
        f"&state={state}"
        f"&prompt=consent"
    )
    return f"{config.ZOHO_ACCOUNTS_URL}/oauth/v2/auth{params}"


def exchange_code_for_token(code: str, state: str, accounts_server: Optional[str] = None) -> dict:
    """
    Validate the CSRF state and exchange the authorization code for tokens.

    Args:
        code:            The `code` query param returned by Zoho.
        state:           The `state` query param returned by Zoho.
        accounts_server: The `accounts-server` query param returned by Zoho.
                         MUST be used for the token endpoint when present —
                         it tells us the exact DC the user authenticated on.

    Returns:
        Token dict with: access_token, refresh_token, expires_in, expiry_ts,
                         accounts_server (for future refreshes).
    Raises:
        ValueError on state mismatch or Zoho error.
        httpx.HTTPStatusError on network/HTTP error.
    """
    _verify_and_consume_state(state)

    # ── KEY FIX: use the accounts-server Zoho gave us, not our config ──
    token_base = (accounts_server or config.ZOHO_ACCOUNTS_URL).rstrip("/")
    token_url  = f"{token_base}/oauth/v2/token"

    payload = {
        "code":          code,
        "client_id":     config.ZOHO_CLIENT_ID,
        "client_secret": config.ZOHO_CLIENT_SECRET,
        "redirect_uri":  config.ZOHO_REDIRECT_URI,
        "grant_type":    "authorization_code",
    }

    with httpx.Client(timeout=15) as http:
        resp = http.post(token_url, data=payload)
        resp.raise_for_status()

    data = resp.json()
    if "error" in data:
        raise ValueError(f"Zoho returned: {data['error']}")

    # Store accounts_server so refresh_access_token hits the right DC
    data["accounts_server"] = token_base
    return _attach_expiry(data)


def refresh_access_token(refresh_token: str) -> dict:
    """Silently obtain a new access token using the stored refresh token."""
    # Use the accounts_server we stored at exchange time (correct DC)
    token_base = st.session_state.get("accounts_server", config.ZOHO_ACCOUNTS_URL).rstrip("/")
    token_url  = f"{token_base}/oauth/v2/token"

    payload = {
        "refresh_token": refresh_token,
        "client_id":     config.ZOHO_CLIENT_ID,
        "client_secret": config.ZOHO_CLIENT_SECRET,
        "grant_type":    "refresh_token",
    }
    with httpx.Client(timeout=15) as http:
        resp = http.post(token_url, data=payload)
        resp.raise_for_status()

    data = resp.json()
    if "error" in data:
        raise ValueError(f"Token refresh error: {data['error']}")

    data.setdefault("refresh_token", refresh_token)
    data["accounts_server"] = token_base
    return _attach_expiry(data)


def store_tokens(token_data: dict) -> None:
    """Persist token dict into st.session_state."""
    st.session_state["access_token"]     = token_data["access_token"]
    st.session_state["token_expiry_ts"]  = token_data.get("expiry_ts", time.time() + 3540)
    st.session_state["code_exchanged"]   = True          # ← prevents double-exchange
    if "refresh_token" in token_data:
        st.session_state["refresh_token"]    = token_data["refresh_token"]
    if "accounts_server" in token_data:
        st.session_state["accounts_server"]  = token_data["accounts_server"]


def get_valid_access_token() -> Optional[str]:
    """Return a valid access token, refreshing silently if needed."""
    token = st.session_state.get("access_token")
    if not token:
        return None
    if time.time() < st.session_state.get("token_expiry_ts", 0):
        return token
    refresh_tok = st.session_state.get("refresh_token")
    if not refresh_tok:
        return None
    try:
        new_tokens = refresh_access_token(refresh_tok)
        store_tokens(new_tokens)
        return new_tokens["access_token"]
    except Exception:
        return None


def is_authenticated() -> bool:
    return get_valid_access_token() is not None


def logout() -> None:
    for key in [
        "access_token", "refresh_token", "token_expiry_ts", "accounts_server",
        "code_exchanged", "zoho_portals", "active_portal_id", "active_portal_name",
        "portals_loaded", "agent_executor", "messages",
    ]:
        st.session_state.pop(key, None)


# ═══════════════════════════════════════════════════════════════════════════════
# PRIVATE — file-based CSRF state store
# ═══════════════════════════════════════════════════════════════════════════════

def _save_state(state: str) -> None:
    store = _load_store()
    store[state] = time.time() + _STATE_TTL
    _write_store(store)


def _verify_and_consume_state(state: str) -> None:
    store = _load_store()
    expiry = store.get(state)
    if expiry is None:
        raise ValueError(
            "OAuth state not found. The 10-minute window may have expired, "
            "or the login was started in a different browser tab. "
            "Please click 'Connect to Zoho Projects' and try again."
        )
    if time.time() > expiry:
        store.pop(state, None)
        _write_store(store)
        raise ValueError("OAuth state expired (10-minute window). Please log in again.")
    store.pop(state)
    _write_store(store)


def _load_store() -> dict:
    try:
        if _STATE_FILE.exists():
            raw = _STATE_FILE.read_text(encoding="utf-8").strip()
            if raw:
                data = json.loads(raw)
                now = time.time()
                return {k: v for k, v in data.items() if v > now}
    except Exception:
        pass
    return {}


def _write_store(store: dict) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(store), encoding="utf-8")
    except Exception:
        pass


def _attach_expiry(data: dict) -> dict:
    data["expiry_ts"] = time.time() + int(data.get("expires_in", 3600)) - 60
    return data