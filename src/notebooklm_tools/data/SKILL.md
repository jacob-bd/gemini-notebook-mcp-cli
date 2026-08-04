---
name: nlm-skill
version: "0.9.6"
description: "Expert guide for the Gemini Notebook (formerly Google NotebookLM) CLI (`nlm`) and MCP server - interfaces for Gemini Notebook. Use this skill when users want to interact with Gemini Notebook programmatically, including: creating/managing notebooks, adding sources (URLs, YouTube, text, Google Drive), generating content (podcasts, reports, quizzes, flashcards, mind maps, slides, infographics, videos, data tables), conducting research, chatting with sources, or automating Gemini Notebook workflows. Triggers on mentions of \"nlm\", \"notebooklm\", \"Gemini Notebook\", \"podcast generation\", \"audio overview\", \"refactor document\", \"critique draft\", or any Gemini Notebook-related automation task."
---

# Gemini Notebook CLI & MCP Expert

This skill provides comprehensive guidance for using Gemini Notebook via both the `nlm` CLI and MCP tools.

## Tool Detection (CRITICAL - Read First!)

**ALWAYS check which tools are available before proceeding:**

1. **Check for MCP tools**: Look for tools starting with `mcp__gemini-notebook-mcp__*` or `mcp_gemini_notebook_mcp_*`
2. **If BOTH MCP tools AND CLI are available**: **ASK the user** which they prefer to use before proceeding
3. **If only MCP tools are available**: Use them directly (refer to tool docstrings for parameters)
4. **If only CLI is available**: Use `nlm` CLI commands via Bash

**Decision Logic:**
```
has_mcp_tools = check_available_tools()  # Look for mcp__gemini-notebook-mcp__* or mcp_gemini_notebook_mcp_*
has_cli = check_bash_available()  # Can run nlm commands

if has_mcp_tools and has_cli:
    # ASK USER: "I can use either MCP tools or the nlm CLI. Which do you prefer?"
    user_preference = ask_user()
else if has_mcp_tools:
    # Use MCP tools directly
    mcp__gemini-notebook-mcp__notebook_list()
else:
    # Use CLI via Bash
    bash("nlm notebook list")
```

This skill documents BOTH approaches. Choose the appropriate one based on tool availability and **user preference**.

## Quick Reference

**Run `nlm --ai` to get comprehensive AI-optimized documentation** - this provides a complete view of all CLI capabilities.

```bash
nlm --help              # List all commands
nlm <command> --help    # Help for specific command
nlm --ai                # Full AI-optimized documentation (RECOMMENDED)
nlm --version           # Check installed version
```

## Critical Rules (Read First!)

1. **Authenticate when needed**: Run `nlm login` for first-time setup or confirmed stale/missing credentials. Saved cookies often remain usable for weeks.
2. **Do not confuse network failures with expired auth**: `auth_status="unverified"` means the probe was inconclusive. Check connectivity or try an API call before asking the user to log in again.
3. **Auto-Authentication Recovery**: The CLI includes automatic 3-layer auth recovery (CSRF refresh -> Token reload -> Headless Auth) and 3x server error retries. Most errors are handled automatically. You only need to manually run `nlm login` if all recovery layers fail.
4. **⚠️ ALWAYS ASK USER BEFORE DELETE**: Before executing ANY delete command, ask the user for explicit confirmation. Deletions are **irreversible**. Show what will be deleted and warn about permanent data loss.
5. **Always obtain approval before generation or deletion**: Direct
   `studio_create` and delete operations enforce `--confirm` / `confirm=True`.
   The current MCP batch Studio path does not enforce its confirm parameter,
   so the agent must preserve the approval gate.
6. **Research needs a destination**: Pass `--notebook-id <id>` for an existing notebook or `--title <title>` to create one.
7. **Capture IDs from output**: Create/start commands return IDs needed for subsequent operations
8. **Use aliases**: Simplify long UUIDs with `nlm alias set <name> <uuid>`
9. **Check aliases before creating**: Run `nlm alias list` before creating a new alias to avoid conflicts with existing names.
10. **DO NOT launch REPL**: Never use `nlm chat start` - it opens an interactive REPL that AI tools cannot control. Use `nlm notebook query` for one-shot Q&A instead.
11. **Choose output format wisely**: Default output (no flags) is compact and token-efficient—use it for status checks. Use `--quiet` to capture IDs for piping. Only use `--json` when you need to parse specific fields programmatically.
12. **Use `--help` when unsure**: Run `nlm <command> --help` to see available options and flags for any command.
13. **Studio: fast track by default**: Infer format/style/prompt silently—one compact line, then `studio_create(confirm=True)`. No intake questionnaires. Fast track reduces clarifying questions, not the confirm gate. **Cinematic video is always guided** (quota-limited). Full preview only when vague, high-stakes, cinematic, or user asks. See **[references/studio-prompting-guide.md](references/studio-prompting-guide.md)**.

**Current MCP surface:** 43 tools. Consolidated action tools include `note`,
`label`, `studio_status`, `batch`, `pipeline`, and `tag`. Consolidated type
tools include `source_add`, `studio_create`, and `download_artifact`.

## Workflow Decision Tree

Use this to determine the right sequence of commands:

