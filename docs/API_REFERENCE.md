# Gemini Notebook (formerly Google NotebookLM) MCP API Reference

This document contains detailed API documentation for the internal Gemini Notebook APIs. Only read this file when debugging API issues or adding new features.

**For general project info, see [CLAUDE.md](../CLAUDE.md)**

---

## Python Usage Examples

These examples show how to use the MCP tools programmatically via Python (for developers building with the API). **For end users**: see the main README for natural language examples.

### List Notebooks
```python
notebooks = notebook_list()
```

### Create and Query
```python
# Create a notebook
notebook = notebook_create(title="Research Project")

# Add sources
notebook_add_url(notebook_id, url="https://example.com/article")
notebook_add_text(notebook_id, text="My research notes...", title="Notes")

# Ask questions
result = notebook_query(notebook_id, query="What are the key points?")
print(result["answer"])
```

Queries use a 120-second wall-clock timeout by default. Source-heavy notebooks
may need a larger budget, for example `notebook_query(..., timeout=180)`. If a
query may take longer, use `notebook_query_start(..., timeout=180)` and poll
`notebook_query_status` until it completes. A deadline error includes a retry
hint and the `query_deadline_exceeded` debug code.

### Configure Chat Settings
```python
# Set a custom chat persona with longer responses
chat_configure(
    notebook_id=notebook_id,
    goal="custom",
    custom_prompt="You are an expert data analyst. Provide detailed statistical insights.",
    response_length="longer"
)

# Use learning guide mode with default length
chat_configure(
    notebook_id=notebook_id,
    goal="learning_guide",
    response_length="default"
)

# Reset to defaults with concise responses
chat_configure(
    notebook_id=notebook_id,
    goal="default",
    response_length="shorter"
)
```

**Goal Options:** default, custom (requires custom_prompt), learning_guide
**Response Lengths:** default, longer, shorter

### Get AI Summaries

```python
# Get AI-generated summary of what a notebook is about
summary = notebook_describe(notebook_id)
print(summary["summary"])  # Markdown with **bold** keywords
print(summary["suggested_topics"])  # Suggested report topics

# Get AI-generated summary of a specific source
source_info = source_describe(source_id)
print(source_info["summary"])  # AI summary with **bold** keywords
print(source_info["keywords"])  # Topic chips: ["Medical education", "AI tools", ...]
```

### Get Raw Source Content

```python
# Get raw text content from a source (no AI processing)
# Much faster than notebook_query for bulk content export
content = source_get_content(source_id)
print(content["title"])        # Source title
print(content["source_type"])  # pdf, web_page, youtube, pasted_text, google_docs, etc.
print(content["url"])          # Source URL (if available)
print(content["char_count"])   # Character count
print(content["content"])      # Full raw text

# Example: Export all sources to markdown files
sources = notebook_get(notebook_id)["sources"]
for source in sources:
    content = source_get_content(source["id"])
    with open(f"{content['title']}.md", 'w') as f:
        f.write(content["content"])
```

**Supported source types:** google_docs, google_slides_sheets, pdf, pasted_text, web_page, youtube

### Batch, Cross-Notebook, Pipelines & Tags
```python
# Tag notebooks for organization
tag(action="add", notebook_id="...", tags="ai,research")

# Batch query across tagged notebooks
batch(action="query", query="What are the key findings?", tags="ai")

# Cross-notebook query with aggregated answers
cross_notebook_query(query="Compare approaches", notebook_names="Project A, Project B")

# Batch generate podcasts for all tagged notebooks
batch(action="studio", artifact_type="audio", tags="research", confirm=True)

# Run a multi-step pipeline
pipeline(action="run", notebook_id="...", pipeline_name="ingest-and-podcast", input_url="https://...")

# Find relevant notebooks by tag match
tag(action="select", query="ai research")
```

**Built-in pipelines:** `ingest-and-podcast`, `research-and-report`, `multi-format`

### Sync Stale Drive Sources
```python
# Check which sources need syncing
sources = source_list_drive(notebook_id)

# For very large notebooks, skip freshness checks when you only need the source list
sources = source_list_drive(notebook_id, skip_freshness=True)

# Sync stale sources (after user confirmation)
source_sync_drive(source_ids=["id1", "id2"], confirm=True)
```

### Delete Sources
```python
# Delete a source from notebook (after user confirmation)
source_delete(source_id="source-uuid", confirm=True)
```

### Research and Import Sources
```python
# Start web research (fast mode, ~30 seconds)
result = research_start(
    query="value of ISVs on cloud marketplaces",
    source="web",   # or "drive" for Google Drive
    mode="fast",    # or "deep" for extended research (web only)
    title="ISV Research"
)
notebook_id = result["notebook_id"]

# Poll until complete (built-in wait, polls every 30s for up to 5 min)
# By default, report is truncated to 500 chars to save tokens
# Use compact=False to get full 10,000+ char report and all sources
status = research_status(notebook_id)

# Import all discovered sources
research_import(
    notebook_id=notebook_id,
    task_id=status["research"]["task_id"],
    timeout=600  # Optional: increase for large notebooks (default: 300s)
)

# Or import specific sources by index
research_import(
    notebook_id=notebook_id,
    task_id=status["research"]["task_id"],
    source_indices=[0, 2, 5],  # Import only sources at indices 0, 2, and 5
    timeout=600  # Optional: increase for large notebooks (default: 300s)
)

# Or import only sources cited by the deep research report
research_import(
    notebook_id=notebook_id,
    task_id=status["research"]["task_id"],
    cited_only=True,  # Overrides source_indices when enabled
    timeout=600
)
```

**Research Modes:**
- `fast` + `web`: Quick web search, ~10 sources in ~30 seconds
- `deep` + `web`: Extended research with AI report, ~40 sources in 3-5 minutes
- `fast` + `drive`: Quick Google Drive search, ~10 sources in ~30 seconds

### Generate Audio/Video Overviews
```python
# Create an audio overview (podcast)
result = audio_overview_create(
    notebook_id=notebook_id,
    format="deep_dive",  # deep_dive, brief, critique, debate
    length="default",    # short, default, long
    language="en",
    confirm=True         # Required - show settings first, then confirm
)

# Create a video overview
result = video_overview_create(
    notebook_id=notebook_id,
    format="explainer",      # explainer, brief, cinematic, short
    visual_style="classic",  # auto_select, custom, classic, whiteboard, kawaii, anime, etc.
    focus_prompt="",         # Optional host/content focus text
    visual_style_prompt="",  # Optional custom style text when visual_style="custom"
    language="en",
    confirm=True
)

# Check generation status (takes several minutes)
status = studio_status(notebook_id, artifact_id=result["artifact_id"])
for artifact in status["artifacts"]:
    print(f"{artifact['title']}: {artifact['status']}")

# Rich fields are opt-in and responses are paginated.
detailed = studio_status(notebook_id, include_details=True, limit=20, offset=0)

# Delete an artifact (after user confirmation)
studio_delete(
    notebook_id=notebook_id,
    artifact_id="artifact-uuid",
    confirm=True
)
```

**Audio Formats:** deep_dive (conversation), brief, critique, debate
**Audio Lengths:** short, default, long
**Video Formats:** explainer, brief, cinematic, short (vertical, ~60s, no visual style)
**Video Styles:** auto_select, custom, classic, whiteboard, kawaii, anime, watercolor, retro_print, heritage, paper_craft

For Short videos, language selection is best-effort. The captured RPC uses a
null language slot, so non-English requests are reinforced through the focus
prompt rather than an undocumented payload change.

---

## Base Endpoint

```
POST https://notebook.google.com/_/LabsTailwindUi/data/batchexecute
```

### Gemini Notebook Enterprise

