# CLI Guide

Complete command reference for the `nlm` command-line interface.

## Installation

```bash
# Using uv (recommended)
uv tool install notebooklm-mcp-cli

# Using pip
pip install notebooklm-mcp-cli
```

## Authentication

```bash
nlm login                         # Opens browser, extracts cookies automatically
nlm login --profile work          # Named profile for multiple accounts
nlm login --check                 # Check if authenticated
nlm login switch <profile>        # Switch default profile
nlm login profile list            # List all profiles with email addresses
nlm login profile delete <name>   # Delete a profile
nlm login profile rename <old> <new>  # Rename a profile

# External CDP provider (e.g., OpenClaw-managed browser)
nlm login --provider openclaw --cdp-url http://127.0.0.1:18800
```

Each profile gets its own isolated browser session (supports Chrome, Arc, Brave, Edge, Chromium, and more), so you can stay logged into multiple Google accounts simultaneously.

## Command Structure

The CLI supports **two styles** - use whichever feels natural:

```bash
# Noun-first (resource-oriented)
nlm notebook create "Title"
nlm source add <notebook> --url <url>

# Verb-first (action-oriented)  
nlm create notebook "Title"
nlm add url <notebook> <url>
```

---

## Command Reference

### Notebooks

```bash
nlm notebook list                      # List all notebooks
nlm notebook list --json               # JSON output
nlm notebook create "Title"            # Create notebook
nlm notebook get <id> --json           # Get details, including notebook emoji
nlm notebook describe <id>             # AI summary
nlm notebook rename <id> "New Title"   # Rename
nlm notebook delete <id> --confirm --json  # Delete with structured confirmation
nlm notebook query <id> "question" --json # Response includes the original question
```

### Sources

```bash
nlm source list <notebook>                         # List sources
nlm source add <notebook> --url "https://..."      # Add URL
nlm source add <notebook> --url "https://..." --json  # Return the new source ID as JSON
nlm source add <notebook> --url "https://..." --wait  # Add and wait until ready
nlm source add <notebook> --text "content" --title "Notes"  # Add text
nlm source add <notebook> --file document.pdf --wait  # Upload file
nlm source add <notebook> --youtube "https://..."  # Add YouTube
nlm source add <notebook> --drive <doc-id>         # Add Drive doc
nlm source get <source-id>                         # Get content
nlm source describe <source-id>                    # AI summary
nlm source stale <notebook>                        # Check stale Drive sources
nlm source sync <notebook> --confirm               # Sync stale sources
nlm source delete <source-id> --confirm --json     # Structured deletion result
```

### Studio Content Creation

```bash
# Audio (podcasts)
nlm audio create <notebook> --confirm
nlm audio create <notebook> --confirm --json  # Return the artifact ID as JSON
nlm audio create <notebook> --format deep_dive --length long --confirm
nlm audio create <notebook> --language es-419 --confirm  # Latin-American Spanish
# Formats: deep_dive, brief, critique, debate
# Lengths: short, default, long

# Video
nlm video create <notebook> --confirm
nlm video create <notebook> --format explainer --style classic --confirm
nlm video create <notebook> --style custom --style-prompt "A children's storybook illustration" --confirm
# Formats: explainer, brief, cinematic, short (vertical, ~60s)
# Styles: auto_select, custom, classic, whiteboard, kawaii, anime, watercolor, retro_print, heritage, paper_craft (not for cinematic/short)
# Short language selection is best-effort; --language adds an explicit requirement to the focus prompt.

# Reports
nlm report create <notebook> --format "Briefing Doc" --confirm
# Formats: "Briefing Doc", "Study Guide", "Blog Post", "Create Your Own"

# Quiz & Flashcards
nlm quiz create <notebook> --count 10 --difficulty medium --focus "Focus on key concepts" --confirm
nlm flashcards create <notebook> --difficulty hard --focus "Focus on definitions" --confirm

# Other
nlm mindmap create <notebook> --confirm
nlm slides create <notebook> --confirm

# Revise slides (creates new deck)
nlm slides revise <artifact-id> --slide '1 Make the title larger' --confirm
nlm slides revise <artifact-id> --slide '1 Fix title' --slide '3 Remove image' --confirm
nlm infographic create <notebook> --orientation landscape --style professional --confirm
nlm data-table create <notebook> --description "Sales by region" --confirm
```