```
User wants to...
│
├─► Work with NotebookLM for the first time
│   └─► nlm login → nlm notebook create "Title"
│
├─► Add content to a notebook
│   ├─► From a URL/webpage → nlm source add <nb-id> --url "https://..."
│   ├─► From YouTube → nlm source add <nb-id> --url "https://youtube.com/..."
│   ├─► From pasted text → nlm source add <nb-id> --text "content" --title "Title"
│   ├─► From Google Drive → nlm source add <nb-id> --drive <doc-id> --type doc
│   └─► Discover new sources → nlm research start "query" --notebook-id <nb-id>
│
├─► Generate content from sources (→ Studio Prompting for optimal focus_prompt)
│   ├─► Podcast/Audio → nlm audio create <nb-id> --confirm
│   ├─► Written summary → nlm report create <nb-id> --confirm
│   ├─► Study materials → nlm quiz/flashcards create <nb-id> --confirm
│   ├─► Visual content → nlm mindmap/slides/infographic create <nb-id> --confirm
│   ├─► Video → nlm video create <nb-id> --confirm
│   └─► Extract data → nlm data-table create <nb-id> "description" --confirm
│
├─► Refactor, critique, or improve a draft document
│   └─► See Workflow 15 in references/workflows.md
│
├─► Ask questions about sources
│   └─► nlm notebook query <nb-id> "question"
│       (Use --conversation-id for follow-ups)
│       ⚠️ Do NOT use `nlm chat start` - it's a REPL for humans only
│
├─► Review or export a past chat
│   └─► nlm chats list <nb-id> → nlm chats get/export <nb-id> [conversation-id]
│
├─► Check generation status
│   └─► nlm studio status <nb-id>
│
└─► Manage/cleanup
    ├─► List notebooks → nlm notebook list
    ├─► List sources → nlm source list <nb-id>
    ├─► Delete source → nlm source delete <source-id> --confirm
    └─► Delete notebook → nlm notebook delete <nb-id> --confirm
```

## Command Categories

### 1. Authentication

#### MCP Authentication

If using MCP tools and encountering authentication errors:

```bash
# Run the CLI authentication (works for both CLI and MCP)
nlm login

# Then reload tokens in MCP
mcp__gemini-notebook-mcp__refresh_auth()
# Returns status: "success" (valid), "expired" (tokens dead, run `nlm login`),
# or "error". `nlm login` is the only recovery path for "expired".
```

Or manually save cookies via MCP (fallback):
```python
# Extract cookies from Chrome DevTools and save
mcp__gemini-notebook-mcp__save_auth_tokens(cookies="<cookie_header>")
```
```

#### CLI Authentication

```bash
nlm login                           # Launch browser, extract cookies (primary method)
nlm login --check                   # Validate current session
nlm login --profile work            # Use named profile for multiple accounts
nlm login --provider openclaw --cdp-url http://127.0.0.1:18800  # External CDP provider
nlm login switch <profile>          # Switch the default profile
nlm login profile list              # List all profiles with email addresses
nlm login profile delete <name>     # Delete a profile
nlm login profile rename <old> <new> # Rename a profile
```

**Multi-Profile Support**: Each profile gets its own isolated browser session (supports Chrome, Arc, Brave, Edge, Chromium, and more), so you can be logged into multiple Google accounts simultaneously.

**Auth status:** `configured` means usable; `stale` means run `nlm login`;
`not_configured` means first-time setup is required; `unverified` means the
probe was inconclusive; `error` means the health check itself failed.

**Switching MCP Accounts**: The MCP server always uses the active default profile. If you need to switch which Google account the MCP server is communicating with, you MUST use the CLI: run `nlm login switch <name>`. Your next MCP tool call will instantly use the new account.

**Note**: Both MCP and CLI share the same authentication backend, so authenticating with one works for both.

### 2. Notebook Management

#### MCP Tools

Use `notebook_list`, `notebook_create`, `notebook_get`, `notebook_describe`,
`notebook_query`, `notebook_rename`, and `notebook_delete`. The
get/describe/query/rename/delete tools require `notebook_id`; list and create
do not. Delete requires `confirm=True`.

For large notebooks or long-running questions, call `notebook_query_start`,
then poll `notebook_query_status(query_id)` until completed or errored.

#### CLI Commands
```bash
nlm notebook list                      # List all notebooks
nlm notebook list --json               # JSON output for parsing
nlm notebook list --quiet              # IDs only (for scripting)
nlm notebook create "Title"            # Create notebook, returns ID
nlm notebook create "Title" --json     # Stable machine-readable ID capture
nlm notebook get <id>                  # Get notebook details
nlm notebook describe <id>             # AI-generated summary + suggested topics
nlm notebook query <id> "question"     # One-shot Q&A with sources
nlm notebook rename <id> "New Title"   # Rename notebook
nlm notebook delete <id> --confirm     # PERMANENT deletion
```

### 3. Source Management

#### MCP Tools

Use `source_add` with these `source_type` values:
- `url` - Web page or YouTube URL (`url` param)
- `text` - Pasted content (`text` + `title` params)
- `file` - Server-local file upload (`file_path` param). The path must exist on
  the machine running the MCP server, not merely on the client host. Failures
  preserve the concrete reason and include a host-path hint. Supported:
  `PDF, TXT, MD, DOCX, CSV, EPUB, MP3, M4A, WAV, AAC, OGG, OPUS, MP4, JPG,
  JPEG, PNG, GIF, WEBP`.
- `drive` - Google Drive doc (`document_id` + `doc_type` params)

Other tools: `source_list_drive` (`skip_freshness=True` reports
`stale/is_stale=null`, meaning unknown, not fresh), `source_describe`,
`source_get_content`, `source_rename`, `source_sync_drive`, and
`source_delete`. Bulk URL add uses `source_add(source_type="url", urls=[...])`;
bulk delete uses `source_delete(source_ids=[...], confirm=True)`. MCP Drive
sync requires explicit source UUIDs: list first, select stale IDs, then call
`source_sync_drive(source_ids=[...], confirm=True)`.

#### Source Labels

Use `label` with actions `auto`, `list`, `reorganize`, `create`, `rename`,
`set_emoji`, `move_source`, and `delete`. Full reorganization and deletion
require `confirm=True`; `reorganize(unlabeled_only=True)` does not.

#### CLI Commands
```bash
# Adding sources
nlm source add <nb-id> --url "https://..."           # Web page
nlm source add <nb-id> --url "https://youtube.com/..." # YouTube video
nlm source add <nb-id> --text "content" --title "X"  # Pasted text
nlm source add <nb-id> --drive <doc-id>              # Defaults to Drive doc
nlm source add <nb-id> --drive <doc-id> --type slides # Explicit type
nlm source add <nb-id> --file "/path/to/diagram.png" --wait # Local file upload (images, PDFs, documents, audio, video)

