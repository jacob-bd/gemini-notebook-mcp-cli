"""The wrapper layers reach `core/` only through `services/`.

AGENTS.md, CLAUDE.md, and CONTRIBUTING.md require `cli/` and `mcp/` to be thin
wrappers: they may import services, never core. Shared primitives (errors,
aliases, credential storage, notices, cookie parsing, the API client class)
are re-exported by the services layer, following the pattern in
`services.auth`.
"""

import ast
from importlib.util import resolve_name
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "notebooklm_tools"
WRAPPER_LAYERS = ("cli", "mcp")
CORE_PREFIX = "notebooklm_tools.core"


def _is_core(module: str) -> bool:
    return module == CORE_PREFIX or module.startswith(CORE_PREFIX + ".")


def _package_for(path: Path) -> str:
    """Dotted package that contains ``path`` (only cli/ and mcp/ are scanned)."""
    relative = path.relative_to(PACKAGE)
    return ".".join(("notebooklm_tools", *relative.parent.parts))


def _core_imports(path: Path) -> list[str]:
    """Return ``file:line module`` for every direct core import in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _package_for(path)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                # Resolve ``from ..core import x`` relative to this module's package.
                try:
                    module = resolve_name("." * node.level + module, package)
                except (ImportError, ValueError):
                    found.append(f"{path.name}:{node.lineno} <unresolved relative import>")
                    continue
            if _is_core(module):
                found.append(f"{path.name}:{node.lineno} {module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_core(alias.name):
                    found.append(f"{path.name}:{node.lineno} {alias.name}")
    return found


def test_wrapper_layers_do_not_import_core():
    scanned = 0
    offenders: list[str] = []
    for layer in WRAPPER_LAYERS:
        for path in sorted((PACKAGE / layer).rglob("*.py")):
            scanned += 1
            offenders.extend(_core_imports(path))

    assert scanned > 0, "no wrapper modules found; check the package path"
    assert not offenders, (
        "cli/ and mcp/ must import shared primitives from services/, not core/. "
        f"Direct core imports: {offenders}"
    )


def test_service_facades_expose_the_shared_primitives():
    """Pin the shim contract so a facade cannot silently drop a symbol."""
    from notebooklm_tools.services import aliases, auth, auth_storage, client, errors, notices

    for name in (
        "NLMError",
        "AuthenticationError",
        "AccountMismatchError",
        "ClientAuthenticationError",
        "ArtifactNotReadyError",
        "CredentialStoreError",
    ):
        assert getattr(errors, name).__module__.startswith("notebooklm_tools.core")

    assert callable(aliases.get_alias_manager)
    assert callable(aliases.detect_id_type)
    assert callable(auth.extract_cookies_from_chrome_export)
    for name in ("CredentialStore", "get_backend_factory", "get_envelope_revision"):
        assert getattr(auth_storage, name).__module__.startswith("notebooklm_tools.core")
    for name in (
        "get_protect_answer",
        "record_protect_answer",
        "is_cli_notice_shown",
        "mark_cli_notice_shown",
        "is_mcp_notice_shown",
        "mark_mcp_notice_shown",
    ):
        assert getattr(notices, name).__module__.startswith("notebooklm_tools.core")
    assert client.NotebookLMClient.__module__.startswith("notebooklm_tools.core")
