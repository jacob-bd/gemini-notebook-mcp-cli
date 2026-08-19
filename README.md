# Gemini Notebook (formerly Google NotebookLM) CLI & MCP Server

![Gemini Notebook MCP Header](docs/media/header.jpg)

[![PyPI version](https://img.shields.io/pypi/v/notebooklm-mcp-cli)](https://pypi.org/project/notebooklm-mcp-cli/)
[![PyPI downloads](https://img.shields.io/pypi/dm/notebooklm-mcp-cli)](https://pypistats.org/packages/notebooklm-mcp-cli)
[![Total downloads](https://static.pepy.tech/badge/notebooklm-mcp-cli)](https://pepy.tech/projects/notebooklm-mcp-cli)
[![Python](https://img.shields.io/pypi/pyversions/notebooklm-mcp-cli)](https://pypi.org/project/notebooklm-mcp-cli/)
[![License](https://img.shields.io/pypi/l/notebooklm-mcp-cli)](https://github.com/jacob-bd/gemini-notebook-mcp-cli/blob/main/LICENSE)

**Programmatic access to Gemini Notebook** — via command-line interface (CLI) or Model Context Protocol (MCP) server.

> **Note:** Tested with Pro/free and Google AI Ultra ($249/mo) tier accounts. May work with Gemini Notebook Enterprise accounts but has not been tested.

> ☕ **If you find notebooklm-mcp-cli useful, consider [buying me a coffee](https://buymeacoffee.com/jacobbd).**
> It's free and built in my spare time — but testing every Gemini Notebook feature takes real time and resources. A coffee helps me cover it and keep shipping. Thank you! 🙏
>
> <a href="https://buymeacoffee.com/jacobbd"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="42"></a>

📺 **Watch the Demos**

### Latest

| **Codex Setup + Cinematic Video & Slides** |
|:---:|
| [![Latest](https://img.youtube.com/vi/KrgLCrvU1dw/mqdefault.jpg)](https://www.youtube.com/watch?v=KrgLCrvU1dw) |

### MCP Demos

| **General Overview** | **Claude Desktop** | **Perplexity Desktop** | **MCP Super Assistant** |
|:---:|:---:|:---:|:---:|
| [![General](https://img.youtube.com/vi/d-PZDQlO4m4/mqdefault.jpg)](https://www.youtube.com/watch?v=d-PZDQlO4m4) | [![Claude](https://img.youtube.com/vi/PU8JhgLPxes/mqdefault.jpg)](https://www.youtube.com/watch?v=PU8JhgLPxes) | [![Perplexity](https://img.youtube.com/vi/BCKlDNg-qxs/mqdefault.jpg)](https://www.youtube.com/watch?v=BCKlDNg-qxs) | [![MCP SuperAssistant](https://img.youtube.com/vi/7aHDbkr-l_E/mqdefault.jpg)](https://www.youtube.com/watch?v=7aHDbkr-l_E) |

### CLI Demos

| **CLI Overview** | **CLI, MCP & Skills** | **Setup, Doctor & mcpb** | **Infographics Support** |
|:---:|:---:|:---:|:---:|
| [![CLI Overview](https://img.youtube.com/vi/XyXVuALWZkE/mqdefault.jpg)](https://www.youtube.com/watch?v=XyXVuALWZkE) | [![CLI, MCP & Skills](https://img.youtube.com/vi/ZQBQigFK-E8/mqdefault.jpg)](https://www.youtube.com/watch?v=ZQBQigFK-E8) | [![Setup, Doctor & mcpb](https://img.youtube.com/vi/5tOUilBTJ3Q/mqdefault.jpg)](https://www.youtube.com/watch?v=5tOUilBTJ3Q) | [![Infographics](https://img.youtube.com/vi/Uc6iH5NuQ9A/mqdefault.jpg)](https://www.youtube.com/watch?v=Uc6iH5NuQ9A) |


## Two Ways to Use

### 🖥️ Command-Line Interface (CLI)

Use `nlm` directly in your terminal for scripting, automation, or interactive use:

```bash
nlm notebook list                              # List all notebooks
nlm notebook create "Research Project"         # Create a notebook
nlm source add <notebook> --url "https://..."  # Add sources
nlm audio create <notebook> --confirm          # Generate podcast
nlm download audio <notebook> <artifact-id>    # Download audio file
nlm download all <notebook> -d ./exports       # Download every artifact
nlm share public <notebook>                    # Enable public link
```

Run `nlm --ai` for comprehensive AI-assistant documentation.

### 🤖 MCP Server (for AI Agents)

Connect AI assistants (Claude, Gemini, Cursor, etc.) to Gemini Notebook:

```bash
# Automatic setup — picks the right config for each tool
nlm setup add claude-code
nlm setup add claude-desktop
nlm setup add gemini
nlm setup add github-copilot
nlm setup add cursor
nlm setup add cline
nlm setup add antigravity

# Generate JSON config for any other tool
nlm setup add json
```

Then use natural language: *"Create a notebook about quantum computing and generate a podcast"*

## Features

| Capability | CLI Command | MCP Tool |
|------------|-------------|----------|
| List notebooks | `nlm notebook list` | `notebook_list` |
| Create notebook | `nlm notebook create` | `notebook_create` |
| Add Sources (URL, Text, Drive, File) | `nlm source add` | `source_add` |
| Query notebook (persists to web UI) | `nlm notebook query` | `notebook_query` |
| List/view/export chat sessions | `nlm chats list/get/export` | `chat_list`/`chat_get`/`chat_export` |
| Create Studio Content (Audio, Video, etc.) | `nlm studio create` | `studio_create` |
| Revise slide decks | `nlm slides revise` | `studio_revise` |
| Download artifacts | `nlm download <type>` | `download_artifact` |
| Download all artifacts (one or all notebooks) | `nlm download all` | `download_all_artifacts` |
| Web/Drive research | `nlm research start` | `research_start` |
| Share notebook | `nlm share public/invite` | `notebook_share_*` |
| Sync Drive sources | `nlm source sync` | `source_sync_drive` |
| Batch operations | `nlm batch query/create/delete` | `batch` |
| Cross-notebook query | `nlm cross query` | `cross_notebook_query` |
| Pipelines (multi-step workflows) | `nlm pipeline run/list` | `pipeline` |
| Tag & smart select | `nlm tag add/list/select` | `tag` |
| Configure AI tools | `nlm setup add/remove/list` | — |
| Install AI Skills | `nlm skill install/update` | — |
| Diagnose issues | `nlm doctor` | — |

📚 **More Documentation:**
- **[Getting Started](docs/GETTING_STARTED.md)** — Install, login, agent setup, and migration from another Gemini Notebook MCP
- **[CLI Guide](docs/CLI_GUIDE.md)** — Complete command reference
- **[MCP Guide](docs/MCP_GUIDE.md)** — All 43 MCP tools with examples
- **[Authentication](docs/AUTHENTICATION.md)** — Setup and troubleshooting
- **[Remote MCP](docs/REMOTE_MCP.md)** — Web/mobile connector feasibility, security, and authentication limitations
- **[API Reference](docs/API_REFERENCE.md)** — Internal API docs for contributors

## Important Disclaimer

This MCP and CLI use **internal APIs** that:
- Are undocumented and may change without notice
- Require cookie extraction from your browser (I have a tool for that!)

Use at your own risk for personal/experimental purposes.

## Installation

> 🆕 **Claude Desktop users:** [Download the extension](https://github.com/jacob-bd/gemini-notebook-mcp-cli/releases/latest) (`.mcpb` file) → double-click → done! One-click install, no config needed.

Install from PyPI. This single package includes **both the CLI and MCP server**:

### Using uv (Recommended)
```bash
uv tool install notebooklm-mcp-cli
```

### Using uvx (Run Without Install)
```bash
uvx --from notebooklm-mcp-cli nlm --help
uvx --from notebooklm-mcp-cli notebooklm-mcp
```

### Using pip
```bash
pip install notebooklm-mcp-cli
```

### Using pipx
```bash
pipx install notebooklm-mcp-cli
```

**After installation, you get:**
- `nlm` — Command-line interface
- `notebooklm-mcp` — Gemini Notebook MCP server for AI assistants

<details>
<summary>Alternative: Install from Source</summary>

```bash
# Clone the repository
git clone https://github.com/jacob-bd/gemini-notebook-mcp-cli.git
cd notebooklm-mcp

# Install with uv
uv tool install .
```
</details>

## Upgrading

```bash
# Using uv
uv tool upgrade notebooklm-mcp-cli

# Using pip
pip install --upgrade notebooklm-mcp-cli

# Using pipx
pipx upgrade notebooklm-mcp-cli
```

After upgrading, restart your AI tool to reconnect to the updated MCP server:

- **Claude Code:** Restart the application, or use `/mcp` to reconnect
- **Cursor:** Restart the application
- **Gemini CLI:** Restart the CLI session

## Upgrading from Legacy Versions

If you previously installed the **separate** CLI and MCP packages, you need to migrate to the unified package.

### Step 1: Check What You Have Installed

```bash
uv tool list | grep notebooklm
```

**Legacy packages to remove:**
| Package | What it was |
|---------|-------------|
| `notebooklm-cli` | Old CLI-only package |
| `notebooklm-mcp-server` | Old MCP-only package |

### Step 2: Uninstall Legacy Packages

```bash
# Remove old CLI package (if installed)
uv tool uninstall notebooklm-cli

# Remove old MCP package (if installed)
uv tool uninstall notebooklm-mcp-server
```

### Step 3: Reinstall the Unified Package

After removing legacy packages, reinstall to fix symlinks:

```bash
uv tool install --force notebooklm-mcp-cli
```

> **Why `--force`?** When multiple packages provide the same executable, `uv` can leave broken symlinks after uninstalling. The `--force` flag ensures clean symlinks.

### Step 4: Verify Installation

```bash
uv tool list | grep notebooklm
```

You should see only:
```
notebooklm-mcp-cli v0.2.0
- nlm
- notebooklm-mcp
```

### Step 5: Re-authenticate

Your existing cookies should still work, but if you encounter auth issues:

```bash
nlm login
```

> **Note:** The configured MCP server name is now `gemini-notebook-mcp`. The executable remains `notebooklm-mcp` for compatibility with existing installations.

## Getting Started

If you are setting up the tool for the first time — or migrating from a
browser-based Gemini Notebook MCP — see the
[Getting Started Guide](docs/GETTING_STARTED.md). It covers install,
login, agent registration, and a step-by-step migration path that avoids
the "two Gemini Notebook servers registered" trap.

## Uninstalling

To completely remove the MCP:

```bash
# Using uv
uv tool uninstall notebooklm-mcp-cli

# Using pip
pip uninstall notebooklm-mcp-cli

# Using pipx
pipx uninstall notebooklm-mcp-cli

# Remove cached auth tokens and data (optional)
rm -rf ~/.notebooklm-mcp-cli
```

Also remove from your AI tools:

```bash
nlm setup remove claude-code
nlm setup remove cursor
# ... or any configured tool
```

## Authentication

Before using the CLI or MCP, you need to authenticate with Gemini Notebook:

### CLI Authentication (Recommended)

```bash
# Auto mode: launches your browser, you log in, cookies extracted automatically
nlm login

# Check if already authenticated
nlm login --check

# Use a named profile (for multiple Google accounts)
nlm login --profile work
nlm login --profile personal

# Manual mode: import cookies from a file
nlm login --manual --file cookies.txt

# External CDP provider (e.g., OpenClaw-managed browser)
nlm login --provider openclaw --cdp-url http://127.0.0.1:18800
```

**Profile management:**
```bash
nlm login --check                    # Show current auth status
nlm login switch <profile>           # Switch the default profile
nlm login profile list               # List all profiles with email addresses
nlm login profile delete <profile>   # Delete a profile
nlm login profile rename <old> <new> # Rename a profile
```

Each profile gets its own isolated browser session, so you can be logged into multiple Google accounts simultaneously.

### Standalone Auth Tool

If you only need the MCP server (not the CLI):

```bash
nlm login              # Auto mode (launches browser)
nlm login --manual     # Manual file mode
```

**How it works:** Auto mode launches a dedicated browser profile (supports Chrome, Arc, Brave, Edge, Chromium, Firefox, and more), you log in to Google, and cookies are extracted automatically. Your login persists for future auth refreshes.

**Prefer a specific browser?** Set it with `nlm config set auth.browser chromium` (or `brave`, `arc`, `edge`, `chrome`, `firefox`, etc.). Falls back to auto-detection if the preferred browser is not found. When Chromium/CDP is unavailable, `auto` can fall back to Firefox.

For detailed instructions and troubleshooting, see **[docs/AUTHENTICATION.md](docs/AUTHENTICATION.md)**.

## MCP Configuration

> **⚠️ Context Window Warning:** This MCP provides **43 tools**. Disable it when not using Gemini Notebook to preserve context. In Claude Code: `@gemini-notebook-mcp` to toggle. To keep it on but expose only a subset, see [Selective tool exposure](docs/MCP_GUIDE.md#selective-tool-exposure).

### Automatic Setup (Recommended)

Use `nlm setup` to automatically configure the MCP server for your AI tools — no manual JSON editing required:

```bash
# Add to any supported tool
nlm setup add claude-code
nlm setup add claude-desktop
nlm setup add claude-desktop --profile 3p  # Relay AI / Claude 3P
nlm setup add gemini
nlm setup add github-copilot
nlm setup add cursor
nlm setup add windsurf

# Generate JSON config for any other tool
nlm setup add json

# Check which tools are configured
nlm setup list

# Diagnose installation & auth issues
nlm doctor
```

Claude Desktop setup only writes to profiles that are detected as present. If
both regular and Relay AI/3P profiles exist, the CLI asks whether to configure
regular, 3P, or both. For scripts, use `--profile regular|3p|both`. If no
Claude Desktop profile is detected, nothing is created or changed.

Removal uses the same profile selection, for example
`nlm setup remove claude-desktop --profile regular`.
Removal only offers detected profiles containing this MCP or a recognized
legacy entry; unrelated MCP servers are left untouched.

Before adding or removing the MCP, fully quit the selected Claude Desktop
profile. The CLI detects running regular and Relay AI/3P instances and refuses
to write while they are open, because Claude may rewrite the config and discard
the change. Reopen Claude Desktop after setup completes.

### Install AI Skills (Optional)

Install the Gemini Notebook expert guide for your AI assistant to help it use the tools effectively. Supported for **Cline**, **Antigravity**, **OpenClaw**, **Codex**, **OpenCode**, **Claude Code**, and **Gemini CLI**.

```bash
# Install skill files
nlm skill install cline
nlm skill install openclaw
nlm skill install codex
nlm skill install antigravity

# Update skills
nlm skill update
```

User-level skill installation requires the target tool to be detected first;
the CLI will not create a missing tool directory or install anyway. Use
`--level project` when you intentionally want a project-local skill.

### Remove from a tool

```bash
nlm setup remove claude-code
```

### Using uvx (No Install Required)

If you don't want to install the package, you can use `uvx` to run on-the-fly:

```bash
# Run CLI commands directly
uvx --from notebooklm-mcp-cli nlm setup add cursor
uvx --from notebooklm-mcp-cli nlm login
```

For tools that use JSON config, point them to uvx:
```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "uvx",
      "args": ["--from", "notebooklm-mcp-cli", "notebooklm-mcp"]
    }
  }
}
```

<details>
<summary>Manual Setup (if you prefer)</summary>

> **Tip:** Run `nlm setup add json` for an interactive wizard that generates the right JSON snippet for your tool.

**Claude Code / Gemini CLI** support adding MCP servers via their own CLI:
```bash
claude mcp add --scope user gemini-notebook-mcp notebooklm-mcp
gemini mcp add --scope user gemini-notebook-mcp notebooklm-mcp
```

**Cursor / Windsurf** resolve commands from your `PATH`, so the command name is enough:
```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "notebooklm-mcp"
    }
  }
}
```

| Tool | Config Location |
|------|-----------------|
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |

**GitHub Copilot (VS Code workspace)** uses `.vscode/mcp.json` with a top-level `servers` key:
```json
{
  "servers": {
    "gemini-notebook-mcp": {
      "command": "notebooklm-mcp",
      "args": []
    }
  }
}
```

**Claude Desktop** may not resolve `PATH` — use the full path to the binary:
```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "/full/path/to/notebooklm-mcp"
    }
  }
}
```

Find your path with: `which notebooklm-mcp`

| Tool | Config Location |
|------|-----------------|
| Claude Desktop (macOS current/3P) | `~/Library/Application Support/Claude-3p/claude_desktop_config.json` |
| Claude Desktop (macOS legacy) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` (an unambiguous MSIX path is detected automatically) |
| Claude Desktop (Windows 3P) | `%LOCALAPPDATA%\Claude-3p\claude_desktop_config.json` |
| Claude Desktop (Linux) | `~/.config/Claude/claude_desktop_config.json` |
| Claude Desktop (Linux 3P) | `${XDG_CONFIG_HOME:-~/.config}/Claude-3p/claude_desktop_config.json` |
| GitHub Copilot | `.vscode/mcp.json` |

</details>

📚 **Full configuration details:** [MCP Guide](docs/MCP_GUIDE.md) — Server options, environment variables, HTTP transport, and context window management. For Claude web/mobile and public deployment, read [Remote MCP Deployment](docs/REMOTE_MCP.md) first.

## What You Can Do

Simply chat with your AI tool (Claude Code, Cursor, Gemini CLI) using natural language. Here are some examples:

### Research & Discovery

- "List all my Gemini Notebook notebooks"
- "Create a new notebook called 'AI Strategy Research'"
- "Start web research on 'enterprise AI ROI metrics' and show me what sources it finds"
- "Do a deep research on 'cloud marketplace trends' and import the top 10 sources"
- "Search my Google Drive for documents about 'product roadmap' and create a notebook"

### Adding Content

- "Add this URL to my notebook: https://example.com/article"
- "Add this YouTube video about Kubernetes to the notebook"
- "Add my meeting notes as a text source to this notebook"
- "Import this Google Doc into my research notebook"

### AI-Powered Analysis

- "What are the key findings in this notebook?"
- "Summarize the main arguments across all these sources"
- "What does this source say about security best practices?"
- "Get an AI summary of what this notebook is about"
- "Configure the chat to use a learning guide style with longer responses"

*(All queries sent from CLI or MCP automatically persist in your Gemini Notebook web UI chat history!)*

### Content Generation

- "Create an audio podcast overview of this notebook in deep dive format"
- "Generate a video explainer with classic visual style"
- "Make a short vertical video overview of the key idea"
- "Make a briefing doc from these sources"
- "Create flashcards for studying, medium difficulty"
- "Generate an infographic in landscape orientation with professional style"
- "Build a mind map from my research sources"
- "Create a slide deck presentation from this notebook"

### Smart Management

- "Check which Google Drive sources are out of date and sync them"
- "Show me all the sources in this notebook with their freshness status"
- "Delete this source from the notebook"
- "Check the status of my audio overview generation"
- "Check this specific artifact without listing every Studio item"
- "List only the generated videos in this notebook"

### Sharing & Collaboration

- "Show me the sharing settings for this notebook"
- "Make this notebook public so anyone with the link can view it"
- "Disable public access to this notebook"
- "Invite user@example.com as an editor to this notebook"
- "Add a viewer to my research notebook"

**Pro tip:** After creating studio content (audio, video, reports, etc.), poll the status to get download URLs when generation completes.

## Authentication Lifecycle

| Component | Duration | Refresh |
|-----------|----------|---------|
| Cookies | ~2-4 weeks | Auto-refresh via headless browser (if profile saved) |
| CSRF Token | ~minutes | Auto-refreshed on every request failure |
| Session ID | Per MCP session | Auto-extracted on MCP start |

**v0.1.9+**: The server now automatically handles token expiration:
1. Refreshes CSRF tokens immediately when expired
2. Reloads cookies from disk if updated externally
3. Runs headless browser auth if profile has saved login

You can also call `refresh_auth()` to explicitly reload tokens.

If automatic refresh fails (Google login fully expired), run `nlm login` again.

For suspected browser-bound auth replay failures, run `nlm doctor auth-replay`.
If the `cdp_in_page` probe succeeds while normal replay fails, see
[Experimental browser-backed RPC transport](docs/AUTHENTICATION.md#experimental-browser-backed-rpc-transport).

## Troubleshooting

### `uv tool upgrade` Not Installing Latest Version

**Symptoms:**
- Running `uv tool upgrade notebooklm-mcp-cli` installs an older version (e.g., 0.1.5 instead of 0.1.9)
- `uv cache clean` doesn't fix the issue

**Why this happens:** `uv tool upgrade` respects version constraints from your original installation. If you initially installed an older version or with a constraint, `upgrade` stays within those bounds by design.

**Fix — Force reinstall:**
```bash
uv tool install --force notebooklm-mcp-cli
```

This bypasses any cached constraints and installs the absolute latest version from PyPI.

**Verify:**
```bash
uv tool list | grep notebooklm
# Should show: notebooklm-mcp-cli v0.1.9 (or latest)
```


## Limitations

- **Rate limits**: Free tier has ~50 queries/day
- **No official support**: API may change without notice
- **Cookie expiration**: Need to re-extract cookies every few weeks

## Contributing

See [CLAUDE.md](CLAUDE.md) for detailed API documentation and how to add new features.

## Vibe Coding Alert

Full transparency: this project was built by a non-developer using AI coding assistants. If you're an experienced Python developer, you might look at this codebase and wince. That's okay.

The goal here was to scratch an itch - programmatic access to Gemini Notebook - and learn along the way. The code works, but it's likely missing patterns, optimizations, or elegance that only years of experience can provide.

**This is where you come in.** If you see something that makes you cringe, please consider contributing rather than just closing the tab. This is open source specifically because human expertise is irreplaceable. Whether it's refactoring, better error handling, type hints, or architectural guidance - PRs and issues are welcome.

Think of it as a chance to mentor an AI-assisted developer through code review. We all benefit when experienced developers share their knowledge.

## Credits

Special thanks to:
- **Le Anh Tuan** ([@latuannetnam](https://github.com/latuannetnam)) for contributing the HTTP transport, debug logging system, and performance optimizations.
- **David Szabo-Pele** ([@davidszp](https://github.com/davidszp)) for the `source_get_content` tool and Linux auth fixes.
- **saitrogen** ([@saitrogen](https://github.com/saitrogen)) for the research polling query fallback fix.
- **devnull03** ([@devnull03](https://github.com/devnull03)) for multi-browser CDP authentication support (Arc, Brave, Edge, Chromium, Vivaldi, Opera).
- **VooDisss** ([@VooDisss](https://github.com/VooDisss)) for multi-browser authentication improvements.
- **codepiano** ([@codepiano](https://github.com/codepiano)) for the configurable DevTools timeout for the auth CLI.
- **Tony Hansmann** ([@997unix](https://github.com/997unix)) for contributing the `nlm setup` and `nlm doctor` commands and CLI Guide documentation.
- **Fabiana Furtado** ([@fabianafurtadoff](https://github.com/fabianafurtadoff)) for batch operations, cross-notebook query, pipelines, and smart select/tagging (PR #90).
- **Amy-Ra-lph** ([@Amy-Ra-lph](https://github.com/Amy-Ra-lph)) for security hardening: TOCTOU-safe credential storage, sensitive cookie redaction from debug logs, and pinning all CI actions to full commit SHAs (PRs #205–207).
- **Kyle Brodeur** ([@kylebrodeur](https://github.com/kylebrodeur)) for WSL2 authentication support with Windows Chrome integration (PR #138).
- **Robiton** ([@Robiton](https://github.com/Robiton)) for enterprise Gemini Notebook support via configurable base URL (PR #114).
- **pjeby** ([@pjeby](https://github.com/pjeby)) for connection pooling and fast startup improvements (PR #54).
- **beausea** ([@beausea](https://github.com/beausea)) for making the interface language configurable via the `NOTEBOOKLM_HL` environment variable (PR #59).
- **JumpLao** ([@JumpLao](https://github.com/JumpLao)) for extended audio, video, and image format support (PR #82).
- **cbruyndoncx** ([@cbruyndoncx](https://github.com/cbruyndoncx)) for including `cited_text` passages in query output (PR #81).
- **zxyasfas** ([@zxyasfas](https://github.com/zxyasfas)) for cited-only research import (PR #188).
- **Serdar Akın** ([@SERDAR-AKIN](https://github.com/SERDAR-AKIN)) for the multi-probe `AuthHealthChecker` that fixes false `"stale"` reports for semi-stale cookies (PR #219).


## Star History

[![Star History Chart](https://star-history.dera.page/svg?repos=jacob-bd/gemini-notebook-mcp-cli&type=Date)](https://star-history.dera.page/#jacob-bd/gemini-notebook-mcp-cli&Date)

## License

[MIT License](LICENSE)
