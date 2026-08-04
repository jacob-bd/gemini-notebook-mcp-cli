# Remote MCP Deployment

This guide explains whether Gemini Notebook (formerly Google NotebookLM) MCP can be used as a remote connector
from Claude web, Claude mobile, or another networked MCP client.

## Short Answer

The server supports Streamable HTTP, so remote operation is technically
possible. However, this project is designed and supported primarily for local,
single-user use. It is **not currently a secure, turnkey remote MCP service**.

A production remote deployment must solve two independent authentication
problems:

1. **MCP client authentication** — protecting the public MCP endpoint so only
   authorized clients can call it.
2. **Gemini Notebook authentication** — maintaining the Google browser session used
   by the server to access Gemini Notebook.

The project currently handles the second problem for local installations with a
persistent browser profile. It does not provide the OAuth layer, HTTPS
termination, or per-user isolation required for a public remote connector.

## Current Capabilities

| Requirement | Current status |
|-------------|----------------|
| Streamable HTTP transport | Supported |
| Stateless HTTP sessions | Supported and enabled by default |
| Configurable host, port, and MCP path | Supported |
| Public HTTPS endpoint | Not provided |
| Authentication protecting the MCP endpoint | Not implemented |
| Automatic Google session recovery | Supported when the host has a usable persistent browser profile |
| Fully headless recovery after Google requires sign-in | Not supported |
| Separate Gemini Notebook account per remote user | Not supported |
| Upload files from a browser or phone | Not supported |
| Return downloaded files to a browser or phone | Not supported |

## Why Claude Web and Mobile Are Different

Claude custom connectors connect to remote MCP servers from Anthropic's cloud
infrastructure, not from the user's phone or computer. This also applies when
the connector is used from Claude Desktop.

Therefore:

- A connector cannot use `localhost` or a private endpoint that only your
  computer can reach.
- The MCP server must be reachable from the public internet or from allowed
  Anthropic IP ranges.
- The endpoint should use HTTPS.
- If the endpoint requires authentication, it should implement an
  OAuth-compatible flow supported by Claude custom connectors.