Enterprise uses a project- and location-scoped Cloud NotebookLM endpoint. The
configured base host may be `notebook.cloud.google.com` (current documented
host), `notebooklm.cloud.google.com`, or `vertexaisearch.cloud.google.com` for
older deployments. Set `NOTEBOOKLM_PROJECT_ID` and `NOTEBOOKLM_LOCATION` before
starting the client. `NOTEBOOKLM_PROJECT_ID` is required for Enterprise; the
location defaults to `global`.

For the documented `notebook.cloud.google.com` host, the routes are:

```
POST https://notebook.cloud.google.com/{location}/_/CloudNotebookLmUi/data/batchexecute
POST https://notebook.cloud.google.com/{location}/_/CloudNotebookLmUi/data/google.cloud.notebooklm.v1main.NotebookService/GenerateFreeFormStreamed
POST https://notebook.cloud.google.com/{location}/upload/_/
```

The Enterprise list-notebooks RPC is `rG2vCb` with a project-qualified parent:

```json
["projects/{project}/locations/{location}", null, null, 1]
```

Enterprise streamed-query requests identify the notebook with the resource
name `projects/{project}/locations/{location}/notebooks/{notebook_id}`:

```json
[
  [[["source-id"]]],
  "question",
  {"70000": "projects/{project}/locations/{location}/notebooks/{notebook_id}"}
]
```

These structures are based on a contributor-provided Enterprise web-client
capture and are covered by the Enterprise routing tests. Live validation still
requires access to an Enterprise deployment; record a redacted network capture
when updating them because Google may rotate the internal RPC IDs and paths.

## Request Format

```
Content-Type: application/x-www-form-urlencoded

f.req=<URL-encoded JSON>&at=<CSRF token>
```

The `f.req` structure:
```json
[[["<RPC_ID>", "<params_json>", null, "generic"]]]
```

## URL Query Parameters

| Param | Description |
|-------|-------------|
| `rpcids` | The RPC ID being called |
| `source-path` | Current page path (e.g., `/notebook/<id>`) |
| `bl` | Build label, auto-extracted from page HTML (`cfb2h` key). Override via `NOTEBOOKLM_BL` env var. |
| `f.sid` | Session ID |
| `hl` | Language code (e.g., `en`) |
| `_reqid` | Request counter |
| `rt` | Response type (`c`) |

## Response Format

```
)]}'
<byte_count>
<json_array>
```

- Starts with `)]}'` (anti-XSSI prefix) - MUST be stripped
- Followed by byte count, then JSON
- Multiple chunks may be present

---

## Known RPC IDs

| RPC ID | Purpose | Params Structure |
|--------|---------|------------------|
| `wXbhsf` | List notebooks | `[null, 1, null, [2]]` |
| `rLM1Ne` | Get notebook details | `[notebook_id, null, [2], null, 0]` |
| `CCqFvf` | Create notebook | `[title, null, null, [2], [1,null,null,null,null,null,null,null,null,null,[1]]]` |
| `s0tc2d` | Rename notebook / Configure chat | See s0tc2d section below |
| `WWINqb` | Delete notebook | `[[notebook_id], [2]]` |
| `izAoDd` | Add source (unified) | See source types below |
| `hizoJc` | Get source details | `[["source_id"], [2], [2]]` |
| `yR9Yof` | Check source freshness | `[null, ["source_id"], [2]]` - returns `false` if stale |
| `FLmJqe` | Sync Drive source | `[null, ["source_id"], [2]]` |
| `b7Wfje` | Rename source | `[null, ["source_id"], [[["new_title"]]]]` - path: `/notebook/<notebook_id>` |
| `tGMBJ` | Delete source | `[[["source_id"]], [2]]` - deletion is IRREVERSIBLE |
| `hPTbtc` | Get conversation IDs | `[notebook_id]` |
| `khqZz` | Get conversation turns (full Q&A history) | See "Conversation Turns (khqZz)" below |
| `hT54vc` | User preferences | - |
| `ZwVcOc` | Settings | - |
| `ozz5Z` | Add source v2 (Unified) | See source types below |
| `Ljjv0c` | Start Fast Research | `[["query", source_type], null, 1, "notebook_id"]` |
| `QA9ei` | Start Deep Research | `[null, [1], ["query", source_type], 5, "notebook_id"]` |
| `e3bVqc` | Poll Research Results | `[null, null, "notebook_id"]` |
| `LBwxtb` | Import Research Sources | `[null, [1], "task_id", "notebook_id", [sources]]` |
| `R7cb6c` | Create Studio Content | See Studio RPCs section |
| `gArtLc` | Poll Studio Status | `[[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']` |
| `V5N4be` | Delete Studio Content | `[[2], "artifact_id"]` |
| `rc3d8d` | Rename Studio Artifact | `[["artifact_id", "new_title"], [["title"]]]` |
| `KmcKPe` | Revise Slide Deck | `[[2], artifact_id, [[[0-based_index, "instruction"], ...]]]` |
| `yyryJe` | Generate Mind Map | See Mind Map RPCs section |
| `CYK0Xb` | Save Mind Map | See Mind Map RPCs section |
| `cFji9` | List Mind Maps | `[notebook_id]` |
| `ciyUvf` | Get Suggested Report Formats | `[[2], notebook_id, [[source_id1], ...]]` |
| `VfAZjd` | Get Report Suggestions | `[notebook_id, [2]]` |
| `tr032e` | Get Source Guide | `[[[["source_id"]]]]` |

---

## `s0tc2d` - Notebook Update RPC

This RPC handles multiple notebook update operations based on which array position is populated.

### Rename Notebook

Updates the notebook title.

```python
# Request params
[notebook_id, [[null, null, null, [null, "New Title"]]]]

# Example
["549e31df-1234-5678-90ab-cdef01234567", [[null, null, null, [null, "My New Notebook Name"]]]]

# Response
# Returns updated notebook info
```

### Configure Chat Settings

Configures the notebook's chat behavior - goal/style and response length.

```python
# Request params
[notebook_id, [[null, null, null, null, null, null, null, [[goal_code, custom_prompt?], [response_length_code]]]]]

# chat_settings is at position 7 in the nested array
# Format: [[goal_code, custom_prompt_if_custom], [response_length_code]]

# Example - Default goal + Longer response:
["549e31df-...", [[null, null, null, null, null, null, null, [[1], [4]]]]]

# Example - Custom goal + Default response:
["549e31df-...", [[null, null, null, null, null, null, null, [[2, "You are an expert..."], [1]]]]]

# Example - Learning Guide + Shorter response:
["549e31df-...", [[null, null, null, null, null, null, null, [[3], [5]]]]]
```

### Goal/Style Codes

| Code | Goal | Description |
|------|------|-------------|
| 1 | Default | General purpose research and brainstorming |
| 2 | Custom | Custom prompt (up to 10,000 characters) |
| 3 | Learning Guide | Educational focus with learning-oriented responses |

### Response Length Codes

| Code | Length | Description |
|------|--------|-------------|
| 1 | Default | Standard response length |
| 4 | Longer | Verbose, detailed responses |
| 5 | Shorter | Concise, brief responses |

---

## Source Types (via `izAoDd` RPC)

All source types use the same RPC but with different param structures:

### URL/YouTube Source

**IMPORTANT:** YouTube and regular web URLs use **different positions** in the source_data array!

#### Regular Website URL
```python
source_data = [
    None,
    None,
    [url],  # URL at position 2 for regular websites
    None, None, None, None, None, None, None,
    1
]
params = [[[source_data]], notebook_id, [2], settings]
```

#### YouTube URL
```python
source_data = [
    None,
    None,
    None,  # Position 2 must be None for YouTube
    None, None, None, None,
    [url],  # URL at position 7 for YouTube
    None, None,
    1
]
params = [[[source_data]], notebook_id, [2], settings]
```

**Detection:** Check if URL contains `youtube.com` or `youtu.be` to determine which format to use.

