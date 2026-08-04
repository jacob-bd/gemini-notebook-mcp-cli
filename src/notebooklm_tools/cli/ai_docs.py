"""AI-friendly documentation output for the --ai flag."""

from notebooklm_tools import __version__

AI_DOCS = """# NLM CLI - AI Assistant Guide

You are interacting with `nlm`, a command-line interface for Google NotebookLM.
This documentation teaches you how to use the tool effectively.

## Version

nlm version {version}

---

## CRITICAL: Authentication

Saved cookies often remain usable for weeks. Authenticate for first-time setup
or confirmed stale/missing credentials. Do not treat an `unverified` auth
health result as confirmed expiration.

### First-Time Setup / Re-Authentication
```bash
nlm login
```
This opens NotebookLM in your browser (Chrome, Arc, Brave, Edge, Chromium, or another supported Chromium-family browser) and extracts cookies automatically.
Output on success: `✓ Successfully authenticated!`

### Check If Already Authenticated
```bash
nlm login --check
```
Validates credentials by making a real API call (lists notebooks).
Shows: `✓ Authenticated` with notebook count, or error if expired.

### Auto-Authentication Recovery (Automatic)
The CLI includes automatic recovery for both auth and server errors:

**Auth Recovery (3-layer):**
1. **CSRF/Session Refresh**: Automatically refreshes tokens on 401 errors
2. **Token Reload**: Reloads tokens from disk if updated externally (e.g., by another session)
3. **Headless Auth**: If browser profile has saved login, attempts headless authentication

**Server Error Retry:**
Transient server errors (429, 500, 502, 503, 504) are automatically retried up to 3 times with exponential backoff (1s, 2s, 4s). This handles Google API flakiness transparently.

This means most errors are handled automatically. You only need to manually run `nlm login` if all recovery layers fail.

### Session Expired?
If ANY command returns:
- "Cookies have expired"
- "authentication may have expired"

Run:
```bash
nlm login
```

---

## Command Structure: Noun-First vs Verb-First

The CLI supports **TWO command styles** - use whichever feels more natural:

### Noun-First (Resource-Oriented)
```bash
nlm notebook create "Title"
nlm notebook list
nlm source add <notebook> --url <url>
nlm studio status <notebook>
```

### Verb-First (Action-Oriented)
```bash
nlm create notebook "Title"
nlm list notebooks
nlm add url <notebook> <url>
nlm status artifacts <notebook>
```

**Both styles call the same functions.** Choose based on preference. This guide shows both.

---

## Quick Reference

### All Top-Level Commands (Noun-First)

| Command | Description |
|---------|-------------|
| `nlm login` | Authenticate with NotebookLM and manage profiles (**START HERE**) |
| `nlm config` | View/edit configuration (show, get, set) |
| `nlm notebook` | Manage notebooks (list, create, get, describe, rename, delete, query) |
| `nlm source` | Manage sources (list, add, get, describe, content, rename, delete, stale, sync) |
| `nlm chat` | Chat with notebooks (start, configure) |
| `nlm studio` | Manage artifacts (status, delete) |
| `nlm research` | Research and discover sources (start, status, import) |
| `nlm alias` | Manage ID shortcuts (set, get, list, delete) |
| `nlm download` | Download artifacts (audio, video, report, mind-map, slides, infographic, data-table) |
| `nlm audio` | Create audio overviews/podcasts (create) |
| `nlm report` | Create reports (create) |
| `nlm quiz` | Create quizzes (create) |
| `nlm flashcards` | Create flashcards (create) |
| `nlm mindmap` | Create mind maps (create) |
| `nlm slides` | Create and revise slide decks (create, revise) |
| `nlm infographic` | Create infographics (create) |
| `nlm video` | Create video overviews (create) |
| `nlm data-table` | Create data tables (create) |
| `nlm share` | Manage notebook sharing (status, public, private, invite) |
| `nlm batch` | Batch operations across multiple notebooks (query, add-source, create, delete, studio) |
| `nlm cross` | Cross-notebook aggregated query (query) |
| `nlm pipeline` | Multi-step notebook workflows (list, run) |
| `nlm tag` | Tag notebooks and find relevant ones (add, remove, list, select) |
| `nlm skill` | Install AI assistant skills (install, uninstall, list, show) |
| `nlm doctor` | Diagnose installation, auth, browser, and AI tool configs |
| `nlm setup` | Configure MCP server for AI tools (add, remove, list) |

### All Verb-First Commands

| Command | Description |
|---------|-------------|
| `nlm create` | Create resources (notebook, audio, video, report, infographic, slides, quiz, flashcards, data-table, mindmap) |
| `nlm list` | List resources (notebooks, sources, artifacts, aliases, stale-sources) |
| `nlm get` | Get details (notebook, source, config, alias) |
| `nlm delete` | Delete resources (notebook, source, artifact, alias) |
| `nlm add` | Add sources (url, text, drive) |
| `nlm describe` | Get AI summaries (notebook, source) |
| `nlm query` | Chat with sources (notebook) |
| `nlm sync` | Sync Drive sources |
| `nlm content` | Get raw source content |
| `nlm stale` | List stale Drive sources |
| `nlm rename` | Rename resources (notebook, source, studio) |
| `nlm status` | Check status (artifacts, research) |
| `nlm configure` | Configure settings (chat) |
| `nlm set` | Set values (alias, config) |
| `nlm show` | Show information (config, aliases, skill) |
| `nlm install` | Install resources (skill) |
| `nlm uninstall` | Uninstall resources (skill) |

---

## Alias System (Shortcuts for UUIDs)

Create memorable names for long UUIDs:

```bash
# IMPORTANT: Always check existing aliases before creating new ones
nlm alias list

# Set an alias (type is auto-detected)
nlm alias set myproject abc123-def456-...

# Use aliases anywhere an ID is expected
nlm notebook get myproject
nlm source list myproject  
nlm audio create myproject --confirm

# Manage aliases
nlm alias list                    # List all
nlm alias get myproject           # Resolve to UUID
nlm alias delete myproject        # Remove
```

---

## Complete Command Reference

### Login & Auth

```bash
nlm login                              # Authenticate (opens browser)
nlm login --profile work               # Named profile
nlm login --manual --file <path>       # Import cookies from file
nlm login --check                      # Only check if auth valid
nlm login --provider openclaw --cdp-url http://127.0.0.1:18800  # External CDP provider
nlm login switch <profile>          # Switch the default profile
nlm login profile list              # List all profiles with email addresses
nlm login profile delete <name>     # Delete a profile
nlm login profile rename <old> <new> # Rename a profile
```


### Notebook Commands

**Noun-First:**
```bash
nlm notebook list                      # List all notebooks
nlm notebook list --json               # JSON output
nlm notebook list --quiet              # IDs only
nlm notebook list --title              # "ID: Title" format
nlm notebook list --full               # All columns

nlm notebook create "Title"            # Create new notebook
nlm notebook get <id> --json           # Get details, including notebook emoji
nlm notebook describe <id>             # AI summary with topics
nlm notebook describe <id> --json      # JSON output
nlm notebook rename <id> "New Title"   # Rename notebook
nlm notebook delete <id> --confirm --json  # Structured deletion result
nlm notebook query <id> "question"     # Chat with sources
nlm notebook query <id> "question" --json  # JSON output
nlm notebook query <id> "follow up" --conversation-id <cid>  # Persists in web UI history
nlm notebook query <id> "question" --source-ids <id1,id2>
```

**Verb-First:**
```bash
nlm list notebooks                     # List all notebooks
nlm create notebook "Title"            # Create new notebook
nlm get notebook <id>                  # Get notebook details
nlm describe notebook <id>             # AI summary with topics
nlm rename notebook <id> "New Title"   # Rename notebook
nlm delete notebook <id> --confirm     # Delete permanently
nlm query notebook <id> "question"     # Chat with sources
```

### Source Commands

**Noun-First:**
```bash
nlm source list <notebook-id>          # List sources
nlm source list <notebook-id> --full   # Full details
nlm source list <notebook-id> --url    # "ID: URL" format
nlm source list <notebook-id> --drive  # Show Drive sources with freshness
nlm source list <notebook-id> --drive --skip-freshness  # Faster, skip freshness checks

nlm source add <notebook-id> --url "https://..."           # Add URL
nlm source add <notebook-id> --url "https://..." --json    # Return new source ID as JSON
nlm source add <notebook-id> --url "https://..." --wait    # Add URL and wait until processed
nlm source add <notebook-id> --url "https://youtube.com/..." # Add YouTube
nlm source add <notebook-id> --text "content" --title "Title"  # Add text
nlm source add <notebook-id> --file /path/to/doc.pdf        # Upload local file
nlm source add <notebook-id> --file doc.pdf --wait          # Upload and wait until processed
nlm source add <notebook-id> --drive <doc-id>              # Add Drive doc
nlm source add <notebook-id> --drive <doc-id> --type slides  # Add Drive slides
# Types: doc, slides, sheets, pdf
# Supported file types: PDF, TXT, MD, DOCX, CSV, EPUB, MP3, M4A, WAV, AAC, OGG, OPUS, MP4, JPG, JPEG, PNG, GIF, WEBP

nlm source get <source-id>             # Get source metadata
nlm source get <source-id> --json      # JSON output
nlm source describe <source-id>        # AI summary + keywords
nlm source describe <source-id> --json # JSON output
nlm source content <source-id>         # Raw text content
nlm source content <source-id> --json  # JSON output
nlm source content <source-id> --output file.txt  # Export to file
nlm source rename <source-id> "New Title" --notebook <notebook-id>  # Rename source
nlm source delete <source-id> --confirm --json  # Structured deletion result
nlm source stale <notebook-id>         # List stale Drive sources
nlm source sync <notebook-id> --confirm  # Sync all stale
nlm source sync <notebook-id> --source-ids <ids> --confirm  # Sync specific
```

**Verb-First:**
```bash
nlm list sources <notebook-id>         # List sources
nlm add url <notebook-id> <url>        # Add URL source
nlm add url <notebook-id> <url> --wait # Add URL and wait until processed
nlm add text <notebook-id> "content" --title "Title"  # Add text source
# Note: verb-first `add text` takes the text as a positional argument, not --text
nlm add drive <notebook-id> <doc-id>   # Add Drive source
nlm get source <source-id>             # Get source metadata
nlm describe source <source-id>        # AI summary + keywords
nlm content source <source-id>         # Raw text content
nlm rename source <source-id> "New Title" --notebook <notebook-id>  # Rename source
nlm delete source <source-id> --confirm  # Delete source
nlm list stale-sources <notebook-id>   # List stale Drive sources
nlm stale sources <notebook-id>        # Alternative: list stale sources
nlm sync sources <notebook-id> --confirm  # Sync all stale sources
```

### Chat Commands

**Noun-First:**
```bash
# Interactive REPL (multi-turn conversation)
nlm chat start <notebook-id>           # Start interactive session
# In REPL:
#   /sources - List sources
#   /clear   - Reset conversation
#   /help    - Show commands
#   /exit    - Exit

# Configure chat behavior
nlm chat configure <notebook-id> --goal default
nlm chat configure <notebook-id> --goal learning_guide
nlm chat configure <notebook-id> --goal custom --prompt "Act as a tutor..."
nlm chat configure <notebook-id> --response-length longer   # longer, default, shorter

# NOTE: All CLI querying via `nlm notebook query` and MCP querying automatically persist 
# their chat history natively into the NotebookLM web UI, enabling seamless cross-device sessions.
```

**Verb-First:**
```bash
nlm configure chat <notebook-id> --goal default            # Configure chat
nlm configure chat <notebook-id> --style conversational    # Set chat style
nlm configure chat <notebook-id> --length longer           # Set response length
```

### Research Commands

**Noun-First:**
```bash
# Start research in an existing notebook or create a destination notebook
nlm research start "query" --notebook-id <id>                    # Fast web (default)
nlm research start "query" --title "New Research"                # Create destination notebook
nlm research start "query" --notebook-id <id> --mode deep        # Deep web (~5min)
nlm research start "query" --notebook-id <id> --source drive     # Fast drive
nlm research start "query" --notebook-id <id> --force            # Override pending
nlm research start "query" --notebook-id <id> --auto-import      # Auto wait (15min) and import

# Check progress
nlm research status <notebook-id>                    # Poll until done (5min max, 30s interval)
nlm research status <notebook-id> --max-wait 900     # Allow up to 15min for deep research
nlm research status <notebook-id> --max-wait 0       # Single check
nlm research status <notebook-id> --task-id <tid>    # Specific task
nlm research status <notebook-id> --full             # Full details

# Import discovered sources
nlm research import <notebook-id> <task-id>              # Import all
nlm research import <notebook-id> <task-id> --indices 0,2,5  # Import specific
nlm research import <notebook-id> <task-id> --cited-only     # Import cited sources
nlm research import <notebook-id> <task-id> --timeout 600    # Custom timeout (default: 300s)
```

**Verb-First:**
```bash
nlm status research <notebook-id>                        # Check progress
```

**Research Modes:**
- `fast`: ~30 seconds, ~10 sources (web or drive)
- `deep`: ~5 minutes, ~40-80 sources (web only)

### Generation Commands (Studio)

**All generation commands support:**
- `--confirm` or `-y`: Skip confirmation (REQUIRED for automation)
- `--source-ids <id1,id2>`: Limit to specific sources
- `--language <code>`: BCP-47 code, including regional locales such as `es-419`
- `--profile <name>`: Use specific auth profile

#### Audio (Podcast)

**Noun-First:**
```bash
nlm audio create <notebook-id> --confirm
nlm audio create <notebook-id> --confirm --json  # Return artifact ID as JSON
nlm audio create <notebook-id> --format deep_dive --length default --confirm
nlm audio create <notebook-id> --format brief --focus "key topic" --confirm
nlm audio create <notebook-id> --language es-419 --confirm
# Formats: deep_dive, brief, critique, debate
# Lengths: short, default, long
```

NotebookLM has been observed using the BCP-47 region subtag to select the
Audio Overview accent. `es`/`es-ES` produces Spain Spanish, while
`es-US`/`es-419` produces Latin-American Spanish. Prompt text does not
reliably override the accent. `NOTEBOOKLM_HL` can set the regional default.

**Verb-First:**
```bash
nlm create audio <notebook-id> --confirm
nlm create audio <notebook-id> --format deep_dive --length short --confirm
```

#### Report

**Noun-First:**
```bash
nlm report create <notebook-id> --confirm
nlm report create <notebook-id> --format "Study Guide" --confirm
nlm report create <notebook-id> --format "Create Your Own" --prompt "Summary..." --confirm
# Formats: "Briefing Doc", "Study Guide", "Blog Post", "Create Your Own"
```

**Verb-First:**
```bash
nlm create report <notebook-id> --confirm
nlm create report <notebook-id> --format "Study Guide" --confirm
```

#### Quiz

**Noun-First:**
```bash
nlm quiz create <notebook-id> --confirm
nlm quiz create <notebook-id> --count 5 --difficulty 3 --confirm
# Count: number of questions (default: 2)
# Difficulty: 1-5 (1=easy, 5=hard, default: 2)
```

**Verb-First:**
```bash
nlm create quiz <notebook-id> --confirm
nlm create quiz <notebook-id> --difficulty 3 --count 10 --confirm
```

#### Flashcards

**Noun-First:**
```bash
nlm flashcards create <notebook-id> --confirm
nlm flashcards create <notebook-id> --difficulty hard --confirm
# Difficulty: easy, medium, hard (default: medium)
```

**Verb-First:**
```bash
nlm create flashcards <notebook-id> --confirm
nlm create flashcards <notebook-id> --difficulty hard --confirm
```

#### Mind Map

**Noun-First:**
```bash
nlm mindmap create <notebook-id> --confirm
nlm mindmap create <notebook-id> --title "Topic Overview" --confirm
```

**Verb-First:**
```bash
nlm create mindmap <notebook-id> --confirm
nlm create mindmap <notebook-id> --title "Overview" --confirm
```

#### Slides

**Noun-First:**
```bash
nlm slides create <notebook-id> --confirm
nlm slides create <notebook-id> --format presenter --length short --confirm
# Formats: detailed_deck, presenter_slides (default: detailed_deck)
# Lengths: short, default
```

**Verb-First:**
```bash
nlm create slides <notebook-id> --confirm
nlm create slides <notebook-id> --length short --format detailed_deck --confirm
```

#### Revise Slides

**Noun-First:**
```bash
nlm slides revise <artifact-id> --slide '1 Make the title larger' --confirm
nlm slides revise <artifact-id> --slide '1 Fix title' --slide '3 Remove image' --confirm
# Each --slide value must be: '<slide-number> <instruction>'
# Creates a NEW slide deck with revisions applied. Original is not modified.
```

#### Infographic

**Noun-First:**
```bash
nlm infographic create <notebook-id> --confirm
nlm infographic create <notebook-id> --orientation portrait --detail detailed --confirm
# Orientations: landscape, portrait, square (default: landscape)
# Detail: concise, standard, detailed (default: standard)
```

**Verb-First:**
```bash
nlm create infographic <notebook-id> --confirm
nlm create infographic <notebook-id> --orientation portrait --detail detailed --confirm
```

#### Video

**Noun-First:**
```bash
nlm video create <notebook-id> --confirm
nlm video create <notebook-id> --format brief --style whiteboard --confirm
nlm video create <notebook-id> --format short --confirm
# Formats: explainer, brief, cinematic, short (default: explainer; short is vertical ~60s, no --style)
# Non-English Short output is best-effort; --language adds an explicit language requirement to the focus prompt.
# Styles: auto_select, classic, whiteboard, kawaii, anime, watercolor, retro_print, heritage, paper_craft
```

**Verb-First:**
```bash
nlm create video <notebook-id> --confirm
nlm create video <notebook-id> --style whiteboard --format mp4 --confirm
```

#### Data Table

**Noun-First:**
```bash
nlm data-table create <notebook-id> "Extract all dates and events" --confirm
# DESCRIPTION is REQUIRED as second argument
```

**Verb-First:**
```bash
nlm create data-table <notebook-id> "Extract all dates and events" --confirm
# DESCRIPTION is REQUIRED as second argument
```

### Studio Commands (Artifact Management)

**Noun-First:**
```bash
nlm studio status <notebook-id>                    # List all artifacts + status
nlm studio status <notebook-id> --json             # JSON output
nlm studio status <notebook-id> --full             # All details
nlm studio status <notebook-id> --artifact-id <id> # Check one artifact
nlm studio status <notebook-id> --json --mcp-compatible  # MCP-shaped, paginated JSON
nlm video list <notebook-id>                        # List video artifacts only
nlm studio delete <notebook-id> <artifact-id> --confirm  # Delete artifact
nlm slides revise <artifact-id> --slide '1 instruction' --confirm  # Revise slides
```

**Verb-First:**
```bash
nlm status artifacts <notebook-id>                 # List all artifacts + status
nlm status artifacts <notebook-id> --full          # All details
nlm delete artifact <notebook-id> <artifact-id> --confirm  # Delete artifact
```

### Download Commands (Get Artifact Files)

**Download generated artifacts to local files.** All artifacts are streamed efficiently to avoid memory issues.

**Noun-First:**
```bash
nlm download audio <notebook-id> --id <artifact-id>              # Download specific audio
nlm download audio <notebook-id> --output podcast.mp3          # Download latest audio to file
nlm download video <notebook-id>                               # Download latest video (default filename)
nlm download report <notebook-id> --output report.md           # Download report
nlm download mind-map <notebook-id>                            # Download mind map
nlm download slide-deck <notebook-id>                          # Download slides (PDF)
nlm download slide-deck <notebook-id> --format pptx            # Download slides (PPTX)
nlm download infographic <notebook-id>                         # Download infographic
nlm download data-table <notebook-id>                          # Download data table
```

**Download Workflow:**
1. Generate artifact: `nlm audio create <notebook> --confirm`
2. Check status: `nlm studio status <notebook>` (wait for "completed")
3. Get artifact ID from status output
4. Download: `nlm download audio <notebook> --id <artifact-id>`

**Supported Formats:**
- Audio: `.mp3` (Deep Dive, Brief, Critique, Debate)
- Video: `.mp4` (Explainer, Brief with various styles; Cinematic and Short with no style picker)
- Report: `.txt` or `.md` (Briefing Doc, Study Guide, Blog Post)
- Mind Map: `.txt` (node structure)
- Slide Deck: `.txt` (slide content)
- Infographic: `.png` (visual)
- Data Table: `.csv` (tabular data)

#### Interactive Artifact Downloads (Quiz, Flashcards)

**Download with format conversion:**
```bash
nlm download quiz <notebook-id> <artifact-id>                    # JSON (default)
nlm download quiz <notebook-id> <artifact-id> --format json      # Structured JSON
nlm download quiz <notebook-id> <artifact-id> --format markdown  # Markdown format
nlm download quiz <notebook-id> <artifact-id> --format html      # Interactive HTML

nlm download flashcards <notebook-id> <artifact-id>                    # JSON (default)
nlm download flashcards <notebook-id> <artifact-id> --format markdown  # Markdown format
nlm download flashcards <notebook-id> <artifact-id> --format html      # Interactive HTML
```

**Format Options:**
- `json`: Structured data (for programmatic use)
- `markdown`: Human-readable format
- `html`: Interactive browser-based quiz/flashcards with scoring

### Export Commands (to Google Docs/Sheets)

```bash
nlm export to-docs <notebook-id> <artifact-id>              # Export report to Google Docs
nlm export to-docs <notebook-id> <artifact-id> --title "My Doc"  # With custom title
nlm export to-sheets <notebook-id> <artifact-id>            # Export data table to Google Sheets
```

**Exportable Types:**
- Reports (Briefing Doc, Study Guide, Blog Post) → Google Docs
- Data Tables → Google Sheets

### Alias Commands

**Noun-First:**
```bash
nlm alias set <name> <id>       # Create/update alias (auto-detects notebook/source)
nlm alias get <name>            # Get UUID for alias
nlm alias list                  # List all aliases
nlm alias delete <name>         # Remove (no --confirm needed)
```

**Verb-First:**
```bash
nlm set alias <name> <uuid>     # Create/update alias
nlm get alias <name>            # Get UUID for alias
nlm list aliases                # List all aliases
nlm show aliases                # Alternative: show all aliases
nlm delete alias <name>         # Remove alias
```

### Share Commands

**Noun-First:**
```bash
nlm share status <notebook-id>              # View sharing settings + collaborators
nlm share status <notebook-id> --json       # JSON output
nlm share public <notebook-id>              # Enable public link access
nlm share private <notebook-id>             # Disable public link access
nlm share invite <notebook-id> <email>      # Invite as viewer (default)
nlm share invite <notebook-id> <email> --role editor  # Invite as editor
```

**Verb-First:**
```bash
nlm share status <notebook-id>              # View sharing settings (same as noun-first)
nlm share public <notebook-id>              # Enable public access
nlm share private <notebook-id>             # Disable public access
nlm share invite <notebook-id> <email> --role viewer  # Invite collaborator
```

### Batch Operations (Multi-Notebook)

Perform operations across multiple notebooks at once:

```bash
nlm batch query "What are the key takeaways?" --notebooks "id1,id2"
nlm batch query "Summarize" --tags "ai,research"          # Select by tag
nlm batch query "Summarize" --all                         # ALL notebooks

nlm batch add-source "https://..." --notebooks "id1,id2"
nlm batch add-source "https://..." --tags "research"

nlm batch create "Project A, Project B, Project C"        # Create multiple
nlm batch delete --notebooks "id1,id2" --confirm
nlm batch studio audio --tags "research"
```

### Cross-Notebook Query

Query multiple notebooks and get aggregated answers with per-notebook citations:

```bash
nlm cross query "What are the common themes?" --notebooks "id1,id2"
nlm cross query "Compare approaches" --tags "ai,research"
nlm cross query "Summarize everything" --all
```

### Pipelines (Multi-Step Workflows)

Run predefined multi-step workflows on a notebook:

```bash
nlm pipeline list                                         # List available pipelines
nlm pipeline run ingest-and-podcast --notebook <id> --input-url "https://..."
nlm pipeline run research-and-report --notebook <id> --input-url "https://..."
nlm pipeline run multi-format --notebook <id>             # Audio + report + flashcards
```

**Built-in pipelines:**
- `ingest-and-podcast`: Add source → generate podcast
- `research-and-report`: Research → import → generate report
- `multi-format`: Generate audio + report + flashcards

Custom pipelines: create YAML files in `~/.notebooklm-mcp-cli/pipelines/`

### Tag & Smart Select

Tag notebooks for organization and discovery:

```bash
nlm tag add <notebook-id> --tags "ai,research,llm"
nlm tag add <notebook-id> --tags "product" --title "Product Notes"
nlm tag remove <notebook-id> --tags "ai"
nlm tag list                                              # List all tagged notebooks
nlm tag select "ai research"                              # Find relevant notebooks
```

Tags are stored locally and used by `nlm tag select` and batch operations (`--tags` flag) to find relevant notebooks.

### Skill Commands (Install AI Assistant Skills)

Install the NotebookLM skill for various AI coding assistants:

```bash
nlm skill list                              # Show installation status for all tools
nlm skill install <tool>                    # Install at user level (default)
nlm skill install <tool> --level project    # Install at project level
nlm skill update                            # Update all outdated skills
nlm skill update <tool>                     # Update a specific tool's skill
nlm skill uninstall <tool>                  # Remove installed skill
nlm skill show                              # Display skill content
```

**Supported Tools:**
- `claude-code` - Claude Code CLI and Desktop (`~/.claude/skills/nlm-skill/`)
- `cursor` - Cursor AI editor (`~/.cursor/skills/nlm-skill/`)
- `opencode` - OpenCode AI assistant (`~/.config/opencode/skills/nlm-skill/`)
- `agents` - Generic agent skill for Gemini CLI, Codex, and others (`~/.agents/skills/nlm-skill/`)
- `antigravity` - Antigravity agent framework (`~/.gemini/antigravity/skills/nlm-skill/`)
- `cline` - Cline CLI terminal agent (`~/.cline/skills/nlm-skill/`)
- `openclaw` - OpenClaw AI agent framework (`~/.openclaw/workspace/skills/nlm-skill/`)
- `alef-agent` - Alef Agent AI agent framework (`~/.alef-agent/workspace/skills/nlm-skill/`)
- `hermes` - Hermes Agent by NousResearch (`~/.hermes/skills/nlm-skill/`)
- `other` - Export all formats to `./nlm-skill-export/` for manual installation

User-level installs require the target tool to be detected and never create a
missing tool directory. Project-level installs are explicit and remain
available for project-local skills.

**Installation Levels:**
- `user` (default): Installs to user config directory (e.g., `~/.claude/skills/nlm-skill/`)
- `project`: Installs to current project directory (e.g., `.claude/skills/nlm-skill/`)

**Examples:**
```bash
# Install for Claude Code at user level
nlm skill install claude-code

# Install for Codex/Gemini CLI at project level
nlm skill install agents --level project

# Check what's installed
nlm skill list

# Export all formats for manual installation
nlm skill install other --level project
# Creates ./nlm-skill-export/nlm-skill/ with SKILL.md and references

# View skill content
nlm skill show | head -50
```

**What Gets Installed:**
- `SKILL.md` - Main skill file with Gemini Notebook CLI/MCP documentation
- `references/` - Additional documentation, including command, troubleshooting, workflow, Studio prompting, and remote MCP guides

For Gemini CLI (v0.33.1+) and Codex, it installs to `~/.agents/skills/nlm-skill/SKILL.md` — the cross-tool compatible path.

**Note:** If the parent directory doesn't exist (e.g., `~/.claude/` for Claude Code), the installer will prompt you to either create it, switch to project-level installation, or cancel.

**Verb-First Alternatives:**
```bash
nlm install skill claude-code              # Same as: nlm skill install claude-code
nlm install skill cursor --level project  # Install for Cursor at project level
nlm update skill                           # Same as: nlm skill update
nlm update skill claude-code               # Same as: nlm skill update claude-code
nlm uninstall skill agents             # Same as: nlm skill uninstall agents
nlm list skills                            # Same as: nlm skill list
nlm show skill                             # Same as: nlm skill show
```

### Config Commands

**Noun-First:**
```bash
nlm config show                 # Display current config (TOML)
nlm config show --json          # Display as JSON
nlm config get <key>            # Get specific setting
nlm config set <key> <value>    # Update setting
```

**Verb-First:**
```bash
nlm show config                 # Display current config
nlm show config --json          # Display as JSON
nlm get config <key>            # Get specific setting
nlm set config <key> <value>    # Update setting
```

**Available config keys:**
- `auth.browser` — Preferred browser for login: auto (default), chrome, arc, brave, edge, chromium, vivaldi, opera. Falls back to auto if preferred browser is not found.
- `auth.default_profile` — Default profile name (default: "default")
- `output.format` — Default output format: table, json (default: "table")
- `output.color` — Enable colored output (default: true)
- `output.short_ids` — Show abbreviated IDs (default: true)

### Diagnostics & Setup

**Doctor** - Diagnose your Gemini Notebook MCP installation:
```bash
nlm doctor                      # Run all diagnostic checks
nlm doctor --verbose            # Show additional details
```

Checks: installation, authentication, browser profile, AI tool configs. Shows suggestions for any issues found.

**Setup** - Configure MCP server for AI tools:
```bash
nlm setup list                          # Show all clients and their MCP status
nlm setup add claude-code               # Add to Claude Code (via claude mcp add)
nlm setup add claude-desktop            # Add to Claude Desktop config
nlm setup add claude-desktop --profile 3p  # Select Relay AI / 3P explicitly
nlm setup remove claude-desktop --profile regular  # Remove from regular explicitly
nlm setup add gemini                    # Add to Gemini CLI config
nlm setup add cursor                    # Add to Cursor config
nlm setup add windsurf                  # Add to Windsurf config
nlm setup add cline                     # Add to Cline CLI config
nlm setup add antigravity               # Add to Antigravity config
nlm setup add codex                     # Add to Codex CLI (via codex mcp add)
nlm setup add json                      # Generate JSON config for any tool (interactive)
nlm setup add all                       # Scan system & configure all detected tools
nlm setup remove <client>               # Remove MCP from client
nlm setup remove all                    # Remove MCP from ALL configured tools (with confirmation)
```

The configured MCP server name is `gemini-notebook-mcp`; the executable remains
`notebooklm-mcp` for compatibility with existing installations. Legacy server
names are recognized for migration and removal.

Claude Desktop setup only targets detected regular or Relay AI/3P profiles and
never creates a missing profile. Fully quit the selected profile before adding
or removing configuration; the CLI refuses to write while its executable is
running. User-level skill installation likewise requires the target tool to be
detected; use `--level project` for an intentional project-local install.

**Supported Clients:** claude-code, claude-desktop, gemini, cursor, windsurf, cline, antigravity, codex

**For other tools:** `nlm setup add json` launches an interactive wizard — choose uvx or regular mode, full path or command name, and existing or new config. The JSON is printed with syntax highlighting and can be copied to clipboard (macOS).

---

## Output Formats

Many commands support `--json` for structured output:

| Flag | Description | Available On |
|------|-------------|------|
| (none) | Rich table (human-readable) | All |
| `--json` | JSON output (for parsing/piping) | list, get, describe, query, content, status, source add/delete, notebook delete, Studio create |
| `--quiet` | IDs only (for piping) | list |
| `--title` | "ID: Title" format | notebook list |
| `--url` | "ID: URL" format | source list |
| `--full` | All columns/details | list, status |

**Auto-detection:** When stdout is not a TTY (e.g., piping to `jq`), JSON output is used automatically.

---

## Error Handling

| Error Message | Cause | Solution |
|--------------|-------|----------|
| "Cookies have expired" | Session expired | Run `nlm login` |
| "authentication may have expired" | Session expired | Run `nlm login` |
| "Notebook not found" | Invalid ID | Run `nlm notebook list` |
| "Source not found" | Invalid ID | Run `nlm source list <notebook-id>` |
| "Rate limit exceeded" | Too many API calls | Briefly auto-retried; Studio limits may require waiting 1-2 minutes |
| Server 503/502/500 | Google API flaky | Auto-retried (up to 3x with backoff) |
| "Research already in progress" | Pending research | Use `--force` or import first |

---

## Complete Task Sequences

### Sequence 1: Research → Podcast → Download (Noun-First)

```bash
# 1. Authenticate
nlm login

# 2. Create notebook
nlm notebook create "AI Research 2026"
# ID: abc123...

# 3. Set alias for convenience
nlm alias set ai abc123...

# 4. Start deep research
nlm research start "agentic AI trends 2026" --notebook-id ai --mode deep
# Task ID: task456...

# 5. Wait for completion
nlm research status ai --max-wait 900

# 6. Import all sources
nlm research import ai task456...

# 7. Generate podcast
nlm audio create ai --format deep_dive --confirm

# 8. Check status until completed
nlm studio status ai
# Note artifact ID: audio789...

# 9. Download when ready
nlm download audio ai audio789... --output podcast.mp3
```

### Sequence 1 Alternative: Research → Podcast → Download (Verb-First)

```bash
# 1. Authenticate
nlm login

# 2. Create notebook
nlm create notebook "AI Research 2026"
# ID: abc123...

# 3. Set alias
nlm set alias ai abc123...

# 4. Start research
nlm research-verb start "agentic AI trends 2026" --notebook-id ai --mode deep

# 5. Check status
nlm status research ai --max-wait 300

# 6. Import sources
nlm research-verb import ai task456...

# 7. Create podcast
nlm create audio ai --confirm

# 8. Check status
nlm status artifacts ai

# 9. Download
nlm download-verb audio ai audio789... --output podcast.mp3
```

### Sequence 2: Quick Source Ingestion

**Noun-First:**
```bash
nlm source add <notebook-id> --url "https://example1.com"
nlm source add <notebook-id> --url "https://example2.com"
nlm source add <notebook-id> --text "My notes here" --title "Notes"
nlm source list <notebook-id>
```

**Verb-First:**
```bash
nlm add url <notebook-id> "https://example1.com"
nlm add url <notebook-id> "https://example2.com"
nlm add text <notebook-id> "My notes here" --title "Notes"
nlm list sources <notebook-id>
```

### Sequence 3: Generate Study Materials

**Noun-First:**
```bash
nlm quiz create <notebook-id> --count 10 --difficulty 3 --confirm
nlm flashcards create <notebook-id> --difficulty hard --confirm
nlm report create <notebook-id> --format "Study Guide" --confirm
```

**Verb-First:**
```bash
nlm create quiz <notebook-id> --difficulty medium --quantity 10 --confirm
nlm create flashcards <notebook-id> --difficulty hard --confirm
nlm create report <notebook-id> --type study-guide --confirm
```

### Sequence 4: Complete Content Generation Pipeline

```bash
# Create all content types at once
nlm create audio <notebook-id> --confirm
nlm create video <notebook-id> --confirm
nlm create report <notebook-id> --confirm
nlm create quiz <notebook-id> --confirm
nlm create flashcards <notebook-id> --confirm
nlm create mindmap <notebook-id> --confirm
nlm create slides <notebook-id> --confirm
nlm create infographic <notebook-id> --confirm

# Check all statuses
nlm status artifacts <notebook-id> --full

# Download all when ready (replace <artifact-ids> with actual IDs)
nlm download audio <notebook-id> --id <audio-id>
nlm download video <notebook-id> --id <video-id>
nlm download report <notebook-id> --id <report-id>
nlm download mind-map <notebook-id> --id <mindmap-id>
nlm download slide-deck <notebook-id> --id <slides-id>             # PDF (default)
nlm download slide-deck <notebook-id> --id <slides-id> --format pptx  # PPTX
nlm download infographic <notebook-id> --id <infographic-id>
```

---

## Tips for AI Assistants

1. **Always run `nlm login` first** if any auth error occurs
2. **Use `--confirm` for all generation/delete commands** to avoid blocking prompts
3. **Capture IDs from create outputs** - you'll need them for subsequent operations
4. **Use aliases** for frequently-used notebooks to simplify commands
5. **Poll for long operations** - audio/video takes 1-5 minutes; use `nlm studio status` or `nlm status artifacts`
6. **Research needs a destination** - use `--notebook-id` for an existing notebook or `--title` to create one
7. **Re-authenticate only for stale/missing credentials** - `unverified` means the probe was inconclusive
8. **Use `--max-wait 0`** for single status poll instead of blocking
9. **⚠️ ALWAYS ask user before delete** - Before running ANY delete command, ask the user for explicit confirmation. Deletions are IRREVERSIBLE. Show what will be deleted and warn about permanent data loss.
10. **Check aliases before creating** - Run `nlm alias list` or `nlm list aliases` before creating a new alias to avoid conflicts with existing names.
11. **DO NOT launch REPL** - Never use `nlm chat start` - it opens an interactive REPL that AI tools cannot control. Use `nlm notebook query` or `nlm query notebook` for one-shot Q&A instead.
12. **Choose output format wisely** - Default output (no flags) is compact and token-efficient—use it for status checks. Use `--quiet` to capture IDs for piping. Only use `--json` when you need to parse specific fields programmatically.
13. **Verb-first vs Noun-first** - Both command styles work identically. Use whichever is more natural for the context. Noun-first groups by resource (notebook, source), verb-first groups by action (create, list, delete).
14. **Download workflow** - Always wait for artifact completion before downloading. Check status with `nlm studio status <notebook>`, get the artifact ID, then download with `nlm download <type> <notebook> <artifact-id>`.
15. **Artifact generation takes time** - Audio/video: 1-5 minutes. Reports/quizzes: 30-60 seconds. Always poll status before attempting download.
16. **Download output files** - If no `--output` specified, files are saved with default names (e.g., `audio_<id>.mp3`, `video_<id>.mp4`, `report_<id>.txt`). Use `--output` to specify custom filenames.
17. **Streaming downloads** - All downloads use efficient streaming to handle large files without memory issues. This is automatic.
18. **Drive source sync** - Use `nlm source stale <notebook>` or `nlm list stale-sources <notebook>` to check which Drive sources need syncing before running sync commands.
19. **Use --wait for blocking source adds** - When adding sources before querying, use `nlm source add ... --wait` to block until processing completes. This ensures the source is ready for queries.
20. **Export to Google Docs/Sheets** - Reports can be exported to Google Docs, Data Tables to Google Sheets. Use `nlm export to-docs/to-sheets <notebook> <artifact-id>`.
21. **Batch with tags** - Tag notebooks first (`nlm tag add ... --tags "topic"`), then use `--tags` flag with batch commands for targeted multi-notebook operations.
22. **Pipelines for automation** - Use `nlm pipeline list` to see available workflows, then `nlm pipeline run` for automated multi-step operations (ingest → generate).
"""


def print_ai_docs() -> None:
    """Print the AI-friendly documentation."""
    print(AI_DOCS.format(version=__version__))
