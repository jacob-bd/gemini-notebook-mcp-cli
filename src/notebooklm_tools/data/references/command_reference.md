# Gemini Notebook (formerly Google NotebookLM) CLI - Complete Command Reference

This document contains the complete command signatures and all available options for every `nlm` command.

## Table of Contents

1. [Global Options](#global-options)
2. [Authentication](#authentication)
3. [Plan Usage](#plan-usage)
4. [Notebook Commands](#notebook-commands)
5. [Source Commands](#source-commands)
6. [Research Commands](#research-commands)
7. [Generation Commands](#generation-commands)
8. [Studio Commands](#studio-commands)
9. [Download Commands](#download-commands)
10. [Export Commands](#export-commands)
11. [Sharing Commands](#sharing-commands)
12. [Note Commands](#note-commands)
13. [Chat Commands](#chat-commands)
14. [Alias Commands](#alias-commands)
15. [Config Commands](#config-commands)
16. [Organization and Automation](#organization-and-automation)
17. [Setup, Skill, and Diagnostics](#setup-skill-and-diagnostics)

---

## Global Options

```bash
nlm --version, -v      # Show version and exit
nlm --ai               # Output AI-friendly documentation
nlm --install-completion  # Install shell completion
nlm --show-completion  # Show completion script
nlm --help             # Show help and exit
```

---

## Authentication

### nlm login

Authenticate with Gemini Notebook using the managed browser auth flow.

```bash
nlm login [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Profile name for multiple accounts |
| `--check` | | Validate current credentials without re-authenticating |
| `--provider` | | Auth provider: `builtin` (default) or `openclaw` |
| `--cdp-url` | | CDP endpoint URL for external provider mode (default: `http://127.0.0.1:18800`) |
| `--manual` | `-m` | Import cookies from file |
| `--file` | `-f` | Cookie file path for manual mode |
| `--force` | | Replace credentials even if the detected account differs |
| `--clear` | | Clear stored browser/profile state before login |
| `--wsl` | | Use the WSL/Windows-browser authentication path |
| `--storage` | | `protected` or `file`: where to keep the saved login for a NEW profile (skips the question; refused for existing profiles) |

**Note**: Each profile gets its own isolated Chrome session, so you can be logged into multiple Google accounts simultaneously.

### nlm login profile list

List all authentication profiles with their associated email addresses.

```bash
nlm login profile list
```

### nlm login profile delete

Delete an authentication profile and its credentials.

```bash
nlm login profile delete <profile>
```

### nlm login profile rename

Rename an authentication profile.

```bash
nlm login profile rename <old-name> <new-name>
```

### nlm login switch

Switch the default profile for all commands.

```bash
nlm login switch <profile>
```

| Argument | Description |
|----------|-------------|
| `<profile>` | Profile name to switch to |

### nlm auth refresh

Refresh a session non-interactively so Google reissues its short-lived
cookies. Runs a headless-browser pass against the saved profile — no user
interaction — which keeps an unattended session (cron/launchd) alive without
an interactive `nlm login`. Exits non-zero if the refresh fails.

`--http-only` refreshes eligible cookies and page tokens over HTTP, even when
CDP transport is configured. It cannot renew browser-dependent PSIDTS cookies
or revive a fully expired login. Explicit refresh bypasses automatic recovery
cooldown and failure limits.

```bash
nlm auth refresh
nlm auth refresh --profile work
nlm auth refresh --http-only
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Profile to refresh (default: the configured default profile) |
| `--http-only` | | Force HTTP transport without launching a browser; validate before saving |

**Example:**
```bash
nlm login switch work
# Output: ✓ Switched default profile to work
#         Account: jsmith@company.com
```

### nlm auth storage status

Show current credential storage mode (`file` or `protected`) for a profile, envelope status, and any detected conflicts.

```bash
nlm auth storage status [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Profile to check (default: configured default profile) |
| `--json` | `-j` | Output as JSON |

### nlm auth storage set

Change credential storage mode for one or more profiles. In a terminal with several saved logins and no `--profile`, a picker lets you choose which ones (nothing pre-selected). Scripts and agents without a terminal act on the default profile and are told which profiles are still in the other mode. In `protected` mode, credentials are encrypted via the OS credential store (macOS Keychain, Windows Credential Manager, Secret Service / libsecret).

```bash
nlm auth storage set <mode> [OPTIONS]
```

| Argument | Description |
|----------|-------------|
| `<mode>` | Target mode: `file` or `protected` |

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Profile to set (skips the picker) |
| `--all` | | Apply to every saved profile not already in this mode |
| `--json` | `-j` | Output as JSON |

> **Downgrade Preparation**: If downgrading to an older version of `notebooklm-mcp-cli` that does not support Protected mode, run `nlm auth storage set file` for every protected profile first to restore plaintext files.

### nlm auth storage resolve

Resolve a credential storage conflict when both encrypted credentials and legacy plaintext files exist, clear stuck operation markers, or discard inaccessible credentials.

```bash
nlm auth storage resolve [choice] [OPTIONS]
```

| Argument | Description |
|----------|-------------|
| `[choice]` | Resolution choice: `file` (keep plaintext, discard encrypted) or `protected` (keep encrypted, discard plaintext) |

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Profile to resolve (default: configured default profile) |
| `--discard-inaccessible` | | Discard inaccessible ciphertext and reset to file mode without exporting |
| `--clear-marker` | | Clear a stuck or corrupt operation marker |
| `--yes` | `-y` | Confirm action without interactive prompt |
| `--json` | `-j` | Output as JSON |

### nlm auth storage relocate

Re-bind installation identity after moving or restoring the storage directory to update the stored installation ID and path binding.

```bash
nlm auth storage relocate [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--json` | `-j` | Output as JSON |

---

## Plan Usage

### nlm usage

Show the account's measured Gemini Notebook compute usage across the rolling
and weekly allowance windows, including reset times and the subscription tier
when available.

```bash
nlm usage [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--json` | Output machine-readable JSON; reset timestamps are ISO 8601 UTC |

The human-readable table renders reset timestamps in the local timezone. The
JSON response has this shape:

```json
{
  "windows": [
    {
      "window": "rolling",
      "percent_used": 0.0,
      "percent_remaining": 100,
      "resets_at": "2026-09-12T22:44:21+00:00"
    },
    {
      "window": "weekly",
      "percent_used": 8.7,
      "percent_remaining": 91.3,
      "resets_at": "2026-09-19T17:44:21+00:00"
    }
  ],
  "tier": "NOTEBOOKLM_TIER_PRO_CONSUMER_USER"
}
```

Use the window name rather than list position. The backend does not guarantee
the order of its raw entries, while the CLI and service return `rolling` first
and `weekly` second. If authentication has expired, refresh with `nlm auth
refresh` or `nlm login`; an auth failure is not an exhausted quota.

---

## Notebook Commands

### nlm notebook list

List all notebooks.

```bash
nlm notebook list [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--json` | | Output as JSON |
| `--quiet` | `-q` | Output IDs only |
| `--title` | | Output as "ID: Title" |
| `--full` | | Show all columns |
| `--profile` | `-p` | Use specific profile |

### nlm notebook create

Create a new notebook.

```bash
nlm notebook create <title> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--json` | `-j` | Output stable machine-readable result |
| `--profile` | `-p` | Use specific profile |

### nlm notebook get

Get notebook details.

```bash
nlm notebook get <notebook-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

### nlm notebook describe

Get AI-generated notebook summary with suggested topics.

```bash
nlm notebook describe <notebook-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

### nlm notebook query

Ask a question about notebook sources.

```bash
nlm notebook query <notebook-id> <question> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--source-ids` | | Limit to specific sources (comma-separated) |
| `--conversation-id` | | Continue existing conversation |
| `--profile` | `-p` | Use specific profile |

### nlm notebook rename

Rename a notebook.

```bash
nlm notebook rename <notebook-id> <new-title> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

### nlm notebook delete

Delete a notebook permanently.

```bash
nlm notebook delete <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--confirm` | **Required** to confirm deletion |
| `--profile` | Use specific profile |

---

## Source Commands

### nlm source list

List sources in a notebook.

```bash
nlm source list <notebook-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--json` | | Output as JSON |
| `--quiet` | `-q` | Output IDs only |
| `--url` | | Output as "ID: URL" |
| `--full` | | Show all columns (wider URL display) |
| `--drive` | | Show Drive sources with freshness status |
| `--skip-freshness` | `-S` | Skip freshness checks (faster with --drive) |
| `--profile` | `-p` | Use specific profile |

When freshness is skipped, `stale`/`is_stale` is `null` (unknown), not
`false` (fresh).

Source listing JSON includes `url` for web and YouTube sources. The current MCP
`source_list_drive` and `source_get_content` responses omit this field; use the
CLI when an original source URL is needed.

### nlm source add

Add a source to a notebook.

```bash
nlm source add <notebook-id> [OPTIONS]
```

**URL Source:**
| Option | Description |
|--------|-------------|
| `--url` | URL to add; repeat for bulk URL add |
| `--youtube` | Explicit YouTube URL |

**Text Source:**
| Option | Description |
|--------|-------------|
| `--text` | Text content to add |
| `--title` | Title for text source |

**Drive Source:**
| Option | Description |
|--------|-------------|
| `--drive` | Google Drive document ID |
| `--type` | Drive doc type: `doc`, `slides`, `sheets`, `pdf` |
| `--title` | Display title |

**File Source:**
| Option | Description |
|--------|-------------|
| `--file` | Local path on the machine running `nlm` |
| `--wait` | Wait until Gemini Notebook finishes processing |
| `--wait-timeout` | Processing timeout in seconds |

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

### nlm source get

Get source metadata.

```bash
nlm source get <source-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

`nlm source get <source-id> --json` includes the original web or YouTube `url`.

### nlm source describe

Get AI-generated source summary with keywords.

```bash
nlm source describe <source-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

### nlm source content

Get raw text content of a source.

```bash
nlm source content <source-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Export to file path |
| `--profile` | `-p` | Use specific profile |

### nlm source stale

List stale (outdated) Drive sources.

```bash
nlm source stale <notebook-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

### nlm source sync

Sync Drive sources with latest content.

```bash
nlm source sync <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--confirm` | **Required** to execute sync |
| `--source-ids` | Specific source IDs to sync (comma-separated) |
| `--profile` | Use specific profile |

### nlm source rename

Rename a source.

```bash
nlm source rename <source-id> <new-title> [OPTIONS]
nlm rename source <source-id> <new-title> [OPTIONS]  # verb-first alias
```

| Option | Description |
|--------|-------------|
| `--notebook` | **Required** - Notebook ID containing the source |
| `--profile` | Use specific profile |

### nlm source delete

Delete a source permanently.

```bash
nlm source delete <source-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--confirm` | **Required** to confirm deletion |
| `--profile` | Use specific profile |

---

## Research Commands

### nlm research start

Start a research task to discover new sources.

```bash
nlm research start <query> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--notebook-id` | Existing target notebook ID |
| `--title` | Create a new destination notebook with this title |
| `--mode` | `fast` (default, ~30s) or `deep` (~5min, web only) |
| `--source` | `web` (default) or `drive` |
| `--force` | Override pending research |
| `--auto-import` | Poll every 30 seconds for up to 900 seconds, then import completed results (alias: `--wait-and-import`) |
| `--profile` | Use specific profile |

### nlm research status

Check research task progress.

```bash
nlm research status <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--task-id` | Check specific task (auto-detected if omitted) |
| `--max-wait` | Max seconds to wait (default: 300, 0=single check) |
| `--full` | Show full details |
| `--profile` | Use specific profile |

### nlm research import

Import discovered sources into notebook.

```bash
nlm research import <notebook-id> <task-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--indices` | Comma-separated indices of sources to import (default: all) |
| `--cited-only` | Import only sources cited by the research report (overrides `--indices`) |
| `--timeout` | Import timeout in seconds (default: 300) |
| `--profile` | Use specific profile |

---

## Generation Commands

All generation commands share `--confirm`, `--source-ids`, and `--profile`.
The `--language` option is available for audio, report, slides, infographic,
video, and data-table.

| Option | Short | Description |
|--------|-------|-------------|
| `--confirm` | `-y` | **Required** to execute generation |
| `--source-ids` | | Limit to specific sources (comma-separated) |
| `--language` | | BCP-47 language code where supported, including regional locales such as `es-419` |
| `--profile` | `-p` | Use specific profile |

### nlm audio create

Generate audio overview (podcast).

```bash
nlm audio create <notebook-id> [OPTIONS]
```

| Option | Values | Default |
|--------|--------|---------|
| `--format` | `deep_dive`, `brief`, `critique`, `debate` | `deep_dive` |
| `--length` | `short`, `default`, `long` | `default` |
| `--focus` | Focus text/topic | |

For audio, regional locales can affect the voice accent. Gemini Notebook has been
observed using `es`/`es-ES` for Spain Spanish and `es-US`/`es-419` for
Latin-American Spanish. `NOTEBOOKLM_HL` can set the regional default.

### nlm report create

Generate written report.

```bash
nlm report create <notebook-id> [OPTIONS]
```

| Option | Values | Default |
|--------|--------|---------|
| `--format` | `"Briefing Doc"`, `"Study Guide"`, `"Blog Post"`, `"Create Your Own"` | `"Briefing Doc"` |
| `--prompt` | Custom prompt (required for "Create Your Own") | |

### nlm quiz create

Generate quiz questions.

```bash
nlm quiz create <notebook-id> [OPTIONS]
```

| Option | Values | Default |
|--------|--------|---------|  
| `--count` | Number of questions | 2 |
| `--difficulty` | 1-5 (1=easy, 5=hard) | 2 |
| `--focus` | Focus text/topic | |

### nlm flashcards create

Generate flashcards.

```bash
nlm flashcards create <notebook-id> [OPTIONS]
```

| Option | Values | Default |
|--------|--------|---------|
| `--difficulty` | `easy`, `medium`, `hard` | `medium` |
| `--focus` | Focus text/topic | |

### nlm mindmap create

Generate mind map.

```bash
nlm mindmap create <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--title` | Display title for the mind map |

List mind maps through `nlm studio status <notebook-id>`.

### nlm slides create

Generate slide deck.

```bash
nlm slides create <notebook-id> [OPTIONS]
```

| Option | Values | Default |
|--------|--------|---------|
| `--format` | `detailed_deck`, `presenter_slides` | `detailed_deck` |
| `--length` | `short`, `default` | `default` |
| `--focus` | Focus text/topic | |

### nlm slides revise

Revise one or more slides and create a new deck.

```bash
nlm slides revise <artifact-id> --slide "1 Make the title larger" --confirm
```

`--slide` is repeatable and uses `"<1-based slide number> <instruction>"`.
The original deck is unchanged.

### nlm infographic create

Generate infographic.

```bash
nlm infographic create <notebook-id> [OPTIONS]
```

| Option | Values | Default |
|--------|--------|---------|
| `--orientation` | `landscape`, `portrait`, `square` | `landscape` |
| `--detail` | `concise`, `standard`, `detailed` | `standard` |
| `--style` | `auto_select`, `sketch_note`, `professional`, `bento_grid`, `editorial`, `instructional`, `bricks`, `clay`, `anime`, `kawaii`, `scientific` | `auto_select` |
| `--focus` | Focus text/topic | |

### nlm video create

Generate video overview.

```bash
nlm video create <notebook-id> [OPTIONS]
```

| Option | Values | Default |
|--------|--------|---------|
| `--format` | `explainer`, `brief`, `cinematic`, `short` | `explainer` |
| `--style` | `auto_select`, `custom`, `classic`, `whiteboard`, `kawaii`, `anime`, `watercolor`, `retro_print`, `heritage`, `paper_craft` (not for cinematic/short) | `auto_select` |
| `--style-prompt` | Custom visual style text (requires `--style custom`, or implies it when `--style` omitted) | |
| `--focus` | Focus text/topic | |

`short` produces a ~60s vertical video with no visual style picker. Non-English
output is best-effort: `--language` adds an explicit language requirement to the
focus prompt because the captured Short RPC uses a null language slot.

List generated videos with `nlm video list <notebook-id>`.

### nlm data-table create

Extract structured data as a table.

```bash
nlm data-table create <notebook-id> <description> [OPTIONS]
```

**Note**: `<description>` is a **required positional argument** describing what data to extract.

---

## Studio Commands

### nlm studio status

List all generated artifacts in a notebook.

```bash
nlm studio status <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--json` | Output as JSON |
| `--full` | Show all details |
| `--artifact-id` | Return one artifact by ID |
| `--limit` | Maximum artifacts to return (1-100) |
| `--offset` | Skip artifacts for pagination |
| `--mcp-compatible` | Return the lean, paginated MCP envelope as JSON |
| `--profile` | Use specific profile |

`--json --full` includes `source_ids`, allowing each artifact to be traced to
the source set used to generate it.

The legacy `--json` shape remains a plain list and now contains both `id` and
`artifact_id`. MCP-compatible output defaults to 20 lean artifacts; combine it
with `--full` only when prompts or other rich fields are needed.

### nlm studio delete

Delete a generated artifact.

```bash
nlm studio delete <notebook-id> <artifact-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--confirm` | **Required** to confirm deletion |
| `--profile` | Use specific profile |
---

## Download Commands

### nlm download

Download generated artifacts to local files.

```bash
nlm download <type> <notebook-id> [OPTIONS]
```

**Available types:** `audio`, `video`, `report`, `mind-map`, `slide-deck`,
`infographic`, `quiz`, `flashcards`, `data-table`, `file`

| Option | Description |
|--------|-------------|
| `--id` | Specific artifact ID (uses latest if omitted) |
| `--format` | Output format for quiz/flashcards: `json`, `markdown`, `html` |
| `--output` | Output file path |

**Examples:**
```bash
nlm download audio <nb-id> --output podcast.m4a
nlm download video <nb-id> --output video.mp4
nlm download report <nb-id> --output report.md
nlm download file <nb-id> --id <artifact-id> --output export.bin
nlm download quiz <nb-id> --output quiz.html --format html
nlm download flashcards <nb-id> --output cards.json --format json
```

Audio arrives as AAC in an MP4 container, so it needs a `.m4a` or `.mp4`
suffix; `.mp3` and other mismatched extensions are rejected rather than
written with bytes that contradict the name. Transcode afterwards if you
need MP3:

```bash
nlm download audio <notebook> --id <artifact-id> --output raw.m4a
ffmpeg -i raw.m4a -acodec libmp3lame -q:a 2 podcast.mp3
```

### nlm download all

Download every completed artifact of a notebook — or every notebook — into
per-notebook directories named after each notebook's title.

```bash
nlm download all <notebook-id> [OPTIONS]
nlm download all --all-notebooks [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--output-dir`, `-d` | Base directory; a subdirectory per notebook is created inside |
| `--types`, `-t` | Comma-separated artifact types to include (default: all) |
| `--all-notebooks`, `-a` | Sweep every notebook in the account |
| `--skip-existing` | Skip artifacts whose file already exists (incremental re-runs) |

**Examples:**
```bash
nlm download all <nb-id> --output-dir ./exports
nlm download all --all-notebooks --output-dir ./exports --skip-existing
```

---

## Export Commands

### nlm export

Export artifacts to Google Docs or Sheets.

```bash
nlm export <type> <notebook-id> <artifact-id> [OPTIONS]
```

**Available types:** `docs`, `sheets`

| Option | Description |
|--------|-------------|
| `--title` | Title for the exported document |
| `--profile` | Use specific profile |

**Examples:**
```bash
nlm export sheets <nb-id> <artifact-id> --title "Data Table Export"
nlm export docs <nb-id> <artifact-id> --title "My Report"
```

---

## Sharing Commands

### nlm share status

Get current sharing settings for a notebook.

```bash
nlm share status <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--profile` | Use specific profile |

### nlm share public

Enable or disable public link sharing.

```bash
nlm share public <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--off` | Disable public sharing (default: enable) |
| `--profile` | Use specific profile |

**Examples:**
```bash
nlm share public <nb-id>         # Enable public link
nlm share public <nb-id> --off   # Disable public link
```

### nlm share invite

Invite a collaborator by email.

```bash
nlm share invite <notebook-id> <email> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--role` | `viewer` (default) or `editor` |
| `--profile` | Use specific profile |

**Examples:**
```bash
nlm share invite <nb-id> user@example.com
nlm share invite <nb-id> user@example.com --role editor
```

---

## Note Commands

### nlm note create

Create a note in a notebook.

```bash
nlm note create <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--content` | Note content (required) |
| `--title` | Note title |
| `--profile` | Use specific profile |

### nlm note list

List all notes in a notebook.

```bash
nlm note list <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--json` | Output as JSON |
| `--profile` | Use specific profile |

### nlm note update

Update an existing note.

```bash
nlm note update <notebook-id> <note-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--content` | New content |
| `--title` | New title |
| `--profile` | Use specific profile |

### nlm note delete

Delete a note permanently.

```bash
nlm note delete <notebook-id> <note-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--confirm` | **Required** to confirm deletion |
| `--profile` | Use specific profile |

## Chat Commands

### nlm chat start

Start interactive chat REPL session.

```bash
nlm chat start <notebook-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Use specific profile |

**REPL Commands:**
- `/sources` - List available sources
- `/clear` - Reset conversation context
- `/help` - Show available commands
- `/exit` - Exit the REPL

### nlm chat configure

Configure chat behavior for a notebook.

```bash
nlm chat configure <notebook-id> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--goal` | `default`, `learning_guide`, `custom` |
| `--prompt` | Custom system prompt (required when goal is `custom`) |
| `--response-length` | `default`, `longer`, `shorter` |
| `--profile` | Use specific profile |

### nlm chats list

List chat sessions for a notebook (alias: `nlm chat list`).

```bash
nlm chats list <notebook-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Max chat sessions to display (default: 20) |
| `--json` | | Output raw JSON |
| `--profile` | `-p` | Use specific profile |

### nlm chats get

Retrieve the full Q&A transcript for a chat session. Transcripts are fetched
from the Gemini Notebook server, so past chats are visible even from a fresh CLI
invocation — not just chats made earlier in the same process.

```bash
nlm chats get <notebook-id> [conversation-id] [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| (positional) | | Conversation ID; defaults to the notebook's latest session |
| `--json` | | Output raw JSON |
| `--profile` | `-p` | Use specific profile |

### nlm chats export

Export a chat transcript to Markdown or JSON.

```bash
nlm chats export <notebook-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--conversation-id` | `-c` | Conversation ID; defaults to the latest session |
| `--format` | `-f` | `md` (default) or `json` |
| `--output` | `-o` | File path to save the export (prints to stdout if omitted) |
| `--profile` | `-p` | Use specific profile |

### nlm chats to-note

Save a chat turn or the full chat session as a Note in the notebook.

```bash
nlm chats to-note <notebook-id> <conversation-id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--turn` | `-t` | 1-indexed turn to save (default: entire chat) |
| `--title` | | Note title |
| `--json` | | Output raw JSON |

### nlm chats delete

Permanently delete all server-side chat history for a notebook. The command
prompts for confirmation unless `--confirm` is supplied.

```bash
nlm chats delete <notebook-id-or-title> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--confirm` | `-y` | Skip the interactive confirmation |
| `--json` | | Output raw JSON |
| `--profile` | `-p` | Use specific profile |
| `--profile` | `-p` | Use specific profile |

---

## Alias Commands

### nlm alias set

Create or update an alias for a Gemini Notebook ID.

```bash
nlm alias set <name> <id>
```

Type is auto-detected. Notebook and source IDs are verified automatically.

### nlm alias get

Resolve an alias to its UUID.

```bash
nlm alias get <name>
```

### nlm alias list

List all aliases.

```bash
nlm alias list
```

### nlm alias delete

Delete an alias.

```bash
nlm alias delete <name>
```

---

## Config Commands

### nlm config show

Display current configuration.

```bash
nlm config show [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--json` | Output as JSON instead of TOML |

### nlm config get

Get a specific configuration value.

```bash
nlm config get <key>
```

### nlm config set

Set a configuration value.

```bash
nlm config set <key> <value>
```

**Available Configuration Keys:**

| Key | Default | Description |
|-----|---------|-------------|
| `output.format` | `table` | Default output format (table, json) |
| `output.color` | `true` | Enable colored output |
| `output.short_ids` | `true` | Show shortened IDs |
| `auth.browser` | `auto` | Preferred browser for login (auto, chrome, arc, dia, comet, brave, edge, edge-beta, chromium, firefox, vivaldi, opera). Falls back to auto if a preferred named browser is not found. |
| `auth.browser_path` | empty | Explicit Chromium-compatible executable path. Overrides named discovery; `NLM_BROWSER_PATH` provides the environment override. |
| `auth.default_profile` | `default` | Profile to use when `--profile` not specified. **Note:** The MCP Server always uses the active default profile. Changing this setting will instantaneously switch the MCP server's Google account. |

**Example**: Set default profile to avoid typing `--profile` for every command:

```bash
# Preferred method (simpler)
nlm login switch work

# Alternative method (via config)
nlm config set auth.default_profile work
```

---

## Organization and Automation

### Labels

```bash
nlm label auto <notebook-id>
nlm label list <notebook-id>
nlm label reorganize <notebook-id> --confirm
nlm label create <notebook-id> "Research"
nlm label rename <notebook-id> <label-id> "New Name"
nlm label emoji <notebook-id> <label-id> "📚"
nlm label move <notebook-id> <source-id> <label-id>
nlm label delete <notebook-id> <label-id> --confirm
```

Full reorganization and deletion are destructive label operations. Sources are
preserved when labels are deleted.

### Tags and cross-notebook query

```bash
nlm tag add <notebook-id> --tags "ai,research"
nlm tag remove <notebook-id> --tags "ai"
nlm tag list
nlm tag select "ai research"
nlm cross query "Compare approaches" --notebooks "id1,id2"
nlm cross query "Summarize" --tags "ai,research"
nlm cross query "Everything" --all
```

### Batch operations

```bash
nlm batch query "Summarize" --notebooks "id1,id2"
nlm batch add-source "https://example.com" --notebooks "id1,id2"
nlm batch create "Project A, Project B"
nlm batch delete --notebooks "id1,id2" --confirm
nlm batch studio audio --tags "research"
```

### Pipelines

```bash
nlm pipeline list
nlm pipeline run ingest-and-podcast --notebook <id> --input-url "https://..."
nlm pipeline run research-and-report --notebook <id> --input-url "https://..."
nlm pipeline run multi-format --notebook <id>
nlm pipeline create my-pipeline --file pipeline.yaml
```

Run `nlm <family> <command> --help` for selector and profile options.

---

## Setup, Skill, and Diagnostics

MCP setup writes the configured server name `gemini-notebook-mcp`; the
`notebooklm-mcp` executable remains unchanged for compatibility.

```bash
nlm setup
nlm setup list
nlm setup add <tool>
nlm setup remove <tool>

# Claude Desktop profile selection
nlm setup add claude-desktop --profile regular|3p|both
nlm setup remove claude-desktop --profile regular|3p|both

nlm skill list
nlm skill install <tool> [--level user|project]
nlm skill update [tool]
nlm skill uninstall <tool>
nlm skill show
nlm skill package [--output DIR]   # Zip for Claude Desktop / claude.ai skill upload

nlm doctor
nlm doctor --verbose
```

Claude Desktop setup only targets detected profiles. If both regular and
Relay AI/3P profiles exist, the command prompts for a selection unless
`--profile` is supplied; if no profile exists, nothing is created. Fully quit
the selected Claude profile before adding or removing MCP configuration. The
CLI refuses to write while the active Claude executable is running, including
when Relay AI launched it. Bare `nlm setup` opens a wizard with Show my tools' status,
Add the MCP to my tools/agents, Add the skill to my tools/agents, Remove an MCP
or skill, Credential protection, Copy MCP setup for a tool not listed, and Exit (Esc goes back). It
offers to rename entries still using the old `notebooklm-mcp` name. MCP configuration defaults to app/user scope;
GitHub Copilot is configured in the VS Code user profile by the wizard. Its
direct command defaults to the current project and accepts `--scope user` for
the global profile. The optional skill defaults to **All projects (user level)**
and can target **This folder (project level)**. Skill updates skip equal or
newer versions and ask before replacing older or unversioned installs; existing
skill directories are backed up before replacement or removal. `nlm skill
package` writes `nlm-skill.zip` for Claude Desktop Chat/Cowork and claude.ai
(Customize → Skills → Add); re-upload it after updating `nlm`.

Verb-first aliases are also available for common operations, including
`nlm create`, `nlm list`, `nlm get`, `nlm add`, `nlm rename`, `nlm delete`,
`nlm status`, `nlm describe`, `nlm query`, `nlm sync`, `nlm download`,
`nlm install skill`, and `nlm update skill`.
