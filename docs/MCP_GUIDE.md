# MCP Guide

Complete reference for the Gemini Notebook (formerly Google NotebookLM) MCP server — **55 tools** for AI assistants.

## Installation

```bash
# Install the package
uv tool install notebooklm-mcp-cli

# Add to Claude Code
claude mcp add --scope user gemini-notebook-mcp notebooklm-mcp

# Add to Gemini CLI
gemini mcp add --scope user gemini-notebook-mcp notebooklm-mcp
```

> **Server naming:** Use `gemini-notebook-mcp` as the server name when
> registering with your agent. The executable remains `notebooklm-mcp`.
> If you have a legacy
> browser-automation Gemini Notebook MCP installed under a different name
> (e.g. `notebooklm`), remove that one first — agents like Hermes get
> confused when two servers expose overlapping tool names
> (`notebook_create`, `source_add`, `notebook_query`, …).
>
> See the [Migrating from another Gemini Notebook MCP](GETTING_STARTED.md#migrating-from-another-notebooklm-mcp)
> section in the Getting Started guide for the full step-by-step.

## Authentication

Before using MCP tools, authenticate:

```bash
nlm login
```

Or use the standalone auth tool:
```bash
nlm login
```

A new profile asks whether to store the login **protected** (OS keystore, recommended) or as a plain file before the browser opens. To use a different Google account from inside an AI app, use the `profile` tool (see [Profiles & Aliases](#profiles--aliases-2-tools)).

---

## Tool Reference

### Notebooks (6 tools)

| Tool | Description |
|------|-------------|
| `notebook_list` | List all notebooks |
| `notebook_create` | Create new notebook |
| `notebook_get` | Get notebook details with sources |
| `notebook_describe` | Get AI summary and suggested topics |
| `notebook_rename` | Rename a notebook |
| `notebook_delete` | Delete notebook (requires `confirm=True`) |

### Sources (7 tools)

| Tool | Description |
|------|-------------|
| `source_add` | **Unified** - Add URL, text, file, or Drive source |
| `source_list_drive` | List sources with Drive freshness status; use `skip_freshness=True` for large notebooks when freshness is not needed |
| `source_sync_drive` | Sync stale Drive sources |
| `source_delete` | Delete source (requires `confirm=True`) |
| `source_describe` | Get AI summary with keywords |
| `source_get_content` | Get raw text content |
| `source_rename` | Rename a source in a notebook |

**Source URLs:** CLI `nlm source list --json` and `nlm source get --json` return
URLs for web and YouTube sources. The current MCP `source_list_drive` and
`source_get_content` responses do not expose a `url` field. Use the CLI when
the original source URL is required; do not infer it from transcript text.

**`source_list_drive` parameters:**
```python
source_list_drive(
    notebook_id="...",
    skip_freshness=False,  # True skips per-source freshness API calls for faster listing
)
```

**`source_add` parameters:**
```python
source_add(
    notebook_id="...",
    source_type="url",        # url | text | file | drive
    url="https://...",        # for source_type=url
    text="...",               # for source_type=text
    title="...",              # optional title
    file_path="/path/to.pdf", # for source_type=file
    document_id="...",        # for source_type=drive
    doc_type="doc",           # doc | slides | sheets | pdf
    wait=True,                # wait for processing to complete
    wait_timeout=120.0        # seconds to wait
)
```

### Querying (4 tools)

| Tool | Description |
|------|-------------|
| `notebook_query` | Ask AI about sources in notebook |
| `notebook_query_start` | Start a query asynchronously for source-heavy notebooks or long-running questions |
| `notebook_query_status` | Poll an async query started with `notebook_query_start` |
| `chat_configure` | Set chat goal and response length |

Queries use a 120-second wall-clock budget by default. Source-heavy notebooks
can take longer than that; retry with `timeout=180` (or another value suited
to the notebook). For longer operations, use `notebook_query_start` and poll
`notebook_query_status` until it reports `completed` or `error`. A timeout
returns a structured error with a retry hint rather than an uninformative
transport failure.

### Chat Sessions (5 tools)

| Tool | Description |
|------|-------------|
| `chat_list` | List chat sessions for a notebook |
| `chat_get` | Get full transcript of a chat session (defaults to latest) |
| `chat_export` | Export a chat transcript to Markdown or JSON |
| `chat_save_to_note` | Save a chat (or one turn) as a Note in the notebook |
| `chat_delete` | Permanently delete all chat history for a notebook (requires `confirm=True`) |

### Studio Content (8 tools)

| Tool | Description |
|------|-------------|
| `studio_create` | **Unified** - Create any artifact type |
| `studio_status` | Check generation progress |
| `studio_delete` | Delete artifact (requires `confirm=True`) |
| `studio_revise` | Revise slides in existing deck (requires `confirm=True`) |
| `report` | **Unified** - Interactive report elements: `action=get` (markdown + elements), `elements` (list; optional `wait_for`, `include_content`), `generate` (validate a plan; runs with `confirm=True`) |

**`studio_create` artifact types:**
- `audio` - Podcast (formats: deep_dive, brief, critique, debate)
- `video` - Video overview (formats: explainer, brief, cinematic, short)
- `report` - Report (Briefing Doc, Study Guide, Blog Post, or **Interactive**)
- `quiz` - Multiple choice quiz
- `flashcards` - Study flashcards
- `mind_map` - Visual mind map
- `slide_deck` - Presentation slides
- `infographic` - Visual infographic
- `data_table` - Structured data table

**Interactive reports (type 11):** create with
`studio_create(artifact_type="report", report_format="Interactive", report_template="learning_overview", custom_prompt="...", confirm=True)`.
The report weaves Studio elements (audio, video, mind map, infographic,
flashcards, slide deck, quiz) into a single browsable document as recommended
placeholders:

```python
# 1. Create interactive report
studio_create(notebook_id, artifact_type="report", report_format="Interactive",
              custom_prompt="Summarize the key ideas with a quiz", confirm=True)
# ... poll studio_status until the artifact status is "completed" ...

# 2. Read report and list suggested elements
report(notebook_id, artifact_id, action="get")                 # markdown + element list
listing = report(notebook_id, artifact_id, action="elements")  # ids, types, sections, settings

# 3. Generation: validate the plan first (no confirm), then run it
plan = [
    {"element_id": "el-1", "settings": {"difficulty": "hard", "question_amount": "more"}},
    {"element_id": "el-2", "steering_prompt": "Custom anchored prompt"},
]
preview = report(notebook_id, artifact_id, action="generate", plan=plan)
# Show preview to user; after approval:
batch_result = report(notebook_id, artifact_id, action="generate", plan=plan, confirm=True)

# 4. Bounded wait and inline review content
results = report(
    notebook_id,
    artifact_id,
    action="elements",
    wait_for=["el-1", "el-2"],
    timeout=600,
    include_content=True,
)
```

Omit `steering_prompt` to use the element card's description (same as a plain
"Generate" in the UI), or pass your own to steer the element.

### Downloads (2 tools)

| Tool | Description |
|------|-------------|
| `download_artifact` | **Unified** - Download any artifact type |
| `download_all_artifacts` | Download every completed artifact of a notebook — or every notebook with `all_notebooks=True` — into per-notebook folders |

**`download_artifact` types:**
`audio`, `video`, `report`, `mind_map`, `slide_deck`, `infographic`, `data_table`, `data_table_xlsx`, `quiz`, `flashcards`

### Exports (1 tool)

| Tool | Description |
|------|-------------|
| `export_artifact` | Export to Google Docs/Sheets |

### Research (3 tools)

| Tool | Description |
|------|-------------|
| `research_start` | Start web/Drive research |
| `research_status` | Poll research progress |
| `research_import` | Import discovered sources (`timeout` and `cited_only` supported) |

### Notes (1 unified tool)

| Tool | Description |
|------|-------------|
| `note` | **Unified** - Manage notes (action: list, create, update, delete) |

**`note` actions:**
```python
note(notebook_id, action="list")             # List all notes
note(notebook_id, action="create", content="...", title="...")
note(notebook_id, action="update", note_id="...", content="...")
note(notebook_id, action="delete", note_id="...", confirm=True)
```

### Labels (1 tool)

| Tool | Description |
|------|-------------|
| `label` | **Unified** - Manage source labels (action: auto, list, reorganize, create, rename, set_emoji, move_source, delete) |

**`label` actions:**
```python
label(notebook_id="abc", action="auto")           # AI auto-labels all sources
label(notebook_id="abc", action="list")           # List current labels
label(notebook_id="abc", action="reorganize", unlabeled_only=True)
label(notebook_id="abc", action="create", name="Research", emoji="📚")
label(notebook_id="abc", action="move_source", label_id="...", source_id="...")
label(notebook_id="abc", action="delete", label_id="...", confirm=True)
```

### Collections (5 tools)

Native collections group whole notebooks on the NotebookLM home page (distinct
from source labels inside a notebook).

| Tool | Description |
|------|-------------|
| `collection_list` | List all collections with their notebook IDs and emoji |
| `collection_create` | Create a collection, optionally with an initial notebook list |
| `collection_edit` | Rename a collection and/or replace its notebook list |
| `collection_set_emoji` | Set or clear the collection emoji (pass `""` to clear) |
| `collection_delete` | Delete a collection (requires `confirm=True`); notebooks are not deleted |

**Examples:**
```python
collection_create(name="Client work", notebook_ids=["abc123"])
collection_edit(collection_id="...", name="Current clients")
collection_edit(collection_id="...", notebook_ids=["abc123", "def456"])  # complete list
collection_set_emoji(collection_id="...", emoji="📁")
collection_delete(collection_id="...", confirm=True)
```

`collection_edit` accepts the complete notebook list and sends only what
changed. An unknown `collection_id` raises before anything is written.

### Sharing (4 tools)

| Tool | Description |
|------|-------------|
| `notebook_share_status` | Get sharing settings |
| `notebook_share_public` | Enable/disable public link |
| `notebook_share_invite` | Invite collaborator by email |
| `notebook_share_batch` | Invite multiple collaborators in a single request |

### Auth (2 tools)

| Tool | Description |
|------|-------------|
| `refresh_auth` | Validate/reload tokens or recover a saved session; optional `profile` targets a named account without switching the active account (File and Protected storage) |
| `save_auth_tokens` | Save cookies (fallback method) |

### Profiles & Aliases (2 tools)

| Tool | Description |
|------|-------------|
| `profile` | **Unified** — list saved accounts, show storage status, switch account (action: list, status, switch) |
| `alias` | **Unified** — short names for notebook IDs (action: list, get, set, delete); every `notebook_id` accepts an alias |

```python
profile(action="list")                                   # accounts, storage mode, which is active
profile(action="switch", name="personal")                # this MCP server, until it restarts
profile(action="switch", name="work", make_default=True) # ALSO the saved default (CLI + future sessions)
```

A switch applies to the whole MCP server process. Apps that share one server across chats (Claude Desktop, CoWork) apply it to every open chat until you quit the app, so while a switch is active each tool result carries an `active_profile_note`. If the server was started with `NOTEBOOKLM_COOKIES`, switching is refused because those cookies override saved profiles. Aliases are shared across all profiles.

### Server (1 tool)

| Tool | Description |
|------|-------------|
| `server_info` | Get version, update check, `storage_warning` diagnostic, and the saved profiles with their storage mode |

`server_info` returns server metadata, update availability, and an optional `storage_warning` field. If credential storage has an unresolved conflict, an unfinished migration marker, or an inaccessible keystore, `storage_warning` provides clear instructions on which `nlm auth storage` command to run.

### Batch & Cross-Notebook (2 tools)

| Tool | Description |
|------|-------------|
| `batch` | **Unified** — Batch operations across multiple notebooks (action: query, add_source, create, delete, studio) |
| `cross_notebook_query` | Query multiple notebooks and get aggregated answers with per-notebook citations |

**`batch` actions:**
```python
batch(action="query", query="What are the key findings?", notebook_names="AI Research, Dev Tools")
batch(action="add_source", source_url="https://...", tags="ai,research")
batch(action="create", titles="Project A, Project B, Project C")
batch(action="delete", notebook_names="Old Project", confirm=True)
batch(action="studio", artifact_type="audio", tags="research", confirm=True)
```

**`cross_notebook_query`:**
```python
cross_notebook_query(query="Compare approaches", notebook_names="Notebook A, Notebook B")
cross_notebook_query(query="Summarize", tags="ai,research")
cross_notebook_query(query="Everything", all=True)
```

### Pipelines (1 tool)

| Tool | Description |
|------|-------------|
| `pipeline` | **Unified** — List, run or create multi-step workflows (action: list, run, create) |

**`pipeline` actions:**
```python
pipeline(action="list")  # List available pipelines
pipeline(action="run", notebook_id="...", pipeline_name="ingest-and-podcast", input_url="https://...")
pipeline(action="create", pipeline_name="mine", description="...", steps=[{"action": "notebook_query", "params": {"query": "Summarize"}}])
```

**Built-in pipelines:** `ingest-and-podcast`, `research-and-report`, `multi-format`

### Tags & Smart Select (1 tool)

| Tool | Description |
|------|-------------|
| `tag` | **Unified** — Tag notebooks and find relevant ones (action: add, remove, list, select) |

**`tag` actions:**
```python
tag(action="add", notebook_id="...", tags="ai,research,llm")
tag(action="remove", notebook_id="...", tags="ai")
tag(action="list")  # List all tagged notebooks
tag(action="select", query="ai research")  # Find notebooks by tag match
```

---

## Example Workflows

### Research → Podcast

```
1. research_start(query="AI trends 2026", mode="deep")
2. research_status(notebook_id, auto_import=True)  # waits up to 15 min, imports automatically
# Or review sources first, then import manually:
2a. research_status(notebook_id)  # waits up to 15 min, returns next_action hint
2b. research_import(notebook_id, task_id, cited_only=True, timeout=600)  # optional cited subset
4. studio_create(notebook_id, artifact_type="audio", confirm=True)
5. studio_status(notebook_id, artifact_id=created_artifact_id)  # poll one artifact
6. download_artifact(notebook_id, artifact_type="audio", output_path="podcast.m4a")
```

`studio_status` returns lean fields and at most 20 artifacts by default. Poll a
new artifact with `artifact_id`, page large notebooks with `limit`/`offset`, and
set `include_details=True` only when prompts, source IDs, report content, or media
details are required.

### Add Sources with Wait

```
source_add(notebook_id, source_type="url", url="https://...", wait=True)
# Returns when source is fully processed and ready for queries
```

### Generate Study Materials

```
studio_create(notebook_id, artifact_type="quiz", question_count=10, confirm=True)
studio_create(notebook_id, artifact_type="flashcards", difficulty="hard", confirm=True)
studio_create(notebook_id, artifact_type="report", report_format="Study Guide", confirm=True)
studio_create(notebook_id, artifact_type="audio", language="es-419", confirm=True)
```

For Audio Overviews, Gemini Notebook has been observed using BCP-47 region
subtags to select the voice accent. `es` and `es-ES` produce Spain Spanish,
while `es-US` and `es-419` produce Latin-American Spanish. The generation
prompt does not reliably override the accent. Treat this as observed behavior,
not a guaranteed API contract.

### Tag, Batch & Cross-Notebook

```
# Tag notebooks for organization
tag(action="add", notebook_id="abc", tags="ai,research")
tag(action="add", notebook_id="def", tags="ai,product")

# Find relevant notebooks
tag(action="select", query="ai research") 

# Query across tagged notebooks
cross_notebook_query(query="What are the main conclusions?", tags="ai")

# Batch generate podcasts for all tagged notebooks
batch(action="studio", artifact_type="audio", tags="ai", confirm=True)
```

### Pipeline Automation

```
# List available pipelines
pipeline(action="list")

# Run a full ingest-and-podcast workflow
pipeline(action="run", notebook_id="abc", pipeline_name="ingest-and-podcast", input_url="https://example.com")
```

---

## Configuration

> Planning to connect from Claude web/mobile or expose the server over a
> network? Read [Remote MCP Deployment](REMOTE_MCP.md) first. HTTP transport
> support does not provide HTTPS, caller authentication, per-user Gemini Notebook
> accounts, or remote file transfer.

### MCP Server Options

| Flag | Description | Default |
|------|-------------|---------|
| `--transport` | Protocol (stdio, http, sse) | stdio |
| `--port` | Port for HTTP/SSE | 8000 |
| `--debug` | Enable verbose logging | false |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `NOTEBOOKLM_MCP_TRANSPORT` | Transport type |
| `NOTEBOOKLM_MCP_PORT` | HTTP/SSE port |
| `NOTEBOOKLM_MCP_DEBUG` | Enable debug logging |
| `NOTEBOOKLM_HL` | Interface language and default artifact locale, including regional BCP-47 values such as `es-419` (default: en) |
| `NOTEBOOKLM_QUERY_TIMEOUT` | Query timeout (seconds) |
| `NOTEBOOKLM_ASYNC_QUERY_MAX_INFLIGHT` | Maximum concurrent `notebook_query_start` workers (default: 8; minimum: 1) |
| `NOTEBOOKLM_BASE_URL` | Override base URL for Enterprise/Workspace (default: `https://notebooklm.google.com`) |
| `NOTEBOOKLM_PROJECT_ID` | Required GCP project ID or number for Gemini Notebook Enterprise |
| `NOTEBOOKLM_LOCATION` | Enterprise location/multi-region (`global`, `us`, or `eu`; default: `global`) |
| `NOTEBOOKLM_DOWNLOAD_DIR` | Directory MCP artifact downloads are confined to. Unset defaults to `~/Downloads/gemini-notebook`, or `~/.notebooklm-mcp-cli/downloads/` where no `~/Downloads` exists. Also bounds CLI downloads when set. |
| `NOTEBOOKLM_ALLOWED_FILE_DIRS` | Optional OS-separated list of directories allowed for local file sources. Unset means unrestricted. |
| `NOTEBOOKLM_DISABLED_GROUPS` | Comma-separated tool groups to hide (see [Selective tool exposure](#selective-tool-exposure)) |
| `NOTEBOOKLM_DISABLED_TOOLS` | Comma-separated individual tools to hide |
| `NOTEBOOKLM_ENABLED_TOOLS` | Comma-separated tools to re-enable, overriding the two above |

---

## Context Window Tips

This MCP has **55 tools** which consume context. Best practices:

- **Disable when not using**: In Claude Code, use `@gemini-notebook-mcp` to toggle
- **Hide tools you don't need**: See [Selective tool exposure](#selective-tool-exposure) below to expose only a subset
- **Use unified tools**: `source_add`, `studio_create`, `download_artifact`, `download_all_artifacts` handle multiple operations each
- **Poll wisely**: Use `studio_status` sparingly - artifacts take 1-5 minutes

### Selective tool exposure

Gating is opt-in: with no configuration all tools are visible. To reduce context,
hide tools by group or by name via environment variables. Tools are hidden rather
than removed, so no code changes are needed.

Resolution order (later wins): `NOTEBOOKLM_DISABLED_GROUPS`, then
`NOTEBOOKLM_DISABLED_TOOLS`, then `NOTEBOOKLM_ENABLED_TOOLS`.

```bash
# Query-first setup: hide mutating groups, keep read + chat tools
export NOTEBOOKLM_DISABLED_GROUPS="notebooks_manage,sources_manage,studio,research,sharing,notes"

# Hide one extra tool, but keep studio_status from an otherwise-hidden group
export NOTEBOOKLM_DISABLED_TOOLS="tag"
export NOTEBOOKLM_ENABLED_TOOLS="studio_status"
```

Available groups: `notebooks_read`, `notebooks_manage`, `sources_read`,
`sources_manage`, `chat`, `query_multi`, `organization`, `automation`, `notes`,
`auth`, `server`, `sharing`, `research`, `studio`.

Unknown group names are ignored. Changes take effect on server restart.

---

## IDE Configuration

The easiest way to configure supported tools is with the guided wizard:

```bash
nlm setup
```

Choose **Show my tools' status** to see what is connected, **Add the MCP to
my tools/agents** to connect detected clients (nothing is pre-selected; entries
still using the old `notebooklm-mcp` name are offered under **Needs a fix** and
renamed to `gemini-notebook-mcp`), **Add the skill to my tools/agents** for the
optional skill (including an upload file for Claude Desktop Chat/Cowork and
claude.ai), **Remove an MCP or skill**, **Credential protection** (protect or
restore your saved logins), or **Copy MCP setup for a tool not
listed** to copy a config snippet. Esc goes back from any screen. MCP setup
defaults to the app/user-level configuration. The optional skill defaults to
all projects (user level); project-level installation targets the current
folder. Codex CLI
and the ChatGPT desktop app share one MCP configuration on the same host.
GitHub Copilot uses the VS Code user profile in the wizard; the direct command
without `--scope user` targets the current workspace.

<details>
<summary>Manual configuration</summary>

### Claude Code
```bash
claude mcp add --scope user gemini-notebook-mcp notebooklm-mcp
```

### Cursor
Add to `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "gemini-notebook-mcp": {
      "command": "/path/to/notebooklm-mcp"
    }
  }
}
```

### GitHub Copilot / VS Code
Add to `.vscode/mcp.json`:
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

### Gemini CLI
```bash
gemini mcp add --scope user gemini-notebook-mcp notebooklm-mcp
```

</details>

Experimental passage retrieval: see [Native source search](native-source-search-experimental.md). The source_search tool is disabled by default.