### Pasted Text Source
```python
source_data = [
    None,
    [title, text_content],  # Title and content at position 1
    None,
    2,  # Type indicator at position 3
    None, None, None, None, None, None,
    1
]
params = [[[source_data]], notebook_id, [2], settings]
```

### Google Drive Source
```python
source_data = [
    [document_id, mime_type, 1, title],  # Drive doc at position 0
    None, None, None, None, None, None, None, None, None,
    1
]
params = [[[source_data]], notebook_id, [2], settings]
```

**MIME Types:**
- `application/vnd.google-apps.document` - Google Docs
- `application/vnd.google-apps.presentation` - Google Slides
- `application/vnd.google-apps.spreadsheet` - Google Sheets
- `application/pdf` - PDF files

---

## Query Endpoint (Streaming)

Queries use a **different endpoint** - NOT batchexecute!

```
POST /_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed
```

### Query Request Structure
```python
params = [
    [  # Source IDs - each in nested array
        [[["source_id_1"]]],
        [[["source_id_2"]]],
    ],
    "Your question here",  # Query text
    None,
    [2, None, [1]],  # Config
    "conversation-uuid"  # For follow-up questions
]

f_req = [None, json.dumps(params)]
```

### Query Response
Streaming JSON with multiple chunks:
1. **Thinking steps** - "Understanding...", "Exploring...", etc.
2. **Final answer** - Markdown formatted with citations
3. **Source references** - Links to specific passages in sources

---

## Conversation Turns (`khqZz`)

Discovered via Chrome DevTools capture of the web UI loading a notebook's chat panel
(2026-07-22). This is a `batchexecute` RPC (unlike the streaming query endpoint above)
that fetches the **full Q&A history for a past conversation from the server** — it's
what lets the same chat re-appear after closing and reopening a notebook, and it's what
`nlm chats get` / `chat_get` / `chat_export` use to show real transcripts even on a
fresh CLI invocation or MCP server session (`get_conversation_turns()` in
`core/conversation.py`, wrapping `RPC_GET_CONVERSATION_TURNS`).

Companion to `hPTbtc` (`get_conversation_id`), which only returns the conversation
UUID — `khqZz` is the RPC that returns the actual turn content for that UUID.

### Request
```python
params = [
    [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]],  # boilerplate client-capability descriptor, same shape used by hPTbtc
    None,
    None,
    "conversation-uuid",  # from get_conversation_id()
    20,                   # max turns to return (page size; no pagination implemented yet)
]
```

### Response
```
[[turn, turn, ...], "continuation_token"]
```
Turns are returned **newest-first**, alternating **answer then query** per turn pair
(the same `[answer, None, 2]` / `[query, None, 1]` shape the client already builds
locally in `_build_conversation_history()` for follow-up queries):

- **Answer turn**: `[turn_id, [unix_sec, nanos], 2, None, content]` where
  `content[0] = [answer_text, None, [conv_id, conv_id, num]]` — the answer text is
  nested **one level inside `content[0]`** (`content[0][0]`), not `content[0]` directly.
  The remaining `content` entries (`content[1]`, `content[3]`, ...) carry rich
  formatting/citation spans.
- **Query turn**: `[turn_id, [unix_sec, nanos], 1, "query_text"]`

`get_conversation_turns()` pairs consecutive `(answer, query)` entries, reverses them
to chronological order, and returns `[{"turn": 1, "query": ..., "answer": ...}, ...]` —
the same shape as the local-cache-based `get_conversation_history()`. Only plain
answer/query text is extracted; the rich formatting and citation spans are not yet
parsed. The `continuation_token` for fetching turns beyond the requested `limit` is
not yet used (no pagination).

---

## Research RPCs (Source Discovery)

Gemini Notebook's "Research" feature discovers and suggests sources based on a query. It supports two source types (Web and Google Drive) and two research modes (Fast and Deep).

### Source Types
| Type | Value | Description |
|------|-------|-------------|
| Web | `1` | Searches the public web for relevant sources |
| Google Drive | `2` | Searches user's Google Drive for relevant documents |

### Research Modes
| Mode | Description | Duration | Can Leave Page |
|------|-------------|----------|----------------|
| Fast Research | Quick search, ~10 sources | ~10-30 seconds | No |
| Deep Research | Extended research with AI report, ~40+ sources | 3-5 minutes | Yes |

### `Ljjv0c` - Start Fast Research

Initiates a Fast Research session for either Web or Drive sources.

```python
# Request params
[["query", source_type], null, 1, "notebook_id"]

# source_type: 1 = Web, 2 = Google Drive
# Example (Web):  [["What is OpenShift", 1], null, 1, "549e31df-..."]
# Example (Drive): [["sales strategy documents", 2], null, 1, "549e31df-..."]

# Response
["task_id"]
# Example: ["6837228d-d832-4e5c-89d3-b9aa33ff7815"]
```

### `QA9ei` - Start Deep Research (Web Only)

Initiates a Deep Research session with extended web crawling and AI-generated report.

```python
# Request params
[null, [1], ["query", source_type], 5, "notebook_id"]

# The `5` indicates Deep Research mode
# source_type: 1 = Web (Drive not supported for Deep Research)
# Example: [null, [1], ["enterprise kubernetes trends 2025", 1], 5, "549e31df-..."]

# Response
["task_id", "report_id"]
# Example: ["a02dd39b-94c0-443e-b9e4-9c15ab9016c5", null]
```

### `e3bVqc` - Poll Research Results

Polls for research completion and retrieves results. Call repeatedly until status = 2.

```python
# Request params
[null, null, "notebook_id"]

# Response structure (when completed)
[[[
  "task_id",
  [
    "notebook_id",
    ["query", source_type],
    research_mode,  # 1 = Fast, 5 = Deep
    [
      # Array of discovered sources
      [
        "url",           # Web URL or Drive URL
        "title",         # Source title
        "description",   # AI-generated description
        result_type      # 1 = Web, 2 = Google Doc, 3 = Slides, 8 = Sheets
      ],
      # ... more sources
    ],
    "summary"  # AI-generated summary of sources
  ],
  status  # 1 = in progress, 2 = completed
],
[end_timestamp, nanos],
[start_timestamp, nanos]
]]

# Deep Research also includes a report in the results (long markdown document)
```

**Result Types (in poll response):**
| Type | Meaning |
|------|---------|
| 1 | Web URL |
| 2 | Google Doc |
| 3 | Google Slides |
| 5 | Deep Research Report |
| 8 | Google Sheets |

### `LBwxtb` - Import Research Sources

Imports selected sources from research results into the notebook.

```python
# Request params
[null, [1], "task_id", "notebook_id", [source1, source2, ...]]

# Each source structure:
# Web source:
[null, null, ["url", "title"], null, null, null, null, null, null, null, 2]

# Drive source:
[["document_id", "mime_type", null, "title"], null, null, null, null, null, null, null, null, null, 1]

# Response
# Array of created source objects with source_id, title, metadata
[[source_id, title, metadata, [null, 2]], ...]
```

### Research Flow Summary

```
1. Start Research
   ├── Fast: Ljjv0c with source_type (1=Web, 2=Drive)
   └── Deep: QA9ei with mode=5 (Web only)

2. Poll Results
   └── e3bVqc → repeat until status=2

3. Import Sources
   └── LBwxtb with selected sources

4. Sources appear in notebook → can query them
```

### Important Notes

- **Only one active research per notebook**: Starting a new research cancels any pending results
- **Deep Research runs in background**: User can navigate away after initiation
- **Fast Research blocks navigation**: Must stay on page until complete
- **Drive URLs format**: `https://drive.google.com/a/redhat.com/open?id=<document_id>`
- **Web URLs**: Standard HTTP/HTTPS URLs

---

## Studio RPCs (Audio/Video Overviews)

Gemini Notebook's "Studio" feature generates audio podcasts and video overviews from notebook sources.

