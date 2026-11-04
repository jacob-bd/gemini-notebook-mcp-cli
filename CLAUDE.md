# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Gemini Notebook (formerly Google NotebookLM) MCP Server & CLI** - Provides programmatic access to Gemini Notebook (notebook.google.com) via both a Model Context Protocol server and a comprehensive command-line interface.

Tested with personal/free tier accounts. May work with Google Workspace accounts but has not been tested.

## Development Commands

```bash
# Fetch latest from remote (run before git operations)
git fetch

# Install dependencies
uv tool install .

# Reinstall after code changes (ALWAYS clean cache first)
uv cache clean && uv tool install --force .

# Run the MCP server (stdio)
notebooklm-mcp

# Run with Debug logging
notebooklm-mcp --debug

# Run as HTTP server
notebooklm-mcp --transport http --port 8000

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_function -v

# Setup wizard end-to-end tests (opt-in, ~2 min, macOS). Run after ANY change to
# cli/commands/setup.py, setup_wizard.py or skill.py. They drive the real
# `nlm setup` in a pseudo-terminal against a sandboxed HOME and check the files written.
uv run pytest -m wizard_e2e
```

**Python requirement:** >=3.11

## Authentication (SIMPLIFIED!)

**You only need to provide COOKIES!** The CSRF token and session ID are now **automatically extracted** when needed.

### Method 1: Chrome DevTools MCP (Recommended)

**Option A - Fast (Recommended):**
Extract CSRF token and session ID directly from network request - **no page fetch needed!**

```python
# 1. Navigate to NotebookLM page
navigate_page(url="https://notebook.google.com/")

# 2. Get a batchexecute request (any NotebookLM API call)
get_network_request(reqid=<any_batchexecute_request>)

# 3. Save with all three fields from the network request:
save_auth_tokens(
    cookies=<cookie_header>,
    request_body=<request_body>,  # Contains CSRF token
    request_url=<request_url>      # Contains session ID
)
```

**Option B - Minimal (slower first call):**
Save only cookies, tokens extracted from page on first API call

```python
save_auth_tokens(cookies=<cookie_header>)
```