# Listing and viewing
nlm source list <nb-id>                # Table of sources
nlm source list <nb-id> --drive        # Show Drive sources with freshness
nlm source list <nb-id> --drive -S     # Skip freshness checks (faster)
nlm source get <source-id>             # Source metadata
nlm source describe <source-id>        # AI summary + keywords
nlm source content <source-id>         # Raw text content
nlm source content <source-id> -o file.txt  # Export to file

# Drive sync (for stale sources)
nlm source stale <nb-id>               # List outdated Drive sources
nlm source sync <nb-id> --confirm      # Sync all stale sources
nlm source sync <nb-id> --source-ids <ids> --confirm  # Sync specific

# Rename
nlm source rename <source-id> "New Title" --notebook <nb-id>
nlm rename source <source-id> "New Title" --notebook <nb-id>  # verb-first

# Deletion
nlm source delete <source-id> --confirm
```

**Drive types**: `doc`, `slides`, `sheets`, `pdf`

### 4. Research (Source Discovery)

Research finds NEW sources from the web or Google Drive.

#### MCP Tools

Use `research_start` with:
- `source`: `web` or `drive`
- `mode`: `fast` (~30s) or `deep` (~5min, web only)

Preferred workflow: `research_start` → `research_status(auto_import=True)`.
For manual source selection, poll without auto-import and then call
`research_import`. `research_start` accepts either `notebook_id` or `title`
to create a destination notebook. MCP status defaults to a 900-second wait
with 30-second polling.

#### CLI Commands
```bash
# Start research in an existing notebook or create one with --title
nlm research start "query" --notebook-id <id>              # Fast web (~30s)
nlm research start "query" --title "New Research"           # Create destination notebook
nlm research start "query" --notebook-id <id> --mode deep  # Deep web (~5min)
nlm research start "query" --notebook-id <id> --source drive  # Drive search
nlm research start "query" --notebook-id <id> --mode deep --auto-import

# Check progress
nlm research status <nb-id>                   # Poll until done
nlm research status <nb-id> --max-wait 0      # Single check, no waiting
nlm research status <nb-id> --task-id <tid>   # Check specific task
nlm research status <nb-id> --full            # Full details

