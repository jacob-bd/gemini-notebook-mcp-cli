# Authentication Guide

This guide explains how to authenticate with Gemini Notebook (formerly Google NotebookLM) MCP and CLI.

> For public HTTP deployment or Claude web/mobile connectors, see
> [Remote MCP Deployment](REMOTE_MCP.md). Remote use introduces a separate MCP
> endpoint authentication requirement in addition to the Google browser session
> described here.

## Overview

Gemini Notebook uses browser cookies for authentication (there is no official API). The CLI/MCP extracts these cookies automatically from a managed browser session:
- Chromium-family browsers use Chrome DevTools Protocol (CDP)

**Supported browsers**: Google Chrome, Arc (macOS), Brave, Microsoft Edge, Chromium, Vivaldi, Opera.

**Two authentication methods are available:**

| Method | Best For | Requires |
|--------|----------|----------|
| **Auto Mode** (default) | Most users | Any supported Chromium-family browser installed |
| **File Mode** (`--file`) | Complex setups, troubleshooting | Manual cookie extraction |

---

## Method 1: Auto Mode (Recommended)

This method launches your browser automatically and extracts cookies after you log in.

### Prerequisites

- A supported browser installed (Chrome, Arc, Brave, Edge, Chromium, Vivaldi, or Opera)
- Chromium-family browsers should be **completely closed** before running

### Steps

```bash
# 1. Close your browser completely (Cmd+Q on Mac, or quit from taskbar)

# 2. Run the auth command (CLI or standalone)
nlm login                      # Recommended

# 3. Log in to your Google account in the browser window that opens

# 4. Wait for "SUCCESS!" message
```

If your DevTools endpoint is slow to respond, you can increase the timeout:

```bash
nlm login --devtools-timeout 15
```

### What Happens Behind the Scenes

1. The first available supported browser is detected (or your preferred browser if configured)
2. A dedicated browser profile is created for authentication
3. The browser launches with the appropriate automation backend
4. You log in to Gemini Notebook via the browser
5. Cookies, CSRF token, and account email are extracted and cached
6. The browser is closed automatically

### Browser Preference

By default, `nlm login` uses the first available browser. To use a specific browser:

```bash
# Set preferred browser
nlm config set auth.browser brave

# Or use an environment variable
export NLM_BROWSER=arc

# Valid values: auto, chrome, arc, brave, edge, chromium, vivaldi, opera
# If the preferred browser is not installed, falls back to auto-detection.
```

### Persistent Login

The dedicated browser profile persists your Google login:
- **First run:** You must log in to Google
- **Future runs:** Already logged in, just extracts fresh cookies

This profile is separate from your regular browser profile. Chromium profiles disable extensions.

---

## Multi-Profile Support

Use multiple Google accounts by creating named profiles:

```bash
# Create profiles for different accounts
nlm login --profile work       # Opens browser - log in with work account
nlm login --profile personal   # Opens browser - log in with personal account

# List all profiles
nlm login profile list
# Output:
#   work: jsmith@company.com
#   personal: jsmith@gmail.com

# Switch default profile (no --profile flag needed)
nlm login switch personal
# Output: ✓ Switched default profile to personal

# Use profiles
nlm notebook list                    # Uses default (personal)
nlm notebook list --profile work     # Uses work account

# Manage profiles
nlm login profile rename work company
nlm login profile delete old-profile
```

### How Multi-Profile Works

Each profile gets:
- **Separate credentials**: Stored in `~/.notebooklm-mcp-cli/profiles/<name>/`
- **Separate browser profile**: Isolated browser session in `~/.notebooklm-mcp-cli/chrome-profiles/<name>/`
- **Captured email**: Automatically extracted during login for easy identification

This means you can stay logged into multiple Google accounts simultaneously without conflicts.

---

## Enterprise / Google Workspace

If your organization uses **Google Workspace** with a managed Gemini Notebook instance (e.g., `notebooklm.cloud.google.com` instead of `notebook.google.com`), set the `NOTEBOOKLM_BASE_URL` environment variable before authenticating:

```bash
# Set the enterprise URL
export NOTEBOOKLM_BASE_URL=https://notebooklm.cloud.google.com

# Then authenticate as usual
nlm login
```

All CLI commands, MCP tools, and internal API calls will use this URL automatically. If the variable is not set, the default personal URL (`https://notebook.google.com`) is used.

> **Tip:** Add the export to your shell profile (`~/.zshrc`, `~/.bashrc`) so it persists across sessions.

For MCP server configuration, pass the variable in your client config:

```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "notebooklm-mcp",
      "env": {
        "NOTEBOOKLM_BASE_URL": "https://notebooklm.cloud.google.com"
      }
    }
  }
}
```

