# MCP Guide

Complete reference for the Gemini Notebook (formerly Google NotebookLM) MCP server — **43 tools** for AI assistants.

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
| `notebook_query_start` | Start a query asynchronously for large notebooks that may time out |
| `notebook_query_status` | Poll an async query started with `notebook_query_start` |
| `chat_configure` | Set chat goal and response length |

### Chat Sessions (3 tools)

| Tool | Description |
|------|-------------|
| `chat_list` | List chat sessions for a notebook |
| `chat_get` | Get full transcript of a chat session (defaults to latest) |
| `chat_export` | Export a chat transcript to Markdown or JSON |

### Studio Content (4 tools)

| Tool | Description |
|------|-------------|
| `studio_create` | **Unified** - Create any artifact type |
| `studio_status` | Check generation progress |
| `studio_delete` | Delete artifact (requires `confirm=True`) |
| `studio_revise` | Revise slides in existing deck (requires `confirm=True`) |

**`studio_create` artifact types:**
- `audio` - Podcast (formats: deep_dive, brief, critique, debate)
- `video` - Video overview (formats: explainer, brief, cinematic, short)
- `report` - Text report (Briefing Doc, Study Guide, Blog Post)
- `quiz` - Multiple choice quiz
- `flashcards` - Study flashcards
- `mind_map` - Visual mind map
- `slide_deck` - Presentation slides
- `infographic` - Visual infographic
- `data_table` - Structured data table

### Downloads (2 tools)

| Tool | Description |
|------|-------------|
| `download_artifact` | **Unified** - Download any artifact type |
| `download_all_artifacts` | Download every completed artifact of a notebook — or every notebook with `all_notebooks=True` — into per-notebook folders |

**`download_artifact` types:**
`audio`, `video`, `report`, `mind_map`, `slide_deck`, `infographic`, `data_table`, `quiz`, `flashcards`

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
| `refresh_auth` | Reload auth tokens |
| `save_auth_tokens` | Save cookies (fallback method) |

### Server (1 tool)

| Tool | Description |
|------|-------------|
| `server_info` | Get version and check for updates |

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
| `pipeline` | **Unified** — List or run multi-step workflows (action: list, run) |

**`pipeline` actions:**
```python
pipeline(action="list")  # List available pipelines
pipeline(action="run", notebook_id="...", pipeline_name="ingest-and-podcast", input_url="https://...")
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
6. download_artifact(notebook_id, artifact_type="audio", output_path="podcast.mp3")
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
| `NOTEBOOKLM_BASE_URL` | Override base URL for Enterprise/Workspace (default: `https://notebook.google.com`) |
| `NOTEBOOKLM_DOWNLOAD_DIR` | Optional directory boundary for artifact downloads. Unset preserves the default behavior. |
| `NOTEBOOKLM_ALLOWED_FILE_DIRS` | Optional OS-separated list of directories allowed for local file sources. Unset means unrestricted. |
| `NOTEBOOKLM_DISABLED_GROUPS` | Comma-separated tool groups to hide (see [Selective tool exposure](#selective-tool-exposure)) |
| `NOTEBOOKLM_DISABLED_TOOLS` | Comma-separated individual tools to hide |
| `NOTEBOOKLM_ENABLED_TOOLS` | Comma-separated tools to re-enable, overriding the two above |

---

## Context Window Tips

This MCP has **43 tools** which consume context. Best practices:

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

The easiest way to configure any tool is with `nlm setup`:

```bash
nlm setup add claude-code       # Claude Code
nlm setup add gemini            # Gemini CLI
nlm setup add github-copilot    # GitHub Copilot
nlm setup add cursor            # Cursor
nlm setup add windsurf          # Windsurf
nlm setup add json              # Any other tool (interactive JSON generator)
```

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