### `R7cb6c` - Create Studio Content

Creates both Audio and Video Overviews using the same RPC, distinguished by type code.

#### Audio Overview Request
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        1,                         # STUDIO_TYPE_AUDIO
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None,
        [
            None,
            [
                focus_prompt,      # Focus text (what AI should focus on)
                length_code,       # 1=Short, 2=Default, 3=Long
                None,
                [[source_id1], [source_id2], ...],  # Source IDs (simpler format)
                language_code,     # "en", "es", etc.
                None,
                format_code        # 1=Deep Dive, 2=Brief, 3=Critique, 4=Debate
            ]
        ]
    ]
]
```

#### Video Overview Request
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        3,                         # STUDIO_TYPE_VIDEO
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None, None, None,
        [
            None, None,
            [
                [[source_id1], [source_id2], ...],  # Source IDs
                language_code,     # "en", "es", etc.
                focus_prompt,      # Host/content focus text
                None,
                format_code,       # 1=Explainer, 2=Brief, 3=Cinematic, 4=Short
                visual_style_code,  # 1=Auto, 3=Classic, etc. (null when using custom style text)
                visual_style_prompt  # Present when visual_style="custom"
            ]
        ]
    ]
]
```

**Short format (code 4) — verified via live capture, 2026-06-30:** Short Video
Overviews have no visual style picker, so the inner options list omits
`visual_style_code`/`visual_style_prompt` entirely (matching Cinematic), and
additionally sends `language_code` as `null` plus a trailing flag `1` whose
meaning is undocumented by Google but required for the request to succeed.
Current service behavior adds a best-effort language requirement to
`focus_prompt` for non-English Short requests:
```python
[
    [[source_id1], [source_id2], ...],  # Source IDs
    None,                                # language — always null for Short
    focus_prompt,
    None,
    4,                                   # format_code = Short
    None, None,                          # no visual style
    1,                                   # required trailing flag (unexplained)
]
```

#### Response Structure
```python
# Returns: [[artifact_id, title, type, sources, status, ...]]
# status: 1 = in_progress, 3 = completed
```

### `gArtLc` - Poll Studio Status

Polls for audio/video generation status.

```python
# Request
params = [[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']

# Response Structure
[
    [
        # Artifact Data Array
        [
            artifact_id,       # [0] UUID
            "Title",           # [1] Title
            type_code,         # [2] Type (1=Audio, 3=Video, etc)
            [source_ids],      # [3] Source IDs used
            wait_time_sec,     # [4] Est wait time
            None,              # [5] (Previously thought to be prompt)
            [                  # [6] Custom Prompt / Focus Data
                 null,
                 [
                     "Custom Prompt Text",  # [1][0] The actual prompt text
                     audience_level,        # [1][1] (e.g. 2)
                     ...
                 ]
            ],
            None,              # [7]
            [url_data],        # [8] URL for audio/video (nested)
            ...
        ],
        ... # More artifacts
    ],
    ...
]
```

Artifacts with type code `4` use the nested subtype at `[9][1][0]`:

- `1` = flashcards
- `2` = quiz
- `4` = mind map

Mind map subtype `4` was confirmed from a live `gArtLc` response on 2026-07-14.
Older clients that only distinguish flashcards and quizzes will mislabel these
saved mind maps as flashcards.

### `V5N4be` - Delete Studio Content

Deletes an audio or video overview artifact permanently.

```python
# Request
params = [[2], "artifact_id"]

# Response
[]  # Empty array on success
```

**WARNING:** This action is IRREVERSIBLE. The artifact is permanently deleted.

### `rc3d8d` - Rename Studio Artifact

Renames a studio artifact (audio, video, report, etc.).

```python
# Request
params = [["artifact_id", "New Title"], [["title"]]]

# Response
# Returns the updated artifact data on success
```

**Note:** This RPC was discovered in v0.2.8. The second array `[["title"]]` specifies which field(s) to update.

### `KmcKPe` - Revise Slide Deck

Revises individual slides in an existing slide deck. Creates a **new** artifact — the original is not modified.

#### Request
```python
params = [
    [2],                           # Version/mode indicator (always [2])
    artifact_id,                   # UUID of the existing slide deck
    [
        [                          # Array of slide revision instructions
            [0, "Make the title larger"],   # [0-based slide index, instruction text]
            [2, "Remove the image"],        # Multiple instructions supported
        ]
    ]
]
```

#### Response
Returns the same structure as `R7cb6c` (Create Studio Content):
- `result[0][0]` — New artifact UUID
- `result[0][2]` — Title (original title + " (2)")
- `result[0][4]` — Status code (1 = in_progress, 3 = completed)
- `result[0][20]` — Original artifact UUID

#### Notes
- Slide index is **0-based** (slide 1 = index 0)
- Multiple slides can be revised in one call
- Original deck settings (focus prompt, language, format, length) are preserved
- Poll with `gArtLc` (studio_status) for completion
- Only slide decks support revision (no other artifact types)

### Audio Options

| Option | Values |
|--------|--------|
| **Formats** | 1=Deep Dive (conversation), 2=Brief, 3=Critique, 4=Debate |
| **Lengths** | 1=Short, 2=Default, 3=Long |
| **Languages** | BCP-47 codes, including regional values such as `"es-ES"`, `"es-US"`, and `"es-419"` |

For Audio Overviews, Gemini Notebook has been observed using the region subtag to
select the voice accent. `es` and `es-ES` produce Spain Spanish, while `es-US`
and `es-419` produce Latin-American Spanish. Prompt text does not reliably
override the accent. This is observed behavior and may change upstream.

### Video Options

| Option | Values |
|--------|--------|
| **Formats** | 1=Explainer (comprehensive), 2=Brief, 3=Cinematic, 4=Short (vertical, ~60s) |
| **Visual Styles** | 1=Auto-select, 2=Custom, 3=Classic, 4=Whiteboard, 5=Kawaii, 6=Anime, 7=Watercolor, 8=Retro print, 9=Heritage, 10=Paper-craft (not applicable to Cinematic or Short) |
| **Languages** | BCP-47 codes: "en", "es", "fr", "de", "ja", etc. Short uses best-effort prompt steering because its RPC language slot is null. |

#### Infographic Request
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        7,                         # STUDIO_TYPE_INFOGRAPHIC
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None, None, None, None, None, None, None, None, None,  # 10 nulls
        [[focus_prompt, language, None, orientation_code, detail_level_code, visual_style_code]]  # Options at position 14
    ]
]
```

### Infographic Options

| Option | Values |
|--------|--------|
| **Orientations** | 1=Landscape (16:9), 2=Portrait (9:16), 3=Square (1:1) |
| **Detail Levels** | 1=Concise, 2=Standard, 3=Detailed (BETA) |
| **Visual Styles** | 1=Auto-select, 2=Sketch Note, 3=Professional, 4=Bento Grid, 5=Editorial, 6=Instructional, 7=Bricks, 8=Clay, 9=Anime, 10=Kawaii, 11=Scientific |
| **Languages** | BCP-47 codes: "en", "es", "fr", "de", "ja", etc. |

#### Slide Deck Request
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        8,                         # STUDIO_TYPE_SLIDE_DECK
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None, None, None, None, None, None, None, None, None, None, None,  # 12 nulls
        [[focus_prompt, language, format_code, length_code]]  # Options at position 16
    ]
]
```

### Slide Deck Options

| Option | Values |
|--------|--------|
| **Formats** | 1=Detailed Deck (comprehensive), 2=Presenter Slides (key points) |
| **Lengths** | 1=Short, 3=Default |
| **Languages** | BCP-47 codes: "en", "es", "fr", "de", "ja", etc. |

### Studio Flow Summary

