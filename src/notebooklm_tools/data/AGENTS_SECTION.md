<!-- nlm-skill-start -->
<!-- nlm-version: 0.9.6 -->
## NLM - Gemini Notebook (formerly Google NotebookLM) CLI Expert

**Triggers:** "nlm", "notebooklm", "Gemini Notebook", "podcast", "audio overview", "research"

Expert assistant for Gemini Notebook automation via CLI. Use when users want to create/manage notebooks, add sources (URLs, YouTube, text, Google Drive), generate AI content (podcasts, reports, quizzes, flashcards, mind maps, slides, infographics, videos, data tables), conduct research, or chat with sources.

### Quick Reference

```bash
nlm login                    # Authenticate with NotebookLM
nlm notebook create "Title"  # Create notebook
nlm source add <id> --url "https://..."  # Add web source
nlm audio create <id> --confirm          # Generate podcast
nlm research start "query" --notebook-id <id>  # Discover sources
nlm research start "query" --title "New Research"  # Create destination notebook
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
9. **Never configure blindly**: `nlm setup` verifies the MCP executable and detected client profile before writing. User-level skills require the target tool to be detected; use `--level project` for an intentional project-local install.

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

**Quick Content Ingestion:**
```bash
nlm source add <id> --url "https://example.com"
nlm source add <id> --text "Notes..." --title "My Notes"
nlm source add <id> --drive <doc-id>
```

**Study Materials:**
```bash
nlm report create <id> --format "Study Guide" --confirm
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
