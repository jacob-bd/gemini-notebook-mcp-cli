<!-- nlm-skill-start -->
<!-- nlm-version: 0.16.0 -->
## NLM - Gemini Notebook (formerly Google NotebookLM) CLI Expert

**Triggers:** "nlm", "notebooklm", "Gemini Notebook", "plan usage", "quota", "podcast", "audio overview", "research"

Expert assistant for Gemini Notebook automation via CLI. Use when users want to create/manage notebooks, check plan usage and quota windows, add sources (URLs, YouTube, text, Google Drive), generate AI content (podcasts, reports, interactive reports, quizzes, flashcards, mind maps, slides, infographics, videos, data tables), conduct research, or chat with sources.

### Quick Reference

```bash
nlm login                    # Authenticate with NotebookLM
nlm auth refresh             # Non-interactive refresh (unattended/schedulers)
nlm auth refresh --http-only # Validate and save without launching a browser
nlm notebook create "Title"  # Create notebook
nlm source add <id> --url "https://..."  # Add web source
nlm audio create <id> --confirm          # Generate podcast
nlm research start "query" --notebook-id <id>  # Discover sources
nlm research start "query" --title "New Research"  # Create destination notebook
nlm usage                    # Check rolling + weekly plan usage and reset times
nlm usage --json             # Machine-readable usage percentages and timestamps
nlm auth storage status      # Check credential storage mode (file or protected)
nlm auth storage set protected # Encrypt stored credentials (OS credential store)
```

### Critical Rules

1. **Authenticate when needed**: Run `nlm login` for setup or confirmed stale credentials
2. **Do not treat `unverified` as expired**: Check connectivity or try an API call first
3. **`--confirm` required** for generation/delete commands
4. **Capture IDs from output** for subsequent operations
5. **Use `nlm alias set`** to simplify UUIDs
6. **⚠️ NEVER auto-delete**: Always ask user before `nlm delete`
7. **⚠️ NEVER use `nlm chat start`**: It's an interactive REPL. Use `nlm notebook query` instead
8. **Use the configured MCP name**: Register this server as `gemini-notebook-mcp`; the executable remains `notebooklm-mcp` for compatibility.
9. **Use the setup wizard for client configuration**: Run `nlm setup` to detect installed clients and choose status, add MCP, add skill, remove, or copy MCP setup (the user drives it in a real terminal; Esc goes back). Connections still using the old `notebooklm-mcp` name are offered for a rename to `gemini-notebook-mcp`. For Claude Desktop Chat/Cowork or claude.ai, `nlm skill package` creates an upload file (`~/Downloads/nlm-skill.zip`). MCP setup defaults to app/user scope. Codex CLI and the ChatGPT desktop app share one MCP config on the same host. The optional skill defaults to all projects (user level); choose project level only when the user wants this folder. The wizard backs up existing configs and skills before changing them.
10. **Check plan usage before quota-limited work**: Run `nlm usage` or call `usage_get` to inspect rolling and weekly percentages and reset times. Authentication failures should be refreshed with `nlm auth refresh`, not treated as exhausted quota. Use `--http-only` when browser launch must be avoided; fully expired logins still require `nlm login`. MCP `refresh_auth(profile="work")` refreshes a named account without switching the active account.

### Common Workflows

**Research → Podcast Pipeline:**
```bash
nlm notebook create "AI Research"
nlm alias set ai <notebook-id>
nlm research start "AI trends" --notebook-id ai --mode deep
nlm research status ai --max-wait 900
nlm research import ai <task-id>
nlm audio create ai --confirm
nlm studio status ai
```

**Plan Usage Check:**
```bash
nlm usage
nlm usage --json
```
The report is read-only and shows rolling and weekly compute windows, the
remaining percentage, reset timestamps in UTC (JSON) or local time (table),
and the subscription tier when available. Use `usage_get` for the same report
through MCP.

**Quick Content Ingestion:**
```bash
nlm source add <id> --url "https://example.com"
nlm source add <id> --text "Notes..." --title "My Notes"
nlm source add <id> --drive <doc-id>
```

**Study Materials:**
```bash
nlm report create <id> --format "Study Guide" --confirm
nlm report create <id> --format Interactive --prompt "Lesson goal" --confirm  # lesson report; embeds elements
nlm report get <id> <report-id>          # read the lesson markdown
nlm report elements <id> <report-id>     # embedded elements + status
nlm quiz create <id> --count 10 --focus "Key Concepts" --confirm
nlm flashcards create <id> --focus "Vocabulary" --confirm
```

**Multi-Notebook Operations:**
```bash
nlm tag add <id> --tags "ai,research"                     # Tag notebooks
nlm batch query "Summarize" --tags "ai"                   # Batch query by tag
nlm cross query "Compare approaches" --notebooks "id1,id2"  # Cross-notebook query
nlm pipeline run ingest-and-podcast --notebook <id> --input-url "https://..."
```

### Full Documentation

For complete command reference, troubleshooting, and workflows, install the full skill:

```bash
# Install via uv
uv tool install notebooklm-mcp-cli

# Then install/update skill for your AI tool
nlm skill install <tool>  # Install (claude-code, agents, opencode, etc)
nlm skill update <tool>   # Update existing skill
```

Or view inline: `nlm --ai`

<!-- nlm-skill-end -->

### New in 0.16.0

- Experimental MCP source_search retrieves bounded, source-attributed passages. Off by default; enable NOTEBOOKLM_ENABLE_NATIVE_SOURCE_SEARCH=1. Supports notebook aliases and native source UUID filters. No CLI equivalent.
- chat_delete / nlm chats delete permanently clears notebook chat turns after explicit confirmation. The persistent conversation ID can remain. Use the active authenticated MCP client and never replay uncertain deletion requests.