---

## The "Gemini Notebook" rebrand (`notebook.google.com`)

Google is rolling out a rebrand of Gemini Notebook that redirects some signed-in accounts to `notebook.google.com` instead of `notebook.google.com`. This is handled automatically as of v0.9.3: `nlm login` records whichever host your account actually lands on (per-profile, in `metadata.json`), and every CLI/MCP request is routed to that host afterward. No configuration is needed.

Resolution order, if you need to override it manually:

1. `NOTEBOOKLM_BASE_URL` env var, if set (see Enterprise section above).
2. The host your account last signed in on (auto-detected).
3. The default `https://notebook.google.com`.

---

## Method 2: File Mode

This method lets you manually extract and provide cookies. Use this if:
- Auto mode doesn't work on your system
- You have browser extensions that interfere (e.g., Google Antigravity IDE)
- You prefer manual control

### Steps

```bash
# Option A: Interactive mode (shows instructions, prompts for file path)
nlm login --manual

# Option B: Direct file path
nlm login --manual --file /path/to/cookies.txt
```

### How to Extract Cookies Manually

1. Open Chrome and go to https://notebook.google.com
2. Make sure you're logged in
3. Press **F12** (or **Cmd+Option+I** on Mac) to open DevTools
4. Click the **Network** tab
5. In the filter box, type: `batchexecute`
6. Click on any notebook to trigger a request
7. Click on a `batchexecute` request in the list
8. In the right panel, scroll to **Request Headers**
9. Find the line starting with `cookie:`
10. Right-click the cookie **value** and select **Copy value**
11. Paste into a text file and save

### Cookie File Format

The cookie file should contain the raw cookie string from Chrome DevTools:

```
SID=abc123...; HSID=xyz789...; SSID=...; APISID=...; SAPISID=...; __Secure-1PSID=...; ...
```

**Notes:**
- Lines starting with `#` are treated as comments and ignored
- The file can contain the cookie string on one or multiple lines
- A template file `cookies.txt` is included in the repository

---

## Where Tokens Are Stored

All data is stored under `~/.notebooklm-mcp-cli/`:

```
~/.notebooklm-mcp-cli/
├── config.toml                    # CLI configuration
├── aliases.json                   # Notebook aliases
├── profiles/                      # Authentication profiles
│   ├── default/
│   │   └── auth.json              # Cookies, tokens, email
│   ├── work/
│   │   └── auth.json
│   └── personal/
│       └── auth.json
├── chrome-profile/                # Chrome profile (single-profile users)
└── chrome-profiles/               # Chrome profiles (multi-profile users)
    ├── work/
    └── personal/
```

Each profile's `auth.json` contains:
- Parsed cookies
- CSRF token (auto-extracted)
- Session ID (auto-extracted)
- Account email (auto-extracted)
- Extraction timestamp

---

## After Authentication

Once authenticated, add the MCP to your AI tool:

**Claude Code:**
```bash
claude mcp add gemini-notebook-mcp -- notebooklm-mcp
```

**Gemini CLI:**
```bash
gemini mcp add gemini-notebook-mcp notebooklm-mcp
```

**Manual (settings.json):**
```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "notebooklm-mcp"
    }
  }
}
```

Then restart your AI assistant.

---

## Token Expiration

- **Cookies:** Generally stable for weeks, but some rotate on each request
- **CSRF token:** Auto-refreshed on each MCP client initialization
- **Session ID:** Auto-refreshed on each MCP client initialization

When you start seeing authentication errors, simply run `nlm login` again to refresh.

---

## Understanding `auth_status`

The MCP `server_info` tool and `nlm login --check` report one of five
`auth_status` values from the multi-probe AuthHealthChecker. Knowing the
difference matters: a `stale` status means you must re-auth, but
an `unverified` status is a network problem, not a credential problem.