```
1. Create Studio Content
   ├── Audio: R7cb6c with type=1 and audio options
   ├── Video: R7cb6c with type=3 and video options
   ├── Infographic: R7cb6c with type=7 and infographic options
   └── Slide Deck: R7cb6c with type=8 and slide deck options

2. Returns immediately with artifact_id (status=in_progress)

3. Poll Status
   └── gArtLc → repeat until status=3 (completed)

4. When complete, response includes download URLs

5. Delete (optional)
   └── V5N4be with artifact_id → permanently removes content
```

---

## Report RPCs

Reports use the same `R7cb6c` RPC with **type code 2** (STUDIO_TYPE_REPORT).

### Report Request Structure
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        2,                         # STUDIO_TYPE_REPORT
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None, None,
        [
            None,
            [
                "Briefing Doc",           # Report title/format
                "Key insights and quotes", # Short description
                None,
                [[source_id1], [source_id2], ...],  # Source IDs (simpler format)
                "en",                      # Language code
                "Create a comprehensive...",  # Full prompt/instructions
                None,
                True                       # Unknown flag
            ]
        ]
    ]
]
```

### Standard Report Formats

| Format | Description | Prompt Style |
|--------|-------------|--------------|
| **Briefing Doc** | Key insights and important quotes | Comprehensive briefing with Executive Summary |
| **Study Guide** | Short-answer quiz, essay questions, glossary | Educational focus with test prep materials |
| **Blog Post** | Insightful takeaways in readable article format | Engaging, accessible writing style |
| **Create Your Own** | Custom format with user-defined structure | User provides custom prompt |

### `ciyUvf` - Get Suggested Report Formats

Returns AI-generated suggested report topics based on notebook sources.

```python
# Request params
params = [[2], notebook_id, [[source_id1], [source_id2], ...]]

# Response: Array of suggested reports with full prompts
[
    [
        "Strategy Briefing",           # Title
        "An analysis of...",           # Description
        None,
        [[source_ids]],                # Sources
        "Synthesize the provided...",  # Full AI prompt
        2                              # Audience level (1=beginner, 2=advanced)
    ],
    # ... more suggestions
]
```

### `VfAZjd` - Get Notebook Summary and Report Suggestions

Returns an AI-generated summary of the notebook and suggested report topics.

```python
# Request params
[notebook_id, [2]]

# Response structure
[
    [
        "The provided documents explore...",  # AI-generated summary (markdown formatted)
    ],
    [
        [
            [
                "How do generative AI tools...",  # Suggested topic question
                "Create a detailed briefing..."   # Full prompt for report
            ],
            # ... more suggested topics
        ]
    ]
]
```

**Summary format:** Markdown text with **bold** keywords highlighting key themes.

**Use case:** This RPC provides the notebook description shown in the Chat panel when you first open a notebook. Perfect for a `notebook_describe` tool to give users a high-level overview of what a notebook contains.

### `tr032e` - Get Source Guide

Generates an AI summary and keyword chips for a specific source. This is the "Source Guide" feature shown when clicking on a source in the Gemini Notebook UI.

```python
# Request params
params = [[[["source_id"]]]]
# Source ID in deeply nested arrays

# Example
params = [[[["5d318300-1b66-4bf6-ad3a-072c76f8a8eb"]]]]

# Response structure
[
    [
        null,
        [
            "This facilitator's guide outlines a specialized workshop designed to help **medical residents and fellows** leverage **generative artificial intelligence**..."
            # AI-generated summary with **bold** markdown for keywords
        ],
        [
            ["Medical education", "Generative AI tools", "Resident teaching skills", "Educational content creation", "Ethics and risks"]
            # Array of keyword chips
        ],
        []
    ]
]
```

**Response fields:**
- `[0][1][0]`: AI-generated summary (markdown formatted with **bold** keywords)
- `[0][2][0]`: Array of keyword chip strings

**Use case:** Perfect for a `source_describe` tool that provides an AI-generated overview of individual sources, similar to `notebook_describe` for notebooks.

---

## Flashcard RPCs

Flashcards use the same `R7cb6c` RPC with **type code 4** (STUDIO_TYPE_FLASHCARDS).

### Flashcard Request Structure
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        4,                         # STUDIO_TYPE_FLASHCARDS
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None, None, None, None,  # 5 nulls (positions 4-8)
        [
            None,
            [
                1,                     # Unknown (possibly default count)
                None, None, None, None, None,
                [difficulty, card_count]  # [difficulty_code, card_count_code]
            ]
        ]
    ]
]
```

### Flashcard Options

| Option | Values |
|--------|--------|
| **Difficulty** | `easy` (1), `medium` (2), `hard` (3) - MCP tools accept string names |
| **Card Count** | Default count generated by AI |

**Note:** MCP tools (`flashcards_create`, `quiz_create`) accept string difficulty names which are mapped to internal codes via `constants.CodeMapper`.

---

## Quiz RPCs

Quizzes use the same `R7cb6c` RPC with **type code 4** (shared with Flashcards) but with different options structure.