### Method 2: Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NOTEBOOKLM_COOKIES` | Yes | Full cookie header from Chrome DevTools |
| `NOTEBOOKLM_CSRF_TOKEN` | No | (DEPRECATED - auto-extracted) |
| `NOTEBOOKLM_SESSION_ID` | No | (DEPRECATED - auto-extracted) |
| `NOTEBOOKLM_BL` | No | Override for build label / bl URL param (auto-extracted from page) |
| `NOTEBOOKLM_HL` | No | Interface language and default artifact language (default: `en`) |
| `NOTEBOOKLM_AUTH_RECOVERY_COOLDOWN_SECONDS` | No | Automatic browser recovery cooldown per profile/process (default: 900; 0 disables) |
| `NOTEBOOKLM_AUTH_MAX_HEADLESS_FAILURES` | No | Automatic browser recovery failure ceiling per profile/process (default: 3; 0 disables) |
| `NOTEBOOKLM_RPC_OVERRIDES` | No | Hot-patch rotated batchexecute RPC method IDs without a release. JSON object mapping `BaseClient` RPC attribute names to new IDs, e.g. `{"RPC_LIST_NOTEBOOKS": "abc123"}` |
| `NOTEBOOKLM_DISABLE_HEADLESS_REFRESH` | No | Set to `1` to disable the automatic headless self-heal and `nlm auth refresh`. Use on Google Workspace accounts whose session is revoked when the saved browser profile is relaunched (issue #330) |

### Resilience: rotated RPC IDs

Gemini Notebook's internal API uses short RPC "method IDs" (e.g. `wXbhsf`) that Google rotates without notice. When one rotates, calls using the old ID fail. The client now:

- **Detects drift loudly**: raises `RPCDriftError` (instead of returning silently) when the server responds with **other** `wrb.fr` RPC IDs than the one requested. An empty response still returns silently (no comparison points), so use `--debug` to inspect in that case.
- **Discovers the new ID**: run with `--debug` to log `RPC IDs in response: [...]` — the new ID for your call appears there.
- **Hot-patches without a release**: set `NOTEBOOKLM_RPC_OVERRIDES='{"RPC_LIST_NOTEBOOKS": "<new_id>"}'` (use the `RPC_*` attribute name from `core/base.py`) to override the ID for the current session. **Restart the MCP server for the override to take effect** — the env var is read once at client init, not per call. The CLI (`nlm`) picks it up on the next invocation automatically.
- **Auto-retries throttling**: `RESOURCE_EXHAUSTED` (RPC error code 8) responses are retried with exponential backoff.

### Token Expiration

- **Cookies**: Stable for weeks, but some rotate on each request
- **CSRF token**: Auto-refreshed on each client initialization
- **Session ID**: Auto-refreshed on each client initialization
- **Build label (bl)**: Auto-extracted during login and CSRF refresh; stays current with Google's build

When API calls fail with auth errors, re-extract fresh cookies from Chrome DevTools.

**Unattended keep-alive:** A live session self-heals — auth recovery reloads
newer disk cookies (external re-login) or runs a headless-browser refresh to
make Google reissue the short-lived `*PSIDTS` freshness cookies when they age
out. For schedulers, `nlm auth refresh` triggers that headless refresh
non-interactively so a session never lapses between jobs. (RotateCookies alone
refreshes only the `*SIDCC` session cookies, not `*PSIDTS`, from a plain HTTP
client — see issue #316.)

## Architecture

```
src/notebooklm_tools/
├── __init__.py          # Package version
├── services/            # Shared service layer (v0.3.0+)
│   ├── errors.py        # ServiceError, ValidationError, NotFoundError, etc.
│   ├── chat.py          # Chat/query logic
│   ├── downloads.py     # Artifact downloading
│   ├── exports.py       # Google Docs/Sheets export
│   ├── notebooks.py     # Notebook CRUD + describe
│   ├── notes.py         # Note CRUD
│   ├── research.py      # Research start/poll/import
│   ├── sharing.py       # Public link, invite, status
│   ├── sources.py       # Source add/list/sync/delete
│   └── studio.py        # Artifact creation, status, rename, delete
├── cli/                 # CLI commands and formatting (thin wrapper)
├── mcp/                 # MCP server + tools (thin wrapper)
│   ├── server.py        # FastMCP server facade
│   └── tools/           # Modular tool definitions per domain
├── core/                # Low-level API client (no business logic)
│   ├── client.py        # Internal batchexecute API calls
│   ├── constants.py     # Code-name mappings (CodeMapper class)
│   └── auth.py          # AuthManager for profile-based token caching
└── utils/
    ├── config.py        # Configuration and storage paths
    └── cdp.py           # Chrome DevTools Protocol for cookie extraction
```

**Layering Rules (v0.3.0+):**
- `cli/` and `mcp/` are thin wrappers: they handle UX concerns (prompts, spinners, JSON responses) and delegate to `services/`
- `services/` contains all business logic, validation, and error handling. Returns typed dicts.
- `cli/` and `mcp/` must NOT import from `core/` directly — always go through `services/`
- `services/` raises `ServiceError`/`ValidationError` — never raw exceptions

**Storage Structure (`~/.notebooklm-mcp-cli/`):**
```
├── config.toml                    # CLI settings (default_profile, output format)
├── aliases.json                   # Notebook aliases
├── installation.json              # Installation identity
├── locks/                         # Inter-process profile locks
├── operations/                    # Migration state & quarantine markers
├── profiles/<name>/
│   ├── metadata.json              # Non-secret metadata (email, host, storage mode)
│   ├── credentials.enc            # AES-256-GCM encrypted credentials (Protected mode)
│   └── cookies.json               # Plaintext cookies (File mode only)
├── auth.json                      # Root mirror of default profile (File mode only)
├── chrome-profile/                # Chrome session (single-profile/legacy)
└── chrome-profiles/<name>/        # Chrome sessions (multi-profile)
```

**Credential Storage Modes:**
- **Protected mode (recommended for personal computers):** Credentials are encrypted at rest (`credentials.enc`) with keys in the OS keystore (macOS Keychain, Windows Credential Manager, Linux SecretService). Managed via `nlm auth storage status`, `set protected|file`, `resolve`, and `relocate`.
- **File mode (default / servers / cron / Docker):** Plaintext cookies stored with `0600` permissions.
- **First login:** for a NEW profile `nlm login` asks plain vs protected before the browser opens (only in a desktop terminal; `--storage protected|file` skips it). The marker is written right before the first save and rolled back if the save fails; the answer is recorded only after success.
- **Safety rule for AI assistants:** Never print decrypted credentials, cookies, or raw keystore values. Output redacted diagnostics only.

**Executables:**
- `nlm` - Command-line interface
- `notebooklm-mcp` - The Gemini Notebook MCP server executable

**Configured MCP name:** `gemini-notebook-mcp` (the executable name remains
`notebooklm-mcp` for compatibility). Claude Desktop setup detects regular and
Relay AI/3P profiles, never creates missing profiles, and refuses to write
while the selected Claude instance is running. User-level skill installation
also requires the target tool to be detected. The `nlm setup` wizard flags
entries still named `notebooklm-mcp`/`notebooklm` as "old name" and renames
them on request. `nlm skill package` (`cli/skill_package.py`) builds the
`nlm-skill.zip` upload file for Claude Desktop Chat/Cowork and claude.ai, which
don't read local skill folders.

## MCP Tools Provided

| Tool | Purpose |
|------|---------|
| `notebook_list` | List all notebooks |
| `notebook_create` | Create new notebook |
| `notebook_get` | Get notebook details |
| `notebook_describe` | Get AI-generated summary of notebook content with keywords |
| `source_describe` | Get AI-generated summary and keyword chips for a source |
| `source_get_content` | Get raw text content from a source (no AI processing). Supports `wait`, `wait_timeout`, `poll_interval` params and returns `download_url` when MCP HTTP transport is active. |
| `source_add_chatgpt_file` | Add a ChatGPT-uploaded file to a notebook (supports `openai/fileParams`). Supports `wait`, `wait_timeout`, `cleanup` params. |
| `notebook_rename` | Rename a notebook |
| `chat_configure` | Configure chat goal/style and response length |
| `notebook_delete` | Delete a notebook (REQUIRES confirmation) |
| `source_add` | Add source (url, text, drive, file) |
| `notebook_query` | Ask questions (AI answers!) |
| `chat_list` | List chat sessions for a notebook |
| `chat_delete` | Permanently delete chat history (REQUIRES confirmation) |
| `source_search` | Experimental, off-by-default source passage retrieval |
| `chat_get` | Get full transcript of a chat session (defaults to latest) |
| `chat_export` | Export a chat transcript to Markdown or JSON |
| `source_list_drive` | List sources with types, check Drive freshness |
| `source_sync_drive` | Sync stale Drive sources (REQUIRES confirmation) |
| `source_rename` | Rename a source in a notebook |
| `source_delete` | Delete a source from notebook (REQUIRES confirmation) |
| `research_start` | Start Web or Drive research to discover sources |
| `research_status` | Check research progress (default: 900s wait, 30s poll). Pass `auto_import=True` to automatically import sources on completion — no separate `research_import` call needed. |
| `research_import` | Import discovered sources into notebook (manual, if `auto_import` not used) |
| `studio_create` | Generate unified content (audio, video, infographic, slides, etc.) |
| `download_artifact` | Download any artifact (audio, video, pdf, markdown, json). Supports `wait`, `wait_timeout`, `poll_interval` params and returns `download_url` when MCP HTTP transport is active. |
| `download_all_artifacts` | Download every completed artifact of a notebook — or every notebook with `all_notebooks=True` — into per-notebook directories (named after notebook titles). Optional `artifact_types` filter and `skip_existing` for incremental re-runs; failures on one artifact/notebook don't stop the rest. CLI: `nlm download all [--all-notebooks] [--skip-existing]` |
| `export_artifact` | Export Data Tables to Google Sheets or Reports to Google Docs |
| `studio_status` | Check studio artifact generation status |
| `studio_delete` | Delete studio artifacts (REQUIRES confirmation) |
| `studio_revise` | Revise slides in an existing slide deck (creates new artifact, REQUIRES confirmation) |
| `report` | Interactive report elements: `action=get` (markdown + elements), `elements` (sections, settings; optional wait / review content), `generate` (validate a plan; runs with `confirm=True`) |
| `notebook_share_status` | Get sharing settings and collaborators |
| `notebook_share_public` | Enable/disable public link access |
| `notebook_share_invite` | Invite collaborator by email |
| `save_auth_tokens` | Save tokens extracted via Chrome DevTools MCP |
| `refresh_auth` | Reload/validate auth or run headless recovery; optional `profile` targets an account without switching the active account |
| `note_create` | Create a note in a notebook |
| `note_list` | List all notes in a notebook |
| `note_update` | Update a note's content or title |
| `note_delete` | Delete a note (REQUIRES confirmation) |
| `usage_get` | Show remaining plan usage per window (rolling + weekly) and reset times |
| `profile` | List saved accounts, show storage status, switch account for this MCP server (`make_default=true` also saves it as the default) |
| `alias` | Manage notebook ID aliases; every tool's `notebook_id` accepts an alias |
| `chat_save_to_note` | Save a chat (or one turn) as a Note |

**IMPORTANT - Operations Requiring Confirmation:**
- `chat_delete` requires `confirm=True` - deletion is IRREVERSIBLE
- `notebook_delete` requires `confirm=True` - deletion is IRREVERSIBLE
- `source_delete` requires `confirm=True` - deletion is IRREVERSIBLE
- `source_sync_drive` requires `confirm=True` - always show stale sources first via `source_list_drive`
- All studio creation tools require `confirm=True` - show settings and get user approval first
- `studio_delete` requires `confirm=True` - list artifacts first via `studio_status`, deletion is IRREVERSIBLE
- `studio_revise` requires `confirm=True` - creates a new artifact with revisions applied
- `report(action="generate")` requires `confirm=True` - starts generation of the plan's elements (without it, the plan is only validated)
- `note_delete` requires `confirm=True` - deletion is IRREVERSIBLE

## Features NOT Yet Implemented

None - all Gemini Notebook features that can be accessed programmatically are implemented.

## Troubleshooting

### "401 Unauthorized" or "403 Forbidden"
- Cookies or CSRF token expired
- Re-extract from Chrome DevTools

### "Invalid CSRF token"
- The `at=` value expired
- Must match the current session

### Empty notebook list
- Session might be for a different Google account
- Verify you're logged into the correct account

### Rate limit errors
- Since 2026-09-02, chat and Studio usage is metered as compute against two
  windows at once: a short rolling window (~5h) and a weekly cap. Allowance
  scales with plan tier.
- Run `nlm usage` (MCP: `usage_get`) to see what is left in each window and
  when it resets, instead of guessing.
- Brief throttling is retried automatically with backoff; an exhausted window
  needs to wait for the reset time that `nlm usage` reports.

## Documentation

### API Reference

**For detailed API documentation** (RPC IDs, parameter structures, response formats), see:

**[docs/API_REFERENCE.md](./docs/API_REFERENCE.md)**

This includes:
- All discovered RPC endpoints and their parameters
- Source type structures (URL, text, Drive)
- Studio content creation (audio, video, reports, etc.)
- Research workflow details
- Mind map generation process
- Source metadata structures

Only read API_REFERENCE.md when:
- Debugging API issues
- Adding new features
- Understanding internal API behavior

### MCP Test Plan

**For comprehensive MCP tool testing**, see:

**[docs/MCP_CLI_TEST_PLAN.md](./docs/MCP_CLI_TEST_PLAN.md)**

This includes:
- Step-by-step test cases for all 53 MCP tools and CLI commands
- Authentication and basic operations tests
- Source management and Drive sync tests
- Studio content generation tests (audio, video, infographics, etc.)
- Quick copy-paste test prompts for validation

Use this test plan when:
- Validating MCP server functionality after code changes
- Testing new tool implementations
- Debugging MCP tool issues

## Contributing

When adding new features:

1. Use Chrome DevTools MCP to capture the network request
2. Document the RPC ID in docs/API_REFERENCE.md
3. Add the param structure with comments
4. Add the low-level API method in `core/client.py`
5. Add business logic in the appropriate `services/*.py` module
6. Add a thin wrapper in `mcp/tools/*.py` (for MCP) and `cli/commands/*.py` (for CLI)
7. Write unit tests for the service function in `tests/services/`
8. Update the "Features NOT Yet Implemented" checklist
9. Add test case to docs/MCP_TEST_PLAN.md

**Bumping the version:** the `Version Alignment Check` workflow (`.github/workflows/version-check.yml`) requires the **same** version in all 5 of these files — bump them together or CI fails:

- `pyproject.toml` → `version = "X.Y.Z"`
- `src/notebooklm_tools/__init__.py` → `__version__ = "X.Y.Z"`
- `src/notebooklm_tools/data/SKILL.md` → `version: "X.Y.Z"`
- `src/notebooklm_tools/data/AGENTS_SECTION.md` → `<!-- nlm-version: X.Y.Z -->`
- `desktop-extension/manifest.json` → `"version": "X.Y.Z"`

**CHANGELOG.md is also REQUIRED on every release** — add the `[X.Y.Z]` section at the top of `CHANGELOG.md` BEFORE committing the version bump. This is not optional and is not covered by the CI version-alignment check. Include:
- A dated header: `## [X.Y.Z] - YYYY-MM-DD`
- All Added / Fixed / Changed / Removed sections with full descriptions
- Community credits with contributor GitHub handles and PR/issue links (e.g. "Thanks to **@username** for …")
- DO NOT claim CHANGELOG.md was updated without verifying the file was actually modified in the commit

## License

MIT License