# Import discovered sources
nlm research import <nb-id> <task-id>            # Import all
nlm research import <nb-id> <task-id> --indices 0,2,5  # Import specific
nlm research import <nb-id> <task-id> --cited-only      # Import cited sources
nlm research import <nb-id> <task-id> --timeout 600    # Custom timeout (default: 300s)
```

**Modes**: `fast` (~30s, ~10 sources) | `deep` (~5min, ~40+ sources, web only)

### 5. Content Generation (Studio)

#### MCP Tools (Unified Creation)

Use `studio_create` with `artifact_type` and type-specific options. All require `confirm=True`. `studio_create` runs a pre-flight auth check before firing the request, so stale auth fails immediately with an `nlm login` hint instead of returning a fake success that collapses seconds later.

| artifact_type | Key Options |
|--------------|-------------|
| `audio` | `audio_format`: deep_dive/brief/critique/debate, `audio_length`: short/default/long |
| `video` | `video_format`: explainer/brief/cinematic/short, `visual_style`: auto_select/classic/whiteboard/kawaii/anime/watercolor/retro_print/heritage/paper_craft (not for cinematic/short), `video_style_prompt` |
| `report` | `report_format`: Briefing Doc/Study Guide/Blog Post/Create Your Own, `custom_prompt` |
| `quiz` | `question_count`, `difficulty`: easy/medium/hard |
| `flashcards` | `difficulty`: easy/medium/hard |
| `mind_map` | `title` |
| `slide_deck` | `slide_format`: detailed_deck/presenter_slides, `slide_length`: short/default |
| `infographic` | `orientation`: landscape/portrait/square, `detail_level`: concise/standard/detailed, `infographic_style`: auto_select/sketch_note/professional/bento_grid/editorial/instructional/bricks/clay/anime/kawaii/scientific |
| `data_table` | `description` (REQUIRED) |

**Common options**: `source_ids`, `language` (BCP-47 code, including regional
locales such as `es-419`), `focus_prompt`

**Audio accent:** NotebookLM has been observed using the `language` region
subtag, not the prompt, to choose the Audio Overview accent. For example,
`es`/`es-ES` produces Spain Spanish, while `es-US`/`es-419` produces
Latin-American Spanish. `NOTEBOOKLM_HL` can set the same regional locale as
the default. Treat this as observed upstream behavior, not a guaranteed API
contract.

**Revise Slides:** Use `studio_revise` to revise individual slides in an existing slide deck.
- Requires `artifact_id` (from `studio_status`) and `slide_instructions`
- Creates a NEW artifact — the original is not modified
- Slide numbers are 1-based (slide 1 = first slide)
- Poll `studio_status` after calling to check when the new deck is ready

#### CLI Commands

All generation commands share `--confirm`, `--source-ids`, and `--profile`.
`--language` is available for audio, report, slides, infographic, video, and
data-table:
- `--confirm` or `-y`: **REQUIRED** to execute
- `--source-ids <id1,id2>`: Limit to specific sources
- `--language <code>`: BCP-47 code (`en`, `es-ES`, `es-US`, `es-419`, `fr`, etc.)

```bash
# Audio (Podcast)
nlm audio create <id> --confirm
nlm audio create <id> --format deep_dive --length default --confirm
nlm audio create <id> --format brief --focus "key topic" --confirm
# Formats: deep_dive, brief, critique, debate
# Lengths: short, default, long

# Report
nlm report create <id> --confirm
nlm report create <id> --format "Study Guide" --confirm
nlm report create <id> --format "Create Your Own" --prompt "Custom..." --confirm
# Formats: "Briefing Doc", "Study Guide", "Blog Post", "Create Your Own"

# Quiz
nlm quiz create <id> --confirm
nlm quiz create <id> --count 5 --difficulty 3 --confirm
nlm quiz create <id> --count 10 --difficulty 3 --focus "Focus on key concepts" --confirm
# Count: number of questions (default: 2)
# Difficulty: 1-5 (1=easy, 5=hard)
# Focus: optional text to guide quiz generation

# Flashcards
nlm flashcards create <id> --confirm
nlm flashcards create <id> --difficulty hard --confirm
nlm flashcards create <id> --difficulty medium --focus "Focus on definitions" --confirm
# Difficulty: easy, medium, hard
# Focus: optional text to guide flashcard generation

# Mind Map
nlm mindmap create <id> --confirm
nlm mindmap create <id> --title "Topic Overview" --confirm
nlm studio status <id>  # Includes existing mind maps

# Slides
nlm slides create <id> --confirm
nlm slides create <id> --format presenter_slides --length short --confirm
# Formats: detailed_deck, presenter_slides | Lengths: short, default
nlm slides revise <artifact-id> --slide '1 Make the title larger' --confirm
# Each --slide value must be: '<slide-number> <instruction>'
# Creates a NEW deck with revisions. Original unchanged.

# Infographic
nlm infographic create <id> --confirm
nlm infographic create <id> --orientation portrait --detail detailed --style professional --confirm
# Orientations: landscape, portrait, square
# Detail: concise, standard, detailed
# Styles: auto_select, sketch_note, professional, bento_grid, editorial, instructional, bricks, clay, anime, kawaii, scientific

# Video
nlm video create <id> --confirm
nlm video create <id> --format brief --style whiteboard --confirm
nlm video create <id> --format cinematic --focus "Full creative brief..." --confirm
nlm video create <id> --format short --focus "Key topic" --confirm
# Formats: explainer, brief, cinematic (English, 18+, quota-limited), short (English, 18+, vertical ~60s, rolling out)
# Styles: auto_select, classic, whiteboard, kawaii, anime, watercolor, retro_print, heritage, paper_craft (not for cinematic/short)
# Cinematic/short: put full brief in --focus; --style-prompt merges into --focus