See Anthropic's
[custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
for current client and network requirements.

## Security Warning

Gemini Notebook MCP has no built-in authentication for its HTTP endpoint.

By default, the server only binds to loopback addresses. It refuses external
binding unless `NOTEBOOKLM_ALLOW_EXTERNAL_BIND=1` is set. That override only
disables the safety check—it does **not** add authentication, authorization, or
encryption.

Never expose the server directly to the public internet:

```bash
# Unsafe by itself: no authentication and no TLS
NOTEBOOKLM_ALLOW_EXTERNAL_BIND=1 \
notebooklm-mcp --transport http --host 0.0.0.0
```

Anyone who can reach an unprotected endpoint can operate the active Gemini Notebook
account. Depending on the enabled tools, that may include reading notebooks,
adding or deleting content, creating artifacts, changing sharing settings, and
downloading data.

Use a trusted HTTPS gateway that authenticates every request before forwarding
traffic to a loopback-only MCP server. A simple public tunnel without access
control is not sufficient.

## The Gemini Notebook Authentication Challenge

Gemini Notebook does not provide an official public API for this project. The CLI and
MCP server authenticate with Google browser cookies extracted by `nlm login`.

The reliable local flow is:

1. `nlm login` creates a dedicated persistent browser profile.
2. The user signs in to Google interactively.
3. The CLI stores cookies and the browser profile on the same machine.
4. The MCP server refreshes short-lived Gemini Notebook tokens automatically.
5. If cookies stop working, the saved browser profile can often obtain fresh
   cookies without another manual sign-in.

This works best when the browser profile and MCP server remain on the same
machine and network.

### What cannot be guaranteed

- Google can require interactive sign-in again at any time.
- A machine with no usable browser profile cannot recover independently when
  the Google session expires.
- Cookies copied from another computer may expire quickly or be rejected.
- Cloud and VPS deployments may experience shorter session lifetimes than a
  normal local installation.
- Setting `NOTEBOOKLM_COOKIES` manually creates a static credential. When it
  expires, `nlm login` cannot replace it while that environment variable
  continues to override the profile on disk.

For authentication details, see the
[Authentication Guide](AUTHENTICATION.md).

## Single-Account Architecture

The MCP server uses one process-wide Gemini Notebook client and whichever profile is
currently selected as the default:

```bash
nlm login switch <profile>
```

Every caller of that server operates the same Google account and sees the same
Gemini Notebook notebooks. The current server does not map a remote Claude user to a
separate Google account.

This has important consequences:

- It may be reasonable for one person connecting from several devices.
- It is not a safe organization-wide connector for unrelated users.
- An OAuth gateway can control who reaches the MCP endpoint, but it does not
  create per-user Gemini Notebook isolation.
- Account switching affects the whole server, not one remote session.

## Remote File Limitations

File paths always refer to the filesystem where `notebooklm-mcp` is running.

For example:

```python
source_add(
    notebook_id="...",
    source_type="file",
    file_path="/path/on/server/document.pdf",
)
```

The server cannot read a path from the user's phone or browser. Similarly:

```python
download_artifact(
    notebook_id="...",
    artifact_type="audio",
    output_path="/path/on/server/audio.m4a",
)
```

The artifact is saved on the server host. The current MCP does not provide a
browser upload mechanism or a secure download URL for returning that file to a
remote client.

Remote deployments are therefore better suited to operations involving:

- Notebook listing and queries
- URL and text sources
- Google Drive sources
- Research
- Studio creation and status checks
- Notebook and source metadata

Local file upload and artifact download require a separate, securely designed
file-transfer layer.

## Deployment Options

### Option 1: Claude Code Remote Control

This is the recommended option when the goal is to use Gemini Notebook from a phone
or another browser without operating a public MCP service.

The Gemini Notebook MCP and Claude Code continue running locally on your computer.
Claude Code Remote Control lets you continue that local session from Claude web
or the Claude mobile app.

Advantages:

- The MCP server remains local and does not need a public inbound port.
- The managed browser profile remains on the same machine.
- Local file paths continue to work.
- No custom OAuth gateway is required.

See
[Claude Code Remote Control](https://docs.anthropic.com/en/docs/claude-code/remote-control).

### Option 2: Advanced Single-User Remote Connector

This architecture is technically viable but is not a supported turnkey
deployment:

```text
Claude web/mobile
        |
        | HTTPS + OAuth
        v
Authenticated gateway
        |
        | private loopback connection
        v
Gemini Notebook MCP (Streamable HTTP)
        |
        | Google browser session
        v
NotebookLM
```

Recommended properties:

- Run on an always-on machine controlled by the same user.
- Keep a supported Chromium-family browser and the managed profile on that host.
- Run the MCP server on `127.0.0.1`, not directly on a public interface.
- Put an OAuth-capable HTTPS gateway in front of the server.
- Restrict the connector to the owner of the active Gemini Notebook account.
- Monitor `nlm login --check` and be prepared for occasional interactive login.
- Treat the host as security-sensitive because it stores Google session data.

The private MCP process can be started with:

```bash
notebooklm-mcp \
  --transport http \
  --host 127.0.0.1 \
  --port 8000 \
  --path /mcp
```

The public gateway—not the MCP process itself—must provide HTTPS and caller
authentication.

### Option 3: Cloud VPS or Container

This is not recommended as a persistent deployment unless the operator accepts
manual authentication maintenance.

Common problems include:

- No interactive browser for the initial or renewed Google login
- Ephemeral storage deleting the managed browser profile
- Copied or environment-variable cookies expiring without automatic recovery
- Datacenter network addresses receiving different Google session treatment
- Public endpoint security and OAuth still needing a separate solution
- Server-local file paths being inaccessible to end users

Running the software in a container does not solve these authentication or
security problems by itself.

## Local HTTP Testing

The HTTP transport can be tested safely on the same machine:

```bash
# Authenticate first
nlm login

# Start a loopback-only Streamable HTTP server
notebooklm-mcp \
  --transport http \
  --host 127.0.0.1 \
  --port 8000 \
  --path /mcp
```

The MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The health endpoint is:

```text
http://127.0.0.1:8000/health
```

This confirms transport compatibility. It does not create a Claude web/mobile
connector because Anthropic's cloud cannot reach your loopback address.

## Support Status

Supported:

- Local stdio MCP usage
- Local loopback HTTP transport
- Authentication through `nlm login`
- Automatic refresh using a persistent local browser profile

Advanced and unsupported:

- Public remote connectors
- Cloud/VPS/container hosting
- Reverse proxies and tunnels
- OAuth gateway configuration
- Multi-user deployments
- Remote file-transfer bridges

Remote deployment reports are useful for understanding demand, but the project
cannot guarantee long-lived Google sessions, cloud compatibility, or secure
multi-user operation.

## Related History

These recurring questions informed this guide:

- [Issue #3: Remote and Docker deployment](https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/3)
- [Issue #51: Cookie expiration on Railway](https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/51)
- [Issue #166: Manual cookies on a VPS](https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/166)
- [Issue #179: Authentication on a headless HPC host](https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/179)
