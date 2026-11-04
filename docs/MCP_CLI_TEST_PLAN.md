# Gemini Notebook (formerly Google NotebookLM) MCP - Comprehensive Test Plan

**Purpose:** Verify all **54 MCP tools** work correctly.

**Version:** 2.7 (Updated 2026-09-27 - synchronized current MCP surface)

**Changes from v2.6:**
- Current tool count: 54 tools — adds `profile`, `alias` and `chat_save_to_note`, plus `pipeline` create and profile info in `server_info` (v0.15.0).

**Historical changes from v2.1:**
- The test plan previously covered 39 tools, including consolidated notes, labels, async query, batch, pipeline, tags, and server_info.

**Historical changes from v1:**
- Tools were consolidated from 45+ to 29 (-36%) before the current 43-tool surface.
- `source_add(source_type=...)` replaces 4 source tools
- `studio_create(artifact_type=...)` replaces 9 creation tools
- `download_artifact(artifact_type=...)` replaces 9 download tools

**Prerequisites:**
- MCP server installed: `uv cache clean && uv tool install --force .`
- Valid authentication cookies saved
- **Restart IDE MCP server** after installation

---

## Automated Testing with AI Tools

**Simply ask your AI assistant to:**
```
Run the automated tests from docs/MCP_TEST_PLAN.md. For the Drive sync test,
pause before checking freshness, ask me to make a change to the doc, then
verify both staleness detection and sync functionality work correctly.
```

### How Automation Works

1. **Execute tests sequentially** - Run through each test group automatically
2. **Track progress** - Use a todo list to show what's being tested
3. **Pause for user input** - Stop at Drive sync test to ask you to modify a document
4. **Report results** - Provide a comprehensive summary of all tests

---

## Test Group 1: Authentication & Basic Operations

### Test 1.1 - Refresh Auth
**Tool:** `refresh_auth`
**CLI:** `nlm login --check` (validates tokens)

**Prompt:**
```
Refresh authentication tokens for NotebookLM.
```

**Expected:** Success message with auth status.

---

### Authentication regressions (#379, #380, #381)

Run `uv run pytest tests/test_auth_open_issues.py`.

- Both page parsers must preserve the minus sign in `FdrFJe` and `f.sid` session IDs.
- An HTTP 200 page containing `landing-header-signin` must report expired authentication
  before attempting token extraction or writing a page-structure debug dump.
- In isolated file-mode storage, writing tokens from a stale root `auth.json` mirror
  must raise `StaleRevisionError` and preserve the canonical profile. A new login must
  still update both stores. Never inject stale credentials into a real user profile.

Live verification: list notebooks twice through HTTP and CDP, and verify an anonymous
homepage request reports expired authentication. For the stale-mirror check, use a
private temporary storage directory containing a copy of working credentials; reject
an injected synthetic stale mirror, then verify the preserved credentials can still
list notebooks twice. Run live checks separately from pytest's storage monitor.
A positive live session ID verifies compatibility only; the negative-ID case requires
its regression fixture unless Google supplies a negative ID for the current session.

---

### Test 1.1b - Non-Interactive Session Refresh (unattended)
**CLI:** `nlm auth refresh` (headless refresh; `--profile <name>` for a named profile)

**Prompt:**
```
Refresh my NotebookLM session without opening a browser window.
```

**Expected:** With a saved Chrome profile and a working login, prints
`✓ Session refreshed for profile '<name>'` and exits 0. With no saved profile
or a dead login, prints a clear failure and exits non-zero (usable in
cron/launchd). Refuses up front when `NOTEBOOKLM_COOKIES` is set in the
environment (that value overrides saved credentials).

---

### Test 1.1c - Credential Storage Management (Protected Mode)
**CLI:** `nlm auth storage status`, `nlm auth storage set protected`, `nlm auth storage set file`

**Prompt:**
```
Check my NotebookLM credential storage mode and test switching between file mode and protected mode.
```

**Expected:**
1. `nlm auth storage status`: Shows profile name, storage mode (`file` or `protected`), and presence of ciphertext or legacy files.
2. `nlm auth storage set protected`: Encrypts credentials to `credentials.enc` using the OS keystore (macOS Keychain, Windows Credential Manager, Linux SecretService) and removes plaintext files.
3. `nlm auth storage set file`: Decrypts credentials back to `cookies.json` with 0600 permissions.

---

### Test 1.1d - Profiles (`profile` tool)
**Tool:** `profile` (action: list, status, switch)

**Prompt:**
```
List my Gemini Notebook profiles, switch to my other profile for this session, then tell me how many notebooks I have. Do not change my default.
```

**Expected:**
1. `profile(action="list")` returns every saved profile with email, `storage_mode`, `is_saved_default`, `is_active`.
2. `profile(action="switch", name=...)` returns `scope: "session"`; later tools use that account and results carry `active_profile_note`.
3. The saved default (`nlm config get auth.default_profile`) is unchanged.
4. Quitting and reopening the app returns to the saved default.
5. `make_default=true` changes `default_profile` in `~/.notebooklm-mcp-cli/config.toml` (switch it back afterwards).
6. With `NOTEBOOKLM_COOKIES` set in the server's environment, switching returns an error.

---

### Test 1.1e - Aliases, chat-to-note, pipeline create
**Tools:** `alias`, `chat_save_to_note`, `pipeline` (action: create)

**Expected:** `alias(action="set", name="nb", value="<notebook id>")` then `notebook_get(notebook_id="nb")` resolves the alias; `chat_save_to_note` creates a note from a chat; `pipeline(action="create", ...)` saves a pipeline that `pipeline(action="list")` shows.