For Audio Overviews, Gemini Notebook (formerly Google NotebookLM) has been observed using the BCP-47 region
subtag to select the voice accent. For example, `es` and `es-ES` produce
Spain Spanish, while `es-US` and `es-419` produce Latin-American Spanish.
Changing the focus prompt does not reliably change the accent. This is
observed Gemini Notebook behavior, not a guaranteed API contract.

Set `NOTEBOOKLM_HL=es-419` to use a regional locale as the default artifact
language, or pass `--language es-419` for a specific generation.

### Downloads

```bash
nlm download audio <notebook> <artifact-id> --output podcast.mp3
nlm download video <notebook> <artifact-id> --output video.mp4
nlm download report <notebook> <artifact-id> --output report.md
nlm download mind-map <notebook> <artifact-id> --output mindmap.json
nlm download slide-deck <notebook> <artifact-id> --output slides.pdf
nlm download infographic <notebook> <artifact-id> --output infographic.png
nlm download data-table <notebook> <artifact-id> --output data.csv

# Interactive formats (quiz/flashcards)
nlm download quiz <notebook> <artifact-id> --format html --output quiz.html
nlm download flashcards <notebook> <artifact-id> --format markdown --output cards.md

# Download every completed artifact into a per-notebook folder
nlm download all <notebook> --output-dir ./exports
nlm download all --all-notebooks --output-dir ./exports --skip-existing
```

### Research

```bash
nlm research start "query" --notebook-id <id> --mode fast  # Quick search
nlm research start "query" --notebook-id <id> --mode deep  # Extended research
nlm research start "query" --notebook-id <id> --source drive  # Search Drive
nlm research start "query" --notebook-id <id> --auto-import # Start, poll, and import in one step
nlm research status <notebook> --max-wait 300              # Poll until done
nlm research import <notebook> <task-id>                   # Import sources
nlm research import <notebook> <task-id> --timeout 600     # Custom timeout (default: 300s)
nlm research import <notebook> <task-id> --cited-only      # Import cited deep research sources
```

### Studio Status

```bash
nlm studio status <notebook>           # Check artifact generation status
nlm studio status <notebook> --artifact-id <id>  # Poll one artifact
nlm studio status <notebook> --json --mcp-compatible  # MCP-shaped paginated JSON
nlm video list <notebook>               # List video artifacts only
nlm studio delete <notebook> <artifact-id> --confirm  # Delete artifact
```

The existing `--json` output remains a plain list for script compatibility and
contains both `id` and `artifact_id`. `--mcp-compatible` returns the MCP envelope,
uses lean fields by default, and limits the response to 20 artifacts. Add
`--full`, `--limit`, or `--offset` when detailed or later-page data is needed.

### Sharing

```bash
nlm share status <notebook>                    # View sharing settings
nlm share public <notebook>                    # Enable public link
nlm share private <notebook>                   # Disable public link
nlm share invite <notebook> email@example.com  # Invite viewer
nlm share invite <notebook> email --role editor  # Invite editor
```

### Batch Operations

```bash
nlm batch query "What are the key takeaways?" --notebooks "id1,id2"
nlm batch query "Summarize" --tags "ai,research"          # Query by tag
nlm batch query "Summarize" --all                         # Query ALL notebooks
nlm batch add-source "https://..." --notebooks "id1,id2"
nlm batch create "Project A, Project B, Project C"        # Create multiple
nlm batch delete --notebooks "id1,id2" --confirm          # Delete multiple
nlm batch studio audio --tags "research"                  # Generate across notebooks
```

### Cross-Notebook Query

```bash
nlm cross query "What features are discussed?" --notebooks "id1,id2"
nlm cross query "Compare approaches" --tags "ai,research"
nlm cross query "Summarize everything" --all              # Query ALL notebooks
```

### Pipelines

```bash
nlm pipeline list                                         # List available pipelines
nlm pipeline run ingest-and-podcast --notebook <id> --input-url "https://..."
nlm pipeline run research-and-report --notebook <id> --input-url "https://..."
nlm pipeline run multi-format --notebook <id>             # Audio + report + flashcards
```

