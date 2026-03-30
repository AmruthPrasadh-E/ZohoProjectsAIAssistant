# Setup Guide — Zoho Projects AI Assistant

Complete this guide once before running the app for the first time.
Estimated time: **10 minutes**.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10 or later | Tested on 3.11 |
| [Ollama](https://ollama.com/download) | Latest | Runs the LLM locally |
| Zoho Projects account | Any paid plan | Free trial works |
| Internet connection | — | For Zoho API calls |

---

## Step 1 — Install Ollama and Pull a Model

Ollama runs the language model on your machine. Install it from
**https://ollama.com/download**, then open a terminal and run:

```bash
# Pull a tool-calling capable model (required — ReAct models will NOT work)
ollama pull qwen2.5:7b

# Start the Ollama server (keep this terminal open)
ollama serve
```

> **Why tool-calling?**
> The agent uses Zoho API tools to fetch real data. Models that only support
> ReAct text format (like base `llama3`) produce malformed tool calls and
> hallucinate data. Use a model confirmed to support tool/function calling.
>
> **Recommended models (confirmed working):**
> | Model | Size | Notes |
> |---|---|---|
> | `qwen2.5:7b` | 4 GB | Best balance of speed and accuracy |
> | `qwen2.5:14b` | 9 GB | Higher quality, slower |
> | `llama3.1:8b` | 5 GB | Good alternative |
> | `mistral-nemo` | 7 GB | Good alternative |
>
> **Not recommended:** `llama3`, `mistral`, `phi3` — these lack reliable tool calling.

---

## Step 2 — Register a Zoho API Application

### 2a. Open the API Console

Go to **https://api-console.zoho.com/** and sign in with the **same Zoho
account** that owns your Zoho Projects portal.

### 2b. Create a New Client

1. Click **"Add Client"** in the top-right corner.
2. Select **"Server-based Applications"**.

> ⚠️ **Do NOT choose "Self Client".**
> Self Client tokens expire in one hour with no refresh capability.
> Server-based Applications give you long-lived refresh tokens.

### 2c. Fill in the Application Details

| Field | Value to Enter |
|---|---|
| **Client Name** | `Zoho Projects AI Assistant` (or any descriptive name) |
| **Homepage URL** | `http://localhost:8501` |
| **Authorized Redirect URIs** | `http://localhost:8501/` |

> ⚠️ **The Redirect URI trailing slash is critical.**
> `http://localhost:8501/` and `http://localhost:8501` are treated as
> different URIs by Zoho. A mismatch causes `redirect_uri_mismatch` errors.

Click **"Create"**.

### 2d. Copy Your Credentials

After creation, Zoho shows you:

```
Client ID     :  1000.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
Client Secret :  XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Save these — you will need them in Step 4.

---

## Step 3 — Find Your Zoho Data Center

Your Zoho account is hosted in one of five regional data centers.
Using the wrong data center causes `401 Unauthorized` errors.

| `ZOHO_DC` value | Region | Accounts URL |
|---|---|---|
| `com` | United States | accounts.zoho.com |
| `eu` | Europe | accounts.zoho.eu |
| `in` | India | accounts.zoho.in |
| `com.au` | Australia | accounts.zoho.com.au |
| `jp` | Japan | accounts.zoho.jp |

**How to find yours:** Log in to Zoho Projects and look at the URL.
- `app.zoho.in/...` → use `in`
- `app.zoho.com/...` → use `com`
- `app.zoho.eu/...` → use `eu`

> The app also auto-detects your data center from the OAuth redirect URL,
> so even if this is set incorrectly the authentication will still work.
> The DC setting only affects which authorization page you are sent to.

---

## Step 4 — Configure Environment Variables

In the project root directory:

```bash
# Copy the template
cp .env.example .env
```

Open `.env` and fill in your values:

```env
# ── Zoho OAuth Credentials (from Step 2d) ───────────────────────────────────
ZOHO_CLIENT_ID=1000.YOUR_CLIENT_ID_HERE
ZOHO_CLIENT_SECRET=YOUR_CLIENT_SECRET_HERE

# Redirect URI — must match exactly what you entered in the API Console
ZOHO_REDIRECT_URI=http://localhost:8501/

# Your Zoho data center (from Step 3)
ZOHO_DC=in

# ── Ollama Configuration ─────────────────────────────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# ── Optional: Standalone Testing ─────────────────────────────────────────────
# Fill these in after first login to run test_zoho_client.py
# ZOHO_ACCESS_TOKEN=
# ZOHO_ACCOUNTS_SERVER=https://accounts.zoho.in

# ── Optional: Show debug token panel in sidebar ───────────────────────────────
# ZOHO_DEBUG=1
```

> **Do not add quotes around values.** Write `ZOHO_DC=in`, not `ZOHO_DC="in"`.
> The app strips surrounding quotes automatically, but it is best practice
> to leave them out.

---

## Step 5 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs: `streamlit`, `langchain`, `langchain-ollama`, `httpx`,
`python-dotenv`, `pandas`, `plotly`.

---

## Step 6 — Run the Application

```bash
streamlit run app.py
```

Open your browser to **http://localhost:8501**.

---

## Step 7 — Authenticate with Zoho

1. Click **"Connect to Zoho Projects"** on the login page.
2. You will be redirected to the Zoho login and consent page.
3. Sign in and click **"Accept"** to grant the requested permissions.
4. You will be redirected back to `http://localhost:8501/` automatically.
5. The app loads your portal and the chat interface appears.

> **How authentication works:**
> The app uses OAuth 2.0 Authorization Code flow. Your credentials are never
> stored in the app — only a short-lived access token (1 hour) and a
> long-lived refresh token are kept in your browser session. Tokens are
> cleared when you click Logout or close the browser.

---

## Step 8 — Verify the Connection (Optional but Recommended)

Before chatting, run the standalone API tester to confirm everything works:

```bash
# First, reveal your token:
# Add ZOHO_DEBUG=1 to .env, open the app, copy the token from sidebar Debug panel
# Then add to .env:
# ZOHO_ACCESS_TOKEN=1000.your_token_here
# ZOHO_ACCOUNTS_SERVER=https://accounts.zoho.in

python test_zoho_client.py
```

Expected output: `12/12 passed`. If some tests fail, the error messages
and the `logs/app.log` file will tell you exactly what is wrong.

---

## Troubleshooting

### Authentication Errors

| Error Message | Cause | Fix |
|---|---|---|
| `redirect_uri_mismatch` | URI in `.env` doesn't match API Console | Ensure trailing slash matches exactly |
| `invalid_code` | Code already used or wrong data center | Delete `auth/.oauth_state_store.json` and try again |
| `invalid_client` | Wrong Client ID or Secret | Re-copy from API Console |
| `access_denied` | Clicked Deny on consent page | Click Connect again and accept |

### API Errors After Login

| Error | Cause | Fix |
|---|---|---|
| `401 Unauthorized` | Wrong data center for API calls | The app auto-detects DC from OAuth — ensure you logged in fresh |
| `403 Forbidden` | Missing OAuth scope | Re-authenticate; the app requests all required scopes |
| Portal not found | Account has no Zoho Projects portal | Ensure you have an active Zoho Projects subscription |

### Ollama / Agent Errors

| Error | Cause | Fix |
|---|---|---|
| `Connection refused` at port 11434 | Ollama not running | Run `ollama serve` in a separate terminal |
| `Model not found` | Model not pulled | Run `ollama pull qwen2.5:7b` |
| Agent hallucinating fake project names | Model does not support tool calling | Switch to `qwen2.5:7b` or `llama3.1:8b` |
| `Agent stopped due to max iterations` | Model not following tool-call protocol | Switch model; check `logs/app.log` for the raw output |

### Debugging Tools

```bash
# Test Zoho API connectivity without the agent
python test_zoho_client.py

# Find the correct API format for status updates on your portal
python debug_status_probe.py

# Find the correct API format for task assignment on your portal
python debug_assign_probe.py

# Watch all logs in real time
Get-Content logs\app.log -Wait     # Windows PowerShell
tail -f logs/app.log               # Mac / Linux
```
