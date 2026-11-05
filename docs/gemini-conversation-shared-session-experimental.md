# Gemini notebook-scoped conversation discovery (experimental)

**Classification:** EXPERIMENTAL. Read-only. Not a documented Google API.
**Scope:** Discover Gemini conversations associated with a notebook that is also
accessible to the *currently selected* NotebookLM profile.
**Transport:** Existing NotebookLM `NotebookLMClient` and HTTP cookie session.

## Why

Gemini's internal `MaZiqc` RPC returns notebook-scoped **Gemini conversations**.
Its `c_...` identifiers are **not native NotebookLM source identifiers**. Native
NotebookLM's `chat_list` exposes its own persistent conversation, while Gemini
can expose multiple conversations for the same notebook. This experimental
tool keeps those namespaces separate rather than pretending that Gemini chats
are sources or importing them into the notebook.

## MCP tool

```text
gemini_notebook_conversation_list(
    notebook_id="<NotebookLM UUID>",
    limit=10,
    gemini_account_index=0
)
```

Requires `NOTEBOOKLM_ENABLE_GEMINI_CONVERSATIONS=1` **and** an explicit
`NOTEBOOKLM_GEMINI_ACCOUNT_BINDINGS` profile-to-Gemini-index JSON mapping in
the MCP process environment. For example, `{"pte":0}` *only after separately
verifying* that profile `pte` corresponds to Gemini `/u/0/` on that device.
Neither variable is set by deployment; the feature remains **off by default**.
The tool belongs to the
`chat` group and honors the existing MCP disabled-tool/group controls.
The selected NotebookLM profile must already be authenticated. The tool does
not log in, change Google accounts, persist Gemini session values, import
transcripts, or mutate anything.

`gemini_account_index` is an *explicit* Gemini web account route (0..9).
The tool does **not** scan alternatives or automatically switch identities.
Index 0 is the route observed in the captured HAR; it is not guaranteed to
be the user's selected NotebookLM Google account. Requests are rejected unless
the active named NotebookLM profile and the requested Gemini index exactly
match the explicitly configured mapping. Environment-only cookie clients
without a named profile cannot use this feature.

## Authentication

1. Check that the requested native NotebookLM notebook exists and retrieve
   its current source UUIDs through the selected NotebookLM client.
2. Use the **same HTTP client's** already-authenticated Google cookie jar to
   load `https://gemini.google.com/app` once, without following redirects.
3. Extract fresh `SNlM0e` (form token), `cfb2h` (build label), and
   `FdrFJe` (session ID) from the page **in memory only**.
4. Make one read-only `HcT8bb` metadata request for the notebook. Verify the
   exact notebook resource and at least one source UUID also present in the
   native NotebookLM source inventory. **If no overlap, fail closed.**
5. Make one read-only `MaZiqc` request for that notebook. Return at most ten
   distinct `c_...` conversation IDs and bounded titles, only if each row
   explicitly contains the requested notebook reference.

There is **no separate credential cache**, HAR replay, token export,
automatic fallback to other accounts, or mutation. Each operation gets fresh
Gemini bootstrap values. If the session is expired or unavailable, the tool
returns a sanitized error and relies on the existing **visible** NotebookLM
login workflow for user-controlled reauthentication.

When HTTP transport diagnostics are enabled at INFO/DEBUG, the operation
fails closed to prevent disclosure of request URLs containing session IDs.
This is session reuse, **not a formal OAuth scope or supported consumer API**.
The source-overlap check confirms the notebook data matches; it cannot prove
that two browser applications are using the same human identity for a shared
notebook. Empty notebooks cannot pass the current fail-closed identity check.

## Response semantics

The result records `gemini_conversation_id`, bounded title (max 200 chars),
and `provenance=gemini_notebook_scoped_conversation`. It includes
`identity_check=native_source_uuid_overlap` and an overlap count.
`complete_history=false` because `MaZiqc` was only validated with a
ten-record first-page request; pagination and ordering are undocumented.
There is **no transcript retrieval** and **no equivalence claim** to native
NotebookLM conversations. Titles may be private metadata.

## Security and reliability

- One notebook and one Gemini account explicitly bound to the active named
  NotebookLM profile; no account probing or implicit switching.
- Reject verbose HTTP logging before making network requests, with additional
  best-effort URL redaction at request time.
- No retries on 401/403/3xx; no hidden browser launch.
- Private titles are not logged by the standard MCP request/response decorator:
  the tool uses the existing `unlogged_tool` central registry.
- Gemini HTTPX diagnostic messages containing Gemini URLs are redacted for
  the request duration, to reduce leakage of the URL's session identifier.
- HTTP exceptions and raw server errors are suppressed in tool responses.
- Private network traces and external instrumentation are outside this
  application-level logging guard. Do not enable unrestricted HTTP tracing.
- RPC request/response formats are undocumented and may change without notice.

## Verification boundary

A read-only implementation test on November 3, 2026 returned successful
`MaZiqc` and `HcT8bb` results through the existing NotebookLM HTTP session.
One notebook had 175 of 183 native source UUIDs verified and 8 Gemini
conversations; a second had 236 of 237 verified and 1 Gemini conversation.
Both had a native NotebookLM chat ID, but neither native ID matched a Gemini
conversation ID. This does not prove global account identity or transcript
interoperability. Future installations must be evaluated per account/profile.
Do not merge or deploy simply because a browser RPC returns 200.

**Dependency:** Uses the upstream `unlogged_tool` registry helper to protect
private conversation titles from generic MCP result logging. This PR does not
require a SanityCloud-specific plugin or service configuration.