> **Caching note:** the `server_info` result is cached for 30 seconds
> (the checker's `CACHE_TTL`) and bypassed on the next call if any auth
> file on disk is rewritten, so an external `nlm login` is reflected
> without waiting for the TTL. `nlm login --check` is always live.

| Status | Meaning | What to do |
|--------|---------|------------|
| `configured` | Live check passed. Credentials are good. | Nothing. |
| `not_configured` | No credentials are stored at all (first-time setup). | Run `nlm login`. |
| `stale` | Credentials are known-bad: the live check was redirected to `accounts.google.com` (cookies expired), the on-disk profile failed to load, or the last successful validation is older than 7 days. | Run `nlm login` to refresh. Subsequent API calls will fail. |
| `unverified` | The live check could not be completed (network timeout, DNS failure, proxy block, non-200 HTTP). Cached credentials on disk are still intact and may work for actual API calls. | Retry later, or check your network/proxy. Do not assume the user needs to re-auth — operations often still succeed. |
| `error` | Unexpected exception inside the check itself (very rare). | File a bug with the traceback. |

> **Heads up for AI agents:** If you see `auth_status = "stale"`, prompt the
> user to re-authenticate. If you see `auth_status = "unverified"` while
> recent operations are succeeding, treat it as a transient monitoring
> failure and continue — re-auth is not required.

---

## Troubleshooting

### "Browser is running but without remote debugging enabled"

Close your browser completely and try again. On Mac, use **Cmd+Q** to fully quit.

### Auto mode fails to connect

Try file mode instead:
```bash
nlm login --manual
```

### "401 Unauthorized" or "403 Forbidden" errors

Your cookies have expired. Run the auth command again to refresh.

### Browser opens with strange branding (e.g., Antigravity IDE)

Some browser extensions or tools modify the browser's behavior. Try a different browser or use file mode:
```bash
nlm login --manual
```

### Cookie file shows "missing required cookies"

Make sure you copied the cookie **value**, not the header name. The value should start with something like `SID=...` not `cookie: SID=...`.

### Authentication loop after `nlm login`

If you keep getting "Authentication expired" even after running `nlm login` or calling `refresh_auth`, check whether `NOTEBOOKLM_COOKIES` is set as an environment variable in your MCP config.

**Why this happens:** When `NOTEBOOKLM_COOKIES` is set in your config (e.g. `claude_desktop_config.json`), it takes absolute priority over all other auth sources — `auth.json`, profile cookies, `save_auth_tokens`, and `nlm login`. When those hardcoded cookies expire, no recovery action can fix a running MCP process because the stale env var is baked into its environment.

**How to check:**

```python
import os
print("NOTEBOOKLM_COOKIES in env:", "YES (overrides everything!)" if os.environ.get("NOTEBOOKLM_COOKIES") else "no")
```

**How to fix (pick one):**

1. **Update the cookie value** in your MCP config file with fresh cookies, then restart your AI tool (Claude Desktop, etc.)
2. **Remove the `NOTEBOOKLM_COOKIES` env var** from your config entirely and use `nlm login` instead (recommended — this way auth recovery works automatically)

Similarly, if you have `NOTEBOOKLM_CSRF_TOKEN` or `NOTEBOOKLM_SESSION_ID` in your config, remove them — both are deprecated and auto-extracted. Stale values can prevent auto-refresh from working.

---

### Experimental browser-backed RPC transport

`nlm doctor auth-replay` compares four lanes: saved cookies through httpx,
httpx after a forced cookie rotation, cookies freshly re-extracted from a
live logged-in browser (also replayed through httpx), and an in-page CDP
fetch from that same browser session. The fresh-cookie lane exists to tell
apart two failure modes that look identical if you only compare saved
cookies against the browser: ordinary expired cookies (verdict
`stale_cookies` — run `nlm login`, no transport needed) versus genuine
device-bound replay (verdict `browser_bound_replay` — even fresh cookies
fail outside the browser).

Only opt in to the experimental CDP transport if the verdict is
`browser_bound_replay`:

```bash
NOTEBOOKLM_RPC_TRANSPORT=cdp nlm notebook list
NOTEBOOKLM_RPC_TRANSPORT=cdp nlm query notebook <notebook-id> "Question?"
```

For MCP clients, add the same environment variable to the server config:

```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "notebooklm-mcp",
      "env": {
        "NOTEBOOKLM_RPC_TRANSPORT": "cdp"
      }
    }
  }
}
```

This runs supported Gemini Notebook form POSTs through `fetch` inside the saved
Gemini Notebook browser profile, so the browser supplies its live cookies. It is
off by default and currently targets normal batchexecute RPCs plus notebook
chat. Uploads, downloads, and artifact file transfers still use the existing
HTTP paths.

If the CDP transport cannot find a saved profile-owned browser session, run
`nlm login` first. Do not use this flag as a general auth refresh shortcut;
use it only for suspected browser-bound replay failures.

---

## Chromium 136+ Compatibility

Chrome 136+ (and other Chromium-based browsers at the same version) restrict remote debugging on the default profile for security reasons. This is handled automatically by:

1. Using dedicated profile directories (`~/.notebooklm-mcp-cli/chrome-profiles/<name>/`)
2. Adding the `--remote-allow-origins=*` flag for WebSocket connections

No action required from users.

---

## Security Notes

- Cookies are stored locally in `~/.notebooklm-mcp-cli/profiles/<name>/auth.json`
- Each browser profile contains your Google login for Gemini Notebook
- Never share your `auth.json` files or commit them to version control
- The `cookies.txt` file in the repo is a template - don't commit real cookies