**Built-in pipelines:** `ingest-and-podcast`, `research-and-report`, `multi-format`

Create custom pipelines: add YAML files to `~/.notebooklm-mcp-cli/pipelines/`

### Tag & Smart Select

```bash
nlm tag add <notebook> --tags "ai,research,llm"           # Add tags
nlm tag add <notebook> --tags "ai" --title "My Notebook"  # With display title
nlm tag remove <notebook> --tags "ai"                     # Remove tags
nlm tag list                                              # List all tagged notebooks
nlm tag select "ai research"                              # Find notebooks by tag match
```

### Chat Configuration

```bash
nlm chat configure <notebook> --goal default --length default
nlm chat configure <notebook> --goal learning_guide --length longer
nlm chat configure <notebook> --goal custom --prompt "You are an expert..."
```

### Configuration

```bash
nlm config show                         # Show all settings
nlm config get auth.default_profile     # Get a specific value
nlm config set auth.default_profile work  # Set default profile
nlm config set output.format json       # Change default output format
```

**Available Settings:**

| Key | Default | Description |
|-----|---------|-------------|
| `output.format` | `table` | Default output format (table, json) |
| `output.color` | `true` | Enable colored output |
| `output.short_ids` | `true` | Show shortened IDs |
| `auth.browser` | `auto` | Preferred browser for login (auto, chrome, arc, brave, edge, chromium, vivaldi, opera). Falls back to auto if the preferred browser is not found. |
| `auth.default_profile` | `default` | Profile to use when `--profile` not specified. **Note:** The MCP Server always uses the active default profile. Changing this setting will instantaneously switch the MCP server's Google account. |

### Aliases (Shortcuts)

```bash
nlm alias set myproject <notebook-id>   # Create alias
nlm alias list                          # List all aliases
nlm alias get myproject                 # Resolve to UUID
nlm alias delete myproject              # Remove alias

# Use aliases anywhere
nlm notebook get myproject
nlm source list myproject
```

### Skills (AI Assistant Integration)

```bash
nlm skill list                           # Show installation status
nlm skill install claude-code            # Install for Claude Code
nlm skill install cursor                 # Install for Cursor AI
nlm skill install <tool> --level project # Install at project level
nlm skill uninstall <tool>               # Remove skill
nlm skill show                           # View skill content

# Verb-first alternatives
nlm install skill claude-code
nlm list skills
```

**Gemini CLI, Codex, and other agent CLIs** all install to `~/.agents/skills/nlm-skill/` (`.agents/skills/` at project level). These three targets are interchangeable aliases:

```bash
nlm skill install agents      # Generic name
nlm skill install codex       # Alias for OpenAI Codex CLI
nlm skill install gemini-cli  # Alias for Google Gemini CLI
```

**Alef Agent** (CLI target `alef-agent`) is separate: it installs under `~/.alef-agent/workspace/skills/nlm-skill/` with tool-specific skill frontmatter, not under `.agents/skills/`.

```bash
nlm skill install alef-agent
```

**Supported Tools:** `claude-code`, `cursor`, `agents`, `gemini-cli`, `codex`, `opencode`, `antigravity`, `cline`, `openclaw`, `alef-agent`, `other`

### Setup (MCP Server Configuration)

Configure the Gemini Notebook MCP server for AI tools in one command:

The configured server name is `gemini-notebook-mcp`; the executable remains
`notebooklm-mcp` for compatibility with existing installations.

```bash
nlm setup add claude-code       # Configure via `claude mcp add`
nlm setup add claude-desktop    # Configure detected Claude Desktop profile(s)
nlm setup add claude-desktop --profile 3p  # Select Relay AI / 3P explicitly
nlm setup remove claude-desktop --profile regular  # Remove from regular explicitly
nlm setup add gemini            # Write ~/.gemini/settings.json
nlm setup add github-copilot    # Write .vscode/mcp.json
nlm setup add cursor            # Write ~/.cursor/mcp.json
nlm setup add windsurf          # Write mcp_config.json
nlm setup add json              # Generate JSON config for any tool

nlm setup remove gemini         # Remove from Gemini CLI

nlm setup list                  # Show all clients and config status
```

