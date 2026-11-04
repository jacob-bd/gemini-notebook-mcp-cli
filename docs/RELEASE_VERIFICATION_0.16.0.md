# 0.16.0 release verification

Date: 2026-11-04. Tested merged code from main, then the release-branch deletion fix.
Account: saved default personal account. Existing notebooks were not modified.

## Live checks

- Created a dedicated release notebook and two additional notebooks with identical test titles.
- Added pasted text and https://example.com; both processed successfully.
- CLI query returned the expected owner, launch date and unique phrase with a source citation.
- CLI chat transcript returned persisted server turns.
- MCP query returned the expected launch color and populated its conversation cache.
- Experimental source_search rejected calls while disabled. With explicit activation, alias lookup returned a passage from the selected source; a foreign source UUID was rejected.
- MCP registry exposes 55 tools, including source_search and chat_delete.
- Collection listing succeeded with confirmed temporary collection cleanup.
- Duplicate-title selection was rejected against the live notebook inventory. Repeated explicit IDs were deduplicated; concurrency 9 was rejected before querying.
- Chat deletion refused an unconfirmed call. Initial confirmed live call exposed INVALID_ARGUMENT: the old body used notebook ID and conversation ID. Captured the web UI request and corrected the body to the consumer header, conversation ID, null, 1.
- Corrected CLI deletion also returned a success acknowledgement.
- Corrected MCP deletion returned success, cleared the shared client cache and left no server turns. Browser reload also showed no prior chat. The persistent conversation ID remains, which is normal and does not imply retained turns.

## Automated and build checks

The complete suite passed 2,608 tests (39 skipped, 42 deselected). Ruff lint and format checks passed. The first full run overlapped live alias cleanup and triggered the storage tripwire; the clean rerun with live operations stopped passed with exit 0. Wheel, source distribution, MCPB extension and skill upload ZIP built successfully. All five release version files are aligned to 0.16.0. Retry and privacy failure paths use deterministic synthetic tests: deliberately inducing ambiguous production write failures would not safely validate replay behavior.

## Limits

This is a personal-account smoke test, not a complete matrix of enterprise accounts, browser-backed transport, operating systems, every source type, Studio generation, or provider outages. No real notebook data was deleted. Test notebooks are retained for inspection. Source search remains experimental and disabled by default. Authenticated HTML dumps from older versions and logging outside the core RPC path remain separate follow-up work.
