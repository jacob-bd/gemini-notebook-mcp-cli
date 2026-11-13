# Contributing to Gemini Notebook (formerly Google NotebookLM) MCP Server & CLI

Thanks for your interest in contributing. This project gives you programmatic access to Gemini Notebook through an MCP server and CLI, built on top of Google's undocumented internal `batchexecute` API. The API can change without notice, so contributions need to be grounded in captured, verified payloads, not assumptions.

## Before You Start

For small features, bug fixes, and improvements, just open a PR with a clear description.

For large architectural changes (new auth providers, enterprise support, new client abstractions), open an issue first to discuss the approach. This saves everyone's time. We may already have plans or constraints you should know about.

## Development Setup

**Requirements:** Python >= 3.11, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and install
git clone https://github.com/jacob-bd/gemini-notebook-mcp-cli.git
cd notebooklm-mcp-cli
uv tool install .

# Authenticate (opens Chrome for Google login)
nlm login

# Verify
nlm login --check
```

### Reinstalling After Code Changes

The MCP server keeps code in memory. After making changes, you **must** run:

```bash
uv cache clean && uv tool install --force .
```

Then restart any running MCP clients (Claude Code, Claude Desktop, etc.) before testing. If you skip this, you're testing old code.

## Architecture

```
cli/  and  mcp/     →  services/  →  core/
(thin wrappers)        (business logic)  (low-level API)
```

**This layering is non-negotiable:**

- `cli/` and `mcp/` are thin wrappers. They handle UX concerns (prompts, spinners, JSON responses) and delegate everything to `services/`
- `services/` contains all business logic, validation, and error handling. Returns typed dicts.
- `cli/` and `mcp/` must **never** import from `core/` directly. Always go through `services/`
- Shared primitives (error types, aliases, credential storage, notices, cookie parsing) are re-exported through `services/` with lazy lookups, following `services/auth.py`. `tests/test_layering.py` enforces the boundary.
- `services/` raises `ServiceError` / `ValidationError`. Never raw exceptions.

See [CLAUDE.md](./CLAUDE.md) for the full module map and storage structure.

## How to Implement a New Feature

This project wraps an undocumented API. The only reliable way to implement new features is to capture the actual network requests Google's web UI makes. Here's the workflow:

### 1. Capture the API Call

1. Open Chrome DevTools, go to the **Network** tab
2. Navigate to [notebook.google.com](https://notebook.google.com) and open a notebook
3. Perform the action you want to implement in the web UI
4. Filter for `batchexecute` requests
5. Copy the `f.req` form parameter (request payload) and the response body

### 2. Implement End-to-End

Think in full circles: **create, status, download**. A half-implemented feature (for example, creation without status parsing) creates gaps that are easy to miss.

| Step | File | What |
|------|------|------|
| 1 | `docs/API_REFERENCE.md` | Document the RPC ID and param structure |
| 2 | `core/client.py` | Add the low-level API method |
| 3 | `services/*.py` | Add business logic, validation, error handling |
| 4 | `mcp/tools/*.py` | Add MCP tool (thin wrapper around service) |
| 5 | `cli/commands/*.py` | Add CLI command (thin wrapper around service) |
| 6 | Status/read-back | Update status parsing if your feature produces artifacts |
| 7 | `tests/services/` | Write unit tests for the service function |
| 8 | `docs/MCP_CLI_TEST_PLAN.md` | Add test cases for manual validation |

**CLI verb wrappers:** When adding a new CLI option to a command function in `cli/commands/`, you must also add it to the corresponding verb wrapper in `cli/commands/verbs.py`. The `tests/cli/test_verbs_parity.py` test enforces this — CI will fail if a verb wrapper is missing a parameter from its target function.

### 3. Test in Python Before Adding MCP/CLI Tools

Always validate the core API call works before wiring up the MCP tool or CLI command. Write a quick Python test script, run it, confirm it works. Then add the wrappers. This prevents shipping broken tools.

## Code Quality

Both checks must pass. CI runs them as separate steps:

```bash
# Linting
uv run ruff check .

# Formatting
uv run ruff format --check .

# Auto-fix formatting
uv run ruff format .
```

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `style:` Formatting, lint fixes (no logic change)
- `docs:` Documentation only
- `refactor:` Code change that neither fixes a bug nor adds a feature
- `test:` Adding or updating tests

## Testing

### Automated Tests

```bash
# Full suite
uv run pytest

# Single test
uv run pytest tests/test_file.py::test_function -v
```

### Manual Testing

Automated tests alone are not enough. You must manually verify your changes work via **both** the CLI and MCP tools:

```bash
# CLI
nlm <your-command> ...

# MCP (restart your MCP client first after reinstalling)
# Use the MCP tool in Claude Code, Claude Desktop, or your client of choice
```

Include evidence of both CLI and MCP testing in your PR description.

## Error Handling

- Services raise `ServiceError` or `ValidationError` from `services/errors.py`. Never raw Python exceptions.
- Chain exceptions properly: `raise ServiceError(...) from err` (ruff rule B904)
- Destructive or long-running operations must require `confirm=True`. Always show the user what will happen before they confirm.

Operations that currently require confirmation:
- Deleting notebooks, sources, notes, or studio artifacts (irreversible)
- Syncing Drive sources
- All studio content creation
- Slide revision

If your feature is destructive or produces billable/quota-consuming results, add the `confirm` parameter.

## Handling API Changes

Google rolls out API changes gradually, sometimes by region, sometimes by account. If users report failures you can't reproduce:

1. Ask for the raw request payload (`f.req`) from their browser
2. Compare it against the current code's param structure
3. If the RPC ID changed, implement a fallback pattern (try new RPC first, fall back to old)

See the `add_url_source()` dual-RPC fallback in `core/sources.py` for an example of this pattern.

## Security

This is a security-conscious codebase. Keep these in mind:

- **Never commit cookies, tokens, or credentials.** Not in code, tests, or examples.
- **Validate output paths.** Downloads must not write to sensitive directories (`.ssh`, `.aws`, `.gnupg`, etc.)
- **Validate URLs.** Base URLs must be HTTPS and on the Google domain allowlist.
- **File permissions.** Auth files and debug output should use restrictive permissions (`0o600` / `0o700`)
- **No command injection.** Never pass user input to shell commands unsanitized.
- **Credential store testing.** Unit and integration tests for authentication and credential storage must always use `fake_credential_store`, `tmp_path`, and synthetic storage paths. Never read, write, or mutate real macOS Keychains, Windows Credential Manager, or the developer's real `~/.notebooklm-mcp-cli` directory. Real-keystore tests require explicit opt-in (`ALLOW_REAL_KEYSTORE=1`) and must use unique test-scoped service names with guaranteed cleanup. On macOS, never point `HOME` at a temp dir when a test touches the real Keychain. Isolate with `NOTEBOOKLM_MCP_CLI_PATH` and a unique service name instead. The `NOTEBOOKLM_KEYSTORE_SERVICE_NAME` environment override is strictly test-only and is only honored when `ALLOW_REAL_KEYSTORE=1` is set.
- **Suite-level storage tripwire.** The test suite includes a session-level tripwire in `tests/conftest.py` that snapshots `~/.notebooklm-mcp-cli` and `~/.notebooklm-mcp` before each run and immediately fails the entire test session if any test creates, deletes, or unexpectedly modifies files in the developer's real storage.

To report a security vulnerability, please email the maintainer directly. Don't open a public issue.

## PR Guidelines

- **One feature or fix per PR.** Keeps reviews manageable.
- **Include a clear description.** What changed, why, and how you verified it.
- **Show live API verification.** Mention that you tested against the actual Gemini Notebook API, not just mocks.
- **Don't bump the version.** The maintainer handles versioning and releases.
- **Don't add `Co-authored-by` trailers.** Commits are attributed to the PR author.

## Dependencies

This project keeps dependencies minimal. If your change requires a new dependency, justify it in the PR description. Prefer using what's already available (`httpx`, `typer`, `websocket-client`) over adding new packages.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](./LICENSE).