### Quiz Request Structure
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        4,                         # STUDIO_TYPE_FLASHCARDS (shared with Quiz)
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None, None, None, None,  # 5 nulls (positions 4-8)
        [
            None,
            [
                2,                     # Format/variant code (distinguishes Quiz from Flashcards)
                None, None, None, None, None, None,
                [question_count, difficulty]  # [questions, difficulty_level]
            ]
        ]
    ]
]
```

### Quiz Options

| Option | Values |
|--------|--------|
| **Question Count** | Integer (default: 2) |
| **Difficulty** | `easy` (1), `medium` (2), `hard` (3) - MCP tools accept string names |

**Key Difference from Flashcards:** Quiz uses format code `2` at the first position of the options array, while Flashcards use `1`.

**Mind maps share type code 4 too:** newer mind maps are stored as type-4 studio artifacts with format code `4` at `artifact[9][1][0]` (older mind maps live in the notes store via the `cFji9` RPC). The status parser classifies format code 4 as `mind_map`, and downloading one fetches the artifact's interactive HTML (`v9rmvd`) and extracts the mind map JSON (`{"name": ..., "children": [...]}`) from the `data-app-data` attribute — the same mechanism quiz/flashcards use.

---

## Data Table RPCs

Data Tables use the `R7cb6c` RPC with **type code 9** (STUDIO_TYPE_DATA_TABLE).

Excel exports of data tables are returned by the same status RPC with **type
code 10** (`STUDIO_TYPE_DATA_TABLE_XLSX`). Their file metadata is at
`artifact[24]` as `[filename, mime_type, viewer_url, download_url]`. The
download path streams `download_url` as binary XLSX without CSV parsing.

### Data Table Request Structure
```python
params = [
    [2],                           # Config
    notebook_id,                   # Notebook UUID
    [
        None, None,
        9,                         # STUDIO_TYPE_DATA_TABLE
        [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
        None, None, None, None, None, None, None, None, None, None,  # 10 nulls (positions 4-13)
        None, None, None, None,    # 4 more nulls (positions 14-17)
        [
            None,
            [description, language]  # ["Description of table", "en"]
        ]
    ]
]
```

### Data Table Options

| Option | Description |
|--------|-------------|
| **Description** | String describing what data to extract (required) |
| **Language** | Language code (default: "en") |

**Note:** Data table options appear at position 18 in the content array, requiring 14 nulls after the sources.

---

## Mind Map RPCs

Mind Maps use a **two-step process** with separate Generate and Save RPCs.

### Step 1: `yyryJe` - Generate Mind Map

Generates the mind map JSON from sources.

```python
# Request params
params = [
    [[[source_id1]], [[source_id2]], ...],  # Source IDs (nested arrays)
    None, None, None, None,
    ["interactive_mindmap", [["[CONTEXT]", ""]], ""],  # Type identifier
    None,
    [2, None, [1]]  # Config
]

# Response
[
    json_mind_map_string,  # Hierarchical JSON with name/children structure
    None,
    [generation_id1, generation_id2, generation_number]
]
```

### Step 2: `CYK0Xb` - Save Mind Map

Saves the generated mind map to the notebook.

```python
# Request params
params = [
    notebook_id,
    json_mind_map_string,  # The full JSON structure from step 1
    [2, None, None, 5, [[source_id1], [source_id2], ...]],  # Metadata with sources
    None,
    "Mind Map Title"  # Display title
]

# Response
[
    mind_map_id,           # UUID for the saved mind map
    json_mind_map_string,  # The saved JSON structure
    [2, version_id, [timestamp, nanos], 5, [[source_ids]]],  # Metadata
    None,
    "Generated Title"      # AI-generated title
]
```

### `cFji9` - List Mind Maps

Retrieves all existing mind maps for a notebook.

```python
# Request params
[notebook_id]

# Response
[
    [
        [mind_map_id, [
            mind_map_id,
            json_mind_map_string,
            [2, version_id, [timestamp, nanos], 5, [[source_ids]]],
            None,
            "Mind Map Title"
        ]],
        # ... more mind maps
    ],
    [timestamp, nanos]  # Last updated
]
```

### Mind Map JSON Structure

```json
{
  "name": "Root Topic",
  "children": [
    {
      "name": "Category 1",
      "children": [
        { "name": "Subcategory 1.1" },
        { "name": "Subcategory 1.2" }
      ]
    },
    {
      "name": "Category 2",
      "children": [
        { "name": "Subcategory 2.1" },
        {
          "name": "Subcategory 2.2",
          "children": [
            { "name": "Leaf Node" }
          ]
        }
      ]
    }
  ]
}
```

### Mind Map Flow Summary

```
1. Generate Mind Map
   └── yyryJe with source IDs → returns JSON structure

2. Save Mind Map
   └── CYK0Xb with notebook_id, JSON, title → returns saved mind map with ID

3. List Mind Maps (optional)
   └── cFji9 with notebook_id → returns all mind maps
```

---

## Notes RPCs

Notes are saved AI chat responses that appear in the notebook's left panel. They share the same storage structure as mind maps (both use `cFji9` for listing) but are distinguished by their content format.

**Key Differences from Mind Maps:**
- Notes: Plain text content
- Mind Maps: JSON structure with `"children"` or `"nodes"` keys

### `CYK0Xb` - Create Note

Creates a new note in a notebook. Same RPC as Save Mind Map, differs by parameters.

```python
# Request params
params = [
    notebook_id,
    "",           # Empty content (updated separately via UPDATE_NOTE)
    [1],          # Note type identifier
    None,
    "Note Title"  # Display title
]

# Response
[
    [note_id, "Note Title"],  # Note ID and title
]
```

**Note:** After creation, use `cYAfTb` (UPDATE_NOTE) to set the content.

### `cFji9` - List Notes and Mind Maps

Retrieves all notes and mind maps for a notebook. Filter by content type to distinguish.

```python
# Request params
[notebook_id]

# Response
[
    [
        # Regular note
        [note_id, [
            note_id,
            "Note content text",
            [metadata],
            None,
            "Note Title"
        ], status],

        # Mind map (has JSON content)
        [mind_map_id, [
            mind_map_id,
            '{"children": [...]}',  # JSON structure
            [metadata],
            None,
            "Mind Map Title"
        ], status],

        # Deleted item (status = 2 or data is None)
        [deleted_id, None, 2],
    ],
    [timestamp, nanos]  # Last updated
]
```

**Item Structure:**
- `[0]`: Item ID
- `[1]`: Item data (or None if deleted)
  - `[0]`: Item ID (duplicate)
  - `[1]`: Content (text for notes, JSON for mind maps)
  - `[2]`: Metadata
  - `[3]`: Always None
  - `[4]`: Title
- `[2]`: Status (2 = deleted)

**Filtering Notes from Mind Maps:**
```python
for item in items:
    if item[1] is None or (len(item) > 2 and item[2] == 2):
        continue  # Skip deleted items

    content = item[1][1]
    try:
        parsed = json.loads(content)
        if "children" in parsed or "nodes" in parsed:
            # It's a mind map
        else:
            # It's a note
    except (json.JSONDecodeError, TypeError):
        # It's a note (plain text)
```

### `cYAfTb` - Update Note

Updates a note's content and/or title.

```python
# Request params
params = [
    notebook_id,
    note_id,
    [[[
        "Updated note content",
        "Updated Title",
        [],  # Unknown field
        0    # Unknown field
    ]]],
]

# Response
null  # Null on success
```

**Important:** Both notebook_id and note_id are required.

### `AH0mwd` - Delete Note

Soft-deletes a note (clears content, keeps ID). Same RPC as Delete Mind Map.

```python
# Request params
params = [
    notebook_id,
    None,
    [note_id]  # Can delete multiple: [note_id1, note_id2, ...]
]

# Response
null  # Null on success
```

**Note:** This is a soft-delete - the item appears in listings with `status = 2` or `data = None`.

### Notes Workflow

```
1. Create Note
   └── CYK0Xb with notebook_id, title → returns note_id

2. Update Content
   └── cYAfTb with notebook_id, note_id, content, title → returns null

3. List Notes
   └── cFji9 with notebook_id → filter by content type (text vs JSON)

4. Delete Note
   └── AH0mwd with notebook_id, note_id → returns null
```

---

## Studio Type Codes Summary

| Type Code | Feature | RPC |
|-----------|---------|-----|
| 1 | Audio Overview | `R7cb6c` |
| 2 | Report | `R7cb6c` |
| 3 | Video Overview | `R7cb6c` |
| 4 | Flashcards | `R7cb6c` |
| 5 | Quiz | `R7cb6c` (not yet documented) |
| 6 | Data Table | `R7cb6c` (not yet documented) |
| 7 | Infographic | `R7cb6c` |
| 8 | Slide Deck | `R7cb6c` |
| N/A | Mind Map | `yyryJe` + `CYK0Xb` (separate RPCs) |

---

## Key Findings

1. **Filtering is client-side**: The `wXbhsf` RPC returns ALL notebooks. "My notebooks" vs "Shared with me" filtering happens in the browser.

2. **Unified source RPC**: All source types (URL, text, Drive) use the same `izAoDd` RPC with different param structures.

3. **Query is streaming**: The query endpoint streams the AI's thinking process before the final answer.

4. **Conversation support**: Pass a `conversation_id` for multi-turn conversations (follow-up questions).

5. **Rate limits**: Free tier has ~50 queries/day limit.

6. **Research uses same RPC for Web and Drive**: The `Ljjv0c` RPC handles both Web (source_type=1) and Drive (source_type=2) Fast Research. Only the source_type parameter differs.

7. **Deep Research is Web-only**: The `QA9ei` RPC only supports Web sources (source_type=1). Google Drive does not have a Deep Research equivalent.

---

## Drive Source Sync

### Problem
Gemini Notebook doesn't auto-update Google Drive sources when the underlying document changes. Users must manually click each source > "Check freshness" > "Click to sync with Google Drive".

### Solution
The `source_list_drive` and `source_sync_drive` tools automate this process.
For very large notebooks, `source_list_drive(notebook_id, skip_freshness=True)` skips
the per-source freshness RPCs and returns the source list faster, with stale status
reported as unknown.

### Source Metadata Structure (from `rLM1Ne` response)

Each source in the notebook response has this structure:
```python
[
  [source_id],           # UUID for the source
  "Source Title",        # Display title
  [                      # Metadata array
    drive_doc_info,      # [0] null OR [doc_id, version_hash] for Drive/Gemini sources
    byte_count,          # [1] content size (0 for Drive, actual size for pasted text)
    [timestamp, nanos],  # [2] creation timestamp
    [version_uuid, [timestamp, nanos]],  # [3] last sync info
    source_type,         # [4] KEY FIELD: 1=Google Docs, 2=Slides/Sheets, 4=Pasted Text
    null,                # [5]
    null,                # [6]
    null,                # [7]
    content_bytes        # [8] actual byte count (for Drive sources after sync)
  ],
  [null, 2]              # Footer constant
]
```

### Source Types (metadata position 4)
| Type | Meaning | Drive Doc Info | Can Sync |
|------|---------|----------------|----------|
| 1 | **Google Docs** (Documents, including Gemini Notes) | `[doc_id, version_hash]` | **Yes** |
| 2 | **Google Slides/Sheets** (Presentations & Spreadsheets) | `[doc_id, version_hash]` | **Yes** |
| 4 | Pasted text | `null` | No |

---

## How We Discovered This

### Method: Network Traffic Analysis

1. Used Chrome DevTools MCP to automate browser interactions
2. Captured network requests during each action
3. Decoded `f.req` body (URL-encoded JSON)
4. Analyzed response structures
5. Tested parameter variations

### Discovery Session Examples

**Creating a notebook:**
1. Clicked "Create notebook" button via Chrome DevTools
2. Captured POST to batchexecute with `rpcids=CCqFvf`
3. Decoded params: `["", null, null, [2], [1,null,...,[1]]]`
4. Response contained new notebook UUID at index 2

**Adding Drive source:**
1. Opened Add source > Drive picker
2. Double-clicked on a document
3. Captured POST with `rpcids=izAoDd`
4. Decoded: `[[[[doc_id, mime_type, 1, title], null,...,1]]]`
5. Different from URL/text which use different array positions

**Querying:**
1. Typed question in query box, clicked Submit
2. Found NEW endpoint: `GenerateFreeFormStreamed` (not batchexecute!)
3. Streaming response with thinking steps + final answer
4. Includes citations with source passage references

---

## Essential Cookies

The MCP needs these cookies (automatically filtered from the full cookie header):

| Cookie | Purpose |
|--------|---------|
| `SID`, `HSID`, `SSID`, `APISID`, `SAPISID` | Core auth (required) |
| `__Secure-1PSID`, `__Secure-3PSID` | Secure session variants |
| `__Secure-1PAPISID`, `__Secure-3PAPISID` | Secure API variants |
| `OSID`, `__Secure-OSID` | Origin-bound session |
| `__Secure-1PSIDTS`, `__Secure-3PSIDTS` | Timestamp tokens |
| `SIDCC`, `__Secure-1PSIDCC`, `__Secure-3PSIDCC` | Session cookies |

**Important:** Some cookies (PSIDTS, SIDCC, PSIDCC) rotate frequently. Always get fresh cookies from an active Chrome session.

### Token Extraction

**Three ways to get CSRF token and session ID:**

1. **From network request (fastest):**
   - Extracted directly from `get_network_request()` data
   - No page fetch required
   - Saves to cache for reuse

2. **From page fetch (slower first time):**
   - Client fetches `notebook.google.com` using cookies
   - Extracts `SNlM0e` (CSRF) and `FdrFJe` (session ID) from HTML
   - Saves to cache for reuse
   - ~1-2 seconds one-time delay

3. **From cache (instant):**
   - Subsequent requests reuse cached tokens
   - No fetching needed
   - Cache updates automatically when tokens are refreshed

---

## Label Management RPCs

Labels allow users to organize sources into thematic categories. Available when a notebook has 5+ sources. Sources can belong to multiple labels.

**UI operations available:**
- Auto-label (AI generates categories from sources)
- Create a new empty label
- Rename a label
- Set/change an emoji on a label
- Remove a label (sources are preserved, not deleted)
- Move a source to a different label (multi-label assignment via checkboxes)
- Return to flat list view

### `agX4Bc` — Auto-Label / Reorganize / Create Label / List Labels

This RPC handles auto-labeling, force-reorganization, and manual label creation.
The 5th parameter (mode) controls the labeling behavior:

| Mode | Meaning |
|------|---------|
| `[]` | Return existing labels, or auto-generate if none exist |
| `[0]` | Reorganize: only label sources not yet in any label (no confirmation in UI) |
| `[1]` | Reorganize: force-regenerate ALL labels from scratch (UI shows confirmation dialog) |
| `null` + 6th param | Create a new empty label with the given name/emoji |

#### Auto-label all sources (returns existing if already labeled)

```python
# Request params
[[2], notebook_id, null, null, []]

# Example
[[2], "180cfc20-9d9f-4ebf-a5d3-1b50d5593b8b", null, null, []]

# Response: [null, [[label_name, [[src_id], ...], label_id, emoji], ...]]
[null, [
    ["User Tutorials",
     [["0baf49b7-..."], ["86132bc5-..."], ["acd49c62-..."]],
     "0245af0d-2663-40df-96b9-567f7ed1ce6f",
     ""],  # emoji (empty string = no emoji)
    ["Enterprise Use Cases",
     [["845deae5-..."], ["86132bc5-..."], ["98881af4-..."]],
     "286c7cc0-39f3-4349-940f-ea50e34169eb",
     ""],
    # ...
]]
```

#### Reorganize — all sources (replaces existing labels)

```python
# Request params — [1] = force full regeneration
[[2], notebook_id, null, null, [1]]

# Example
[[2], "180cfc20-9d9f-4ebf-a5d3-1b50d5593b8b", null, null, [1]]

# Response: same structure as auto-label — returns the new label set
# NOTE: UI shows a confirmation dialog before sending this request
```

#### Reorganize — unlabeled sources only

```python
# Request params — [0] = only label sources with no existing label assignment
[[2], notebook_id, null, null, [0]]

# Example
[[2], "180cfc20-9d9f-4ebf-a5d3-1b50d5593b8b", null, null, [0]]

# Response: same structure as auto-label — returns the full updated label set
# NOTE: UI fires this immediately without a confirmation dialog
```

#### Create a new empty label

```python
# Request params — note position 5 contains [[label_name, emoji]]
[[2], notebook_id, null, null, null, [[label_name, ""]]]

# Example: create "My New Label" with no emoji
[[2], "180cfc20-...", null, null, null, [["My New Label", ""]]]

# Response: same as auto-label — returns full updated label list with new label
# The new label has null sources and a freshly generated label_id:
[null, [
    # ... existing labels ...
    ["My New Label", null, "a0e1a3d0-bcc4-4619-bcd2-f152c64fe7d8", ""]
]]
```

### `le8sX` — Label Mutation (Rename / Set Emoji / Move Source)

This single RPC handles all label content mutations. The 4th parameter determines the operation type.

#### Rename a label

```python
# Request params
[[2], notebook_id, label_id, [[[new_name]]]]

# Example: rename to "Enterprise Use Cases"
[[2], "180cfc20-...", "286c7cc0-...", [[["Enterprise Use Cases"]]]]

# Response: [] (empty = success)
```

#### Set (or change) an emoji on a label

```python
# Request params — null name + emoji string at position 1
[[2], notebook_id, label_id, [[[null, "🏷️"]]]]

# Example
[[2], "180cfc20-...", "6d7564e6-...", [[[null, "📊"]]]]

# Response: [] (empty = success)
```

#### Move / assign a source to a label

Adds the source to the target label (multi-label — sources can be in multiple labels).

```python
# Request params — null at position 0, source_id list at position 1
[[2], notebook_id, target_label_id, [[null, [[source_id]]]]]

# Example: move source to "Marketing Applications"
[[2], "180cfc20-...", "6d7564e6-...", [[null, [["845deae5-df8a-4c9a-9d11-53b0761823af"]]]]]

# Response: [] (empty = success)
```

### `GyzE7e` — Delete Label(s)

Deletes one or more labels. Sources belonging to the deleted labels are NOT deleted.
If removing a label that contains sources exclusively, reassign them first via `le8sX`.

```python
# Request params — array of label_ids to delete
[[2], notebook_id, [label_id, ...]]

# Example: delete one label
[[2], "180cfc20-...", ["286c7cc0-39f3-4349-940f-ea50e34169eb"]]

# Example: delete multiple labels at once
[[2], "180cfc20-...", ["label-id-1", "label-id-2"]]

# Response: [] (empty = success)
```

### `LQhfEb` — Toggle Source Panel View

Saves the user's preference for label view vs flat list view. Not needed for label management itself, but fired when switching between views.

```python
# Label view (view=1)
[null, notebook_id, [null, [null, 1]], [["notebook_lm_state.saved_source_panel_view"]]]

# List view (view=2)
[null, notebook_id, [null, [null, 2]], [["notebook_lm_state.saved_source_panel_view"]]]

# Response: [] (empty = success)
```

### Remove Label — Two-step Process

The "Remove" operation in the UI (which preserves sources) is a two-step sequence:
1. `le8sX` — Move any sources that would become orphaned to another label
2. `GyzE7e` — Delete the now-empty label

```python
# Step 1: reassign orphaned sources to a different label
le8sX([[2], notebook_id, target_label_id, [[null, [[orphaned_source_id]]]]])

# Step 2: delete the label
GyzE7e([[2], notebook_id, [label_id_to_remove]])
```

---

## User Tier and Usage Limits

### `ozz5Z` — Get User Subscription Tier

Returns the user's current Gemini Notebook subscription tier. Fires on the homepage (`source-path=/`) during page load.

**Captured request params (2026-04-27, `source-path=/`):**
```python
# Inner JSON params sent to the RPC:
[[[[null, "1", 627], [null,null,null,null,null,null,null,null,null,[null,null,2]], 1]]]

# 627 and "1" appear to be hardcoded NotebookLM product/SKU constants.
# The same values appear in the support URL: ?ms=pt:1613;s:627
# path used: source-path=/ (homepage, no notebook context needed)
```

**Captured response (decoded, 2026-04-27):**
```python
# Tier string is at response[0][0][1][0][1][...]["NOTEBOOKLM_TIER_PRO_DASHER_END_USER"]
# Full decoded structure (abbreviated):
[[[[null,"1",627],[[1613,[..., "NOTEBOOKLM_TIER_PRO_DASHER_END_USER", ...]], 0]]]]

# Also contains:
# - "Manage subscription" link
# - Support URL: https://support.google.com/notebooklm/answer/16213268?ms=pt:1613;s:627;vp:9
# - Encoded tokens (session context): "CM0MEO4KICso..." and "CAI="
```

**Known tier strings:**
| Tier String | Plan |
|-------------|------|
| `NOTEBOOKLM_TIER_STANDARD` | Free / Standard |
| `NOTEBOOKLM_TIER_PLUS` | Google AI Plus |
| `NOTEBOOKLM_TIER_PRO` | Google AI Pro |
| `NOTEBOOKLM_TIER_PRO_DASHER_END_USER` | Google Workspace Pro user |
| `NOTEBOOKLM_TIER_ULTRA` | Google AI Ultra |

**Implementation note:** This RPC is dual-mapped in `core/utils.py` as `add_source_v2`. When called
with the homepage params above it returns tier info. When called in a notebook context with different
params it handles the newer source-add flow. Use `source-path=/` and the params above for tier detection.

### `ZwVcOc` — Settings (also fires on homepage)

Also fires on every page load. Returns app settings including what appear to be account-level limits.

**Captured request params (2026-04-27):**
```python
[null, [1, null, null, null, null, null, null, null, null, null, [1]]]
```

**Captured response (decoded, 2026-04-27):**
```python
[[null, [6, 500, 300, 500000, 2], [true, null, null, true, ["en", ...], ...], [[1]], [true, 2, 3, 2]]]

# [6, 500, 300, 500000, 2] — second element — suspected to be account limits:
#   500 = max notebooks (matches Pro tier: 500/user)
#   300 = max sources per notebook (matches Pro tier: 300/notebook)
#   6, 500000, 2 — unknown; could be tier code, storage, or other config
# Not confirmed — needs testing against Standard/Plus/Ultra accounts to validate.
```

### Usage Limits by Tier (from official docs, subject to change)

| Feature | Standard | Plus | Pro | Ultra |
|---------|----------|------|-----|-------|
| Notebooks | 100/user | 200/user | 500/user | 500/user |
| Sources | 50/notebook | 100/notebook | 300/notebook | 600/notebook |
| Chats | 50/day | 200/day | 500/day | 5,000/day |
| Audio Overviews | 3/day | 6/day | 20/day | 200/day |
| Video Overviews | 3/day | 6/day | 20/day | 200/day |
| Cinematic Videos | — | — | 2/day | 20/day |
| Reports | 10/day | 20/day | 100/day | 1,000/day |
| Flashcards | 10/day | 20/day | 100/day | 1,000/day |
| Quizzes | 10/day | 20/day | 100/day | 1,000/day |
| Mind Maps | Unlimited | Unlimited | Unlimited | Unlimited |
| Deep Research | 10/month | 3/day | 20/day | 200/day |
| Data Tables | Limited | More | Higher | Highest |
| Infographics | Limited | More | Higher | Highest |
| Slide Decks | Limited | More | Higher | Highest |

**Notes:**
- Auto-generated artifacts (on first source add) do NOT count toward limits
- **Superseded for chat and Studio as of 2026-09-02** — see the compute-based
  windows below. The per-notebook and per-source structural caps still apply.

### `EylDcb` — Get Remaining Usage (compute windows)

On 2026-09-02 Gemini Notebook replaced fixed daily caps for chat and Studio with
a compute-based allowance. Consumption depends on prompt complexity and the
features used, not on a count of requests, so the client cannot derive what is
left by counting its own calls. This RPC reports it directly. Fires when the
usage dialog is opened from the Settings menu.

**Captured request params (2026-09-12):**
```python
# The standard RPC header is the only parameter:
[[2, null, [1], [1, null, null, null, null, null, null, null, null, null, [1, 3]]]]
```

**Captured response (decoded, 2026-09-12):**
```python
[1,
 [[null, null, null, null, 2, [1789697670, 16986000], 8.703406947222222, 91.29659305277778],
  [null, null, null, null, 1, [1789200870, 16877000], null, 100]],
 null,
 [[1, true, 6, 3, 1, 11.177083333333334], ...]]   # 24 entries, appears to be recent activity
```

Each entry in `response[1]` describes one window:

| Index | Meaning |
|-------|---------|
| 4 | Window type: `1` = short rolling window (~5h), `2` = weekly window |
| 5 | Reset time as `[epoch_seconds, nanoseconds]` |
| 6 | Percent of the allowance **used**; `null` when nothing has been consumed |
| 7 | Percent of the allowance **remaining** |

**Index 6 is "used" and index 7 is "remaining"**, confirmed two ways: the web
dialog read "0% used" while the payload carried `100`, and a partly consumed
account returned `8.703406947222222` beside `91.29659305277778`, which sum to
exactly `100`.

**⚠️ The two entries are NOT returned in a stable order.** Observed as `[2, 1]`
in one call and `[1, 2]` in the next, for the same account. Always select a
window by its type code at index 4; reading by position silently swaps the
5-hour budget with the weekly one.

**⚠️ An expired session is not an exhausted quota.** When the saved session has
aged out, this RPC returns RPC error code 16 (`UNAUTHENTICATED`) and `ozz5Z`
returns a well-formed but empty entitlement. Neither may be read as "out of
quota" or as a free-tier account. Run `nlm auth refresh` and retry.

**The `authuser` query parameter has no effect here.** Omitting it and passing
`0`, `1` or `2` all returned byte-identical payloads for the same account.

**Implementation:** `core/usage.py` (`UsageMixin`), `services/usage.py`,
`nlm usage`, MCP tool `usage_get`.