# Data Table
nlm data-table create <id> "Extract all dates and events" --confirm
# DESCRIPTION is required as second argument
```

#### Studio Prompting (Read Before Generating)

**Full guides:** [studio-prompting-guide.md](references/studio-prompting-guide.md) | [studio-prompt-examples.md](references/studio-prompt-examples.md)

**Fast track (default):** Silently infer (user message → notebook title → `notebook_describe` if needed) → **minimal** 1–3 sentence prompt with grounding anchor → one-line notice → `studio_create(confirm=True)`. Never run multi-question intake.

**Guided preview (exception):** Vague request, **any cinematic video**, high-stakes deliverable, empty notebook, or user asks → show settings + **full** prompt → one optional refine → generate.

**Grounding anchor (every prompt):** `Use only uploaded sources. Do not invent statistics, quotes, or examples not in the sources.`

**Iterate only on failure or user dissatisfaction** — do not proactively offer regen on success. Slides: use `studio_revise` for targeted fixes.

**Prompt parameters by artifact:**

| Artifact | Prompt field | CLI flag |
|----------|--------------|----------|
| audio, video, infographic, slide_deck, quiz, flashcards | `focus_prompt` | `--focus` |
| report (Create Your Own) | `custom_prompt` | `--prompt` |
| data_table | `description` | positional arg (required) |

**Quick format picks:**

| User intent | Default |
|-------------|---------|
| Podcast / learn | audio: `deep_dive`, `default` |
| Quick audio recap | audio: `brief`, `short` |
| Teach / explain | video: `explainer` |
| Exec video summary | video: `brief` |
| Narrative / launch video | video: `cinematic` + full brief in focus |
| Shareable slides | slide_deck: `detailed_deck` |
| Live presentation | slide_deck: `presenter_slides` |
| LinkedIn visual | infographic: `square`, `concise`, `bento_grid` |
| Custom report | report: `Create Your Own` + `custom_prompt` |
| Structured extraction | data_table: explicit column schema in `description` |

**After generation:** Poll `studio_status` by `artifact_id`. Revise slides with `studio_revise`. Request `include_details=True` only when reusing a successful prompt from `custom_instructions`.

### 6. Studio (Artifact Management)

#### MCP Tools

Use `studio_status` to check progress, rename with `action="rename"`, or inspect
supported types with `action="list_types"`. Failed artifacts include
`error_reason`. Detailed mode also includes `source_ids`; an empty list means
the upstream payload did not expose provenance, not necessarily that no
sources were used. Use `download_artifact` with `artifact_type` and
`output_path`, `download_all_artifacts` to fetch every completed artifact of a
notebook (or every notebook with `all_notebooks=True`) into per-notebook
folders, `export_artifact` with `export_type` (`docs`/`sheets`), and
`studio_delete` with `confirm=True`.

#### CLI Commands
```bash
# Check status
nlm studio status <nb-id>                          # List all artifacts
nlm studio status <nb-id> --full                   # Show full details (including custom prompts)
nlm studio status <nb-id> --json                   # JSON output
nlm studio status <nb-id> --json --full            # Includes artifact source_ids
nlm studio status <nb-id> --artifact-id <id>       # Poll one artifact
nlm studio status <nb-id> --json --mcp-compatible  # MCP-shaped paginated output
nlm video list <nb-id> --json                      # List videos only

# Download artifacts
nlm download audio <nb-id> --output podcast.mp3
nlm download video <nb-id> --output video.mp4
nlm download report <nb-id> --output report.md
nlm download slide-deck <nb-id> --output slides.pdf           # PDF (default)
nlm download slide-deck <nb-id> --output slides.pptx --format pptx  # PPTX
nlm download quiz <nb-id> --output quiz.html --format html    # Also: json, markdown
nlm download all <nb-id> -d ./exports                          # Every completed artifact
nlm download all --all-notebooks -d ./exports --skip-existing  # Sweep every notebook

# Export to Google Docs/Sheets
nlm export sheets <nb-id> <artifact-id> --title "My Data Table"
nlm export docs <nb-id> <artifact-id> --title "My Report"

# Delete artifact
nlm studio delete <nb-id> <artifact-id> --confirm
```

**Status values**: `completed` (✓), `in_progress` (●), `failed` (✗)

**Prompt Extraction**: MCP `studio_status` is lean and returns at most 20 artifacts by default. Pass `include_details=True` to retrieve `custom_instructions`, source IDs, report content, and media details. Pass `artifact_id` when polling a newly created artifact. CLI `--full` preserves the detailed output.

### Renaming Resources

#### Rename a Source

**MCP Tool:** `source_rename(notebook_id, source_id, new_title)`

**CLI:**
```bash
nlm source rename <source-id> "New Title" --notebook <notebook-id>
nlm rename source <source-id> "New Title" --notebook <notebook-id>  # verb-first
```

#### Rename a Studio Artifact

#### MCP Tools

Use `studio_status` with `action="rename"`, `artifact_id`, and `new_title`.

#### CLI Commands
```bash
nlm studio rename <artifact-id> "New Title"
nlm rename studio <artifact-id> "New Title"  # verb-first alternative
```

### Server Info (Version Check)

#### MCP Tools

Use `server_info` to get version and check for updates:

```python
mcp__gemini-notebook-mcp__server_info()
# Returns version/update fields plus auth_status
```

Treat `stale` as requiring `nlm login`. `unverified` is an inconclusive probe,
not confirmed expiration.

#### CLI Commands
```bash
nlm --version  # Shows version and update availability
```

### 7. Chat Configuration, Chat Sessions, and Notes

#### MCP Tools

Use `chat_configure` with `goal`: default/learning_guide/custom. Use `note` with `action`: create/list/update/delete. Delete requires `confirm=True`.

Use `chat_list`, `chat_get`, and `chat_export` to list/view/export a
notebook's chat history. Transcripts are fetched from NotebookLM's server
(not just this process's cache), so past chats are visible even from a fresh
MCP session. `chat_get`'s `conversation_id` is optional and defaults to the
notebook's latest session. There is no MCP tool for saving a chat to a note
yet — use the CLI's `nlm chats to-note` for that.

#### CLI Commands

> ⚠️ **AI TOOLS: DO NOT USE `nlm chat start`** - It launches an interactive REPL that cannot be controlled programmatically. Use `nlm notebook query` for one-shot Q&A instead.

For human users at a terminal:

```bash
nlm chat start <nb-id>  # Launch interactive REPL
```

**REPL Commands**:
- `/sources` - List available sources
- `/clear` - Reset conversation context
- `/help` - Show commands
- `/exit` - Exit REPL

**Configure chat behavior** (works for both REPL and query):
```bash
nlm chat configure <id> --goal default
nlm chat configure <id> --goal learning_guide
nlm chat configure <id> --goal custom --prompt "Act as a tutor..."
nlm chat configure <id> --response-length longer  # longer, default, shorter
```

**Notes management**:
```bash
nlm note create <nb-id> --content "Content" --title "Title"
nlm note list <nb-id>
nlm note update <nb-id> <note-id> --content "New content"
nlm note delete <nb-id> <note-id> --confirm
```

**Chat sessions** (list/view/export past chats, resume, or save to a note):
```bash
nlm chats list <nb-id>                              # List chat sessions
nlm chats get <nb-id>                               # Latest session's transcript
nlm chats get <nb-id> <conversation-id>              # Specific session
nlm chats export <nb-id> --format md -o chat.md      # Export to file
nlm chats to-note <nb-id> <conversation-id> --turn 3 # Save one turn as a Note
nlm chats to-note <nb-id> <conversation-id>          # Save the full chat as a Note