Claude Desktop setup never creates a profile that is not detected. When both
regular and Relay AI/3P profiles are present, the command prompts for regular,
3P, or both. Removal uses the same profile selection. User-level skill installs
likewise require the target tool to be detected; project-level installs remain
explicitly scoped to the current project.
Removal only offers profiles containing `gemini-notebook-mcp` or a recognized
legacy entry, so unrelated MCP servers are not removed.

Fully quit the selected Claude Desktop profile before adding or removing the
MCP, including when it was launched by Relay AI. The CLI detects running
regular and 3P instances and refuses to write while they are open, since Claude
may rewrite the config and discard the change. Reopen Claude Desktop after the
command completes.

**Supported Clients:** `claude-code`, `claude-desktop`, `gemini`, `github-copilot`, `cursor`, `windsurf`, `cline`, `antigravity`, `codex`, `opencode`

**For unsupported tools:** Use `nlm setup add json` to interactively generate a JSON config snippet. Choose between uvx or regular mode, full path or command name, and whether to include the `mcpServers` wrapper. The result is printed and can be copied to clipboard.

> **Note:** `nlm setup` configures the MCP server transport. Use `nlm skill install` to install skill/reference docs for AI tools that don't use MCP.

### Doctor (Diagnostics)

Run diagnostics to troubleshoot installation, authentication, and configuration issues:

```bash
nlm doctor              # Run all checks
nlm doctor --verbose    # Include additional details (Python version, paths, etc.)
```

**Checks performed:**

| Category | What it checks |
|----------|---------------|
| Installation | Package version, `nlm` and `notebooklm-mcp` binary paths |
| Authentication | Profile status, cookies present, CSRF token, account email |
| Browser | Chromium-based browser installed, saved profiles for headless auth |
| AI Tools | MCP configuration status for each supported client |

Each issue includes a suggested fix (e.g., "Run `nlm login` to authenticate").

---

## Output Formats

| Flag | Description |
|------|-------------|
| (none) | Rich table format |
| `--json` | JSON output, including source/Studio creation and deletion results |
| `--quiet` | IDs only |
| `--title` | "ID: Title" format |
| `--full` | All columns |

---

## Complete Workflow Example

```bash
# 1. Authenticate and configure
nlm login
nlm setup add claude-code       # One-time MCP setup

# 2. Create notebook and set alias
nlm notebook create "AI Research"
nlm alias set ai <notebook-id>

# 3. Add sources (with --wait to ensure ready)
nlm source add ai --url "https://example.com/article" --wait
nlm source add ai --file research.pdf --wait

# 4. Generate podcast
nlm audio create ai --format deep_dive --confirm

# 5. Wait for generation
nlm studio status ai

# 6. Download when ready
nlm download audio ai <artifact-id> --output podcast.mp3
```

---

## Tips

- Saved cookies often remain usable for weeks. Run `nlm login` for confirmed stale or missing credentials.
- Use `--confirm` for all create/delete commands in scripts
- Use `--wait` when adding sources to ensure they're ready before querying
- Use aliases for frequently-used notebooks
- Audio/video takes 1-5 minutes; poll with `nlm studio status`
- Use `nlm login switch <name>` to change the default profile
- Run `nlm login profile list` to see all profiles with their associated email addresses
- Run `nlm doctor` to diagnose installation, auth, or config issues
- Use `nlm setup add <client>` to quickly configure MCP for your AI tool

---

## Scripting & Automation

### Getting IDs for piping

Use `--quiet` when you only need IDs — it outputs one ID per line, no parsing required:

```bash
# Grab the first notebook ID in a shell script
notebook_id=$(nlm notebook list --quiet | head -1)
nlm notebook query "$notebook_id" "Summarize key points"
```

### Parsing `--json` output

When you need more than just IDs (title, source count, etc.), use `--json`. It emits
clean JSON to stdout — always parse it properly rather than splitting strings:

```python
import json
import subprocess

result = subprocess.run(
    ["nlm", "notebook", "list", "--json"],
    capture_output=True, text=True
)
notebooks = json.loads(result.stdout)
notebook_id = notebooks[0]["id"]   # UUID like "abc12345-..."
```
