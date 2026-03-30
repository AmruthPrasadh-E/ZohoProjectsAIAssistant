"""
app.py — Streamlit entry point for Zoho Projects AI Assistant.

Run:  streamlit run app.py

Auth flow:
  1. No token  → login page with "Connect to Zoho" button.
  2. Zoho redirects back with ?code=&state=&accounts-server= →
     _handle_callback() exchanges the code (using the correct DC) and reruns.
  3. Token present → portal load, agent build, chat interface.
"""

import streamlit as st
import os

st.set_page_config(
    page_title="Zoho Projects AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

from urllib.parse import unquote
import config
from pathlib import Path
from auth import oauth
from api.zoho_client import ZohoClient, api_base_from_accounts_server
from agent.agent import build_agent, run_agent
from ui.components import render_chat_message, render_tool_output

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg,#0F172A 0%,#1E293B 100%);
    border-right: 1px solid #334155;
}
section[data-testid="stSidebar"] * { color:#E2E8F0 !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color:#7DD3FC !important; }

.auth-card {
    max-width: 520px; margin: 80px auto; text-align: center;
    background: white; border-radius: 20px; padding: 48px 40px;
    box-shadow: 0 8px 40px rgba(0,0,0,0.10); border: 1px solid #E2E8F0;
}
.auth-card h2 { font-size: 1.8rem; font-weight: 700; color: #0F172A; margin: 10px 0 6px; }
.auth-card p  { color: #64748B; font-size: 1rem; margin-bottom: 28px; }
.connect-btn {
    display: inline-block;
    background: linear-gradient(135deg,#2563EB,#7C3AED);
    color: white !important; text-decoration: none;
    border-radius: 12px; padding: 14px 40px;
    font-size: 1rem; font-weight: 600;
    box-shadow: 0 4px 16px rgba(37,99,235,0.35);
}
.badge-ok { display:inline-block; background:#DCFCE7; color:#166534;
            border-radius:20px; padding:3px 12px; font-size:.78rem; font-weight:600; }
</style>
""", unsafe_allow_html=True)


# ── Session defaults ──────────────────────────────────────────────────────────
def _init():
    for k, v in {
        "messages":           [],
        "agent_executor":     None,
        "portals":            [],
        "active_portal_id":   None,
        "active_portal_name": "",
        "portals_loaded":     False,
        "code_exchanged":     False,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── OAuth callback ────────────────────────────────────────────────────────────
def _handle_callback():
    """
    Reads ?code=, ?state=, and ?accounts-server= from the URL.

    KEY FIXES vs previous version:
    1. Reads `accounts-server` from Zoho's redirect and passes it to
       exchange_code_for_token() so the token request hits the right DC.
    2. Guards with st.session_state["code_exchanged"] to prevent Streamlit's
       re-runs from attempting a second exchange of the already-used code.
    """
    params = st.query_params

    code  = params.get("code")
    state = params.get("state", "")

    if not code:
        return  # Normal render, nothing to do

    # Guard: don't re-exchange on Streamlit reruns
    if st.session_state.get("code_exchanged") or oauth.is_authenticated():
        st.query_params.clear()
        return

    # Extract the accounts-server Zoho returned (URL-decoded)
    raw_server = params.get("accounts-server", "")
    accounts_server = unquote(raw_server) if raw_server else None

    with st.spinner("Connecting to Zoho…"):
        try:
            tokens = oauth.exchange_code_for_token(code, state, accounts_server)
            oauth.store_tokens(tokens)
            st.query_params.clear()
            st.rerun()
        except ValueError as e:
            st.error(f"**Authentication error:** {e}")
            st.query_params.clear()
            st.stop()
        except Exception as e:
            st.error(f"**Unexpected error during login:** {e}")
            st.query_params.clear()
            st.stop()


# ── Portal loader ─────────────────────────────────────────────────────────────
def _load_portals(client: ZohoClient):
    if st.session_state["portals_loaded"]:
        return
    try:
        portals = client.get_portals()
        st.session_state["portals"] = portals
        if portals and not st.session_state["active_portal_id"]:
            st.session_state["active_portal_id"]   = portals[0]["id"]
            st.session_state["active_portal_name"] = portals[0]["name"]
        st.session_state["portals_loaded"] = True
    except Exception as e:
        st.error(f"Could not load Zoho portals: {e}")
        st.stop()


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _sidebar(client: ZohoClient):
    with st.sidebar:
        st.markdown("## 🤖 ZohoBot")
        st.markdown("*AI Assistant for Zoho Projects*")
        st.divider()

        portal_name = st.session_state.get("active_portal_name", "—")
        st.markdown(f'<span class="badge-ok">🟢 {portal_name}</span>', unsafe_allow_html=True)
        st.write("")

        portals = st.session_state.get("portals", [])
        if len(portals) > 1:
            chosen = st.selectbox("Switch Portal", [p["name"] for p in portals], key="portal_select")
            selected = next((p for p in portals if p["name"] == chosen), None)
            if selected and selected["id"] != st.session_state["active_portal_id"]:
                st.session_state["active_portal_id"]   = selected["id"]
                st.session_state["active_portal_name"] = selected["name"]
                st.session_state["agent_executor"]     = None
                st.session_state["messages"]           = []
                st.rerun()

        st.divider()
        st.markdown("#### 💡 Quick prompts")
        quick = [
            ("📋", "List all projects"),
            ("✅", "Show all open tasks"),
            ("📅", "Tasks due this week"),
        ]
        for icon, label in quick:
            if st.button(f"{icon} {label}", use_container_width=True, key=f"q_{label}"):
                st.session_state["pending"] = label


        # ── Debug token panel (add ZOHO_DEBUG=1 to .env to reveal) ───────────
        if os.getenv("ZOHO_DEBUG", "0") == "1":
            st.divider()
            st.markdown("#### 🐛 Debug Token")
            token = st.session_state.get("access_token", "")
            acct  = st.session_state.get("accounts_server", "")
            if token:
                st.text_input("Access Token (for test_zoho_client.py)",
                              value=token, key="dbg_token")
                st.text_input("Accounts Server", value=acct, key="dbg_acct")
                st.caption("Add both to .env as ZOHO_ACCESS_TOKEN and ZOHO_ACCOUNTS_SERVER")
            else:
                st.caption("No token in session yet.")


# ── Login page ────────────────────────────────────────────────────────────────
def _login_page():
    missing = config.validate()
    _, col, _ = st.columns([1, 2, 1])
    with col:
        # st.markdown('<div class="auth-card">', unsafe_allow_html=True)
        # st.markdown("# 🤖",unsafe_allow_html=True)
        st.markdown("## Zoho Projects AI Assistant",unsafe_allow_html=True)
        st.markdown(
            "<p>Manage projects, tasks, and your team through Chat</p>",
            unsafe_allow_html=True,
        )
        if missing:
            st.error(
                f"Missing configuration: **{', '.join(missing)}**\n\n"
                "See **SETUP_GUIDE.md** for instructions."
            )
        else:
            auth_url = oauth.get_authorization_url()
            st.markdown(
                f'<a class="connect-btn" href="{auth_url}" target="_self">'
                '🔐 &nbsp;Connect to Zoho Projects'
                '</a>',
                unsafe_allow_html=True,
            )
            # st.markdown(
            #     "<p style='font-size:.8rem;color:#94A3B8;margin-top:14px'>"
            #     "Secure OAuth 2.0 · Tokens stored in your browser session only"
            #     "</p>",
            #     unsafe_allow_html=True,
            # )
        # st.markdown('</div>', unsafe_allow_html=True)

        # with st.expander("📖 Setup Guide"):
        #     try:
        #         st.markdown(open("SETUP_GUIDE.md").read())
        #     except FileNotFoundError:
        #         st.info("See SETUP_GUIDE.md in the project root.")


# ── Chat page ─────────────────────────────────────────────────────────────────
def _chat_page(client: ZohoClient):
    portal_id   = st.session_state["active_portal_id"]
    portal_name = st.session_state["active_portal_name"]

    st.markdown(f"### 🤖 Zoho Projects Assistant &nbsp;·&nbsp; *{portal_name}*")
    st.caption("Ask anything about your projects and tasks.")
    st.caption(f"Model: `{config.OLLAMA_MODEL}`")
    st.divider()

    # Build agent lazily (once per portal)
    if not st.session_state["agent_executor"]:
        with st.spinner(f"Starting agent for **{portal_name}**…"):
            try:
                st.session_state["agent_executor"] = build_agent(client, portal_id)
            except Exception as e:
                st.error(
                    f"**Could not start the agent:** {e}\n\n"
                    f"Make sure Ollama is running (`ollama serve`) and the model is pulled "
                    f"(`ollama pull {config.OLLAMA_MODEL}`)."
                )
                return

    executor = st.session_state["agent_executor"]

    # Welcome message on first load
    if not st.session_state["messages"]:
        with st.chat_message("assistant"):
            st.markdown(
                f"👋 Hi! I'm ZohoBot, connected to **{portal_name}**.\n\n"
                "Try:\n"
                "- *\"List all projects\"*\n"
                "- *\"Show open tasks in project X\"*\n"
                "- *\"Create a task called Setup CI in project Backend\"*"
            )

    # Render conversation history
    for msg in st.session_state["messages"]:
        render_chat_message(msg)

    # Prompt: sidebar quick-button or chat input
    prompt = st.session_state.pop("pending", None) or st.chat_input(
        "Ask anything about your Zoho Projects…"
    )

    if not prompt:
        return

    # Show user message immediately
    st.session_state["messages"].append({"role": "user", "content": prompt, "tool_calls": []})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Run agent
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                result = run_agent(executor, prompt, st.session_state["messages"])
            except Exception as e:
                st.error(f"Agent error: {e}")
                return

        st.markdown(result["answer"])

        for tc in result["tool_calls"]:
            with st.expander(f"🔧 `{tc['tool']}` — view data", expanded=True):
                render_tool_output(tc["tool"], tc["output"])

    st.session_state["messages"].append({
        "role":       "assistant",
        "content":    result["answer"],
        "tool_calls": result["tool_calls"],
    })

    if len(st.session_state["messages"]) > 2:
        st.divider()
        if st.button("🗑️ Clear conversation"):
            st.session_state["messages"] = []
            st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    _init()
    _handle_callback()     # Must run first, before any auth check

    if not oauth.is_authenticated():
        _login_page()
        return

    token = oauth.get_valid_access_token()
    if not token:
        st.warning("Session expired — please log in again.")
        oauth.logout()
        st.rerun()
        return

    # Derive the correct API base URL from the accounts-server stored during OAuth
    # e.g. https://accounts.zoho.in → https://projectsapi.zoho.in/restapi
    accounts_server = st.session_state.get("accounts_server", "")
    api_base = api_base_from_accounts_server(accounts_server) if accounts_server else None
    client = ZohoClient(token, api_base=api_base)
    _load_portals(client)
    _sidebar(client)

    if not st.session_state.get("active_portal_id"):
        st.warning("No Zoho Projects portal found for this account.")
        return

    _chat_page(client)


if __name__ == "__main__":
    main()