# Resume a listed conversation with a follow-up question:
nlm notebook query <nb-id> "follow-up question" --conversation-id <conversation-id>
```

### 8. Notebook Sharing

#### MCP Tools

Use `notebook_share_status` to check, `notebook_share_public` to enable/disable
public links, and `notebook_share_invite` for one collaborator. Use
`notebook_share_batch` with `recipients=[{"email": "...", "role":
"viewer|editor"}]` and `confirm=True` for multiple collaborators.

#### CLI Commands
```bash
# Check sharing status
nlm share status <nb-id>

# Enable/disable public link
nlm share public <nb-id>          # Enable
nlm share public <nb-id> --off    # Disable

# Invite collaborator
nlm share invite <nb-id> user@example.com
nlm share invite <nb-id> user@example.com --role editor
```

### 9. Aliases (UUID Shortcuts)

Simplify long UUIDs:

```bash
nlm alias set myproject abc123-def456...  # Create alias (auto-detects notebook/source)
nlm alias get myproject                    # Resolve to UUID
nlm alias list                             # List all aliases
nlm alias delete myproject                 # Remove alias

# Use aliases anywhere
nlm notebook get myproject
nlm source list myproject
nlm audio create myproject --confirm
```

### 10. Configuration

CLI-only commands for managing settings:

```bash
nlm config show                              # Show current config
nlm config get <key>                         # Get specific setting
nlm config set <key> <value>                 # Update setting
nlm config set output.format json            # Change default output

