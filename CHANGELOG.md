# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.6] - 2026-08-03

### Added
- **Profile-aware Claude Desktop setup** — `nlm setup add/remove claude-desktop` now detects regular and Relay AI/3P profiles on macOS, Windows, and Linux. When both profiles exist, the command prompts for regular, 3P, or both; scripts can use `--profile regular|3p|both`. Missing profiles are never created. This builds on the original Claude Desktop setup contribution in [PR #275](https://github.com/jacob-bd/gemini-notebook-mcp-cli/pull/275) by **@sanjarcode** — thank you, Sanjar!

### Changed
- **Gemini Notebook MCP branding** — New configuration entries use `gemini-notebook-mcp` across supported clients, MCP metadata, the desktop extension, and the packaged skill. The `notebooklm-mcp` executable and `notebooklm-mcp-cli` package names remain unchanged for compatibility. Recognized legacy entries are migrated or removed safely.
- **Safe user-level skill installation** — `nlm skill install` now requires the target tool to be detected before writing to a user-level directory. Use `--level project` when a project-local skill is intentional.

### Fixed
- **Claude Desktop MCP setup compatibility** — Setup uses the resolved `notebooklm-mcp` binary path, handles Windows MSIX config locations, and remains compatible with Relay AI's Claude Desktop launcher. It only offers configured profiles for removal, refuses to write while the selected Claude instance is active, and ignores leftover Crashpad helper processes after Claude has been closed.

## [0.9.5] - 2026-07-28

### Fixed
- **WSL2 mirrored networking support for `nlm login --wsl` (#273)** — On WSL2 with mirrored networking mode, `get_windows_host_ip()` derived the CDP address from the default gateway, which in mirrored mode is the physical router rather than the Windows host. This caused `nlm login --wsl` to poll the wrong IP and always time out after 30 seconds, even though Chrome and CDP were fully functional. The CLI now detects the active networking mode via `wslinfo --networking-mode` and uses the shared loopback address (`127.0.0.1`) in mirrored mode, while preserving the existing gateway/resolver discovery for NAT mode and older WSL installations. Thanks to **@Premshay** for the outstanding diagnosis, the fix (PR #274), unit tests, and documentation updates!
- **CDP timeout error now shows the polled URL** — The WSL login timeout message previously said only "Chrome did not start within 30 seconds" with generic troubleshooting steps. It now includes the actual URL being polled (e.g., `Could not connect to CDP at http://10.100.102.1:9222`), making wrong-address issues immediately visible. Troubleshooting steps are also mode-aware: mirrored mode suggests checking the portproxy rule; NAT mode points at the firewall rule.
- **Firewall prompt skipped in mirrored mode** — Loopback traffic in mirrored mode never crosses Windows Firewall, so the interactive firewall-rule setup prompt is now bypassed with an informational one-liner instead of walking users through an unnecessary PowerShell step.

## [0.9.4] - 2026-07-25

### Fixed
- **Misleading "Cannot connect to browser on port" error when Chrome is already running (#272)** — if Chrome was already running (but not on a port `nlm login` recognized), the browser we launched would hand off to the existing instance and exit immediately, so the remote-debugging port never bound. The resulting error named a port number that had nothing to do with the actual problem, leaving users chasing the wrong lead. The error now detects this hand-off case and tells you to fully quit Chrome and retry. Thanks to **@argonaut-cm** for the detailed repro with live CDP target output that pinned this down!

### Added
- **`notebook.cloud.google.com` recognized as a Gemini Notebook (formerly Google NotebookLM) host** — the Workspace/enterprise variant of the "Gemini Notebook" rebrand host added in 0.9.3. Covers login detection and `NOTEBOOKLM_BASE_URL` for Workspace accounts landing on the new cloud domain. Thanks to **@conexaoarteiro** for reporting the rebrand issue on a Workspace account.

## [0.9.3] - 2026-07-25

### Fixed
- **Support Google's "Gemini Notebook (formerly Google NotebookLM)" rebrand at `notebook.google.com` (#269)** — Google is rolling out a rebrand of Gemini Notebook that redirects some signed-in accounts from `notebooklm.google.com` to `notebook.google.com`. Previously this broke every auth path for migrated accounts: `nlm login` timed out because sign-in detection only recognized the old host; API calls failed because the httpx client always targeted `notebooklm.google.com` regardless of where the account actually landed; and the `NOTEBOOKLM_BASE_URL` escape hatch rejected the new host outright.
  - `notebook.google.com` is now a recognized Gemini Notebook host for login detection (`is_logged_in`) and for `NOTEBOOKLM_BASE_URL`.
  - The CLI now records which host a signed-in session actually landed on (`base_host`, persisted per-profile in `metadata.json`) and every client construction path — CLI, MCP, chat sessions, and the `nlm doctor auth-replay` diagnostic — routes requests to that host automatically. No configuration is needed for migrated accounts; non-migrated accounts see no change, since the default host is still `notebook.google.com`.
  - Precedence: `NOTEBOOKLM_BASE_URL` env var (if set) > the account's persisted `base_host` > the default host.
  - Thanks to **@grergea** for the detailed report and reproduction steps!

## [0.9.2] - 2026-07-23

### Fixed
- **Desktop extension finds uvx installed via `pip install --user` on Windows (#267)** — the `.mcpb` launcher could fail to start with `Error: Could not find 'uvx'` even when uv was installed, because `pip install --user uv` places `uvx.exe` in `%APPDATA%\Python\Python3XX\Scripts`, which Windows does not add to PATH and which was missing from the launcher's search list. The launcher now checks the per-user Scripts directory of every installed CPython version. No behavior change on macOS/Linux. Thanks to **@onexoluxion** for the fix!

### Security
- **Bumped locked dependencies with published CVEs (#268)** — `uv.lock` now pins mcp 1.28.1, starlette 1.3.1, python-multipart 0.0.32, cryptography 49.0.0, and pyjwt 2.13.0. Lockfile-only change: no source or constraint changes, and end users installing via `uv tool install` were already resolving patched versions from PyPI — this brings the committed lockfile (used by CI and contributors) up to date. Thanks to **@onexoluxion** for the precise report and verified fix command!

## [0.9.1] - 2026-07-22

### Added
- **Chat session management (#256)** — list, view, export, and save past notebook chats.
  - CLI: `nlm chats list <notebook>`, `nlm chats get <notebook> [conversation_id]`, `nlm chats export <notebook> [conversation_id] --format md|json --output file`, and `nlm chats to-note <notebook> <conversation_id> [--turn N] [--title ...]`.
  - MCP tools: `chat_list`, `chat_get`, `chat_export`.
  - Transcripts are fetched from Gemini Notebook's server (a newly-documented `khqZz` RPC, see `docs/API_REFERENCE.md`), so past chats are visible even from a fresh CLI invocation or MCP session — not just chats made earlier in the same process.
  - Documented in `SKILL.md`, `AGENTS_SECTION.md`'s `command_reference.md`, `docs/CLI_GUIDE.md`, `docs/MCP_GUIDE.md`, `README.md`, and `AGENTS.md`.

### Fixed
- **Preserve profile email across token updates (#266)** — `AuthManager.save_profile()` now preserves the existing stored profile email from `metadata.json` when `email=None` is passed during background CSRF updates, token refreshes, and `save_tokens_to_cache()` calls.
- **Chat session tools now respect the configured default profile** — `services/chats.py` no longer hardcodes profile `"default"`; it now falls back to `get_config().auth.default_profile` like the rest of the CLI/MCP client resolution, so `chat_list`/`chat_get`/`chat_export` and `nlm chats ...` work correctly for accounts using `nlm login switch`.
- **`nlm chats to-note` / `save_chat_to_note` now creates the note correctly** — it was calling `notes_service.create_note()` with the wrong signature (`notebook=`/`profile=` keyword args instead of the required `(client, notebook_id, content, title)`), which raised a `TypeError` at runtime. Never shipped, caught before release via live testing.
- **`chat_list`/`chat_get`/`chat_export` are now hideable via `NOTEBOOKLM_DISABLED_GROUPS`** — added to the `chat` tool group in `tool_groups.py`, which previously covered only `notebook_query`/`chat_configure`/`notebook_query_start`/`notebook_query_status`.
- **Tool count corrected to 43 across all docs** — `label`, `notebook_query_start`, and `notebook_query_status` were registered MCP tools missing from `mcp/tools/__init__.py`'s `__all__` and from `docs/MCP_GUIDE.md` (which also separately lacked `source_rename` and `notebook_share_batch`). Fixed the export list and documented every tool; updated the stale "40 tools" (and one "39 tools") count in README.md, the desktop extension manifest, `SKILL.md`, and `docs/MCP_CLI_TEST_PLAN.md`. Added a regression test (`test_groups_cover_every_registered_tool`) so a new tool shipping without a `tool_groups.py` entry fails CI instead of silently drifting.

## [0.9.0] - 2026-07-20

### Added
- **Bulk artifact download (#258, #264)** — New MCP tool `download_all_artifacts` and CLI command `nlm download all` download every completed Studio artifact of a notebook — or every notebook in the account with `--all-notebooks`/`all_notebooks=True` — into per-notebook directories named after each notebook's title. Supports an `--types`/`artifact_types` filter, `--skip-existing`/`skip_existing` for incremental re-runs, and safe cross-platform filenames (invalid characters replaced, Windows reserved names escaped, collisions deduped case-insensitively for both notebook directories and artifact filenames). A failure on one artifact or notebook is recorded and does not stop the rest; the CLI exits non-zero only when nothing was downloaded and failures occurred. Thanks to **@hansschenker** for the original contribution (PR #258), and to **@runthangs** for following up with fixes for directory collisions, case-insensitive overwrites, and the `--all-notebooks` exit code (PR #264)!

### Documentation
- Reconciled the MCP tool count (39 → 40) and added `download_all_artifacts`/`nlm download all` across the README, MCP Guide, CLI Guide, packaged skill, and command reference.

## [0.8.9] - 2026-07-17

### Added
- **Bounded Studio status polling (#263)** — MCP `studio_status` now returns lean fields and at most 20 artifacts by default, supports artifact-specific lookup and pagination, and exposes rich prompts/content only with `include_details=True`.
- **CLI status compatibility bridge (#263)** — Legacy Studio JSON remains a plain list with `id`, while also exposing `artifact_id`; `--mcp-compatible` returns the MCP envelope and `nlm video list` provides discoverable video-only status.

### Fixed
- **Short video language steering (#263)** — Non-English Short requests now add an explicit language requirement for narration, subtitles, and on-screen text without changing the reverse-engineered RPC payload.
- **Studio rate-limit guidance (#263)** — MCP creation errors preserve the service retry hint, and documentation distinguishes brief automatic retries from minute-scale Studio quota waits.

### Documentation
- Updated CLI, MCP, API, troubleshooting, packaged skill, command reference, prompting guide, and test-plan documentation for the new Studio status, Short-language, and retry behavior.

## [0.8.8] - 2026-07-16

### Added
- **Opt-in file upload directory allowlist (#260)** — Set `NOTEBOOKLM_ALLOWED_FILE_DIRS` to restrict local file uploads to approved directories. The setting accepts multiple directories separated by the operating system's path separator and is disabled by default, so existing installations keep their current behavior. Thanks to **@failsafesecurity** for the contribution!
- **Opt-in download output directory (#261)** — Set `NOTEBOOKLM_DOWNLOAD_DIR` to keep downloaded artifacts inside one approved directory. The setting is disabled by default, while the existing protections against sensitive system directories remain active. Thanks again to **@failsafesecurity** for the contribution!

### Fixed
- **Rejected document uploads now fail fast (#257)** — When Gemini Notebook immediately rejects a non-media file, `nlm` now reports the failure on the first terminal status instead of waiting for the full processing timeout. The error includes the source ID and deletion guidance, and source listings expose the numeric processing status for diagnosis. Audio and video uploads retain their transient-processing tolerance. Thanks to **@ericvael** for the detailed reproduction data!
- **Refreshed authentication cookies are persisted** — Rotated cookies are now saved together with refreshed CSRF and session tokens, preventing a successful refresh from leaving stale credentials on disk.
- **Regular notes no longer appear as mind maps (#258)** — Mind-map discovery now excludes ordinary saved notes. Thanks to **@hansschenker** for the contribution!
- **Newer Studio mind maps download correctly (#258)** — Mind maps returned through Gemini Notebook's shared type-4 Studio format are now classified by subtype and downloaded as their embedded JSON instead of being treated as quizzes or flashcards. Thanks again to **@hansschenker** for the contribution!

### Documentation
- Documented the opt-in upload and download directory controls and the observed type-4 mind-map format.

## [0.8.7] - 2026-07-14

### Added
- **JSON output parity for scripting and agents (#256)** — Added `--json` support to source add/delete, notebook delete, and every Studio creation command. Noun-first and verb-first command styles now expose the same JSON options, with machine-readable IDs and deletion confirmations.
- **Notebook emoji and query context in JSON (#256)** — `nlm notebook get --json` now includes the notebook emoji, and `nlm notebook query --json` includes the original question alongside the answer and citations.

### Fixed
- **Mind maps mislabeled as flashcards in Studio status** — Gemini Notebook now returns saved mind maps through the shared Studio type code `4` with subtype `4`. Status parsing now identifies them as `mind_map`, avoids counting their metadata as flashcards, and deduplicates entries returned by both status paths.
- **Drive-picker PDFs mislabeled as Word documents** — When Gemini Notebook returns the ambiguous source type code `14`, source listing and content metadata now prefer an explicit `application/pdf` MIME type. The raw numeric code remains unchanged for compatibility.

### Documentation
- Updated the CLI and AI-facing command references for the new JSON output options and documented the live-observed Studio mind-map subtype.

## [0.8.6] - 2026-07-11

### Fixed
- **`nlm doctor auth-replay` false `browser_bound_replay` verdict on merely expired cookies (#248)** — The diagnostic previously compared *stale on-disk* cookies (`httpx_saved`, `httpx_after_rotate`) against an *always-fresh* live browser session (`cdp_in_page`). Since a live session's cookies are fresh by construction, that comparison could not distinguish ordinary cookie expiry from genuine device-bound replay — both produce the exact same pass/fail pattern. The diagnostic now re-extracts cookies from the same live browser session used for the CDP probe and replays them through plain httpx (new `httpx_fresh` lane) before drawing a conclusion. If fresh cookies succeed over httpx, the verdict is now the new `stale_cookies` (run `nlm login`, no transport needed); `browser_bound_replay` is only reported when even freshly re-extracted cookies fail outside the browser. Thanks to **@leomesheti-crypto** for the detailed controlled-comparison report that caught this.

### Changed
- **`nlm doctor auth-replay` now reports four lanes** instead of three: saved-cookie httpx replay, httpx after forced cookie rotation, fresh-cookie httpx replay, and the in-page CDP fetch. `--no-cdp` skips the two browser-backed lanes together.
- Updated `docs/AUTHENTICATION.md` to describe the corrected four-lane diagnostic and clarify when the experimental `NOTEBOOKLM_RPC_TRANSPORT=cdp` transport is actually justified.

### Other
- README: moved the "Buy Me a Coffee" call-out from a low-visibility badge in the top badge row to a prominent, centered block near the top of the page.

## [0.8.5] - 2026-07-10

### Added
- **Opt-in tool gating** — You can now restrict the tools exposed to your AI agent by setting the `NOTEBOOKLM_DISABLED_GROUPS` environment variable. This saves significant context window tokens for agents that only need a subset of functionality. Huge thanks to **@KoscheiiB** for the excellent PR! (#254)

### Fixed
- **Flaky test in parallel freshness checks** — Fixed a race condition in the test suite that caused intermittent failures during the Drive source freshness fan-out. Thanks again to **@KoscheiiB** for identifying the root cause and proposing the fix! (#255)

## [0.8.4] - 2026-07-09

### Fixed

- **Hardened CDP auth and Windows test failures (PR #253)** — Eliminated a redundant lock-reset in `cdp.py` that created a race condition where a newly opened WebSocket could be prematurely closed. Thanks to **@insane66613** for the PR!
- **Test storage isolation** — Added `conftest.py` with autouse fixtures to isolate test execution from user storage, preventing tests from silently overwriting real user credentials in `~/.notebooklm-mcp-cli/auth.json`. (Cherry-picked from PR #252)

## [0.8.3] - 2026-07-05

### Added

- **Experimental browser-backed RPC transport (`NOTEBOOKLM_RPC_TRANSPORT=cdp`)** — Routes normal batchexecute RPCs and notebook chat through `fetch` inside the saved Gemini Notebook browser profile so Chrome supplies live browser-bound cookies. Off by default; use only when `nlm doctor auth-replay` shows `cdp_in_page` succeeds but normal replay fails. See `docs/AUTHENTICATION.md` for usage.
- **CDP transport support for notebook chat** — `GenerateFreeFormStreamed` queries are routed through the experimental CDP transport when the flag is enabled, with longer CDP response waits to handle long answers.
- **Tests for CDP transport** — Focused tests for transport routing, streamed query routing, long CDP timeouts, and browser lifecycle cleanup.

### Fixed

- **MCP `notebook_query` cancellation crash** — The query tool is now `async` and dispatches blocking I/O to a thread via `anyio.to_thread.run_sync` with `abandon_on_cancel=True`, so MCP client cancellation no longer leaves the server in an inconsistent state.

### Changed

- **`nlm doctor auth-replay` CDP probe uses the shared fetch helper** — The diagnostic path now exercises the same `fetch_form_in_page` helper used by the real experimental transport, keeping the two code paths consistent.
- **`execute_cdp_command` accepts a `response_timeout` parameter** — The default 30 s WebSocket wait is now configurable so long-running in-page fetches (e.g. streamed notebook queries) do not time out prematurely.
- **`find_existing_nlm_chrome` accepts `include_headless`** — Interactive login keeps the existing `False` default; the browser-backed RPC transport passes `True` to reuse profile-owned headless browsers.

## [0.8.2] - 2026-07-03

### Added

- **`nlm doctor auth-replay` diagnostic command** — Compares saved-cookie replay through normal `httpx`, `httpx` replay after a forced Google `RotateCookies` call, and optional in-page CDP fetch from the saved Chrome profile. Verdicts distinguish ordinary cookie freshness failures from likely browser-bound replay behavior, giving actionable next steps for issue #248.
- **Best-effort Google `RotateCookies` support during auth token refresh** — When refreshing auth tokens, the client now attempts a `RotateCookies` call to keep cookies fresh before replay.

### Fixed

- **Auth replay diagnostic HTTP probes matched to normal RPC headers** — Bare `httpx` requests were producing false `browser_bound_replay` verdicts; probes now use the same headers as normal Gemini Notebook RPC calls.
- **`nlm login --check` confirms auth redirects with a real RPC (Fixes #250)** — The homepage probe now validates with a lightweight Gemini Notebook RPC before reporting cookies as expired, eliminating false-positive expiry reports. Thanks to **@laofun** for reporting and contributing this fix!
- **Preserved raw Chrome cookie-list handling across auth checks** — Cookie lists were being flattened too early, causing duplicate cookies to clobber each other before auth checks ran.
- **Preferred exact `.google.com` cookie values when flattening duplicates (Fixes #249)** — When browser cookies contain duplicates, the `.google.com`-domain value is now preferred, preventing stale subdomain values from overriding the correct one. Thanks to **@laofun** for reporting and contributing this fix!
- **Persisted Gemini Notebook build label from profile metadata** — Diagnostics and replay checks now use the current saved build label instead of always re-fetching it.

## [0.8.1] - 2026-07-01 - Happy Canada Day 🇨🇦

### Fixed

- **`nlm login --check` crash on slow accounts (Fixes #243, PR #245)** — Auth checks now use the lightweight Gemini Notebook homepage probe instead of the full notebook-list RPC, and notebook counts are fetched as a best-effort extra so large accounts no longer crash the command with a raw timeout. Connect-phase RPC failures are retried safely without retrying read/write timeouts that may have already reached Gemini Notebook. Thanks to **@LesleyMurfin** for the report, careful fix, and regression coverage!
- **CDP reuse with foreign Chrome on port 9222 (Fixes #244, PR #246)** — `find_existing_nlm_chrome()` now verifies mapped Chrome PIDs still use the NLM profile's `--user-data-dir` and the expected `--remote-debugging-port`, skips headless automation browsers on all platforms, and clears stale port-map entries instead of reconnecting to unrelated CDP listeners such as agent-browser or Playwright. Thanks to **@syf2211** for the focused Windows CDP fix and tests!
- **Exact CDP ownership matching** — Tightened the follow-up validation for mapped Chrome processes so `--user-data-dir` and `--remote-debugging-port` must match exactly, preventing prefix matches such as `chrome-profile-other` or port `92222` from being accepted as the intended NLM profile/port.

## [0.8.0] - 2026-06-30

### Added

- **Short Video Overview format** — `video_format="short"` (CLI: `nlm video create <id> --format short`) generates Gemini Notebook's new ~60-second, vertical "bite-sized overview" video format, announced by Google on 2026-06-30. Like Cinematic, Short has no visual style picker (`--style`/`--style-prompt` map into `--focus`) and is currently English-only, 18+, and rolling out gradually to Pro/Ultra accounts. The request payload was verified via a live network capture against a production Gemini Notebook account.
- **Studio artifact source provenance (PR #240)** — `studio_status` and `nlm studio status --json --full` now include each artifact's `source_ids`, allowing callers to trace generated podcasts, videos, reports, slide decks, infographics, quizzes, flashcards, and data tables back to their source documents. The parser handles the nested source-ID shapes returned by current Gemini Notebook responses. Thanks to **@tonhuu96** for identifying the missing capability and contributing the end-to-end implementation!

### Fixed

- **Actionable file-source upload errors** — File upload failures now preserve the concrete reason and received path instead of returning only `Could not add file source.` The hint clarifies that paths must be accessible on the machine running `nlm` or the MCP server, which makes different-host and remote MCP failures diagnosable.

### Documentation

- **Closed-loop "Refactor with Gemini Notebook" workflow (#239)** — Added a reference workflow and a corresponding skill trigger for iteratively refactoring documents using Gemini Notebook as the editing loop.
- **Regional audio accent locales** — Documented the observed BCP-47 region behavior for Audio Overviews: `es`/`es-ES` selects Spain Spanish, while `es-US`/`es-419` selects Latin-American Spanish. The same regional locale can be supplied through `NOTEBOOKLM_HL`.
- **Packaged skill capability audit** — Brought the installable Gemini Notebook skill and references in sync with the current 39-tool MCP surface and CLI. Updated authentication semantics, async query tools, research auto-import and 15-minute polling, labels, bulk source and sharing operations, artifact source provenance, server-local file paths, remote MCP security, RPC drift recovery, current command syntax, pipeline/batch examples, and consolidated tool contracts.

## [0.7.7] - 2026-06-19

### Fixed

- **SOCKS proxy environments failed during HTTP client initialization (Fixes #237)** — The package now installs HTTPX with its SOCKS transport dependency. Environments that provide outbound access through `ALL_PROXY=socks5://...` or `socks5h://...` no longer fail with a missing `socksio` import before the first request. Sync and async client initialization are covered by regression tests and were verified through a live SOCKS5 proxy.

### Documentation

- **Remote MCP deployment guide (Issue #238)** — Added a dedicated guide explaining Claude web/mobile connector requirements, the separate MCP and Google authentication layers, external-bind security, single-account behavior, remote file limitations, supported deployment boundaries, and Claude Code Remote Control as the recommended mobile-access alternative.

## [0.7.6] - 2026-06-16

### Added

- **Skip Drive freshness checks for large notebooks** — `source_list_drive` now accepts `skip_freshness=True`, and `nlm source list <notebook-id> --drive --skip-freshness` returns the source list without making one freshness API call per Drive source. This gives users with very large notebooks a fast listing path when freshness status is not needed. Skipped freshness is reported as unknown (`stale: null` / `is_stale: null`), not fresh.

### Changed

- **Release publish workflow now gates PyPI publishing** — The publish workflow now runs version alignment, ruff lint/format checks, and the non-E2E pytest suite before building and publishing. This catches release-blocking failures inside the publishing workflow before uploading to PyPI.

## [0.7.5] - 2026-06-15

### Fixed

- **Layering violation on RPCDriftError** — The `RPCDriftError` was bypassing the service layer error wrapping, exposing raw exception types instead of the friendly `ServiceError` payload. It is now correctly wrapped while perfectly preserving the actionable `NOTEBOOKLM_RPC_OVERRIDES` hot-patch instructions for the user.

### Community

- **Version alignment & PR #233 follow-ups (PR #235)** — Brought version strings back into alignment and silenced a noisy RPC override warning in the logs by dropping it to `INFO` level. Thanks to **@Grobiou** for the cleanups!

## [0.7.4] - 2026-06-15

### Added

- **`research_status`: `auto_import` parameter** — Pass `auto_import=True` and the tool automatically imports discovered sources on completion. No separate `research_import` call needed. When `False` (default), the response includes a `next_action` hint pointing you to the exact `research_import` call to make. Fixes the empty-notebook-shell problem reported in #231.

### Fixed

- **`source_list_drive` timeouts on large notebooks (Fixes #232)** — Drive-source freshness checks were made one at a time, in sequence. A notebook with 50 Drive sources took ~30 seconds and routinely hit the 30-second timeout. Freshness checks now run in parallel (8 workers). Measured on a live 44-source notebook: 29s sequential → 3.1s parallel, zero rate-limit errors. If one source's freshness check fails, that source reports `stale: null` instead of failing the whole list.
- **`research_status` default timeout too short for deep research** — The MCP default was 5 minutes; deep research frequently runs longer. Default `max_wait` bumped to 15 minutes (900s), poll interval stays 30s. The CLI `--auto-import` flow is now consistent: same 15-minute / 30-second cadence instead of the old mode-specific 10-minute / 10-second split.
- **RPC drift detection silent on empty responses (PR #233, follow-up)** — The `RPCDriftError` doc said "instead of returning silently" but the code still returned `None` silently when the response had no `wrb.fr` chunks to compare against. Clarified the behavior in `CLAUDE.md` and added the MCP server restart requirement to the `NOTEBOOKLM_RPC_OVERRIDES` hot-patch instructions.

### Community

- **RPC resilience (PR #233)** — Runtime RPC-ID overrides via `NOTEBOOKLM_RPC_OVERRIDES`, loud `RPCDriftError` on rotation detection, and exponential-backoff retry for `RESOURCE_EXHAUSTED` (code 8) throttling. Thanks to **@Grobiou** for the contribution!

## [0.7.3] - 2026-06-09

### Added

- **Scripting & Automation section in CLI_GUIDE.md (PR #226)** — Documents how to reliably parse `--json` output in automation scripts using a JSON parser rather than string splitting. Thanks to **@JanaGK2** for the first contribution!

### Fixed

- **Reverted ChatGPT file bridge (PR #220)** — The ChatGPT file upload/download bridge introduced an SSRF vulnerability (no hostname validation on downloaded URLs), a disk leak (every `source_get_content` call wrote files to disk with no cleanup), and unintended behavioral changes to `source_get_content` and `download_artifact` for all users. The feature has been reverted. A future release will re-introduce the polling improvements (`wait`/`poll_interval`) cleanly, and the ChatGPT integration may return in a hardened form.
- **Tightened `no_proxy` sanitization** — The v0.7.2 sanitizer stripped all `no_proxy` entries containing `:`, incorrectly removing legitimate IPv6 loopback addresses (`::1`) and `host:port` entries. The fix now targets only CIDR-style IPv6 entries (e.g., `fe11::/16`) that crash httpx's URL parser, preserving all other valid entries.

## [0.7.2] - 2026-06-08

### Fixed

- **Modern Chrome Cookie DB path detection (PR #222)** — Improved the SQLite cookie database location search logic for Google Chrome to work correctly with modern Chrome setups. Thanks to **@insane66613**!
- **Profile-aware headless refresh (PR #223)** — Fixed headless login refresh to use the default/active profile configured in the CLI configuration file instead of falling back. Thanks to **@insane66613**!
- **`AuthHealthChecker` API fallback passed wrong cookie format, causing false `stale` on semi-stale sessions (PR #225)** — The API fallback flattened `profile.cookies` to a dict, dropping domain-specific duplicates and omitting `session_id` / `build_label`. The API probe now passes `profile.cookies` unchanged with all session fields, matching `nlm login --check`. Thanks to **@insane66613**!
- **`server_info`, `refresh_auth`, and `studio_create` disagreed on semi-stale auth (PR #225, Fixes #224)** — These three MCP paths each ran independent auth checks, so `server_info` could report `stale` and `studio_create` refuse to run while `notebook_list` and CLI tools worked fine. All MCP auth gates now share `credentials_are_usable()` (`AuthHealthChecker` + live API confirmation), eliminating split-brain results. Thanks to **@insane66613**!
- **Sanitize `no_proxy` environment variable (PR #221)** — Fixed package import crashes on Windows systems caused by CIDR-style IPv6 entries in `no_proxy` that httpx cannot parse. Thanks to **@insane66613**!

## [0.7.1] - 2026-06-06

### Fixed

- **`server_info` reported `"stale"` for valid semi-stale cookies (PR #219)** — Google enforces different session lifecycles for the Gemini Notebook homepage (a navigation endpoint) and the RPC API endpoints. Cookies that are "semi-stale" — rejected by the homepage with a redirect to `accounts.google.com`, but still 100% accepted by the RPC API — were causing the MCP `server_info` tool (and `nlm login --check`) to falsely report `"stale"` even though every actual API tool would work fine. The new `AuthHealthChecker` runs a homepage probe first and, on `expired` / `http_401` / `http_403`, falls back to a live `NotebookLMClient.list_notebooks()` call before deciding. The homepage headers were also upgraded to use the full browser-like `_PAGE_FETCH_HEADERS` (including `Sec-Fetch-Dest` / `Sec-Fetch-Mode` / `Sec-Fetch-Site` / `Sec-Fetch-User`) — without them Google was bot-detecting the homepage check and redirecting even fresh cookies, producing false `"stale"` reports on first probe. Results are cached for 30 seconds with mtime-based bypass, so an external `nlm login` is reflected without waiting for the TTL. The CLI and MCP now share the cache via the `get_auth_health_checker()` singleton in `services/auth.py`. Thanks to **@SERDAR-AKIN** for the original multi-probe design and PR #219!

### Changed

- **`AuthHealthChecker` lives in `services/auth.py`, not `core/auth.py`** — the multi-probe orchestration, 30-second cache, and verdict aggregation are business logic and belong in the services layer per the layering rule in `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`. `core/auth.py` stays focused on the low-level auth primitives (`AuthManager`, `AuthTokens`, `check_auth`, `save_tokens_to_cache`, `load_cached_tokens`, `_fetch_notebooklm_homepage`).
- **`server_info` docstring no longer calls `auth_status` a "live check"** — it is cached for 30 seconds with mtime-based bypass. `docs/AUTHENTICATION.md` documents the same contract for `nlm login --check` (always live) vs `server_info` (cached).
- **`AuthHealthReport.valid` is now `verdict == "configured"` (was `!=`)** — the field was inverted: it returned `True` for `stale` / `unverified` / `not_configured` reports. Pinned by `TestReportValid` in `tests/services/test_auth_health.py`.
- **API-probe exceptions are classified as transport errors when they are** — `_probe_api` now catches `httpx.TimeoutException` and `httpx.RequestError` explicitly and emits the `"network_error:"` prefix so `_determine_verdict` can route them to `"unverified"`. Previously all exceptions emitted `f"{type(e).__name__}: {e}"`, which meant a real transport error on the API path was misclassified as an auth failure (`"stale"`). Pinned by `TestProbeApiErrorClassification` in `tests/services/test_auth_health.py`.

## [0.7.0] - 2026-06-03

### Added

- **Studio prompting guide and fast-track agent behavior** — AI agents using the MCP skill now follow a fast-track prompting model: infer format, style, and prompt from context, emit a one-line notice, and generate immediately — no multi-question intake questionnaires. A guided preview mode (show settings + full prompt before generating) kicks in only for vague requests, high-stakes content (e.g. cinematic video), or when the user explicitly asks. Two new reference documents ship with the skill: `references/studio-prompting-guide.md` (per-artifact decision trees, prompt parameters) and `references/studio-prompt-examples.md` (copy-paste templates). SKILL.md and `workflows.md` updated throughout.
- **Cinematic video format** — `video_format=cinematic` is now documented and supported in the skill, CLI, and MCP guide. Cinematic videos take the full creative brief via `focus_prompt` / `--focus`; `--style` is not applicable.

### Fixed

- **Query returns thinking step instead of short answer (Issue #214)** — When the AI's final answer was under 20 characters, for example `ANSWER: C` from a multiple-choice prompt, `nlm` discarded it and returned the longest thinking chunk instead. The 20-char guard in `_extract_answer_from_chunk` (both the list-form and string-form branches) was redundant with the existing type indicator at `first_elem[4][-1]` (1 = answer, 2 = thinking), which is the authoritative discriminator. Removed both guards. The type indicator still routes short thinking chunks to the thinking bucket, so behavior for normal answers is unchanged. 4 new regression tests in `TestShortAnswerRegression` cover: short answer wins over a longer thinking chunk, single-character answers, short thinking chunks still filtered as thinking, and the string-form first_elem path.
- **`nlm notebook create` missing `--json` (Issue #215)** — Every other notebook verb (`list`, `get`, `describe`, `query`) already supported `--json`, but `create` did not. This was a real friction point for agent workflows that need to capture the new notebook ID reliably. Added the flag; the output is the same `notebook_id` / `title` / `url` / `message` dict that other verbs return, so scripting just works. Thanks to **@SimonMallas** for the report and end-to-end test in the issue!
- **`auth_status = "stale"` was misleading (Issue #215)** — The MCP `server_info` tool (and `nlm login --check`) reported `"stale"` for any non-`configured` / non-`not_configured` outcome, which silently grouped three very different conditions together: (a) credentials are actually expired and operations will fail, (b) the live check hit a network error/timeout/non-200 and cached creds may still work, and (c) the saved profile failed to load. The new state machine splits this into two distinct values: `"stale"` is reserved for cases (a) and (c) where the user genuinely needs to `nlm login`, and a new `"unverified"` reports case (b) so agents don't pester users to re-auth on transient network blips. Unknown future reasons stay conservative (`"stale"`). No raw `AuthCheckResult.reason` strings are exposed; only the 5 stable status values. The new `Understanding auth_status` section in `docs/AUTHENTICATION.md` documents each state and what to do.
- **`format_item` silently discarded plain-dict results** — All three formatter classes (`TableFormatter`, `JsonFormatter`, `CompactFormatter`) checked for `model_dump` / `__dict__` before `isinstance(item, dict)`. Because `TypedDict` instances are plain `dict` at runtime (no `model_dump`, no per-instance `__dict__` in CPython), they fell through to the worst-case path: `JsonFormatter` wrapped the payload as `{"value": {...}}` instead of printing it flat, and `CompactFormatter` emitted `str(item)` (the raw dict repr) instead of the notebook ID. Fixed by adding `isinstance(item, dict)` as the first branch in all three `format_item` methods. `nlm notebook create --json` and pipe capture now work correctly.
- **HTTP 401/403 misclassified as `"unverified"` in `server_info`** — The `reason.startswith("http_")` catch-all in `_check_auth_status` mapped every non-200 response — including definitive credential-rejection codes 401 and 403 — to `"unverified"` ("cached credentials may still work, do not prompt re-auth"). Added explicit `http_401` / `http_403` → `"stale"` guards before the general `http_` branch so agents correctly prompt re-authentication when cookies are genuinely rejected by Gemini Notebook.

### Documentation

- **New `docs/GETTING_STARTED.md` guide** — First-time setup, agent registration, and a full 5-step migration path from a browser-automation–based Gemini Notebook MCP (the kind of setup reported in Issue #215). The migration section explicitly calls out removing any legacy `notebooklm` server config as the #1 cause of "Hermes picked the wrong tool" symptoms. README is no longer carrying the migration content; the docs index now points at the new guide. (Issue #215, items 3 and 5)
- **`MCP_GUIDE.md` server-naming note** — Recommends the default `notebooklm-mcp` server name and warns against generic names that collide with legacy MCPs. (Issue #215, item 5)

## [0.6.15] - 2026-06-01

### Fixed

- **Auth-guard stale-TTL window when tokens change on disk during the cached period** — The 60s auth-guard introduced in 0.6.14 cached the "auth is valid" result for 60s. If you ran `nlm login` (or any flow that rewrote the auth file) during that window, the guard would still report valid and your server would use the stale tokens until the TTL elapsed. Fixed by `services.auth.get_active_auth_mtime()`: the guard now records the latest mtime of the active auth storage (the legacy `auth.json` plus every `cookies.json` under `profiles/`) and invalidates the cache when any of them changes. A write to ANY profile's file invalidates the guard, regardless of which profile the CLI/MCP session is using. 5 new tests cover modern profile layout, legacy fallback, mid-migration (both files exist), fresh install (no files), and config-error defensiveness.

- **Auth-guard mtime check was watching the wrong file (caught by live testing)** — The first iteration of the mtime fix only watched the config's `default_profile`'s `cookies.json`. But the active profile for a CLI/MCP session can be overridden with `--profile`, while the config-level `default_profile` stays put. If you ran `nlm login --profile <other>` externally, the active profile's `cookies.json` would be rewritten but the guard never saw it. The fix above resolves this by globbing all `profiles/*/cookies.json` files. Live testing against a real Chrome login + real Gemini Notebook API confirmed the fix.

### Changed

- **`services/auth.py` is now a full shim, not a single-symbol re-export** — The 0.6.14 release added `services/auth.py` to route `check_auth` through the services layer. This release extends it to cover all 6 auth symbols that the cli/ and mcp/ layers were importing directly from `core/`: `check_auth`, `load_cached_tokens`, `save_tokens_to_cache`, `get_cache_path`, `validate_cookies`, plus the two class symbols `AuthTokens` and `AuthManager` via PEP 562 `__getattr__`. The shim is a thin layer with no business logic of its own; behavior is unchanged. The only remaining direct `core.auth` import in cli/ or mcp/ is in `utils/cdp.py`, which has a circular-import guard and is explicitly outside the layering rule's scope.

## [0.6.14] - 2026-06-01

### Fixed

- **`nlm login` crash on fully expired auth (PR #211 / Issue #210)** — When the stored Google session/cookies were fully expired, `_validate_saved_profile()` raised `ClientAuthenticationError`, which does **not** inherit from `NLMError`. The `except NLMError:` clause in `login_callback` missed it, so the exception bubbled up to `cli_main()` and exited the process before ever launching Chrome for interactive sign-in. Users had to manually delete all profiles as a workaround. Fixed by also catching `ClientAuthenticationError` in the validation catch. Thanks to **@insane66613** for the fix!
- **MCP silent auth/studio failures (PR #212)** — Three related silent-failure bugs in the MCP server under stale/expired auth:
    1. `refresh_auth()` returned `status: "success"` after reloading dead tokens from disk. A disk reload is not a successful re-auth — now runs `check_auth(live=True)` after the reload and returns `status: "expired"` with an actionable `nlm login` hint if tokens are dead.
    2. `studio_create()` had no pre-flight auth check, so it returned `status: "success"` with an `artifact_id` that failed seconds later — sending agents into pointless polling loops. Now runs `check_auth(live=True)` after the network-free confirmation preview and artifact-type validation; invalid auth returns `status: "error"` with an `nlm login` hint before any doomed request is fired.
    3. `studio_status()` surfaced `status: "failed"` artifacts with every other field `null` and no reason, so callers had no way to know why. The raw gRPC payload carries no error string, so `get_studio_status()` now synthesizes a non-null `error_reason` for failed artifacts while preferring any real `error_reason` / `failure_reason` / `failure_code` / `error` key if a future API version exposes one. 12 new tests cover the full matrix (one is parametrized with 4 cases). Thanks to **@idankatz64-commits** for the comprehensive PR and tests!
    - The pre-flight `check_auth(live=True)` adds ~1 homepage fetch on the `confirm=True` path of `studio_create` and on every `refresh_auth`. A network-free preview path is preserved for `confirm=False`.

### Changed

- **`ArtifactInfo` gains an optional `error_reason` field** — Returned by the MCP `studio_status` tool. `None` for healthy artifacts; a synthesized string for failed artifacts (with a hint to re-check auth); verbatim from the API if a real `error_reason`/`failure_reason`/`failure_code`/`error` key is present. Backward-compatible: existing callers that only inspect `status` are unaffected.
- **Bounded in-process conversation history cache (Issue #213)** — The in-process cache of conversation history used to grow without bound, so a long-lived MCP server (typical for an always-on assistant) eventually OOM'd the host. The cache is now bounded by three new env-var knobs (set any to `0` to disable that specific cap):
    - `NOTEBOOKLM_CONVERSATION_MAX_TURNS` (default `50`) — max turns kept per conversation. Older turns are FIFO-dropped; survivors are renumbered `1..N` so `turn_number` stays a stable 1-indexed position in the current list.
    - `NOTEBOOKLM_CONVERSATION_MAX_CONVS` (default `500`) — max distinct conversations cached. On overflow, the least-recently-used conversation is evicted. Writes and reads both promote to MRU.
    - `NOTEBOOKLM_CONVERSATION_MAX_CHARS_PER_TURN` (default `100000`) — per-turn answer character cap as a safety net against pathological payloads. Queries are user input and not truncated.
    - Public introspection: `get_conversation_cache_stats()` returns `{conversations, total_turns, max_turns_per_conversation, max_conversations, max_chars_per_turn}`.
    - 13 new tests cover defaults, env-var overrides, invalid-fallback, `0`=unlimited, negative-clamp-to-zero, FIFO trim with renumber, LRU eviction on insert, LRU promotion on read, LRU promotion on write, LRU promotion when migrating to a pre-existing key, answer truncation, stats accuracy, and clear compatibility.
    - The `--stateless` flag and `NOTEBOOKLM_MCP_STATELESS` env var continue to control the MCP HTTP transport layer only — they do not affect this cache.

## [0.6.13] - 2026-05-27

### Security

- **TOCTOU-safe credential file creation (PR #205)** — All credential files (`auth.json`, `cookies.json`, `metadata.json`, port map) were previously written with default permissions and then `chmod`'d to `0o600` — leaving a brief window where the file was world-readable. Fixed using `os.open()` + `os.fdopen()` so the file descriptor is created with `0o600` from the start. Thanks to **@Amy-Ra-lph** for the PR and thorough implementation!
- **HTTP and SSE external-bind enforcement** — Running `notebooklm-mcp --transport http --host 0.0.0.0` (or `--transport sse`) previously emitted a warning but still bound to the external address. The server now refuses to start unless `NOTEBOOKLM_ALLOW_EXTERNAL_BIND=1` is explicitly set, preventing accidental cookie exposure on untrusted networks. The guard now covers both HTTP and SSE transports.
- **GitHub Actions pinned to full commit SHAs (PR #207)** — All four workflow files now pin third-party actions (`actions/checkout`, `astral-sh/setup-uv`, `pypa/gh-action-pypi-publish`, `softprops/action-gh-release`) to their full 40-character commit SHAs with a version comment for readability. Prevents tag-drift supply chain attacks. Thanks to **@Amy-Ra-lph** for the careful SHA verification!

### Fixed

- **`terminate_chrome()` null-safety (PR #205)** — On double-call, `_cached_ws.close()` could raise `AttributeError` because `_cached_ws` was read after being set to `None`. The reference is now captured before the try block. Thanks to **@Amy-Ra-lph**!
- **Cookie key whitespace handling (PR #205)** — Added `.strip()` to cookie key parsing in `save_auth_tokens` to handle edge cases with leading/trailing whitespace in cookie headers.
- **Auth check consistency (PR #203)** — Unified auth checking logic under a single `check_auth()` function with a typed `AuthCheckResult`, eliminating subtle differences between the MCP and CLI auth status paths. Thanks to **@derekszen** for the clean refactor!

### Changed

- **Exponential backoff for source reconciliation polling** — `_reconcile_source()` (the fallback poller that verifies a source landed after an ambiguous gRPC error) previously used a fixed 1-second delay between polls. Now uses exponential backoff (1s → 2s → 4s, capped at 4s) to reduce unnecessary API calls on slower operations.
- **File path canonicalization for uploads** — `add_file()` now calls `.expanduser().resolve()` on the input path, so paths like `~/Documents/file.pdf` work correctly and symlinks are fully resolved before validation.
- **`raw_response` field removed from `query()` return** — The `raw_response` key was included in the dict returned by `ConversationMixin.query()` but was never read by any caller (services, MCP tools, or CLI). Removing it avoids leaking raw API response text into any future log aggregators or serializers.

## [0.6.12] - 2026-05-24

### Fixed

- **Manual login Netscape cookie parser fixes (PR #199 / Issue #198)** — Fixed three bugs in the Netscape/Mozilla cookie file parser used in `nlm login --manual`:
  * Resolved a critical bug that treated `#HttpOnly_` lines as comment rows and silently ignored them, which dropped essential Google authentication cookies like `__Secure-1PSIDTS` and `__Secure-3PSIDTS` (resulting in cryptic 401 errors).
  * Allowed empty-value cookies to be parsed with a value of `""` instead of being skipped by ensuring trailing tab characters are not stripped from the end of the line.
  * Hardened value extraction to defensively join tab-containing cookie values instead of truncating them.
  * Added 4 new test cases to prevent future regressions. Thanks to **@pan-long** for the comprehensive PR and excellent troubleshooting!
- **MCP `source_add` tool and `SKILL.md` file-type alignment (PR #197)** — Updated the `source_add` MCP tool docstring and the global `SKILL.md` guidelines to list all 18 supported file-type extensions (`PDF, TXT, MD, DOCX, CSV, EPUB, MP3, M4A, WAV, AAC, OGG, OPUS, MP4, JPG, JPEG, PNG, GIF, WEBP`) instead of a restricted subset. Also documented how image-bearing sources are ingested to feed the Studio video generation's visual-crop pipeline to generate on-screen visual aids in Video Overviews. Thanks to **@Premshay** for the excellent documentation enhancement and detailed research on the visual-crop pipeline!

## [0.6.11] - 2026-05-22

### Fixed

- **False-negative errors on `source_add` and `research_import` (Issue #196)** — `source_add` (text, URL, Drive) and `research_import` were reporting `"Could not add ... source."` errors even when Gemini Notebook had successfully accepted the source for asynchronous processing. Root cause: Gemini Notebook uses the same gRPC error code `3` in the `wrb.fr` response envelope for both "accepted-pending" (async processing started) and "genuine rejection". Added a `_reconcile_source()` helper that polls `get_notebook_sources_with_types()` after a code 3 or 9 error to verify whether the source actually landed. If found → returns success. If not found after polling → re-raises the original error so genuine failures still surface. Also fixed a secondary double-submission bug where URL sources on accounts using the v1 (`izAoDd`) RPC would trigger a spurious v2 (`ozz5Z`) call when v1 returned an accepted-pending code 3 — reconciliation now short-circuits the fallback if v1 actually delivered. 12 new unit tests added (total: 875 tests). Thanks to **@mdshearer** for the detailed report and excellent root cause analysis!
- **Snap Chromium profile directory (PR #195)** — On Ubuntu and other distros, Chromium installed as a Snap package is confined by AppArmor and can only write to `~/snap/<snap-name>/common/`. Launching with `--user-data-dir=~/.notebooklm-mcp-cli/` was failing with `Exit code 21: Failed to create a ProcessSingleton`. Snap browsers are now detected via `/snap/` in the resolved binary path and automatically redirected to `~/snap/chromium/common/notebooklm-mcp-cli/chrome-profiles/`. Profile lock, headless auth, and cache cleanup are all snap-aware. Thanks to **@ildella** for the contribution!
- **Audio download 403 on cross-domain CDN (PR #193)** — Audio artifacts downloaded via `nlm download audio` were returning HTTP 403 from Google's CDN (`lh3.google.com`) because `_download_url` inherited `Sec-Fetch-Site: none` from the page fetch headers. Google's audio CDN treats that value as an unauthorized address-bar navigation and rejects the request regardless of valid cookies. The fix mirrors the header shape Chrome uses for `window.open()` — setting `Sec-Fetch-Site: cross-site` and `Referer: https://notebook.google.com/` on all cross-domain artifact downloads. Verified: same notebook that returned `"Download failed for audio."` now produces a complete 41.7 MB AAC file. Thanks to **@responsiblefleet** for the thorough root cause analysis and fix!

## [0.6.10] - 2026-05-15

### Fixed

- **Windows CDP Authentication Reliability (#192)** — Major stability improvements for authentication on Windows 11. Thanks to **@jonathanzhan1975** for the detailed bug report and testing!
    - Improved Windows Edge detection logic in `nlm doctor` to match the login flow.
    - Optimized CDP port scan timeouts (reduced from 2s to 1s) to prevent 20-second blocks when ports are unresponsive.
    - Added process isolation for Windows via `CREATE_NEW_PROCESS_GROUP`.
    - Added `--disable-features=msEdgeStartupBoost` launch flag to prevent Edge's "Startup Boost" background processes from intercepting CDP sessions.
    - Implemented automated cleanup of stale NLM-spawned browser processes.
    - Enhanced failure diagnostics to log process exit codes when browser initialization fails.

## [0.6.9] - 2026-05-11

### Added

- **Hermes Agent Support** — `nlm skill install hermes` now installs the Gemini Notebook skill for [Hermes Agent](https://github.com/NousResearch/hermes-agent) by NousResearch. Respects the `$HERMES_HOME` environment variable for custom install paths.
- **EPUB File Upload Support (PR #191)** — `.epub` files can now be uploaded as notebook sources. Thanks to **@mateogon** for the contribution!

### Fixed

- **Windows Tool Detection** — `nlm skill install` no longer falsely warns that tools are not installed on Windows. Detection now checks for the tool's binary on PATH and root config directory existence instead of only checking the (possibly non-existent) skills subdirectory.
- **Windows Permission Errors** — `safe_mkdir` now catches `PermissionError` and provides an actionable fix command (`icacls`) instead of a raw traceback. The update-check cache and `print_update_notification()` no longer crash the CLI when the storage directory has restrictive ACLs.
- **Windows Encoding Errors** — All `read_text()` / `write_text()` calls now explicitly specify `encoding="utf-8"` to prevent `UnicodeDecodeError` on Windows systems that default to `cp1252`.
- **CLI Studio Status Missing Mind Maps** — `nlm studio status` now routes through the service layer (`get_studio_status`) so mind maps are included in the output.

### Changed

- **Shared Tool Detection** — Extracted `is_tool_on_system()` helper into `cli/utils.py`, shared by both `nlm skill install` and `nlm setup` to eliminate duplicate detection logic.
- **Typed Skill Config** — `TOOL_CONFIGS` in `skill.py` now uses a `ToolConfig` `TypedDict` instead of `dict[str, Any]` for better type safety.
- **File Upload Docs** — Updated supported file types list to include `.epub` and all audio/image formats actually supported by the API.

---

## [0.6.8] - 2026-05-11

### Fixed

- **Conversation Query Rejection** — Fixed an issue where the notebook query endpoint would reject requests with an opaque error due to strict backend requirements. Explicitly added `Content-Type: application/x-www-form-urlencoded;charset=UTF-8` to the streamed query endpoint. Thanks to **@fabianafurtadoff** for the contribution (PR #189)!

## [0.6.7] - 2026-05-10

### Added

- **Cited-Only Filtering for Research** — Added support for filtering out non-cited sources during research imports. This includes a robust citation parser that handles standard markers (`[1]`), ranges (`[4-6]`), and bibliography extraction. The `research_status` polling output now also annotates sources with a `cited: bool` field for visibility. Thanks to **@zxyasfas** for the contribution (PR #188)!

### Fixed

- **Audio Download Extension Validation (Issue #185)** — `nlm download audio` now rejects incompatible file extensions (like `.mp3` or `.wav`) instead of writing AAC data with the wrong file extension. A helpful hint now suggests using `.m4a` or `.mp4` and provides an `ffmpeg` command for conversion.
- **Conversation Query Hangs** — Replaced direct `client.post()` with a fresh `httpx.Client()` context in conversation queries to prevent internal connection pool exhaustion or unexpected hangs during repeated querying.
- **Fuzzy Title Matching in Research** — Upgraded the research citation title matcher from basic substring checks to whitespace-aware boundary regex, preventing false positives where a short title matches a substring of a longer word.

---

## [0.6.6] - 2026-05-07

### Fixed

- **Opaque error on capacity throttle (Issue #182)** — When Gemini Notebook returns `RPCError code=8` (RESOURCE_EXHAUSTED) with a `UserDisplayableError` payload, the error message now surfaces the human-readable text instead of the raw protobuf type URL. Added `ResourceExhaustedError(RPCError)` subclass so callers can catch throttle errors distinctly. Studio artifact creation now provides retry-specific hints. Thanks to **@nikolaykazakovvs-ux** for the detailed report!

- **Cinematic video silently ignores --style-prompt (Issue #183)** — `--style-prompt` with cinematic format now maps to `custom_instructions` (same API field as the web UI's "Customize Video Overview" dialog) instead of being silently dropped. `--style` still rejects for cinematic since visual style codes don't apply. Validation now runs before source resolution for faster feedback. Thanks to **@guia-matthieu** for the report!

### Changed

- Updated README to note Google AI Ultra ($249/mo) compatibility (PR #184). Thanks to **@guia-matthieu**!

---

## [0.6.5] - 2026-05-05

### Fixed

- **Authentication Race Condition (Issue #181)** — Fixed an issue where the `nlm login` CLI and headless authentication flows exited prematurely, resulting in incomplete cookie extraction and subsequent "Authentication expired" errors. Implemented deterministic DOM polling to wait for session tokens (`FdrFJe` or build label) before extracting cookies.

---

## [0.6.4] - 2026-05-04

### Fixed

- **Cross-domain artifact downloads (PR #180)** — Fixed an authentication bug where `OSID` cookies leaked during cross-domain artifact downloads, causing `ServiceLogin` redirects. The `_download_url` method now correctly strips service-scoped cookies for external hosts. Thanks to **@laofun** for this critical fix!

---

## [0.6.3] - 2026-05-04

### Fixed

- **CDP tab creation failures in locked-down environments (Issue #175)** — Added fallbacks to reuse existing tabs if CDP tab creation fails. Removed redundant page fetch and merged reuse loops into one pass.

---

## [0.6.2] - 2026-04-29

### Fixed

- **Login timeout after Google sign-in (#174)** — `is_logged_in()` used substring matching on the full URL, so the post-sign-in redirect URL containing `original_referer=...accounts.google.com...` in the query string was misidentified as a sign-in page. Now parses the URL hostname via `urlparse()`. Thanks to **@SKMKZP** for the clear root cause analysis and fix!
- **Headless browser hijacking during `nlm login`** — `find_any_existing_cdp_browser()` would blindly reuse any Chrome with CDP enabled on ports 9222-9231, including headless instances from other tools (e.g. Perplexity MCP). This caused `nlm login` to silently hang for 5 minutes waiting for sign-in on an invisible browser. Now checks User-Agent for `HeadlessChrome` and skips automation browsers.
- **Silent login wait loop** — When waiting for user sign-in, the CLI now emits status messages instead of hanging silently for up to 5 minutes with no feedback.

### Changed

- Extracted `_fetch_cdp_version()` helper to share `/json/version` logic between `get_debugger_url()` and `find_any_existing_cdp_browser()`.

---

## [0.6.0] - 2026-04-27

### Added

- **Source Label Management** — Organize notebook sources into thematic categories with the new `label` MCP tool and `nlm label` CLI commands. Full action set: `auto` (AI-generated labels), `list`, `create`, `rename`, `set_emoji`, `move_source`, and `delete`. Multi-label assignment supported — sources can belong to more than one label. Requires 5+ sources for auto-labeling.

### Fixed

- **WSL Firewall check encoding (#172)** — PowerShell on Windows commonly returns output in UTF-16-LE, causing a `UnicodeDecodeError` in `check_firewall_rule()` that made `nlm login --wsl` show a false firewall warning even when the rule already existed. Fixed by adding `errors="replace"` to the subprocess call. Thanks to **@andrepreira** for the diagnosis and clean fix!

---

## [0.5.31] - 2026-04-26

### Fixed
- **EOF on Initialization (Issue #171)** — The MCP `stdio` transport strictly requires `stdout` to be used *only* for JSON-RPC messages. `fastmcp` initialization logs (and any other stray `print()` calls) were corrupting the `stdout` stream, causing MCP clients to crash with an EOF error on Windows and macOS. Added a dedicated `_StdoutToStderrWrapper` in `server.py` that intercepts all standard text output and safely redirects it to `stderr`, while preserving the underlying binary `.buffer` for valid JSON-RPC payloads. Thanks to **@swiezaczek** for the thorough analysis in the issue report!

## [0.5.30] - 2026-04-25
### Fixed
- **Auth loop when `NOTEBOOKLM_COOKIES` env var is stale (Issue #170)** — `refresh_auth` now detects when `NOTEBOOKLM_COOKIES` is set in the environment and returns a clear, actionable error instead of falsely reporting "success" while silently reloading the same stale cookies. Auth failure messages now include a note pointing to the env var when it's the likely cause. Thanks to **@nobolso** for the thorough root cause analysis!
- **Deprecated `NOTEBOOKLM_CSRF_TOKEN` / `NOTEBOOKLM_SESSION_ID` env vars removed** — These were still being read and passed to the client constructor, which caused them to bypass auto-refresh when stale. Both are now always auto-extracted; the deprecated env vars are ignored.

### Documentation
- Added troubleshooting section to `AUTHENTICATION.md` explaining the `NOTEBOOKLM_COOKIES` env var override trap, how to diagnose it, and both fix options.

## [0.5.29] - 2026-04-24

### Fixed
- **Python 3.11 TypedDict compatibility (Issue #167)** — Pydantic v2 rejects `typing.TypedDict` on Python < 3.12. All 13 service files now import `TypedDict` from a centralized compat shim (`services/_compat.py`) that uses `typing_extensions` on < 3.12. Added `typing_extensions` as an explicit dependency for Python < 3.12. Thanks to **@irvinghu07** for the clear report and suggested fixes!
- **SOCKS proxy blocks `nlm login` (Issue #167)** — The CDP helper's `httpx.Client` inherited `ALL_PROXY` from the environment, causing `ImportError: socksio not installed` on localhost CDP connections. Fixed with `trust_env=False`. Thanks to **@irvinghu07**!
- **MCP `notebook_list` always returns "Authentication expired" (Issue #169)** — `save_tokens_to_cache()` only wrote to the legacy `auth.json`, but `load_cached_tokens()` prioritizes `profiles/default/cookies.json`. Tokens saved via the MCP `save_auth_tokens` tool were never read back. Fixed by syncing writes to both `auth.json` and the active profile. Thanks to **@nobolso** for the thorough diagnosis and file structure analysis!
- **Python 3.14 Windows `pathlib.mkdir` regression (Issue #169)** — `Path.mkdir(parents=True, exist_ok=True)` raises `FileExistsError` (WinError 183) on Python 3.14 + Windows. Added `safe_mkdir()` wrapper applied to all `mkdir` calls across `config.py`, `auth.py`, `base.py`, and `cdp.py`. Thanks to **@nobolso**!

## [0.5.28] - 2026-04-23

### Fixed
- **HTTP transport: default to stateless mode (Issue #165)** — HTTP transport (`--transport http`) now defaults to stateless sessions, preventing the MCP SDK double-response crash (`AssertionError: Request already responded to`) that killed entire sessions on slow Google API calls. Use `--no-stateless` to opt out. Thanks to **@mylaser215** for the thorough root cause analysis (#165)!

### Changed
- **CLI flags use `BooleanOptionalAction`** — `--stateless` / `--no-stateless` and `--debug` / `--no-debug` are now proper toggle pairs. Environment variables (`NOTEBOOKLM_MCP_STATELESS`, `NOTEBOOKLM_MCP_DEBUG`) accept `true/false/0/1/yes/no/on/off` (case-insensitive).

### Documentation
- **CLI Guide: document all skill install targets (Issue #163)** — Added `agents`, `codex`, `gemini-cli`, and `alef-agent` with install path details. Fixed missing `opencode` in setup clients list.

## [0.5.27] - 2026-04-21

### Added
- **Restore skill targets for codex and gemini-cli (Issue #163)** — Restored the missing target configurations for `codex` and `gemini-cli` agent skills and added Alef Agent specific frontmatter logic. Thanks to the user who reported this issue (#163)!

### Fixed
- **Source: Honour `--title` when adding a file source (PR #162)** — Fixed an issue where adding a file source via CLI ignored the user's custom title. The source upload is now fully awaited before the follow-up rename is fired to guarantee precision. Huge thanks to **@CryptoWombat** for this excellent contribution and thorough fix!

## [0.5.26] - 2026-04-17

### Added
- **`server_info` reports local auth state (Issue #160)** — Response includes `auth_status` (`configured` | `stale` | `not_configured` | `error`) based on cached token presence and age. This is a local disk check only, not a live Google validation; docstring clarifies. Thanks to **@josuebustosn** for the report and expected behavior.

### Fixed
- **Windows Unicode: all CLI Rich consoles use safe factory (Issue #156)** — Every CLI command module and the default `Formatter` now use `make_console()` (`safe_box`, `legacy_windows=False` on Windows) instead of bare `Console()`. Complements the UTF-8 stdio bootstrap from v0.5.25 and avoids `UnicodeEncodeError` / MCP EOF on legacy Windows code pages when printing API text with arrows, smart quotes, etc. Thanks again to **@argonaut-cm** for the original EOF / Unicode analysis (v0.5.25 thanked the stdio + Rich bootstrap; this completes CLI-wide coverage).
- **MCP reloads client after `nlm login` without manual `refresh_auth` (Issue #161)** — `get_client()` now invalidates the singleton when on-disk tokens are newer than the running client (`extracted_at` vs `_created_at`), not only when the cookie dict changes. Same-profile re-auth updates are picked up automatically. Auth expiry error message mentions `refresh_auth` as a fallback. Thanks to **@josuebustosn** for the clear repro and suggested directions.

## [0.5.25] - 2026-04-15

### Fixed
- **Audio download fails with 302→404 (Issue #158)** — Google's audio media list contains multiple URL variants: `=m140-dv` (download variant, fast CDN via `drum.usercontent.google.com`, ~3 MB/s) and `=m140` (streaming transcode via `googlevideo.com`, ~30 KB/s). The download logic now explicitly prefers the `-dv` variant for both `download_audio` and `_extract_audio_media_url`. Audio downloads that previously failed now complete a 47MB file in ~15 seconds. Thanks to **@Victor777777** for the detailed bug report and redirect chain analysis!
- **CDP WebSocket broken with system proxy (Issue #119, PR #157)** — When `HTTP_PROXY` / `HTTPS_PROXY` environment variables are set (e.g., Clash, Surge), `websocket-client` routed localhost CDP connections through the external proxy, crashing `nlm login`. Fixed by temporarily clearing proxy env vars around `websocket.create_connection` in `execute_cdp_command`. The existing httpx fix (#119) only covered HTTP; this completes the WebSocket side. Thanks to **@ahmelkholy** for identifying the issue and contributing PR #157!
- **Windows: MCP server crashes with UnicodeEncodeError (Issue #156)** — On Windows consoles using cp1252 encoding, Rich's legacy renderer crashed on Unicode characters like `→` (U+2192) returned by NotebookLM, killing the MCP server process and causing client EOF disconnects. Fixed by reconfiguring `stdout`/`stderr` to UTF-8 with replacement at process startup (both CLI and MCP entry points) and setting `legacy_windows=False` on Rich Console instances. Thanks to **@argonaut-cm** for the clear traceback and proposed solutions!

### Changed
- **Lazy-load `NotebookLMClient` in package `__init__`** — `from notebooklm_tools import NotebookLMClient` now uses `__getattr__` to defer the heavy import until first access, keeping the stdio encoding bootstrap lightweight.

## [0.5.24] - 2026-04-13

### Fixed
- **Studio: Surface revise RPC errors with actionable hints (PR #154)** — When `slides revise` fails due to an invalid artifact ID or a rejected revision request, the error now surfaces the specific Google API error code (e.g., `INVALID_ARGUMENT`) along with a clear hint guiding the user to verify their artifact ID. Previously, these failures produced opaque, unhelpful error messages. Thank you **@sickn33** for this fix!
- **WSL2: Auth broken on Chrome 136+ due to localhost-only CDP (PR #155)** — Chrome 136+ ignores `--remote-debugging-address=0.0.0.0`, restricting the DevTools Protocol to `127.0.0.1` only. This completely broke `nlm login --wsl` for all WSL2 users. The fix switches to a port proxy approach: Chrome launches on port 9223 (localhost) and WSL connects via port 9222 through a `netsh interface portproxy` rule. Temp Chrome profiles are now created on the Windows filesystem (`%TEMP%`) instead of WSL's `/tmp` to prevent "Profile error occurred" crashes. Updated `docs/WSL_SETUP.md` with one-time setup instructions. Thank you **@casjogreen** for this critical fix!

## [0.5.23] - 2026-04-12

### Added
- **Restore NotebookLM MCP and CLI runtime contracts (PR #152)** — Fixed MCP tool boundary registration, normalized error payloads, and restored download/upload sync-compatible entrypoints. Thank you **@sickn33** for this immense contribution!

### Fixed
- **Windows: Server crashes immediately on startup (Issue #150)** — `os.execvp` fails on Windows. Replaced with `subprocess.run` to prevent immediate crashes on Windows 11 during server startup via the `.mcpb` bundle. Added explicit `stdin=sys.stdin`, `stdout=sys.stdout`, and `stderr=sys.stderr` to ensure the JSON-RPC stdio channel between Claude Desktop and the server remains properly connected across platforms. Thanks to **@m3saros** for diagnosing the root cause and providing the exact fix!

## [0.5.22] - 2026-04-11

### Added
- **Studio status code parity and normalization (PR #149)** — Consolidated the extraction logic for studio artifacts into a centralized `_normalize_studio_status` routine. The `JsonFormatter` has been updated to dynamically populate returned JSON payloads with newly available artifact fields (such as `audio_url`, `video_url`, `slide_deck_url`, `flashcard_count`) without breaking the shape expected by downstream consumers. Huge thanks to **@sickn33** for this amazing contribution!

### Fixed
- **API `poll_studio_status` bypassing auth recovery** — The core `poll_studio_status` helper function was making raw HTTP calls and dodging the standard `_call_rpc` pipeline. This caused it to immediately fail on `400 Bad Request` exceptions whenever the user's `build_label` or session tokens went stale. The polling function now correctly wraps its logic in `_call_rpc`, securing free auth recovery loops, retries, and unified debug capability during studio polling.

## [0.5.21] - 2026-04-11

### Fixed
- **HTTP 400 bad request causing silent auth failures (Issue #147)** — Google returns `400 Bad Request` instead of `401` or `403` when the internal CSRF token expires. Added 400 to the retryable auth status codes, which fixes auth recovery failures and prevents tracebacks (PR #148).
- **WSL CDP failures breaking auth (Issue #138, #144)** — Native WSL connectivity has been fully added. `nlm login --wsl` securely launches and channels DevTools via `0.0.0.0` to safely bridge the WSL network boundary.
- **Pass Build Label in login check** — The `nlm login --check` command was initiating a client without passing the configured build label, unnecessarily triggering a three-month backward fallback.

## [0.5.20] - 2026-04-10

### Fixed
- **`nlm create infographic` crash when `--style` not specified (Issue #142)** — The verb-first route was missing the `--style` option entirely, causing a `TypeError` on invocation. Fixed alongside 12 other missing parameters across verb-first wrappers.
- **Multiple verb-first commands missing parameters** — The verb-first CLI route (`nlm create`, `nlm add`, `nlm describe`, `nlm query`, `nlm delete`) was missing 13 parameters that existed on the noun-first route: `--focus` on `nlm create quiz` and `nlm create flashcards`; `--wait` and `--wait-timeout` on `nlm add url`, `nlm add text`, and `nlm add drive`; `--auto-import` on `nlm research start`; `--format` on `nlm download slides`; `--json` on `nlm describe notebook`, `nlm query notebook`, and `nlm source content`; and `--confirm` on `nlm delete alias`.

### Changed
- **Widened `fastmcp` dependency to `>=2.0.0,<4.0` (Issue #141)** — The previous upper bound (`<3.0`) caused a startup crash when `fakeredis 2.35.0` was installed alongside `fastmcp 2.x`. Widening to `<4.0` resolves the incompatibility and allows users to use newer FastMCP releases without version conflicts.

### Added
- **Parameter parity test (`tests/cli/test_verbs_parity.py`)** — Automatically compares every verb-first wrapper in `cli/commands/verbs.py` against its target function to detect missing parameters. CI will now fail if a verb wrapper drifts out of sync with its noun-first counterpart.

## [0.5.19] - 2026-04-09

### Added
- **Auto-Import for Research** — Added `--auto-import` / `--wait-and-import` flags to `nlm research start` to automatically wait for research to finish and immediately import.

### Fixed
- **Deep Research Task ID Mismatch (Issue #140)** — Fixed a bug where deep research task IDs were being mutated by the backend and causing import failures. The CLI now polls the correct mutated task ID before issuing the import command.
- **Empty Notebook Error Mapping** — When attempting to query a notebook with 0 sources, the backend previously threw an unhelpful `API error (code 5): unknown`. This now returns a clean validation error indicating the notebook is empty and needs sources added.
- **gRPC Error Code Mapping** — Generic undocumented gRPC error codes from Google's batchexecute API (like 5, 7, 16) are now mapped to their standard names (`NOT_FOUND`, `PERMISSION_DENIED`, etc.) instead of logging as `unknown`.

## [0.5.18] - 2026-04-09

### Added
- **WSL2 Authentication Support (PR #138)** — New `nlm login --wsl` flag launches Windows Chrome from WSL2 for seamless authentication. Includes automatic firewall rule management, cross-boundary CDP communication, and a cleanup mechanism for temporary Chrome profiles. Full setup guide at `docs/WSL_SETUP.md`. Thanks to **@kylebrodeur** for the comprehensive implementation!
- **WSL2 Diagnostics** — `nlm doctor` now detects WSL2 environments and reports Chrome availability, Windows interop status, and firewall configuration.

### Fixed
- **Thread-Safety for Concurrent MCP Tool Calls (PR #135)** — Added `threading.Lock` to `BaseClient` protecting mutable state (`_reqid_counter`, `_conversation_cache`, `_source_rpc_version`) from race conditions during parallel MCP tool invocations. Uses double-checked locking for singleton client initialization. Includes 7 new concurrent access tests. Thanks to **@xiangyuwang1998** for the implementation!
- **Restored CDP WebSocket Timeout** — Re-applied the 30-second timeout on `execute_cdp_command()` that was inadvertently removed during the WSL2 merge. Prevents infinite hangs on stale/dropped WebSocket connections.
- **Restored Port Map File Permissions** — Re-applied `chmod 0o600` on the port map file that was inadvertently removed during the WSL2 merge. Ensures the port map is only readable by the owner.

## [0.5.17] - 2026-04-07

### Security
- **CDP Origin Restriction (PR #133)** — Chrome is now launched with `--remote-allow-origins` restricted to `localhost` and `127.0.0.1` only, preventing malicious webpages from connecting to the CDP debug port. Previously allowed all origins (`*`). Thanks to **@wccheung11011001** for the security audit!
- **Base URL Allowlist (PR #133)** — The `NOTEBOOKLM_BASE_URL` environment variable is now validated against an allowlist of known Google domains (HTTPS only), preventing cookie exfiltration via environment injection.
- **Download Path Traversal Protection (PR #133)** — Added `validate_output_path()` to block downloads from writing to sensitive directories (`.ssh`, `.gnupg`, `.aws`, `.kube`, `.claude`, `.config`) or overwriting sensitive files (`authorized_keys`, `id_rsa`, `.bashrc`, etc.).
- **File Permission Hardening (PR #133)** — Auth-related files, debug output, and the port map are now created with restrictive permissions (`0o600` for files, `0o700` for the storage directory). Thanks to **@wccheung11011001**!
- **CDP WebSocket Timeout (PR #133)** — Added a 30-second timeout to CDP WebSocket commands to prevent infinite blocking on stale or dropped connections.

### Added
- **Custom Visual Style Prompts for Video (PR #131)** — You can now pass a custom style description when creating videos with `--style custom --style-prompt "your description"` (CLI) or `video_style_prompt` (MCP). The style prompt is also returned in studio status responses. Thanks to **@agarwalvipin** for the implementation and live API verification!
- **Audio Source Support (PR #134)** — `nlm source add --file` now correctly handles audio uploads (m4a, wav, mp3). Audio sources use type code 10, which was previously unrecognized. The `--wait` flag now handles audio's transient status 3 state (which is not a hard failure for audio, unlike other source types) and a new `--wait-timeout` flag (default 600s) gives long recordings enough time to finish transcribing. Thanks to **@stanleykao72** for the thorough investigation and fix!
- **CONTRIBUTING.md** — Added a contributor guide covering architecture rules, the Chrome DevTools API capture workflow, testing requirements (both CLI and MCP), security guidelines, error handling patterns, and PR expectations.

### Fixed
- **`build_label` Data Loss (PR #133)** — `Profile.to_dict()` was silently dropping the `build_label` field, causing it to be lost across restarts and re-fetched from scratch. Now properly persisted. Thanks to **@wccheung11011001**!
- **Ruff Lint and Format Violations** — Fixed `B904` exception chaining in CDP timeout handler, and resolved format violations in `sources.py`, `config.py`, `test_url_source_fallback.py`, and `test_studio.py`.

## [0.5.16] - 2026-04-04

### Fixed
- **URL Source Addition Failing with INVALID_ARGUMENT (Issue #121)** — Fixed `source_add` (URL type) failing with `RPC error code 3 (INVALID_ARGUMENT)` for some users due to Google migrating the `add_source` endpoint. Implemented a dual-RPC fallback: the system tries the legacy `izAoDd` endpoint first, and if it returns code 3, automatically retries with the new `ozz5Z` endpoint. The working endpoint is cached per session to avoid extra round-trips on subsequent calls. Both single and bulk URL additions (`url` and `urls` parameters) benefit from the fallback. Thanks to **@Neophen** for reporting!

### Added
- **19 new unit tests** for dual RPC fallback mechanism (total: 704 tests)

## [0.5.15] - 2026-04-02

### Added
- **Async Query Polling (Issue #125)** — New `notebook_query_start` and `notebook_query_status` MCP tools for querying large notebooks (50+ sources) without hitting MCP client timeouts. `notebook_query_start` fires the query in a background thread and returns immediately with a `query_id`. Poll `notebook_query_status` with the `query_id` to get the result when ready. Includes automatic TTL cleanup (10 min) for stale entries. The existing `notebook_query` tool remains unchanged for backward compatibility.
- **10 new unit tests** for async query lifecycle (total: 685 tests)

## [0.5.14] - 2026-04-01

### Fixed
- **Research Start Dead Parameter (Issue #123)** — Fixed a bug where `nlm research start "query" --title "My Title"` (and the corresponding MCP tool parameter `title`) failed because the internal logic did not automatically trigger new notebook creation when `title` was provided without a `notebook_id`.

## [0.5.13] - 2026-03-31

### Fixed
- **Python 3.13 Crash in `nlm skill` (Issue #122)** — Fixed a crash when running `nlm skill install` on Python 3.13, which was caused by using `@click.option(type=Literal["user", "project"])`. Replaced with standard string validation. Thanks to **@zhaoguoqiao** for reporting!
- **CDP Proxy Bypass (Issue #119)** — The `httpx` HTTP2 client was honoring system proxy settings even for the internal `127.0.0.1` CDP WebSocket acquisition call (`http://127.0.0.1:9222/json`). This caused connections to fail on machines running proxies. Restored the `proxy=None` argument to explicitly bypass proxies for local loopback connections. Thanks to **@sjs33** for discovering and reporting this!
- **`research_status` Polling Loop (PR #120)** — Restored the internal polling loop for `research_status` when `max_wait` is set. Previously, the parameters were ignored after a refactor, and it always returned after a single check. The tool now correctly blocks and polls until the research is completed or times out. Thanks to **@byingyang** for the excellent bug report, full implementation, and test suite!

## [0.5.12] - 2026-03-30

### Fixed
- **Auth recovery skips profile-based cookies (Issue #117, Bug 1)** — `_try_reload_or_headless_auth()` gated Layer 2 recovery on `auth.json` existence. If the legacy file didn't exist, valid profile-based credentials in `profiles/default/cookies.json` were completely skipped, falling straight through to headless auth (Layer 3). Now always calls `load_cached_tokens()` which checks the profile directory first, then falls back to `auth.json`. Thanks to **@olaservo** for the incredibly detailed report!
- **`--cdp-url` ignored by builtin provider (Issue #117, Bug 2)** — `nlm login --cdp-url http://127.0.0.1:9222` was ignored when using the default builtin provider, always launching a new Chrome instead. Now, when `--cdp-url` is explicitly provided (even with the builtin provider), the CLI auto-routes to the existing-CDP extraction path, matching the user's intent to connect to an already-running browser. Thanks again to **@olaservo**!
- **Pre-existing lint errors blocking CI** — Fixed 3 lint violations (`SIM105` in `auth.py`, `I001` in `base.py`, `F401` in `test_coerce_list.py`) that were blocking the CI pipeline for PR #118.

### Security
- **Restrict `auth.json` file permissions (PR #116)** — Auth token cache files are now written with `chmod 600` (owner read/write only), preventing other local users or processes from reading active session cookies. Thanks to **@tody-agent** for the security audit!

## [0.5.11] - 2026-03-27

### Added
- **Enterprise / Google Workspace support (PR #114)** — Configurable base URL via `NOTEBOOKLM_BASE_URL` environment variable. Set to `https://notebooklm.cloud.google.com` (or your organization's URL) to use NotebookLM with managed Workspace accounts. All API calls, authentication, file uploads, and URL detection are updated to use the configured base URL. Default remains `https://notebook.google.com` for personal accounts (fully backward compatible). Thanks to **@Robiton** for this contribution!

### Documentation
- Added "Enterprise / Google Workspace" section to `docs/AUTHENTICATION.md`
- Added `NOTEBOOKLM_BASE_URL` to environment variables table in `docs/MCP_GUIDE.md`

## [0.5.10] - 2026-03-27

### Fixed
- **Quiz/Flashcard `focus_prompt` ignored (Issue #113)** — The `focus_prompt` parameter for quiz and flashcard generation was silently ignored due to an off-by-one error in the RPC payload structure. The backend expects `focus_prompt` at array index `[2]` (after a reserved `null` slot), but it was being placed at index `[1]`. Both `create_quiz` and `create_flashcards` in `core/studio.py` now use the correct payload layout. Thanks to **@ojsed** for the detailed analysis!
- **`source_ids` parameter fails with string input (Issue #111)** — MCP clients (Claude Desktop, Cursor, etc.) frequently serialize list parameters as JSON strings (`'["a","b"]'`) or comma-separated strings (`'a,b'`) instead of native Python lists, causing Pydantic validation errors. Added a `coerce_list()` helper in `mcp/tools/_utils.py` that normalizes all input forms (JSON strings, comma-separated, single values, native lists) into proper `list[T]`. Applied to all 6 list parameters across 4 MCP tool files: `studio_create`, `notebook_query`, `source_add`, `source_sync_drive`, `source_delete`, and `research_import`. Thanks to **@Carlos-OL** for reporting!
- **Non-ASCII characters in JSON output (PR #112)** — Fixed `ensure_ascii=False` missing from `json.dumps()` calls across core and CLI layers, causing Unicode characters to be escaped as `\uXXXX` in RPC request bodies and file persistence. Thanks to **@rujinlong** for the fix!

### Added
- **13 new unit tests** for `coerce_list` helper (total: 660 tests)

## [0.5.9] - 2026-03-25
### Fixed
- Fixed a fatal `ImportError` in the CLI (`ArtifactNotReadyError`) caused by missed codebase updates during the v0.5.8 structural refactor.

## [0.5.8] - 2026-03-25

### Fixed/Changed
- Codebase-wide refactor to comply with comprehensive `ruff` linting and formatting standards.
- Fixed broken imports caused by code structure refactoring.
- A massive thank you to **@nikosavola** for submitting BOTH the `ruff` linting and formatting refactor (PR #110) AND the GitHub Actions CI Pipeline (PR #109)! These are huge improvements to the codebase quality.

## [0.5.7] - 2026-03-25

### Added
- **GitHub Actions CI Pipeline (PR #109)** — Added a comprehensive GitHub Actions workflow that automatically runs linting (`ruff format --check`, `ruff check`) and the full pytest suite (`uv run pytest`) on pull requests and pushes to `main`. Linting errors now block the build, guaranteeing code quality before merge. Thanks to **@nikosavola** for this contribution!

## [0.5.6] - 2026-03-24

### Fixed
- **Windows: manual cookies rejected after import (Issue #105)** — `nlm login --manual --file` saved cookies correctly, but subsequent requests to `notebook.google.com` were rejected by Google (302 → login page) because the page-fetch headers included macOS-specific Client Hints (`sec-ch-ua-platform: "macOS"`, `sec-ch-ua`, `sec-ch-ua-mobile`). When cookies were captured from a Windows Chrome session, the OS fingerprint mismatch caused Google to reject the session. Removed all three `sec-ch-ua*` headers (they're optional per spec) and switched to a platform-neutral Linux Chrome UA — making auth platform-agnostic. Also added a multi-pattern CSRF token fallback (`SNlM0e` → `at=` → `FdrFJe`) in `_refresh_auth_tokens`, and a `make_console(safe_box=True)` factory to prevent `UnicodeEncodeError` crashes on Windows `cp1251`/`cp1252` codepage terminals. Thanks to **@pakulyaev** for the detailed diagnosis and debug output! (5 new regression tests added)
- **Windows: IPv6 WebSocket connection error during `nlm login` (Issue #108)** — On Windows, Chrome's DevTools debugger binds to `127.0.0.1` (IPv4), but `websocket-client` resolves `localhost` to `::1` (IPv6), causing `PermissionError: [WinError 10013]`. Added a `_normalize_ws_url()` helper that explicitly rewrites `ws://localhost:` to `ws://127.0.0.1:` at all 4 WebSocket connection sites in `cdp.py`. Thanks to **@theteleporter** for the spot-on diagnosis!

## [0.5.5] - 2026-03-23


### Fixed
- **MCP `download_artifact` failing for report/mind_map/data_table (Issue #107)** — The MCP `download_artifact` tool exclusively routed through `download_async()`, but `_dispatch_async()` had no handlers for `report`, `mind_map`, or `data_table` (only `_dispatch_sync()` did). Added these three non-streaming types to the async dispatcher so all artifact types are downloadable via the MCP tool. Thanks to **@Neophen** for the detailed bug report!
- **`poll_research` returning `None` for deep research in multi-task notebooks (Issue #106)** — When deep research mutates the task ID internally and the notebook has multiple research tasks, `poll_research` returned `None` instead of a valid task. The fallback now prefers any `in_progress` task, then falls back to the most recent task. Thanks to **@Neophen** for reporting!

## [0.5.4] - 2026-03-22

### Fixed
- **Verb-style `nlm delete source` TypeError (Issue #104)** — `nlm delete source <id> --confirm` was crashing with `TypeError: delete_source() got an unexpected keyword argument 'source_id'`. The verb-style CLI layer in `verbs.py` was passing `source_id=source` (singular string) but the underlying function expects `source_ids` (a list). Fixed the parameter name and wrapped the value in a list. The noun-style `nlm source delete` was unaffected. Thanks to **@Le-Yann** for the detailed bug report and root cause analysis!

## [0.5.3] - 2026-03-22

### Improved
- **Actionable Error Hints Across CLI & MCP (Issue #103)** — All CLI commands and MCP tools now provide structured, user-friendly error messages with actionable hints (e.g., "Run 'nlm login' to authenticate" or "Run 'nlm notebook list' to see available notebooks"). Thanks to **@ahnbu** for suggesting this improvement!
  - **CLI**: Consolidated error handling via centralized `handle_error()` across all 13 command modules. Errors with `--json` flag now output structured JSON (`{"status": "error", "error": "...", "hint": "..."}`).
  - **MCP**: All 27 MCP tools now include `hint` fields in error responses for AI agent consumption.
  - **Services**: `ServiceError` now carries an optional `hint` attribute, propagated from `NLMError` exceptions.
  - **Core**: `NotebookLMError` (parent of `RPCError`, `ArtifactError`, etc.) now inherits from `NLMError`, ensuring all low-level API errors are caught and handled gracefully instead of producing raw tracebacks.

### Fixed
- **Non-ASCII characters in JSON output (PR #100)** — CLI JSON output (`--json` flag) now preserves Unicode characters (e.g., `café`, `こんにちは`) instead of escaping them as `\uXXXX` sequences via a shared `print_json()` helper with `ensure_ascii=False`. Thanks to **@nickyfoto** for the contribution. (PR #100)

## [0.5.1] - 2026-03-19

### Fixed
- **Deep Research Transient Errors (Issue #98)** — Deep research (`--mode deep`) no longer silently fails with a generic "no confirmation from API" message when Google returns a transient error. The structured error payload (e.g., `DeepResearchErrorDetail` code 3) is now properly detected and surfaced with an actionable message: *"Google API error code 3 (DeepResearchErrorDetail). This is likely a transient issue. Try again in a few minutes, or use --mode fast."*
- **Research RPC Infrastructure** — Refactored `start_research()` to use the standard `_call_rpc()` pipeline instead of raw HTTP calls. This gives deep and fast research automatic auth retry, server error retries, and enhanced debug logging for free.

### Added
- **`RPCError` exception class** — New structured error type in `core/errors.py` for Google batchexecute errors with error code, detail type, and detail data attributes. All non-auth RPC errors (not just code 16) are now properly raised.
- **6 new unit tests** (3 core-level, 3 service-level) for RPCError detection and user-friendly error messages (total: 634 tests)

## [0.5.0] - 2026-03-18

### Fixed
- **Research Import Timeout (Issue #97)** — `research import` now uses a 300-second default timeout (up from 120s), fixing consistent timeouts on notebooks with many sources. The timeout is configurable via `--timeout` / `-t` in CLI and `timeout` parameter in MCP.
- **Research Start Deadlock (Issue #97)** — `research start` no longer hard-exits when previous research has un-imported sources. Instead, it shows a warning and prompts interactively, so users can choose to proceed or import first. Previously, if import timed out, users were stuck — unable to import or start new research without `--force`.

### Added
- **Configurable Import Timeout** — `nlm research import <notebook> <task-id> --timeout 600` for extra-large notebooks. Available in both CLI (`--timeout` / `-t`) and MCP (`timeout` parameter on `research_import`). Default: 300 seconds.
- **2 new unit tests** for timeout parameter forwarding (total: 624 tests)

## [0.4.9] - 2026-03-16

### Added
- **CC-Claw Skill Support** — Added `cc-claw` as a supported tool for `nlm skill install cc-claw` (`~/.cc-claw/workspace/skills/nlm-skill/`).

### Fixed
- **Windows CLI Argument Parsing (Issue #96)** — Fixed a bug where running `nlm add url <notebook_id> "https://..."` on Windows PowerShell incorrectly parsed the URL string into a list of characters, attempting to add dozens of duplicate sources instead of one.
- **Service Layer Robustness** — Added internal safeguards ensuring single string URL parsing never falls through to character unpacking across the API service boundary.

## [0.4.8] - 2026-03-14

### Added
- **Native Chat History Persistence** — Both the CLI (`nlm notebook query`) and the MCP server now perfectly persist their chat history directly into the Gemini Notebook web UI. All prompts sent via CLI or MCP agents will now appear in the notebook's native chat panel, sharing the same conversational context as the web UI. (Closes #92)
- **OpenCode Support** — Full support for OpenCode in the `nlm setup` command (`nlm setup add opencode`) to automatically configure the Gemini Notebook MCP server for OpenCode. Includes smart config array injection and parsing. Thanks to **@woohyun212** for the comprehensive implementation and thorough unit tests (PR #95, closes #95).

### Fixed
- **MCP Profile Switching** — Fixed a bug where the MCP server wouldn't respect dynamic authentication profile changes made via `nlm login switch <profile>`. The server now automatically detects token file changes and gracefully reloads the Gemini Notebook client in real-time, matching the active profile perfectly.
- **CC-Claw Skill Support** — Added `cc-claw` as a supported tool for `nlm skill install cc-claw` (`~/.cc-claw/workspace/skills/nlm-skill/`).
## [0.4.7] - 2026-03-13

### Changed
- **Skill path migration: `.gemini/skills/` → `.agents/skills/`** — Starting with Gemini CLI v0.33.1, `.agents/skills/` is the recommended cross-tool compatible path (higher priority than `.gemini/skills/`). `nlm skill install gemini-cli` and `nlm skill install codex` are replaced by `nlm skill install agents`, which installs to `~/.agents/skills/nlm-skill/`. This path works for Gemini CLI, Codex, and any tool that reads `.agents/skills/`. Users with existing `gemini-cli` or `codex` installations should run `nlm skill install agents` to reinstall at the new location.
- **Documentation updates** — Added v0.4.6 features (batch, cross-notebook, pipelines, tags) to SKILL.md, AGENTS_SECTION.md, and API_REFERENCE.md. Removed stale QUICK_REFERENCE.md.

## [0.4.6] - 2026-03-12

### Added
- **Batch Operations** — Perform actions across multiple notebooks at once. Thanks to **@fabianafurtadoff** for this contribution (PR #90)!
  - `nlm batch query` — Query multiple notebooks with the same question
  - `nlm batch add-source` — Add a URL to multiple notebooks
  - `nlm batch create` — Create multiple notebooks at once
  - `nlm batch delete` — Delete multiple notebooks (requires `--confirm`)
  - `nlm batch studio` — Generate artifacts across multiple notebooks
  - MCP: Consolidated `batch` tool with `action` parameter (query|add_source|create|delete|studio)
- **Cross-Notebook Query** — Query multiple notebooks and get aggregated answers with per-notebook citations. (PR #90, @fabianafurtadoff)
  - `nlm cross query "question" --notebooks "id1,id2"` — Ask across specific notebooks
  - `nlm cross query "question" --tags "ai,research"` — Query by tag
  - MCP: `cross_notebook_query` tool
- **Pipelines** — Define and execute multi-step notebook workflows. (PR #90, @fabianafurtadoff)
  - `nlm pipeline list` — List available pipelines (3 builtin: ingest-and-podcast, research-and-report, multi-format)
  - `nlm pipeline run <notebook> <pipeline-name>` — Execute a pipeline
  - User-defined pipelines via YAML files in `~/.notebooklm-mcp-cli/pipelines/`
  - MCP: Consolidated `pipeline` tool with `action` parameter (run|list)
- **Smart Select & Tagging** — Tag notebooks and find relevant ones by keyword matching. (PR #90, @fabianafurtadoff)
  - `nlm tag add <notebook> --tags "ai,research"` — Add tags
  - `nlm tag remove <notebook> --tags "ai"` — Remove tags
  - `nlm tag list` — List all tagged notebooks
  - `nlm tag select "query"` — Find notebooks by tag match
  - MCP: Consolidated `tag` tool with `action` parameter (add|remove|list|select)
- **Studio List Types** — Reference of all artifact types and their options, accessible via `studio_status(action="list_types")`
- **73 new unit tests** covering all new service modules (total: 576 tests)

### Changed
- **MCP Tool Consolidation** — Reduced 13 new tools to 4 consolidated tools with action parameters, keeping total MCP tools at 35 (down from what would have been 44). Follows existing patterns (`note`, `source_add`).

### Fixed
- **CLI import violations** — Fixed 3 CLI command files (`batch.py`, `cross.py`, `pipeline.py`) importing `get_client` from `mcp/tools/_utils` instead of `cli/utils`, violating architecture layering
- **Missing UTF-8 encoding** — Added `encoding='utf-8'` to 6 file I/O calls in `smart_select.py` and `pipeline.py` to prevent `UnicodeDecodeError` on Windows
- **Cross-notebook display crash** — Fixed `sources_used` field handling in `cross.py` display formatting (could crash on string values)

## [0.4.5] - 2026-03-10

### Fixed
- **`nlm doctor` crash on Windows (Issue #87)** — Fixed `UnicodeDecodeError` when running `claude mcp list` on Windows systems with non-UTF-8 default encodings (e.g., `cp936`, `cp1252`). Added explicit `encoding="utf-8"` and `errors="replace"` to the subprocess call. Also added a null check for `result.stdout` to prevent `AttributeError` when the subprocess returns no output.
- **Silent Chrome launch failures on Windows (Issue #86)** — `launch_chrome_process` was silently swallowing all `subprocess.Popen` exceptions, causing `nlm login` to report the cryptic "Cannot connect to browser on port XXXX" with no indication of what went wrong. Now logs the browser path, port, and exception details so users get actionable error messages. Added debug logging for successful launches as well.

## [0.4.4] - 2026-03-08

### Fixed
- **Complex citation parsing (PR #84)** — Fixed `notebook_query` dropping cited text when Google returns "direct" citation segments (integer-first elements) alongside the standard "wrapped" format. Both segment variants are now correctly handled. Thanks to **@meirtsvi** for this contribution!
- **Table citation extraction (PR #84)** — When a citation references a data table, the response now includes a structured `cited_table` field with `num_columns` and `rows` data. Table segments are indicated by a `<cited_table>` placeholder in the `cited_text` field.
- **Mind map JSON missing from MCP response (Issue #83)** — `studio_create` for mind maps was returning metadata (`root_name`, `children_count`) but dropping the actual `mind_map_json`. The full JSON now flows through to MCP clients. Thanks to **@cowhi** for reporting!

### Added
- **17 new unit tests** for citation parsing — Comprehensive test coverage for direct/wrapped segment detection, table placeholder insertion, `_extract_text_from_table_rows`, `_extract_table_from_detail`, and `cited_table` in `_extract_citation_data`. Total tests: 503.

## [0.4.3] - 2026-03-08

### Removed
- **`nlm setup add claude-desktop` removed** — Claude Desktop users should install via the `.mcpb` extension (download from [Releases](https://github.com/jacob-bd/gemini-notebook-mcp-cli/releases/latest), double-click to install). The CLI-based config file editing was unreliable compared to the extension approach. `nlm setup add claude-code` (for the Claude Code CLI) is unchanged.

## [0.4.2] - 2026-03-08

### Added
- **Expanded file format support (PR #82)** — File uploads now accept additional formats. Thanks to **@JumpLao** for this contribution!
  - Audio: `.m4a`, `.wav`, `.aac`, `.ogg`, `.opus` (previously only `.mp3`)
  - Images: `.gif`, `.webp` (previously only `.jpg`, `.jpeg`, `.png`)
  - Note: `.flac`, `.webm`, `.mov`, `.avi`, `.mkv` were removed from the original PR as Google's upload server does not accept them
- **Cited text passages in query output (PR #81)** — `notebook_query` responses now include a `references` array with the actual quoted passage text for each citation. Previously, only the source ID and citation number were returned; the passage text was already in the API response but was being discarded. Thanks to **@cbruyndoncx** for this contribution!
  - Each reference includes `source_id`, `citation_number`, and `cited_text`
  - Backward-compatible: existing `sources_used` and `citations` fields unchanged
  - Flows through MCP and CLI automatically
- **`nlm setup add all` — Interactive multi-tool setup** — Scans the system for installed AI tools, shows detection status, and lets you interactively choose which ones to configure with Gemini Notebook MCP
  - Detects: Claude Code, Claude Desktop, Gemini CLI, Cursor, Windsurf, Cline, Antigravity, Codex
  - Shows which tools are already configured vs. newly detected
  - Select `all`, specific numbers, or `none`
- **`nlm setup remove all`** — Remove Gemini Notebook MCP from all configured tools at once, with explicit confirmation and safety warnings. Uses CLI-first removal (e.g., `claude mcp remove`) where available.

### Changed
- **Codex skill path updated** — `nlm skill install codex` now installs to `~/.agents/skills/nlm-skill/SKILL.md` per [official Codex docs](https://developers.openai.com/codex/skills/), replacing the old `~/.codex/AGENTS.md` path. Users with the old installation should run `nlm skill install codex` to reinstall at the correct location.

## [0.4.1] - 2026-03-07

### Added
- **Cinematic Video Format (Experimental)** — Added support for Gemini Notebook's new "Cinematic" video format (`video_format="cinematic"`, format code `3`). This format produces higher-fidelity video overviews and is available to Gemini Notebook Plus/Ultra subscribers. Thanks to **@ovai-felix** for the detailed reverse-engineering and verified payload structure (Issue #79).
  - Core: Cinematic payloads use a 5-element inner options array (omitting `visual_style_code`), while Explainer/Brief continue to use 6 elements
  - MCP: `studio_create` with `video_format="cinematic"` 
  - CLI: `nlm video create <notebook> --format cinematic`
  - ⚠️ **Note for free/Pro users:** Cinematic is gated behind Gemini Notebook Plus/Ultra. Free and Pro tier users will see: `"NotebookLM rejected video creation. Try again later or create from NotebookLM UI for diagnosis."` — this is expected behavior, not a bug.

### Fixed
- **Claude Desktop `.mcpb` extension disconnects (Issue #78)** — The `.mcpb` bundle was incomplete (only contained `manifest.json` with no entrypoint) and relied on `uvx` being in PATH, which Claude Desktop's restricted macOS environment doesn't expose. Fixed by bundling a cross-platform Python launcher (`run_server.py`) that defensively resolves `uvx` across common install locations (`~/.local/bin`, `~/.cargo/bin`, `/opt/homebrew/bin`, etc.) and using `${__dirname}` for reliable path resolution. Thanks to **@abanoub-ashraf** for the detailed diagnosis and reproduction steps.

## [0.4.0] - 2026-03-05

### Added
- **Bulk Sharing (`notebook_share_batch`)** — Invite multiple collaborators to a notebook in a single API call (Issue #73). Supports mixed roles (viewer/editor) per recipient.
  - Core: `add_collaborators_bulk(notebook_id, recipients)` on `SharingMixin`
  - Service: `invite_collaborators_bulk(client, notebook_id, recipients)` with upfront validation
  - MCP: `notebook_share_batch` tool with `recipients` list and `confirm` flag
  - CLI: `nlm share batch <notebook> "a@gmail.com,b@gmail.com" --role viewer`
- **10 new unit tests** for bulk sharing (core + services)

### Fixed
- **Version mismatch (Patch)** — Bump internal `__version__` string in `__init__.py` to correctly report version (was omitted in `0.3.20` release).

## [0.3.20] - 2026-03-04

### Fixed
- **Type errors, thread safety, and silent exceptions (PR #74)**
  - Added Double-Checked Locking (`threading.Lock`) for thread-safe client initialization in MCP tools.
  - Surfaced previously swallowed exceptions for better debug visibility via `logger.debug()`.
  - Fixed multiple type annotations (`str = None` -> `str | None = None`) across the codebase.
  - Replaced unreachable code with explicit `ValidationError` throwing to ensure strict type checking completeness.
  - Thanks to **@adlewis82** for the excellent cleanup and safety improvements!

## [0.3.19] - 2026-03-02

### Fixed
- **JSON output word wrapping (Issue #72)** — CLI commands using `-j` flag (`note list`, `share status`, `export artifact`, `config show`) were producing invalid JSON due to Rich console wrapping long strings at terminal width. JSON output now bypasses Rich and goes directly to stdout. Thanks to **@pjeby** for reporting.

## [0.3.18] - 2026-03-02

### Added
- **Infographic visual styles** — Infographics now support 11 visual styles matching the Gemini Notebook web UI: `auto_select`, `sketch_note`, `professional`, `bento_grid`, `editorial`, `instructional`, `bricks`, `clay`, `anime`, `kawaii`, `scientific`. Available via MCP (`infographic_style` parameter on `studio_create`), CLI (`--style` flag on `nlm infographic create`), and Python API (`visual_style_code` on `create_infographic()`). Default is `auto_select` for backward compatibility.

## [0.3.17] - 2026-03-02

### Added
- **Multi-browser support for `nlm login`** — `nlm login` now detects and launches any Chromium-based browser, not just Google Chrome. Supported browsers (in priority order): Google Chrome, Arc (macOS), Brave, Microsoft Edge, Chromium, Vivaldi, Opera. Checks both system and user-local install paths. Error messages now dynamically list supported browsers per platform. Thanks to **@devnull03** for this contribution (PR #70).
- **Browser preference setting** — Users can now control which browser `nlm login` uses via `nlm config set auth.browser <name>`. Valid values: `auto` (default, first found wins), `chrome`, `arc`, `brave`, `edge`, `chromium`, `vivaldi`, `opera`. Falls back to auto-detection if the preferred browser is not installed. Also settable via `NLM_BROWSER` env var.

### Fixed
- **Deep research task_id mismatch (Issue #69)** — `nlm research status <nb> --task-id <id>` returned "no research found" for deep research because the backend assigns a new task_id internally. Now falls back to returning the only active task when the original task_id doesn't match. Thanks to **@danielbrodie** for reporting.

## [0.3.16] - 2026-02-28

### Fixed
- **Chrome profile isolation bug**: `nlm login` could reuse a Chrome instance from a different NLM profile. Implemented port-to-profile mapping to guarantee strict cross-profile isolation.
- **Auto-retry on Google account mismatch**: When switching NLM profiles (or when multiple users log in on the same machine), Chrome can cache the wrong Google login. The builtin login provider now detects `AccountMismatchError`, automatically clears the stale Chrome user-data-dir, and relaunches Chrome for a fresh Google sign-in.
- **`nlm login profile delete` validation**: Profile deletion was failing for broken/invalid profiles because it strictly checked for valid cookies. Now it checks if the profile directory exists, allowing deletion of empty/corrupt profiles.

## [0.3.15] - 2026-02-26

### Added
- **`nlm setup add json` — Interactive JSON config generator** — Run `nlm setup add json` to generate an MCP JSON config snippet for any tool not directly supported. Interactive wizard with numbered prompts lets you choose uvx vs regular mode, full path vs command name, and whether to include the `mcpServers` wrapper. Prints syntax-highlighted JSON and offers clipboard copy on macOS.

## [0.3.14] - 2026-02-26

### Fixed
- **MCP server instructions: incorrect parameter names** — The consolidated tools summary in the MCP server instructions advertised `type=` for `source_add`, `studio_create`, and `download_artifact`, but the actual tool schemas use `source_type` and `artifact_type`. AI clients reading the instructions would use wrong parameter names, causing validation errors. Also added value parameter hints for `source_add`.

## [0.3.13] - 2026-02-26

### Added
- **Bulk Source Add** — Add multiple URL sources in a single API call, dramatically reducing round-trips and avoiding rate limits (Issue #57).
  - Core: `add_url_sources(notebook_id, urls)` on `SourceMixin`
  - Service: `add_sources(client, notebook_id, sources)` — batches URL sources automatically, falls back to individual calls for other types
  - MCP: `source_add` now accepts optional `urls` list parameter for bulk URL add
  - CLI: `nlm source add <notebook> --url https://a.com --url https://b.com` (repeatable `--url` flag)
- **Bulk Source Delete** — Delete multiple sources in a single API call.
  - Core: `delete_sources(source_ids)` on `SourceMixin`
  - Service: `delete_sources(client, source_ids)` with validation
  - MCP: `source_delete` now accepts optional `source_ids` list parameter for bulk delete
  - CLI: `nlm source delete <id1> <id2> <id3> --confirm` (variadic arguments)
- **12 new unit tests** for bulk add/delete service functions (total: 443 tests)

## [Unreleased / 0.3.12]

### Fixed
- **Source additions bypassing Token Refresh** - Refactored `add_url_source`, `add_drive_source`, `add_text_source`, and multiple other methods in `core/sources.py` to use the unified `_call_rpc` mechanism instead of raw `client.post` requests. This ensures that adding sources now properly benefits from the automatic session/CSRF token refresh if authentication unexpectedly expires (Issue #62).
- **Notebook operations bypassing Token Refresh** - Refactored `list_notebooks` and `delete_notebook` in `core/notebooks.py` to use `_call_rpc`, ensuring they recover from expired CSRF tokens just like other core operations. Thanks to **@byingyang** for identifying this in PR #61.
- **OpenClaw skill path** - Fixed incorrect installation path for OpenClaw skills (`workplace` -> `workspace`) in code and documentation. Thanks to **@maxcanada** for reporting (Issue #63).
- **`create slides` default format** - Fixed a bug where `create slides` would error because it used an invalid format fallback. It now correctly defaults to `detailed_deck`. Added comprehensive tests for all verb defaults. (PR #64)

## [0.3.11] - 2026-02-22

### Added
- **Auto-extract build label (`bl`)** - The `bl` URL parameter is now automatically extracted from the Gemini Notebook page during `nlm login` and CSRF token refresh, instead of using a hardcoded value that goes stale every few weeks. This keeps API requests current with Google's latest build without any manual steps. The `NOTEBOOKLM_BL` env var still works as an override. The `save_auth_tokens` MCP tool also extracts `bl` from the `request_url` parameter when provided.

### Fixed
- **`sources_used` now populated in query responses** - The `sources_used` field was always returning `[]` even when the AI's answer contained citation markers like `[1]`, `[2]`. Google's response includes citation-to-source mapping data that was present but never parsed. Query responses now correctly return `sources_used` (list of cited source IDs) and `citations` (dict mapping each citation number to its parent source ID). This also enables the REPL's citation legend feature. Thanks to **@MinhDung2209** for reporting (issue #57).

## [0.3.10] - 2026-02-22

### Added
- **Source Rename (`source_rename`)** — Rename any source within a notebook via new RPC `b7Wfje`.
  - MCP tool: `source_rename` with `notebook_id`, `source_id`, and `new_title` params
  - CLI: `nlm source rename <source-id> <title> --notebook <notebook-id>`
  - Verb-first alias: `nlm rename source <source-id> <title> --notebook <notebook-id>`

## [0.3.9] - 2026-02-22

### Added
- **`--clear` flag for `nlm login`** - Added a `--clear` flag that wipes the cached Chrome profile before logging in. This solves an issue where `nlm login` would auto-login to an old, cached account without letting the user switch profiles or emails.

### Fixed
- **Accurate Email Extraction** - Fixed a bug in `extract_email` where the CLI would sometimes grab a shared note author's email off the dashboard instead of the logged-in user. The regex now prioritizes actual internal Google account fields before falling back to generic matching.
- **Skipping Migration on Clear** - Fixed an issue where using `--clear` would cause the CLI to mistakenly run a migration step from older CLI versions, reinstating the wrong account profile.

## [0.3.8] - 2026-02-22

### Added
- **CLI `--debug` Flag** - `nlm --debug <command>` enables debug logging across all CLI commands, showing raw API responses and internal state. Useful for diagnosing API issues.

### Fixed
- **Google API errors no longer silently swallowed** - When Google returns an error response (e.g., `INVALID_ARGUMENT`, `UserDisplayableError`) instead of an answer, the CLI now surfaces a clear error message instead of returning an empty answer. Previously, queries would succeed with `{'answer': ''}` and no indication of what went wrong. Thanks to **@MinhDung2209** for the detailed debugging that uncovered this (issue #57).

## [0.3.7] - 2026-02-22

### Added
- **Configurable Interface Language (`NOTEBOOKLM_HL`)** - Set `NOTEBOOKLM_HL` env var to control both the API's `hl` URL parameter and the default artifact creation language. Explicit `--language` flags still take priority. Thanks to **@beausea** for this contribution (PR #59, closes #58).

## [0.3.6] - 2026-02-22

### Added
- **Query Timeout Flag** - `nlm notebook query` and `nlm query notebook` now accept `--timeout` / `-t` to set query timeout in seconds (default: 120). Useful for long extraction prompts that need more processing time (closes #57).

## [0.3.5] - 2026-02-21

### Added
- **Slide Deck Revision (`studio_revise`)** — Revise individual slides in an existing slide deck via new RPC `KmcKPe`. Creates a new artifact with revisions applied; original is never modified.
  - MCP tool: `studio_revise` with `artifact_id`, `slide_instructions`, and `confirm` params
  - CLI: `nlm slides revise <artifact-id> --slide '1 Make the title larger' --confirm`
- **PPTX Download Support** — Download slide decks as PowerPoint (PPTX) in addition to PDF.
  - CLI: `nlm download slide-deck <notebook> --format pptx`
  - MCP: `download_artifact` with `slide_deck_format="pptx"`
- **Login Profile Protection** — Account mismatch guard prevents accidentally overwriting a profile with credentials from a different Google account. Use `--force` to override.
- **Reused Chrome Warning** — `nlm login` now warns when connecting to an existing Chrome instance instead of launching a fresh one.

### Changed
- **Faster Login** — Connection pooling and reduced sleep durations cut `nlm login` time from ~25s to under 3s. Thanks to **@pjeby** for this contribution (PR #54).

## [0.3.4] - 2026-02-19

### Fixed
- **`nlm login` hang on fresh install** - Optimized Chrome port availability scanning (using `socket.bind` instead of `httpx.get`) to avoid 20+ second timeouts on systems that drop network packets. Thanks to **@pjeby** for the diagnosis (closes #52)
- **Chrome "Restore Pages" Warning** - `nlm login` and headless authentication now perform a graceful shutdown of Chrome via CDP (`Browser.close`) rather than abruptly killing the process, resolving crashes on next browser start. Again, great work by **@pjeby** (fixes #52)

## [0.3.3] - 2026-02-16

### Fixed
- **OpenClaw skill path** - Fixed incorrect installation path for OpenClaw skills. Now correctly uses `~/.openclaw/workspace/skills/` instead of `~/.openclaw/skills/`.

## [0.3.2] - 2026-02-14

### Added
- **Focus Prompt Support** - Added `--focus` parameter to `nlm quiz create` and `nlm flashcards create` commands to specify custom instructions.
- **Improved Prompt Extraction** - `studio_status` now correctly extracts custom prompts for all artifact types (Audio, Video, Slides, Quiz, Flashcards).

### Fixed
- **Quiz/Flashcard Prompt Extraction** - Fixed a bug where custom instructions were not being extracted for Quiz and Flashcards artifacts (wrong API index).

## [0.3.1] - 2026-02-14

### Added
- **New AI Client Support** — Added `nlm skill install` support for:
  - **Cline** (`~/.cline/skills`) - Terminal-based AI agent
  - **Antigravity** (`~/.gemini/antigravity/skills`) - Advanced agentic framework
  - **OpenClaw** (`~/.openclaw/workspace/skills`) - Autonomous AI agent
  - **Codex** (`~/.codex/AGENTS.md`) - Now with version tracking
- **`nlm setup` support** — Added automatic MCP configuration for:
  - **Cline** (`nlm setup add cline`)
  - **Antigravity** (`nlm setup add antigravity`)
- **`nlm skill update` command** - Update installed AI skills to the latest version. Supports updating all skills or specific tools (e.g., `nlm skill update claude-code`).
- **Verb-first alias** - `nlm update skill` works identically to `nlm skill update`.
- **Version tracking** - `AGENTS.md` formats now support version tracking via injected comments.

### Fixed
- **Skill version validation** - `nlm skill list` now correctly identifies outdated skills and prevents "unknown" version status for Codex.
- **Package version** - Bumped to `0.3.1` to match release tag.

## [0.3.0] - 2026-02-13

### Added
- **Shared service layer** (`services/`) — 10 domain modules centralizing all business logic previously duplicated across CLI and MCP:
  - `errors.py`: Custom error hierarchy (`ServiceError`, `ValidationError`, `NotFoundError`, `CreationError`, `ExportError`)
  - `chat.py`: Chat configuration and notebook query logic
  - `downloads.py`: Artifact downloading with type/format resolution
  - `exports.py`: Google Docs/Sheets export
  - `notebooks.py`: Notebook CRUD, describe, query consolidation
  - `notes.py`: Note CRUD operations
  - `research.py`: Research start, polling, and source import
  - `sharing.py`: Public link, invite, and status management
  - `sources.py`: Source add/list/sync/delete with type validation
  - `studio.py`: Unified artifact creation (all 9 types), status, rename, delete
- **372 unit tests** covering all service modules (up from 331)

### Changed
- **Architecture: strict layering** — `cli/` and `mcp/` are now thin wrappers delegating to `services/`. Neither imports from `core/` directly.
- **MCP tools refactored** — Significant line count reductions across all tool files (e.g., studio 461→200 lines)
- **CLI commands refactored** — Business logic extracted to services, CLI retains only UX concerns (prompts, spinners, formatting)
- **Contributing workflow updated** — New features follow: `core/client.py` → `services/*.py` → `mcp/tools/*.py` + `cli/commands/*.py` → `tests/services/`

## [0.2.22] - 2026-02-13

### Fixed
- **Fail-fast for all studio create commands** — Audio, report, quiz, flashcards, slides, video, and data-table creation now exit non-zero with a clear error when the backend returns no artifact, instead of silently reporting success. Extends the infographic fix from v0.2.21 to all artifact types (closes #33)

## [0.2.21] - 2026-02-13

### Added
- **OpenClaw CDP login provider** — `nlm login --provider openclaw --cdp-url <url>` allows authentication via an already-running Chrome CDP endpoint (e.g., OpenClaw-managed browser sessions) instead of launching a separate Chrome instance. Thanks to **@kmfb** for this contribution (PR #47)
- **CLI Guide documentation for `nlm setup` and `nlm doctor`** — Added Setup and Doctor command reference sections, updated workflow example, and added tips. Cherry-picked from PR #48 by **@997unix**

### Fixed
- **Infographic create false success** — `nlm infographic create` now exits non-zero with a clear error when the backend returns `UserDisplayableError` and no artifact, instead of silently reporting success (closes #46). Thanks to **@kmfb** (PR #47)
- **Studio status code 4 mapping** — Studio artifact status code `4` now maps to `"failed"` instead of `"unknown"`, making artifact failures visible during polling. By **@kmfb** (PR #47)

### Changed
- **CDP websocket compatibility** — WebSocket connections now use `suppress_origin=True` for compatibility with managed Chrome endpoints, with fallback for older `websocket-client` versions

## [0.2.20] - 2026-02-11

### Added
- **Claude Desktop Extension detection** — `nlm setup list` and `nlm doctor` now detect Gemini Notebook when installed as a Claude Desktop Extension (`.mcpb`), showing version and enabled state.

### Fixed
- **Shell tab completion crash** — Fixed `nlm setup add <TAB>` crashing with `TypeError` due to incorrect completion callback signature.

## [0.2.19] - 2026-02-10

### Added
- **Automatic retry on server errors** — Transient errors (429, 500, 502, 503, 504) are now retried up to 3 times with exponential backoff. Special thanks to **@sebsnyk** for the suggestion in #42.
- **`--json` flag for more commands** — Added structured JSON output to `notebook describe`, `notebook query`, `source describe`, and `source content`. JSON output is also auto-detected when piping. Thanks to **@sebsnyk** for the request in #43.

### Changed
- **Error handling priority** — Server error retry now executes *before* authentication recovery.
- **AI docs & Skills updated** — specific documentation on retry behavior and expanded `--json` flags.

## [0.2.18] - 2026-02-09

### Added
- **Claude Desktop Extension (.mcpb)** — One-click install for Claude Desktop. Download the `.mcpb` file from the release page, double-click to install. No manual config editing required.
- **MCPB build automation** — `scripts/build_mcpb.py` reads version from `pyproject.toml`, syncs `manifest.json`, and packages the `.mcpb` file. Old builds are auto-cleaned.
- **GitHub Actions release asset** — `.mcpb` file is automatically built and attached to GitHub Releases alongside PyPI publish.
- **`nlm doctor` and `nlm setup` documentation** — Added to AI docs (`nlm --ai`) and skill file.

### Changed
- **Manifest uses `uvx`** — Claude Desktop extension now uses `uvx --from notebooklm-mcp-cli notebooklm-mcp` for universal PATH compatibility.

### Removed
- Cleaned up `PROJECT_RECAP.md` and `todo.md` (outdated development artifacts).

## [0.2.17] - 2026-02-08

### Added
- **`nlm setup` command** - Automatically configure Gemini Notebook MCP for AI tools (Claude Code, Claude Desktop, Gemini CLI, Cursor, Windsurf). No more manual JSON editing! Thanks to **@997unix** for this contribution (PR #39)
  - `nlm setup list` - Show configuration status for all supported clients
  - `nlm setup add <client>` - Add MCP server config to a client
  - `nlm setup remove <client>` - Remove MCP server config
- **`nlm doctor` command** - Diagnose installation and configuration issues in one command. Checks authentication, Chrome profiles, and AI tool configurations. Also by **@997unix** (PR #39)

### Fixed
- **Version check not running** - Update notifications were never shown after CLI commands because `typer.Exit` exceptions bypassed the check. Moved `print_update_notification()` to a `finally` block so it always runs.
- **Missing import in setup.py** - Fixed `import os` placement for Windows compatibility

## [0.2.16] - 2026-02-05

### Fixed
- **Windows JSON parse errors** - Added `show_banner=False` to `mcp.run()` to prevent FastMCP banner from corrupting stdio JSON-RPC protocol on Windows (fixes #35)
- **Stdout pollution in MCP mode** - Replaced `print()` with logging in `auth.py` and `notebooks.py` to avoid corrupting JSON-RPC output
- **Profile handling in login check** - Fixed `nlm login --check` to use config's `default_profile` instead of hardcoded "default"

## [0.2.15] - 2026-02-04

### Fixed
- **Chat REPL command broken** - Fixed `nlm chat start` failing with `TypeError: BaseClient.__init__() got an unexpected keyword argument 'profile'`. Now uses proper `get_client(profile)` utility and handles dict/list API responses correctly. Thanks to **@eng-M-A-AbelLatif** for the detailed bug report and fix in issue #25!

### Removed
- **Dead code cleanup** - Removed unused `src/notebooklm_mcp/` directory. This legacy code was not packaged or distributed but caused confusion (e.g., PR #29 targeted it thinking it was active). The active MCP server is `notebooklm_tools.mcp.server`. Thanks to **@NOirBRight** for PR #29 which helped identify this dead code.

### Changed
- **Updated tests** - Removed references to deleted `notebooklm_mcp` package from test suite.

### Community Contributors
This release also acknowledges past community contributions that weren't properly thanked:
- **@latuannetnam** for HTTP transport support, debug logging, and query timeout configuration (PR #12)
- **@davidszp** for Linux Chrome detection fix (PR #6) and source_get_content tool (PR #1)
- **@saitrogen** for the research polling query fallback fix (PR #15)

## [0.2.14] - 2026-02-03

### Fixed
- **Automatic migration from old location** - Auth tokens and Chrome profiles are automatically migrated from `~/.notebooklm-mcp/` to `~/.notebooklm-mcp-cli/` on first use. Users upgrading from older versions don't need to re-authenticate.

## [0.2.13] - 2026-02-03

### Fixed
- **Unified storage location** - Consolidated all storage to `~/.notebooklm-mcp-cli/`. Previously some code still referenced the old `~/.notebooklm-mcp/` location, causing confusion. Now everything uses the single unified location.
- **Note**: v0.2.13 was missing migration support - upgrade to v0.2.14 instead.

## [0.2.12] - 2026-02-03

### Removed
- **`notebooklm-mcp-auth` standalone command** - The standalone authentication tool has been officially deprecated and removed. Use `nlm login` instead, which provides all the same functionality with additional features like named profiles. The headless auth for automatic token refresh continues to work behind the scenes.

### Fixed
- **Auth storage inconsistency** - Previously, `notebooklm-mcp-auth` stored tokens in a different location than `nlm login`, causing "Authentication expired" errors. Now there's only one auth path via `nlm login`.
- **Documentation typo** - Fixed `nlm download slides` → `nlm download slide-deck` in CLI guide.

## [0.2.11] - 2026-02-02

### Fixed
- **`nlm login` not launching Chrome** - Running `nlm login` without arguments now properly launches Chrome for authentication instead of showing help. Workaround for v0.2.10: use `nlm login -p default`.

## [0.2.10] - 2026-01-31

### Fixed
- **Version mismatch** - Synchronized version numbers across all package files

## [0.2.9] - 2026-01-31

### Changed
- **Documentation alignment** - Unified MCP and CLI documentation with comprehensive test plan
- **Build configuration** - Moved dev dependencies to optional-dependencies for standard compatibility

### Fixed
- **Studio custom focus prompt** - Extract custom focus prompt from correct position in API response

## [0.2.7] - 2026-01-30

### Removed
- **Redundant CLI commands** - Removed `nlm download-verb` and `nlm research-verb` (use `nlm download` and `nlm research` instead)

### Fixed
- **Documentation alignment** - Synchronized all CLI documentation with actual CLI behavior:
  - Fixed export command syntax: `nlm export to-docs` / `nlm export to-sheets` (not `docs`/`sheets`)
  - Fixed download command syntax: use `-o` flag for output path
  - Fixed slides format values: `detailed_deck` / `presenter_slides` (not `detailed`/`presenter`)
  - Removed non-existent `nlm mindmap list` from documentation

## [0.2.6] - 2026-01-30

### Fixed
- **Source List Display**: Fixed source list showing empty type by using `source_type_name` key correctly

## [0.2.5] - 2026-01-30

### Added
- **Unified Note Tool** - Consolidated 4 separate note tools (`note_create`, `note_list`, `note_update`, `note_delete`) into a single `note(action=...)` tool
- **CLI Shell Completion** - Enabled shell tab completion for `nlm skill` tool argument
- **Documentation Updates** - Updated `SKILL.md`, `command_reference.md`, `troubleshooting.md`, and `workflows.md` with latest features

### Fixed
- Fixed `nlm skill install other` automatically switching to project level
- Fixed `research_status` handling of `None` tasks in response
- Fixed note creation returning failure despite success (timing issue with immediate fetch)

## [0.2.4] - 2026-01-29

### Added
- **Skill Installer for AI Coding Assistants** (`nlm skill` commands)
  - Install Gemini Notebook skills for Claude Code, OpenCode, Gemini CLI, Antigravity, Cursor, and Codex
  - Support for user-level (`~/.config`) and project-level installation
  - Parent directory validation with smart prompts (create/switch/cancel)
  - Installation status tracking with `nlm skill list`
  - Export all formats with `nlm skill install other`
  - Unified CLI/MCP skill with intelligent tool detection logic
  - Consistent `nlm-skill` folder naming across all installations
  - Complete documentation in AI docs (`nlm --ai`)
- Integration tests for all CLI bug fixes (9 tests covering error handling, parameter passing, alias resolution)
- `nlm login profile rename` command for renaming authentication profiles
- **Multi-profile Chrome isolation** - each authentication profile now uses a separate Chrome session, allowing simultaneous logins to multiple Google accounts
- **Email capture during login** - profiles now display associated Google account email in `nlm login profile list`
- **Default profile configuration** - `nlm config set auth.default_profile <name>` to avoid typing `--profile` for every command
- **Auto-cleanup Chrome profile cache** after authentication to save disk space

### Fixed
- Fixed `console.print` using invalid `err=True` parameter (now uses `err_console = Console(stderr=True)`)
- Fixed verb-first commands passing OptionInfo objects instead of parameter values
- Fixed studio command parameter mismatches (format→format_code, length→length_code, etc.)
- Fixed studio methods not handling `source_ids=None` (now defaults to all notebook sources)

### Changed
- **Consolidated auth commands under login** - replaced `nlm auth status/list/delete` with `nlm login --check` and `nlm login profile list/delete/rename`
- Studio commands now work without explicit `--source-ids` parameter (defaults to all sources in notebook)
- Download commands now support notebook aliases (auto-resolved via `get_alias_manager().resolve()`)
- Added `--confirm` flag to `nlm alias delete` command
- Updated all documentation to reflect login command structure

## [0.2.0] - 2026-01-25

### Major Release: Unified CLI & MCP Package (Code Name: "Cancun Wind")

This release unifies the previously separate `notebooklm-cli` and `notebooklm-mcp-server` packages into a single `notebooklm-mcp-cli` package. One install now provides both the `nlm` CLI and `notebooklm-mcp` server.

### Added

#### Unified Package
- Single `notebooklm-mcp-cli` package replaces separate CLI and MCP packages
- Automatic migration from legacy packages (Chrome profiles and aliases preserved)
- Three executables: `nlm` (CLI), `notebooklm-mcp` (MCP server), `notebooklm-mcp-auth` (auth tool)

#### File Upload
- Direct file upload via HTTP resumable protocol (PDF, TXT, Markdown, Audio)
- No browser automation needed for uploads
- File type validation with clear error messages
- `--wait` parameter to block until source is ready

#### Download System
- Unified download commands for all artifact types (audio, video, reports, slides, infographics, mind maps, data tables)
- Streaming downloads with progress bars
- Interactive artifact support - Quiz and flashcards downloadable as JSON, Markdown, or HTML
- Alias support in download commands

#### Export to Google Workspace
- Export Data Tables to Google Sheets (`nlm export sheets`)
- Export Reports to Google Docs (`nlm export docs`)

#### Notes API
- Full CRUD operations: `nlm note create/list/update/delete`
- MCP tools: `note_create`, `note_list`, `note_update`, `note_delete`

#### Sharing API
- View sharing status and collaborators (`nlm share status`)
- Enable/disable public link access (`nlm share public/private`)
- Invite collaborators by email with role selection (`nlm share invite`)

#### Multi-Profile Authentication
- Named profiles for multiple Google accounts (`nlm login --profile <name>`)
- Profile management: `nlm login profile list/delete/rename`
- Each profile gets isolated Chrome session (no cross-account conflicts)

#### Dual CLI Command Structure
- **Noun-first**: `nlm notebook list`, `nlm source add`, `nlm studio create`
- **Verb-first**: `nlm list notebooks`, `nlm add url`, `nlm create audio`
- Both styles work interchangeably

#### AI Coding Assistant Integration
- Skill installer for Claude Code, Cursor, Gemini CLI, Codex, OpenCode, Antigravity
- `nlm skill install <tool>` adds Gemini Notebook expertise to AI assistants
- User-level and project-level installation options

#### MCP Server Improvements
- HTTP transport mode (`notebooklm-mcp --transport http --port 8000`)
- Debug logging (`notebooklm-mcp --debug`)
- Consolidated from 45+ tools down to 28 unified tools
- Modular server architecture with mixins

#### Research Improvements
- Query fallback for more reliable research polling
- Better status tracking for deep research tasks
- Task ID filtering for concurrent research operations

### Changed
- Storage location moved to `~/.notebooklm-mcp-cli/`
- Client refactored into modular mixin architecture (BaseClient, NotebookMixin, SourceMixin, etc.)
- MCP tools consolidated (e.g., separate `notebook_add_url/text/drive` → unified `source_add`)

## [0.1.14] - 2026-01-17

### Fixed
- **Critical Research Stability**:
  - `poll_research` now accepts status code `6` (Imported) as success, fixing "hanging" Fast Research.
  - Added `target_task_id` filtering to `poll_research` to ensure the correct research task is returned (essential for Deep Research).
  - Updated `research_status` and `research_import` to use task ID filtering.
  - `research_status` tool now accepts an optional `task_id` parameter.
- **Missing Source Constants**:
  - Included the code changes for `SOURCE_TYPE_UPLOADED_FILE`, `SOURCE_TYPE_IMAGE`, and `SOURCE_TYPE_WORD_DOC` that were omitted in v0.1.13.

## [0.1.13] - 2026-01-17

### Added
- **Source type constants** for proper identification of additional source types:
  - `SOURCE_TYPE_UPLOADED_FILE` (11): Direct file uploads (e.g., .docx uploaded directly)
  - `SOURCE_TYPE_IMAGE` (13): Image files (GIF, JPEG, PNG)
  - `SOURCE_TYPE_WORD_DOC` (14): Word documents via Google Drive
- Updated `SOURCE_TYPES` CodeMapper with `uploaded_file`, `image`, and `word_doc` mappings

## [0.1.12] - 2026-01-16

### Fixed
- **Standardized source timeouts** (supersedes #9)
  - Renamed `DRIVE_SOURCE_TIMEOUT` to `SOURCE_ADD_TIMEOUT` (120s)
  - Applied to all source additions: Drive, URL (websites/YouTube), and Text
  - Added graceful timeout handling to `add_url_source` and `add_text_source`
  - Prevents timeout errors when importing large websites or documents

## [0.1.11] - 2026-01-16

### Fixed
- **Close Chrome after interactive authentication** - Chrome is now properly terminated after `notebooklm-mcp-auth` completes, releasing the profile lock and enabling headless auth for automatic token refresh
- **Improve token reload from disk** - Removed the 5-minute timeout when reloading tokens during auth recovery. Previously, cached tokens older than 5 minutes were ignored even if the user had just run `notebooklm-mcp-auth`

These fixes resolve "Authentication expired" errors that occurred even after users re-authenticated.

## [0.1.10] - 2026-01-15

### Fixed
- **Timeout when adding large Drive sources** (fixes #9)
  - Extended timeout from 30s to 120s for Drive source operations
  - Large Google Slides (100+ slides) now add successfully
  - Returns `status: "timeout"` instead of error when timeout occurs, indicating operation may have succeeded
  - Added `DRIVE_SOURCE_TIMEOUT` constant in `api_client.py`

## [0.1.9] - 2026-01-11


### Added
- **Automatic re-authentication** - Server now survives token expirations without restart
  - Three-layer recovery: CSRF refresh → disk reload → headless Chrome auth
  - Works with long-running MCP sessions (e.g., MCP Super Assistant proxy)
- `refresh_auth` MCP tool for explicit token reload
- `run_headless_auth()` function for background authentication (if Chrome profile has saved login)
- `has_chrome_profile()` helper to check if profile exists

### Changed
- `launch_chrome()` now returns `subprocess.Popen` handle instead of `bool` for cleanup control
- `_call_rpc()` enhanced with `_deep_retry` parameter for multi-layer auth recovery

## [0.1.8] - 2026-01-10

### Added
- `constants.py` module as single source of truth for all API code-name mappings
- `CodeMapper` class with bidirectional lookup (name→code, code→name)
- Dynamic error messages now show valid options from `CodeMapper`

### Changed
- **BREAKING:** `quiz_create` now accepts `difficulty: str` ("easy"|"medium"|"hard") instead of `int` (1|2|3)
- All MCP tools now use `constants.CodeMapper` for input validation
- All API client output now uses `constants.CodeMapper` for human-readable names
- Removed ~10 static `_get_*_name` helper methods from `api_client.py`
- Removed duplicate `*_codes` dictionaries from `server.py` tool functions

### Fixed
- Removed duplicate code block in research status parsing

## [0.1.7] - 2026-01-10

### Fixed
- Fixed URL source retrieval by implementing correct metadata parsing in `get_notebook_sources_with_types`
- Added fallback for finding source type name in `get_notebook_sources_with_types`

## [0.1.6] - 2026-01-10

### Added
- `studio_status` now includes mind maps alongside audio/video/slides
- `delete_mind_map()` method with two-step RPC deletion
- `RPC_DELETE_MIND_MAP` constant for mind map deletion
- Unit tests for authentication retry logic

### Fixed
- Mind map deletion now works via `studio_delete` (fixes #7)
- `notebook_query` now accepts `source_ids` as JSON string for compatibility with some AI clients (fixes #5)
- Deleted/tombstone mind maps are now filtered from `list_mind_maps` responses
- Token expiration handling with auto-retry on RPC Error 16 and HTTP 401/403

### Changed
- Updated `bl` version to `boq_labs-tailwind-frontend_20260108.06_p0`
- `delete_studio_artifact` now accepts optional `notebook_id` for mind map fallback

## [0.1.5] - 2026-01-09

### Fixed
- Improved LLM guidance for authentication errors

## [0.1.4] - 2026-01-09

### Added
- `source_get_content` tool for raw text extraction from sources

## [0.1.3] - 2026-01-08

### Fixed
- Chrome detection on Linux distros

## [0.1.2] - 2026-01-07

### Fixed
- YouTube URL handling - use correct array position

## [0.1.1] - 2026-01-06

### Changed
- Improved research tool descriptions for better AI selection

## [0.1.0] - 2026-01-05

### Added
- Initial release
- Full Gemini Notebook API client with 31 MCP tools
- Authentication via Chrome DevTools or manual cookie extraction
- Notebook, source, query, and studio management
- Research (web/Drive) with source import
- Audio/Video overview generation
- Report, flashcard, quiz, infographic, slide deck creation
- Mind map generation