---

### Test 1.2 - Interactive Login (Primary)
**Tool:** `save_auth_tokens` (Fallback)
**CLI:** `nlm login` (Launches Chrome for automated extraction)
**WSL2 CLI:** `nlm login --wsl` (Supports NAT and mirrored networking modes)

**Prompt:**
```
I need to authenticate with NotebookLM.
```

**Expected:** Chrome opens, logs in, and tokens are saved. On WSL2, Windows Chrome opens and
the CDP connection succeeds in both NAT and mirrored networking modes.

**Anonymous-session regression (#350):**
1. Run login with a new profile. Before signing in, the browser must remain open;
   a public landing page, build label, or anonymous `NID` cookie must not finish login.
2. Complete Google sign-in. Login saves signed-in cookies and a CSRF token, then
   closes the browser it launched. Verify the profile with `nlm login --check`.
3. If sign-in times out, login fails without saving anonymous credentials.
4. For a profile previously saved with only `NID`, rerunning login opens the
   sign-in browser. `--check` must not report success based on a public HTTP 200 page.
5. An API authentication rejection must fail validation; a genuine network timeout
   remains inconclusive and must not be mislabeled as credential expiry.

---

### Test 1.3 - List Notebooks
**Tool:** `notebook_list`
**CLI:** `nlm notebook list`

**Prompt:**
```
List all my NotebookLM notebooks.
```

**Expected:** List of notebooks with counts (owned, shared).

---

### Test 1.3E - Enterprise List and Query

Before running this test, set `NOTEBOOKLM_BASE_URL`, `NOTEBOOKLM_PROJECT_ID`,
and `NOTEBOOKLM_LOCATION` for a Gemini Notebook Enterprise deployment. The
project setting is required; the location defaults to `global`. Authenticate
the profile and make it the default profile used by MCP:

```bash
nlm login --profile enterprise
nlm login switch enterprise
nlm notebook list
nlm notebook query <enterprise-notebook-id> "Summarize the sources" --new-conversation
```

**Expected:** Login opens the configured regional project URL, list returns
Enterprise notebooks, and the query uses the Enterprise streamed endpoint.
This test is not complete until it is run against an Enterprise deployment with
a redacted request/response capture; the automated suite only verifies routing
and payload contracts.

---

### Test 1.4 - Create Notebook
**Tool:** `notebook_create`
**CLI:** `nlm notebook create "MCP Test Notebook"`

**Prompt:**
```
Create a new notebook titled "MCP Test Notebook".
```

**Expected:** New notebook created with `notebook_id` and URL.

**Save:** Note the `notebook_id` for subsequent tests.

---

### Test 1.5 - Get Notebook Details
**Tool:** `notebook_get`
**CLI:** `nlm notebook get [notebook_id]`

**Prompt:**
```
Get the details of notebook [notebook_id from Test 1.4].
```

**Expected:** Notebook details with empty sources list, timestamps.

---

### Test 1.6 - Rename Notebook
**Tool:** `notebook_rename`
**CLI:** `nlm notebook rename [notebook_id] "MCP Test - Renamed"`

**Prompt:**
```
Rename notebook [notebook_id] to "MCP Test - Renamed".
```

**Expected:** Success with updated title.

---

## Test Group 2: Adding Sources (Consolidated source_add)

### Test 2.1 - Add URL Source
**Tool:** `source_add`
**CLI:** `nlm source add [notebook_id] --url https://en.wikipedia.org/wiki/Artificial_intelligence`

**Prompt:**
```
Add a URL source to notebook [notebook_id]:
- source_type: url
- url: https://en.wikipedia.org/wiki/Artificial_intelligence
```

**Expected:** Source added with `source_id`, `source_type: url`.

---

### Test 2.2 - Add Text Source
**Tool:** `source_add`
**CLI:** `nlm source add [notebook_id] --text "This is a test document..." --title "Test Document"`

**Prompt:**
```
Add a text source to notebook [notebook_id]:
- source_type: text
- title: "Test Document"
- text: "This is a test document about machine learning. Machine learning is a subset of artificial intelligence."
```

**Expected:** Text source added with `source_id`, `source_type: text`.

---

### Test 2.3 - Add Drive Source (Optional)
**Tool:** `source_add`
**CLI:** `nlm source add [notebook_id] --drive [doc_id] --type doc --title "My Drive Doc"`

**Prompt:**
```
Add a Drive document to notebook [notebook_id]:
- source_type: drive
- document_id: [your_doc_id]
- title: "My Drive Doc"
- doc_type: doc
```

**Expected:** Drive source added (or skip if no Drive doc available).

---

### Test 2.4 - Add File Source (Optional)
**Tool:** `source_add`
**CLI:** `nlm source add [notebook_id] --file /path/to/document.pdf`

**Prompt:**
```
Add a file to notebook [notebook_id]:
- source_type: file
- file_path: /path/to/document.pdf
```

**Expected:** File uploaded with `source_id`, `method: resumable`.

---

### Test 2.5 - List Sources with Drive Status
**Tool:** `source_list_drive`
**CLI:** `nlm source list [notebook_id] --drive`
**CLI (fast list):** `nlm source list [notebook_id] --drive --skip-freshness`

**Prompt:**
```
List all sources in notebook [notebook_id] and check their Drive freshness status.
```

**Expected:** List showing sources by type, Drive sources show freshness.

**Large notebook variant:** Call `source_list_drive` with `skip_freshness=True`, or use
`nlm source list [notebook_id] --drive --skip-freshness`. Expected: sources are listed
without per-source freshness checks; stale status may be unknown.

**Drive-picker file variant:** Include a PDF, text, Markdown, Word, or PowerPoint file
that was imported from Google Drive. Expected: type-14 files with Drive metadata appear
in `drive_sources` with their Drive IDs and `can_sync: true`; directly uploaded type-14
files without that metadata remain in `other_sources`. `can_sync` marks eligibility to
attempt a manual sync, not a guarantee that every source's RPC will succeed. Only
manually sync entries the tool marks `can_sync: true`.

**Save:** Note a `source_id` for next tests.

---

### Test 2.6 - Describe Source
**Tool:** `source_describe`
**CLI:** `nlm source describe [source_id]`

**Prompt:**
```
Get an AI-generated summary of source [source_id].
```

**Expected:** AI summary with keywords.

---

### Test 2.7 - Get Source Content
**Tool:** `source_get_content`
**CLI:** `nlm source content [source_id]`

**Prompt:**
```
Get the raw text content of source [source_id].
```

**Expected:** Raw text content with title, source_type, char_count.

---

### Test 2.8 - Delete Source
**Tool:** `source_delete`
**CLI:** `nlm source delete [source_id] --confirm`

**Prompt:**
```
Delete source [source_id] with confirm=True.
```

**Expected:** Source permanently deleted.

---

## Test Group 3: AI Features

### Test 3.1 - Describe Notebook
**Tool:** `notebook_describe`
**CLI:** `nlm notebook describe [notebook_id]`

**Prompt:**
```
Get an AI-generated summary of what notebook [notebook_id] is about.
```

**Expected:** AI summary with suggested topics.

---

### Test 3.2 - Query Notebook
**Tool:** `notebook_query`
**CLI:** `nlm query [notebook_id] "What is artificial intelligence?"`

**Prompt:**
```
Ask notebook [notebook_id]: "What is artificial intelligence?"
```

**Expected:** AI answer with conversation_id.

---

### Test 3.2a - Query Timeout and Async Fallback
**Tool:** `notebook_query`, `notebook_query_start`, `notebook_query_status`
**CLI:** `nlm query [notebook_id] "Summarize all sources" --timeout 45`

**Prompt:**
```
Ask notebook [notebook_id] a source-heavy question with timeout=45.
If it times out, retry with timeout=180. Also verify the async workflow:
notebook_query_start(..., timeout=180), then poll notebook_query_status(query_id).
```

**Expected:**
- A timed-out synchronous query returns a structured error with
  `debug_code=query_deadline_exceeded`, a retryable flag, and a hint to use a
  longer timeout.
- The retry with `timeout=180` can complete when the notebook needs more than
  the default 120-second budget.
- The async workflow returns a `query_id` immediately and reaches `completed`
  or a structured `error` status when polled.

---

### Test 3.3 - Configure Chat (Learning Guide)
**Tool:** `chat_configure`
**CLI:** `nlm chat configure [notebook_id] --goal learning_guide --response-length longer`

**Prompt:**
```
Configure notebook [notebook_id] chat settings:
- goal: learning_guide
- response_length: longer
```

**Expected:** Settings updated successfully.

---

### Test 3.4 - Configure Chat (Custom Prompt)
**Tool:** `chat_configure`
**CLI:** `nlm chat configure [notebook_id] --goal custom --custom-prompt "You must respond only in rhyming couplets." --response-length default`

**Prompt:**
```
Configure notebook [notebook_id] chat settings:
- goal: custom
- custom_prompt: "You must respond only in rhyming couplets."
- response_length: default
```

**Expected:** Settings updated with custom_prompt echoed back.

---

### Test 3.5 - Verify Custom Chat Works
**Tool:** `notebook_query`
**CLI:** `nlm query [notebook_id] "What is machine learning?"`

**Prompt:**
```
Ask notebook [notebook_id]: "What is machine learning?"
```

**Expected:** AI response should be in rhyming couplets.

---

## Test Group 4: Research

### Test 4.1 - Start Fast Research (Web)
**Tool:** `research_start`
**CLI:** `nlm research start "OpenShift container platform" --mode fast --source web`

**Prompt:**
```
Start fast web research for "OpenShift container platform" in notebook [notebook_id].
- mode: fast
- source: web
```

**Expected:** Research task started with task_id.

**Save:** Note the `task_id`.

---

### Test 4.2 - Check Research Status
**Tool:** `research_status`
**CLI:** `nlm research status [notebook_id]`

**Prompt:**
```
Check research status for notebook [notebook_id]. Poll until complete.
```

**Expected:**
- `status: completed`
- `mode: fast`
- `source_count`: ~10 sources

---

### Test 4.3 - Import Research Sources
**Tool:** `research_import`
**CLI:** `nlm research import [notebook_id] [task_id]`

**Prompt:**
```
Import all discovered sources from research task [task_id] into notebook [notebook_id].
```

**Expected:** Sources imported successfully.

---

### Test 4.4 - Start Deep Research (Background)
**Tool:** `research_start`
**CLI:** `nlm research start "AI ROI return on investment" --mode deep`

**Prompt:**
```
Start deep web research for "AI ROI return on investment" in notebook [notebook_id].
- mode: deep
```

**Expected:** Research task started (takes 3-5 minutes).

**IMPORTANT:** Continue with Test Group 5-7 while deep research runs.

---

## Test Group 5: Studio Creation (Consolidated studio_create)

### Test 5.1 - Create Audio Overview
**Tool:** `studio_create`
**CLI:** `nlm audio create [notebook_id] --format brief --length short`

**Prompt:**
```
Create an audio overview for notebook [notebook_id]:
- artifact_type: audio
- format: brief
- length: short
- confirm: False (show settings first)
```

**Follow-up:**
```
Confirmed. Create with confirm=True.
```

**Expected:** Audio generation started with artifact_id.

---

### Test 5.1b - Create Audio with Custom Prompt (Verify Extraction)
**Tool:** `studio_create`
**CLI:** `nlm audio create [notebook_id] --focus "Explain this to a 5 year old." --confirm`

**Prompt:**
```
Create an audio overview for notebook [notebook_id] with a focus prompt:
- artifact_type: audio
- focus_prompt: "Explain this to a 5 year old."
- confirm: True
```

**Expected:** Audio generation started. We will verify the prompt "Explain this to a 5 year old" appears in Test 5.10.

---

### Test 5.2 - Create Video Overview
**Tool:** `studio_create`
**CLI:** `nlm video create [notebook_id] --format brief --style classic --confirm`

**Prompt:**
```
Create a video overview for notebook [notebook_id]:
- artifact_type: video
- format: brief
- visual_style: classic
- confirm: True
```

**Expected:** Video generation started.

---

### Test 5.3 - Create Report
**Tool:** `studio_create`
**CLI:** `nlm report create [notebook_id] --format "Briefing Doc" --confirm`

**Prompt:**
```
Create a report for notebook [notebook_id]:
- artifact_type: report
- report_format: Briefing Doc
- confirm: True
```

**Expected:** Report generation started.

---

### Test 5.3b - Create Interactive Report
**Tool:** `studio_create`
**CLI:** `nlm report create [notebook_id] --format Interactive --template learning_overview --prompt "Summarize the key ideas with a quiz" --confirm`

**Prompt:**
```
Create an interactive report for notebook [notebook_id]:
- artifact_type: report
- report_format: Interactive
- report_template: learning_overview
- custom_prompt: Summarize the key ideas with a quiz
- confirm: True
```

**Expected:** Interactive report generation starts (status "queued" -> "in_progress"
-> "completed" in `studio_status`). The artifact type shows as `interactive_report`.

---

### Test 5.3c - Read Interactive Report
**Tool:** `report` (action=get)
**CLI:** `nlm report get [notebook_id] [artifact_id]` (or `--json`, `--output report.md`)

**Prompt:**
```
Read interactive report [artifact_id] in notebook [notebook_id]:
- call report(action="get")
- show the first section of the markdown and the element list
```

**Expected:** Markdown content, prompt and the embedded elements
(mind map / infographic / flashcards / slide deck / quiz) with status
"suggested" before they are generated.

---

### Test 5.3d - List and Generate Report Elements
**Tool:** `report` (action=elements, generate)
**CLI:** `nlm report elements [notebook_id] [artifact_id]` then
`nlm report element create [notebook_id] [artifact_id] --type quiz --confirm`

**Prompt:**
```
List the embedded elements of interactive report [artifact_id], then generate
the quiz element.
```

**Expected:** Element list shows ids/types/statuses; generating one flips its
status from "suggested" to generation states and the element also appears in the
notebook Studio panel.

---

### Test 5.3e - Report Element Settings Sweep
**Tool:** `report` (action=generate, one-item plan)
**CLI:** `nlm report element create [notebook_id] [artifact_id] --type quiz --setting difficulty=hard --setting question_amount=more --confirm`

**Prompt:**
```
Generate an interactive report quiz element with settings difficulty=hard and question_amount=more.
```

**Expected:** Generation starts with custom settings passed into generation options (`difficulty=3`, `question_amount=3`).

---

### Test 5.3f - Batch Element Plan Validation (Invalid Item Stops All)
**Tool:** `report` (action=generate)
**CLI:** `nlm report element create-batch [notebook_id] [artifact_id] --plan invalid_plan.json --confirm`

**Prompt:**
```
Validate and attempt to run a batch plan containing 2 valid element IDs and 1 non-existent or invalid element ID:
[
  {"element_id": "valid-id-1"},
  {"element_id": "invalid-id-xyz"}
]
```

**Expected:** Validation fails before any RPC mutation occurs; no elements change status or start generation.

---

### Test 5.3g - Batch Generation Stops on Quota Exhaustion
**Tool:** `report` (action=generate)
**CLI:** `nlm report element create-batch [notebook_id] [artifact_id] --plan plan.json --confirm`

**Prompt:**
```
Run a multi-element batch plan when quota is exhausted.
```

**Expected:** Generation terminates immediately when encountering `RESOURCE_EXHAUSTED`; result reports `stopped_reason="quota"` and remaining planned items stay `not_started`.

---

### Test 5.3h - Element Bounded Waiting and Timeout
**Tool:** `report` (action=elements)
**CLI:** `nlm report elements [notebook_id] [artifact_id] --wait [element_id] --timeout 10`

**Prompt:**
```
Wait on an in-progress element for up to 10 seconds.
```

**Expected:** Returns status before timeout if completed/failed, or returns `timed_out: true` with current status if timeout elapses without raising an error.

---

### Test 5.3i - Inline Content for Element Review
**Tool:** `report` (action=elements)
**CLI:** `nlm report elements [notebook_id] [artifact_id] --content`

**Prompt:**
```
List report elements with include_content=True to review completed quiz, flashcard, or mind map elements.
```

**Expected:** Returns inline structured content for review with label "Checked against the plan and the report section, not against the original sources."

---

### Test 5.4 - Create Flashcards
**Tool:** `studio_create`
**CLI:** `nlm flashcards create [notebook_id] --difficulty medium --focus "Focus on definitions" --confirm`

**Prompt:**
```
Create flashcards for notebook [notebook_id]:
- artifact_type: flashcards
- difficulty: medium
- confirm: True
```

**Expected:** Flashcards generation started.

---

### Test 5.5 - Create Quiz
**Tool:** `studio_create`
**CLI:** `nlm quiz create [notebook_id] --count 2 --difficulty 2 --focus "Focus on integration testing" --confirm`

**Prompt:**
```
Create a quiz for notebook [notebook_id]:
- artifact_type: quiz
- question_count: 2
- difficulty: medium
- confirm: True
```

**Expected:** Quiz generation started.

---

### Test 5.6 - Create Infographic
**Tool:** `studio_create`
**CLI:** `nlm infographic create [notebook_id] --orientation landscape --detail standard --style professional --confirm`

**Prompt:**
```
Create an infographic for notebook [notebook_id]:
- artifact_type: infographic
- orientation: landscape
- detail_level: standard
- infographic_style: professional
- confirm: True
```

**Expected:** Infographic generation started with professional visual style.

**Visual Styles Available:** auto_select, sketch_note, professional, bento_grid, editorial, instructional, bricks, clay, anime, kawaii, scientific

---

### Test 5.7 - Create Slide Deck
**Tool:** `studio_create`
**CLI:** `nlm slides create [notebook_id] --format detailed_deck --length short --confirm`

**Prompt:**
```
Create a slide deck for notebook [notebook_id]:
- artifact_type: slide_deck
- format: detailed_deck
- length: short
- confirm: True
```

**Expected:** Slide deck generation started.

---

### Test 5.8 - Create Mind Map
**Tool:** `studio_create`
**CLI:** `nlm mindmap create [notebook_id] --title "AI Concepts" --confirm`

**Prompt:**
```
Create a mind map for notebook [notebook_id]:
- artifact_type: mind_map
- title: "AI Concepts"
- confirm: True
```

**Expected:** Mind map created immediately.

---

### Test 5.9 - Create Data Table
**Tool:** `studio_create`
**CLI:** `nlm data-table create [notebook_id] "Key features and capabilities" --confirm`

**Prompt:**
```
Create a data table for notebook [notebook_id]:
- artifact_type: data_table
- description: "Key features and capabilities"
- confirm: True
```

**Expected:** Data table generation started.

---

### Test 5.10 - Check Studio Status
**Tool:** `studio_status`
**CLI:** `nlm studio status [notebook_id]`

**Prompt:**
```
Check studio content generation status for notebook [notebook_id].
```

**Expected:**
- Default MCP response contains at most 20 artifacts and only lean status fields.
- `pagination` contains `returned`, `offset`, `limit`, and `has_more`.
- Polling with `artifact_id` returns only the selected artifact.
- Calling with `include_details=True` exposes rich fields and the artifact from
  Test 5.1b shows `custom_instructions: "Explain this to a 5 year old"`.
- `nlm studio status [notebook_id] --json` remains a plain list containing both
  `id` and `artifact_id`.
- `nlm studio status [notebook_id] --json --mcp-compatible` returns the MCP envelope.
- `nlm video list [notebook_id] --json` returns only video artifacts.

---

### Test 5.11 - Rename Studio Artifact
**Tool:** `studio_status` (with action="rename")
**CLI:** `nlm studio rename [artifact_id] "My Renamed Podcast"`

**Prompt:**
```
Rename artifact [artifact_id] in notebook [notebook_id] to "My Renamed Podcast".
- action: rename
- artifact_id: [artifact_id from studio_status]
- new_title: "My Renamed Podcast"
```

**Expected:** Artifact renamed successfully.

---

### Test 5.12 - Revise Slide Deck
**Tool:** `studio_revise`
**CLI:** `nlm slides revise <artifact_id> --slide '1 Make the title larger' --confirm`

**Prompt:**
```
Revise the slide deck artifact [artifact_id] in notebook [notebook_id]:
- slide_instructions: [{"slide": 1, "instruction": "Make the title larger and bolder"}]
- confirm: true
```

**Expected:**
- New artifact created with status "in_progress"
- New artifact_id returned (different from original)
- Original artifact unchanged
- **Verify:** Run `studio_status` — new deck appears with "(2)" suffix in title.

---

## Test Group 6: Downloads (Consolidated download_artifact)

### Test 6.1 - Download Report
**Tool:** `download_artifact`
**CLI (Verb):** `nlm download report [notebook_id] --output /tmp/report.md`

**Prompt:**
```
Download the report from notebook [notebook_id]:
- artifact_type: report
- output_path: /tmp/report.md
```

**Expected:** Report downloaded as markdown.

---

### Test 6.2 - Download Flashcards (JSON)
**Tool:** `download_artifact`
**CLI:** `nlm download flashcards [notebook_id] --format json --output /tmp/flashcards.json`

**Prompt:**
```
Download flashcards from notebook [notebook_id]:
- artifact_type: flashcards
- output_path: /tmp/flashcards.json
- output_format: json
```

**Expected:** Flashcards downloaded as JSON.

---

### Test 6.3 - Download Quiz (Markdown)
**Tool:** `download_artifact`
**CLI:** `nlm download quiz [notebook_id] --format markdown --output /tmp/quiz.md`

**Prompt:**
```
Download quiz from notebook [notebook_id]:
- artifact_type: quiz
- output_path: /tmp/quiz.md
- output_format: markdown
```

**Expected:** Quiz downloaded as markdown.

---

### Test 6.4 - Download Audio
**Tool:** `download_artifact`
**CLI:** `nlm download audio [notebook_id] --output /tmp/podcast.m4a`

**Prompt:**
```
Download audio from notebook [notebook_id]:
- artifact_type: audio
- output_path: /tmp/podcast.m4a
```

**Expected:** Audio downloaded as M4A/MP4.

---

### Test 6.5 - Download Slide Deck
**Tool:** `download_artifact`
**CLI:** `nlm download slide-deck [notebook_id] --output /tmp/slides.pdf`

**Prompt:**
```
Download slide deck from notebook [notebook_id]:
- artifact_type: slide_deck
- output_path: /tmp/slides.pdf
```

**Expected:** Slides downloaded as PDF.

---

### Test 6.6 - Download Data Table Excel Export
**Tool:** `download_artifact`

**Prompt:**
```
Download the Excel data-table export from notebook [notebook_id]:
- artifact_type: data_table_xlsx
- output_path: /tmp/data-table.xlsx
```

**Expected:** The completed type-10 artifact is downloaded byte-for-byte as XLSX.

---

### Test 6.7 - Download All Artifacts
**Tool:** `download_all_artifacts`
**CLI:** `nlm download all [notebook_id] --output-dir /tmp/exports`

**Prompt:**
```
Download all completed artifacts from notebook [notebook_id]:
- output_dir: /tmp/exports
```

**Expected:** A subdirectory named after the notebook title created under the
output dir, containing every completed artifact named after its title
(report → .md, mind_map → .json, video → .mp4, slide_deck → .pdf, ...).
In-progress/failed artifacts are listed as skipped; result reports
downloaded/failed/skipped counts. Also test `--types video,report` filtering.

---

### Test 6.7 - Sweep All Notebooks (Incremental)
**Tool:** `download_all_artifacts` with `all_notebooks=True, skip_existing=True`
**CLI:** `nlm download all --all-notebooks --skip-existing --output-dir /tmp/exports`

**Prompt:**
```
Download all artifacts from every notebook into /tmp/exports, skipping
files that already exist.
```

**Expected:** One subdirectory per notebook. On a second run with
`skip_existing`, previously downloaded artifacts are reported as skipped
("already downloaded") and only new artifacts are fetched. A failure on one
notebook doesn't stop the sweep; result includes per-notebook counts and
`errored_notebooks`.

---

## Test Group 7: Sharing

### Test 7.1 - Get Share Status
**Tool:** `notebook_share_status`
**CLI (Noun):** `nlm share status [notebook_id]`

**Prompt:**
```
Get sharing status for notebook [notebook_id].
```

**Expected:** Status with `is_public`, `access_level`, `collaborators`.

---

### Test 7.2 - Enable Public Link
**Tool:** `notebook_share_public`
**CLI:** `nlm share public [notebook_id]`

**Prompt:**
```
Enable public link for notebook [notebook_id].
- is_public: True
```

**Expected:** Public link returned.

---

### Test 7.3 - Disable Public Link
**Tool:** `notebook_share_public`
**CLI:** `nlm share private [notebook_id]`

**Prompt:**
```
Disable public link for notebook [notebook_id].
- is_public: False
```

**Expected:** Public link disabled.

---

### Test 7.4 - Invite Collaborator (Optional)
**Tool:** `notebook_share_invite`
**CLI:** `nlm share invite [notebook_id] test@example.com --role viewer`

**Prompt:**
```
Invite collaborator to notebook [notebook_id]:
- email: test@example.com
- role: viewer
```

**Expected:** Invitation sent (or error if email invalid).

---

## Test Group 8: Drive Sync (Optional)

### Test 8.1 - Sync Drive Sources
**Tool:** `source_sync_drive`
**CLI (Verb):** `nlm source sync [notebook_id] --confirm`

**Prompt:**
```
Check if any Drive sources in notebook [notebook_id] are stale using source_list_drive.
If any are stale, sync them using source_sync_drive with confirm=True.
```

**Expected:** Sources synced if any were stale.

---

## Test Group 9: Deep Research Verification

**TIMING:** By now, deep research from Test 4.4 should be complete.

### Test 9.1 - Check Deep Research Status
**Tool:** `research_status`
**CLI (Noun):** `nlm research status [notebook_id]`

**Prompt:**
```
Check deep research status for notebook [notebook_id] with max_wait=60.
```

**Expected:**
- `status: completed`
- `mode: deep`
- `source_count`: ~40-50 sources
- `report` field present

---

### Test 9.2 - Import Deep Research Sources
**Tool:** `research_import`
**CLI (Noun):** `nlm research import [notebook_id] [task_id]`

**Prompt:**
```
Import all deep research sources from task [task_id] into notebook [notebook_id].
```

**Expected:** Sources imported successfully.

---

## Test Group 10: Cleanup

### Test 10.1 - Delete Studio Artifacts
**Tool:** `studio_delete`
**CLI (Noun):** `nlm studio delete [notebook_id] [artifact_id] --confirm`

**Prompt:**
```
Get studio status for notebook [notebook_id], then delete each artifact with confirm=True.
```

**Expected:** All artifacts deleted.

---

### Test 10.2 - Delete All Sources
**Tool:** `source_delete`
**CLI (Noun):** `nlm source delete [source_id] --confirm`

**Prompt:**
```
List sources in notebook [notebook_id], then delete each with confirm=True.
```

**Expected:** All sources deleted.

---

### Test 10.3 - Delete Notebook
**Tool:** `notebook_delete`
**CLI (Noun):** `nlm notebook delete [notebook_id] --confirm`

**Prompt:**
```
Delete notebook [notebook_id] with confirm=True.
```

**Expected:** Notebook deleted successfully.

---

## Test Group 11: Notes Management (Unified `note` tool)

### Test 11.1 - Create Note
**Tool:** `note`
**CLI (Noun):** `nlm note create [notebook_id] --content "Test" --title "Title"`

**Prompt:**
```
Create a note in notebook [notebook_id]:
- action: create
- content: "This is a test note about AI"
- title: "AI Note"
```

**Expected:** Note created with `note_id`.

**Save:** Note the `note_id` for subsequent tests.

---

### Test 11.2 - List Notes
**Tool:** `note`
**CLI (Noun):** `nlm note list [notebook_id]`

**Prompt:**
```
List all notes in notebook [notebook_id]:
- action: list
```

**Expected:** Array of notes including the one just created, with previews.

---

### Test 11.3 - Update Note
**Tool:** `note`
**CLI (Noun):** `nlm note update [notebook_id] [note_id] --content "Updated"`

**Prompt:**
```
Update note [note_id] in notebook [notebook_id]:
- action: update
- note_id: [note_id]
- content: "Updated: AI is transforming technology"
```

**Expected:** Success confirmation.

---

### Test 11.4 - Delete Note
**Tool:** `note`
**CLI (Noun):** `nlm note delete [notebook_id] [note_id] --confirm`

**Prompt:**
```
Delete note [note_id] in notebook [notebook_id]:
- action: delete
- note_id: [note_id]
- confirm: True
```

**Expected:** Deletion confirmation message.

---

## Test Group 12: Server Info

### Test 12.1 - Get Server Info
**Tool:** `server_info`

**Prompt:**
```
Get Gemini Notebook MCP server version and check for updates.
```

**Expected:**
- `version`: Current version
- `latest_version`: Latest PyPI version (or null if offline)
- `update_available`: Boolean
- `update_command`: Upgrade command

---

## Test Group 13: Plan Usage

### Test 13.1 - Get Remaining Usage
**Tool:** `usage_get`
**CLI (Noun):** `nlm usage` (add `--json` for raw output)

**Prompt:**
```
How much of my Gemini Notebook usage allowance is left?
```

**Expected:**
- `windows`: two entries, `rolling` first then `weekly`
- each with `percent_used`, `percent_remaining` and `resets_at` (ISO 8601 UTC)
- `tier`: subscription tier string, e.g. `NOTEBOOKLM_TIER_PRO_CONSUMER_USER`

**Also verify:**
- Run it twice. The reported order stays `rolling`, `weekly` even though the API
  returns the two entries in an unstable order.
- `percent_used` and `percent_remaining` sum to 100 for a partly consumed window.
- With an expired session it reports an authentication error and hints at
  `nlm auth refresh`. It must NOT report the allowance as exhausted.

### Test 13.2 - Check Work and Personal Profiles
**Tool:** `usage_get(profile="work")`, then `usage_get(profile="personal")`
**CLI:** `nlm usage --profile work`, then `nlm usage -p personal --json`

**Expected:**
- Each call reads the selected saved account's usage, even when
  `NOTEBOOKLM_COOKIES` is set for a different account.
- The configured default and the account used by other MCP tools are unchanged.
- Missing profiles return an error without falling back to environment cookies
  or the default account.
- Omitting the profile keeps the existing environment/default authentication.

---

## Test Group 14: Setup Wizard (CLI only)

Automated: `uv run pytest -m wizard_e2e` drives the real `nlm setup` in a
pseudo-terminal against a sandboxed HOME (fake `claude`/`codex`/`ps`/`pbcopy`/
`open`) and checks the files written. Run it after any change to
`cli/commands/setup.py`, `setup_wizard.py`, `skill.py` or `cli/skill_package.py`.
The manual checks below cover what the sandbox can't: the real `claude` and
`codex` CLIs, and the real Claude Desktop upload. Run `nlm setup` in a real
terminal (not an agent's shell — it refuses non-interactive sessions).

### Test 14.1 - Status and Esc
**CLI:** `nlm setup` → **Show my tools' status**

**Expected:**
- Only installed tools are listed, with ✓ set up / ✗ not yet / ⚠ old name and
  the skill version (⬆ when an upgrade exists).
- Esc on every screen returns to the main menu within ~0.1s; Esc on the main
  menu quits.

### Test 14.2 - Connect and rename
**CLI:** `nlm setup` → **Add the MCP to my tools/agents**

**Expected:**
- Nothing is pre-ticked; already-connected tools are shown but not selectable.
- Tools whose entry is still `notebooklm-mcp` appear under **Needs a fix**;
  ticking them reports `repaired · Renamed to gemini-notebook-mcp`.
- Verify: `claude mcp list` shows `gemini-notebook-mcp ✔ Connected`;
  `~/.codex/config.toml` has `[mcp_servers.gemini-notebook-mcp]` and kept any
  extra keys (e.g. `enabled = true`); Claude Desktop configs (both profiles if
  chosen) contain `gemini-notebook-mcp` with the full binary path.
- With Claude Desktop open, connecting it is refused ("still running").

### Test 14.3 - Skill and Claude Desktop upload file
**CLI:** `nlm setup` → **Add the skill to my tools/agents** (or `nlm skill package`)

**Expected:**
- No "Add the skill?" question — it opens on "Where should the skill live?".
- The picker includes **Claude Desktop / claude.ai · creates a file to upload**,
  not pre-ticked. Ticking it saves `~/Downloads/nlm-skill.zip`, reveals it in
  Finder, and shows the upload steps last.
- Upload via Claude Desktop **Customize → Skills → Add**: accepted; the skill
  appears on the Skills page and loads in Chat and Cowork.

### Test 14.4 - Remove and copy setup
**CLI:** `nlm setup` → **Remove an MCP or skill**, then **Copy MCP setup for a tool not listed**

**Expected:**
- Remove: grouped MCP connections / Skills, nothing pre-ticked, two separate
  default-No confirmations; only ticked items change; backups appear in
  `~/.notebooklm-mcp-cli/backups/`.
- Copy: the clipboard holds `{"mcpServers": {"gemini-notebook-mcp": {"command": "<full path>/notebooklm-mcp"}}}`.

### Test 14.5 - Credential protection
**CLI:** `nlm setup` → **Credential protection**

**Expected:**
- With no saved logins: "No saved logins yet. Run 'nlm login' first."
- With plain logins: lists each as `plain` and offers **Protect saved logins (recommended)**; with several logins a checkbox picker appears.
- With protected logins: offers **Restore protected logins to plain files** (asks to confirm, default No); never offers Protect for an already-protected login.
- Mixed: offers both.
- Afterwards `nlm auth storage status` matches, and no protection tip appears for a protected login.

### Test 14.6 - First login on a new profile (new-user flow)
**CLI:** `nlm login` on a machine (or sandbox) with no saved logins

**Expected:**
1. Before the browser opens: "Where should your saved login live?" with Protected (recommended) and Plain file.
2. Choosing 1 stores the login encrypted (`credentials.enc`, no `cookies.json`) and ends with "✓ Login stored in protected mode." with no further tips or questions.
3. A profile name protected mode can't use (`my work`, `john@work.com`) offers a working name (`my-work`) or keeping the name as a plain file.
4. Ctrl+C or closing the flow leaves no profile folder, no saved answer, and closes the Chrome window it opened.

---

## Summary: 31 Consolidated Tools

| Category | Tools | Count |
|----------|-------|-------|
| **Auth** | `refresh_auth`, `save_auth_tokens` | 2 |
| **Notebooks** | `notebook_list`, `notebook_get`, `notebook_describe`, `notebook_create`, `notebook_rename`, `notebook_delete` | 6 |
| **Sources** | `source_add`, `source_list_drive`, `source_sync_drive`, `source_delete`, `source_describe`, `source_get_content` | 6 |
| **Sharing** | `notebook_share_status`, `notebook_share_public`, `notebook_share_invite` | 3 |
| **Research** | `research_start`, `research_status`, `research_import` | 3 |
| **Studio** | `studio_create`, `studio_status`, `studio_delete`, `studio_revise` | 4 |
| **Downloads** | `download_artifact`, `download_all_artifacts` | 2 |
| **Exports** | `export_artifact` | 1 |
| **Chat** | `notebook_query`, `chat_configure` | 2 |
| **Notes** | `note` (unified: list, create, update, delete) | 1 |
| **Server** | `server_info` | 1 |
| **Total** | | **31** |

---

## Quick Copy-Paste Test Prompts

```
1. Refresh auth tokens
2. List all my NotebookLM notebooks
3. Create a new notebook titled "MCP Test Notebook"
4. Get details of notebook [id]
5. Rename notebook [id] to "MCP Test - Renamed"
6. Add URL source to notebook [id]: source_type=url, url=https://en.wikipedia.org/wiki/Artificial_intelligence
7. Add text source to notebook [id]: source_type=text, text="Machine learning test document"
8. List sources in notebook [id] with Drive status
9. Get AI summary of source [source_id]
10. Get raw text content of source [source_id]
11. Get AI summary of notebook [id]
12. Ask notebook [id]: "What is artificial intelligence?"
13. Configure notebook [id] chat: goal=learning_guide, response_length=longer
14. Configure notebook [id] chat: goal=custom, custom_prompt="Respond in rhymes"
15. Start fast web research for "OpenShift" in notebook [id]
16. Check research status for notebook [id]
17. Import research sources from task [task_id]
18. Start DEEP web research for "AI ROI" in notebook [id]
19. Create audio overview: artifact_type=audio, format=brief, confirm=True
20. Create video overview: artifact_type=video, format=brief, confirm=True
21. Check studio status for notebook [id]
22. Create report: artifact_type=report, report_format="Briefing Doc", confirm=True
23. Create flashcards: artifact_type=flashcards, confirm=True
24. Create quiz: artifact_type=quiz, question_count=2, confirm=True
25. Create infographic: artifact_type=infographic, confirm=True
26. Create slide deck: artifact_type=slide_deck, confirm=True
27. Create mind map: artifact_type=mind_map, title="AI Concepts", confirm=True
28. Download report: artifact_type=report, output_path=/tmp/report.md
29. Download flashcards: artifact_type=flashcards, output_path=/tmp/cards.json
30. Get share status for notebook [id]
31. Enable public link for notebook [id]
32. Check deep research status
33. Import deep research sources
34. Create note in notebook [id]: content="Test note", title="My Note"
35. List all notes in notebook [id]
36. Update note [note_id] in notebook [id]: content="Updated content"
37. Delete note [note_id] in notebook [id] with confirm=True
38. Delete all studio artifacts with confirm=True
39. Delete all sources with confirm=True
40. Delete notebook [id] with confirm=True
```

### Experimental source_search
With the feature disabled, verify a disabled error. Enable it, search using a notebook alias, and verify bounded passages and source attribution. Check that a foreign source filter is rejected and debug logs contain no query or excerpt.