# For switching profiles, prefer the simpler command:
nlm login switch work                        # Switch default profile
```

**Available Settings:**

| Key | Default | Description |
|-----|---------|-------------|
| `output.format` | `table` | Default output format (table, json) |
| `output.color` | `true` | Enable colored output |
| `output.short_ids` | `true` | Show shortened IDs |
| `auth.browser` | `auto` | Preferred browser for login (auto, chrome, arc, brave, edge, chromium, vivaldi, opera) |
| `auth.default_profile` | `default` | Profile to use when `--profile` not specified |

### Diagnostics & Setup

Diagnose and fix issues with your Gemini Notebook installation, MCP server, and AI tools:

```bash
nlm doctor                                   # Full diagnostic check
nlm setup mcp                                # Show MCP server config JSON
nlm setup add json                           # Interactive MCP config generator
nlm setup add claude-desktop                 # Setup detected Claude Desktop profile(s)
nlm setup add claude-desktop --profile 3p    # Select Relay AI / Claude 3P
nlm setup remove claude-desktop --profile 3p # Remove from Relay AI / Claude 3P
nlm setup add cursor                         # Setup MCP for Cursor
nlm setup remove cursor                      # Remove MCP from Cursor
```

Claude Desktop setup never creates a missing profile. If both regular and
Relay AI/3P profiles exist, select one with `--profile regular|3p|both` or
answer the prompt. Fully quit the selected Claude profile before setup;
the CLI refuses to write while its executable is running. User-level skill
installation likewise requires the target tool to be detected; use
`--level project` for an intentional project-local install.

### 11. Skill Management

Manage the NotebookLM skill installation for various AI assistants:

```bash
nlm skill list                              # Show installation status
nlm skill update                            # Update all outdated skills
nlm skill update <tool>                     # Update specific skill (e.g., claude-code)
nlm skill install <tool>                    # Install skill
nlm skill uninstall <tool>                  # Uninstall skill
```

**Verb-first aliases**: `nlm update skill`, `nlm list skills`, `nlm install skill`

## Output Formats

Most list commands support multiple formats:

| Flag | Description |
|------|-------------|
| (none) | Rich table (human-readable) |
| `--json` | JSON output (for parsing) |
| `--quiet` | IDs only (for piping) |
| `--title` | "ID: Title" format |
| `--url` | "ID: URL" format (sources only) |
| `--full` | All columns/details |

### 12. Batch Operations

Perform the same action across multiple notebooks at once.

#### MCP Tools

Use `batch` with `action` parameter. Select notebooks by `notebook_names`, `tags`, or `all=True`.

```python
batch(action="query", query="What are the key findings?", notebook_names="AI Research, Dev Tools")
batch(action="add_source", source_url="https://example.com", tags="ai,research")
batch(action="create", titles="Project A, Project B, Project C")
batch(action="delete", notebook_names="Old Project", confirm=True)
batch(action="studio", artifact_type="audio", tags="research", confirm=True)
```

#### CLI Commands
```bash
nlm batch query "What are the key takeaways?" --notebooks "id1,id2"
nlm batch query "Summarize" --tags "ai,research"      # Query by tag
nlm batch query "Summarize" --all                      # Query ALL notebooks
nlm batch add-source "https://..." --notebooks "id1,id2"
nlm batch create "Project A, Project B, Project C"     # Create multiple
nlm batch delete --notebooks "id1,id2" --confirm       # Delete multiple
nlm batch studio audio --tags "research"                   # Generate across notebooks
```

### 13. Cross-Notebook Query

Query multiple notebooks and get **aggregated answers with per-notebook citations**.

#### MCP Tools

```python
cross_notebook_query(query="Compare approaches", notebook_names="Notebook A, Notebook B")
cross_notebook_query(query="Summarize", tags="ai,research")
cross_notebook_query(query="Everything", all=True)
```

#### CLI Commands
```bash
nlm cross query "What features are discussed?" --notebooks "id1,id2"
nlm cross query "Compare approaches" --tags "ai,research"
nlm cross query "Summarize everything" --all
```

### 14. Pipelines

Define and execute multi-step notebook workflows. Three built-in pipelines plus support for custom YAML pipelines.

#### MCP Tools

```python
pipeline(action="list")  # List available pipelines
pipeline(action="run", notebook_id="...", pipeline_name="ingest-and-podcast", input_url="https://...")
```

#### CLI Commands
```bash
nlm pipeline list                                         # List available pipelines
nlm pipeline run ingest-and-podcast --notebook <id> --input-url "https://..."
nlm pipeline run research-and-report --notebook <id> --input-url "https://..."
nlm pipeline run multi-format --notebook <id>             # Audio + report + flashcards
nlm pipeline create my-pipeline --file pipeline.yaml
```

**Built-in pipelines:** `ingest-and-podcast`, `research-and-report`, `multi-format`

Create custom pipelines: add YAML files to `~/.notebooklm-mcp-cli/pipelines/`

### 15. Tags & Smart Select

Tag notebooks for organization and use tags to target batch operations.

#### MCP Tools

```python
tag(action="add", notebook_id="...", tags="ai,research,llm")
tag(action="remove", notebook_id="...", tags="ai")
tag(action="list")                           # List all tagged notebooks
tag(action="select", query="ai research")    # Find notebooks by tag match
```

#### CLI Commands
```bash
nlm tag add <notebook> --tags "ai,research,llm"           # Add tags
nlm tag add <notebook> --tags "ai" --title "My Notebook"  # With display title
nlm tag remove <notebook> --tags "ai"                     # Remove tags
nlm tag list                                              # List all tagged notebooks
nlm tag select "ai research"                              # Find notebooks by tag match
```

### 16. Long-Lived MCP Server Configuration

The MCP server runs as a long-lived process. For 24/7 deployments (e.g. an always-on assistant), a few knobs help bound memory and tune behavior.

#### Conversation cache bounds (added in 0.6.14)

The in-process conversation history cache used to grow without bound, eventually OOM'ing the host on always-on servers. Three env-var knobs cap memory. Set any to `0` to disable that specific cap and restore the old unbounded behavior:

| Env var | Default | Purpose |
|---------|---------|---------|
| `NOTEBOOKLM_CONVERSATION_MAX_TURNS` | `50` | Max turns kept per conversation. Older turns are FIFO-dropped. Survivors are renumbered `1..N` so `turn_number` stays a stable 1-indexed position in the current list. |
| `NOTEBOOKLM_CONVERSATION_MAX_CONVS` | `500` | Max distinct conversations cached. On overflow, the least-recently-used conversation is evicted. Reads and writes both promote to MRU. |
| `NOTEBOOKLM_CONVERSATION_MAX_CHARS_PER_TURN` | `100000` | Per-turn answer char cap. Safety net against pathological payloads. Queries are user input and not truncated. |

With all defaults: 500 convs × 50 turns × up to 100k chars = hard upper bound around ~2.5 GB of answer text. In practice answers are 1–10 KB, so the typical ceiling is ~25 MB.

Negative values are clamped to `0` (unlimited) with a warning. Invalid values fall back to the default with a warning.

#### Cache stats (added in 0.6.14)

For monitoring from Python, the `BaseClient` exposes `get_conversation_cache_stats()` which returns:

```python
{
    "conversations": int,            # current number of cached conversations
    "total_turns": int,              # current number of cached turns across all convs
    "max_turns_per_conversation": int,
    "max_conversations": int,
    "max_chars_per_turn": int,
}
```

There's no MCP or CLI tool wrapper in 0.6.14. Call it directly from Python if you need to surface cache pressure in your own tooling.

#### Server startup flags (notebooklm-mcp)

When starting the MCP server directly, two flags control transport-layer behavior. Neither affects the conversation cache above.

- `--stateless` / `--no-stateless` (default: `true`, env `NOTEBOOKLM_MCP_STATELESS`): Controls whether the MCP HTTP transport keeps per-session state. Leave it `true` unless you know you need sessions. The flag exists to work around an MCP SDK double-response crash (python-sdk#2416) and is unrelated to the conversation cache.
- `--transport http` / `--transport stdio` (default: `stdio`): Pick the transport. `--transport http` requires `--port` (default `8000`).
- `--host <addr>` (default `127.0.0.1`): Bind address for HTTP/SSE. Refuses external binds unless `NOTEBOOKLM_ALLOW_EXTERNAL_BIND=1` is set.

#### Remote MCP security

The server has no built-in endpoint authentication or TLS and uses one
process-wide Google account. Never expose it directly to the public internet.
Put authentication, TLS, and network restrictions in front of remote
deployments. Browser/phone-local files are not transferred automatically;
`source_add(file)` requires a path already present on the server host.

## Common Patterns

### Pattern 1: Research → Podcast Pipeline

```bash
nlm notebook create "AI Research 2026"   # Capture ID
nlm alias set ai <notebook-id>
nlm research start "agentic AI trends" --notebook-id ai --mode deep
nlm research status ai --max-wait 900    # Deep research can take up to 15 min
nlm research import ai <task-id>         # Or use research start --auto-import
nlm audio create ai --format deep_dive --confirm
nlm studio status ai                     # Check generation progress
```

### Pattern 2: Quick Content Ingestion

```bash
nlm source add <id> --url "https://example1.com"
nlm source add <id> --url "https://example2.com"
nlm source add <id> --text "My notes..." --title "Notes"
nlm source list <id>
```

### Pattern 3: Study Materials Generation

```bash
nlm report create <id> --format "Study Guide" --confirm
nlm quiz create <id> --count 10 --difficulty 3 --focus "Exam prep" --confirm
nlm flashcards create <id> --difficulty medium --focus "Core terms" --confirm
```

### Pattern 4: Drive Document Workflow

```bash
nlm source add <id> --drive 1KQH3eW0hMBp7WK... --type slides
# ... time passes, document is edited ...
nlm source stale <id>                    # Check freshness
nlm source list <id> --drive -S           # Fast list without freshness checks
nlm source sync <id> --confirm           # Sync if stale
```

### Pattern 5: Batch & Cross-Notebook Workflow

```bash
# Tag notebooks for organization
nlm tag add <id1> --tags "ai,research"
nlm tag add <id2> --tags "ai,product"

