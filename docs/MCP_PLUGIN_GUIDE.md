# NotebookLM MCP Plugin Guide

NotebookLM MCP supports optional plugins for third-party tools and HTTP routes.
The core server registers built-in tools first, then loads explicitly configured
plugins. This lets local integrations add behavior without patching core tool
modules such as `server.py`, `tools/sources.py`, or `tools/downloads.py`.

Plugins are disabled by default.

## Why this exists

Some integrations need to extend NotebookLM MCP with local workflow-specific
tools, tunnel routes, file handoff logic, or organization policy checks. Without
a plugin seam, those integrations must patch built-in modules and repeatedly
rebase whenever upstream changes core tools, auth, or transport code.

The plugin loader keeps the core server stable while giving downstream users a
supported extension point. Core NotebookLM MCP continues to own built-in tools,
authentication, and transport startup. Plugins own optional behavior and can be
installed, audited, enabled, disabled, or upgraded independently.

This is especially useful for integrations that are valuable locally but too
specific or too security-sensitive to enable for every NotebookLM MCP user by
default.

## Configuration

Load plugins with a comma-separated environment variable:

```text
NOTEBOOKLM_MCP_PLUGINS=my_package.plugin,my_package.plugin:register_tools
```

Each item can be one of:

- an entry point name from the `notebooklm_tools.mcp_plugins` group;
- a Python module exposing `register(mcp)`;
- a `module:function` callable spec.

Optional settings:

```text
NOTEBOOKLM_MCP_PLUGIN_STRICT=true
NOTEBOOKLM_MCP_PLUGIN_AUTOLOAD=false
```

`NOTEBOOKLM_MCP_PLUGIN_STRICT=true` is the default. Explicit plugin load
failures stop server startup so a missing or broken integration is not silently
ignored. Set it to `false` only when best-effort loading is desired.

`NOTEBOOKLM_MCP_PLUGIN_AUTOLOAD=true` loads every installed entry point in the
`notebooklm_tools.mcp_plugins` group. Explicit `NOTEBOOKLM_MCP_PLUGINS` is
preferred for production because it is easier to audit.

## Minimal plugin module

```python
# my_package/plugin.py

def register(mcp):
    @mcp.tool()
    def plugin_status() -> dict[str, str]:
        """Return plugin health."""
        return {"status": "success"}
```

Run the MCP server with:

```text
NOTEBOOKLM_MCP_PLUGINS=my_package.plugin notebooklm-mcp
```

## Custom HTTP routes

Plugins receive the FastMCP instance, so they can register routes when they need
HTTP callbacks or short-lived download endpoints:

```python
from starlette.responses import JSONResponse


def register(mcp):
    @mcp.custom_route("/plugins/example/health", methods=["GET"])
    async def plugin_health(request):
        return JSONResponse({"status": "healthy"})
```

Plugins that expose routes are responsible for their own security model:
confirmation gates, token validation, TTLs, path validation, cleanup, and any
public-tunnel exposure controls.

## Packaging entry point

A plugin package can advertise itself through Python package metadata:

```toml
[project.entry-points."notebooklm_tools.mcp_plugins"]
chatgpt_bridge = "notebooklm_chatgpt_bridge:register"
```

Then load it explicitly:

```text
NOTEBOOKLM_MCP_PLUGINS=chatgpt_bridge notebooklm-mcp
```

## Design intent

The plugin seam is intentionally small. Core NotebookLM MCP remains responsible
for built-in NotebookLM tools and authentication. Plugins should depend on
public service-layer APIs and should avoid monkey-patching built-in tools.

## Plugin ideas

The plugin hook is intentionally generic. Examples of extensions it can support:

- **ChatGPT file bridge** — inbound ChatGPT-hosted file URLs to NotebookLM sources, and outbound NotebookLM artifacts behind short-lived tokenized routes.
- **Enterprise policy gate** — enforce organization-specific allowlists, source limits, file-type restrictions, retention rules, or audit metadata before calling NotebookLM services.
- **Local knowledge-base sync** — import/export NotebookLM sources or notes from a local folder, Obsidian vault, Notion workspace, SharePoint mirror, or legal evidence directory.
- **Artifact post-processing** — transcode audio, convert slide decks, normalize filenames, generate sidecar metadata, or package NotebookLM outputs for downstream tools.
- **Webhook/callback routes** — expose local-only HTTP endpoints for workflow orchestrators that need to notify the MCP server when a file, job, or external process is ready.
- **Domain-specific tool packs** — add legal, research, education, medical-literature, or engineering workflow tools that compose NotebookLM primitives without expanding the core tool surface.
- **Observability plugin** — add health probes, metrics, redacted audit logs, queue status, or runtime diagnostics for long-lived MCP deployments.
- **Rate-limit/coordinator plugin** — coordinate local concurrency, backoff, or queueing across multiple MCP clients that share one NotebookLM account.

Plugins should remain opt-in and should document their own threat model when
they expose routes, touch local files, or call third-party services.
## SanityCloud rate-limit policy

The upstream client retries HTTP 429 and RPC `RESOURCE_EXHAUSTED` responses by
default. Multi-agent runtimes that already coordinate retries externally can
disable those internal replays:

```text
NOTEBOOKLM_RATE_LIMIT_RETRY=false
```

This does not disable connection-establishment retries or authentication
recovery. It only surfaces rate-limit responses immediately so the external
queue or coordinator remains the single retry authority.