# Query across tagged notebooks
nlm cross query "What are the main conclusions?" --tags "ai"

# Batch generate podcasts for all tagged notebooks
nlm batch studio audio --tags "ai"

# Run a pipeline on a single notebook
nlm pipeline run ingest-and-podcast --notebook <id> --input-url "https://example.com"
```

## Error Recovery

| Error | Cause | Solution |
|-------|-------|----------|
| "Cookies have expired" | Session timeout | `nlm login` |
| "authentication may have expired" | Session timeout | `nlm login` |
| "Notebook not found" | Invalid ID | `nlm notebook list` |
| "Source not found" | Invalid ID | `nlm source list <nb-id>` |
| "Rate limit exceeded" | Too many calls | Studio creation: wait 1-2 minutes; avoid parallel video batches |
| "Research already in progress" | Pending research | Use `--force` or import first |
| "Import timed out" | Too many sources | Use `--timeout 600` for larger notebooks |
| "Google API error code 3" | Transient deep research error | Retry in a few minutes, or use `--mode fast` |
| Browser doesn't launch | Port conflict | Close browser, retry |
| `nlm login` crashes with `ClientAuthenticationError` | (Fixed in 0.6.14) Disk tokens fully expired | `nlm login` now works directly, no manual `nlm login profile delete` needed |
| `RPCDriftError` / rotated method ID | Gemini Notebook changed an internal RPC ID | Run with `--debug`, apply the suggested `NOTEBOOKLM_RPC_OVERRIDES` JSON mapping, then restart the MCP server |
| File upload path not found | Path exists on the client but not the CLI/MCP host | Use a path accessible on the machine running `nlm` or the MCP server |

## Rate Limiting

Wait between operations to avoid rate limits:
- Source operations: 2 seconds
- Content generation: run sequentially; after a rate limit, wait 1-2 minutes
- Research operations: 2 seconds
- Query operations: 2 seconds

## Advanced Reference

For detailed information, see:
- **[references/studio-prompting-guide.md](references/studio-prompting-guide.md)**: Studio prompt best practices, fast vs guided modes, per-artifact decision trees
- **[references/studio-prompt-examples.md](references/studio-prompt-examples.md)**: Copy-paste prompt templates and command examples
- **[references/command_reference.md](references/command_reference.md)**: Complete command signatures
- **[references/troubleshooting.md](references/troubleshooting.md)**: Detailed error handling
- **[references/workflows.md](references/workflows.md)**: End-to-end task sequences
- **[references/remote-mcp.md](references/remote-mcp.md)**: Remote HTTP deployment boundaries, security, account isolation, and file-transfer limitations
