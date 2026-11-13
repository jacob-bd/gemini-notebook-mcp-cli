"""Service layer errors and exceptions."""


class ServiceError(Exception):
    """Base class for service errors with optional structured metadata."""

    def __init__(
        self,
        message: str,
        user_message: str | None = None,
        hint: str | None = None,
        debug_code: str | None = None,
        *,
        category: str | None = None,
        provider_code: int | str | None = None,
        retryable: bool | None = None,
        suggested_action: str | None = None,
    ):
        super().__init__(message)
        self.user_message = user_message or message
        self.hint = hint
        self.debug_code = debug_code
        self.category = category
        self.provider_code = provider_code
        self.retryable = retryable
        self.suggested_action = suggested_action

    def details(self) -> dict[str, str | int | bool]:
        """Return non-empty machine-readable metadata for API and MCP clients."""
        values: dict[str, str | int | bool | None] = {
            "category": self.category,
            "provider_code": self.provider_code,
            "retryable": self.retryable,
            "suggested_action": self.suggested_action,
            "debug_code": self.debug_code,
        }
        return {key: value for key, value in values.items() if value is not None}


class ValidationError(ServiceError):
    """Raised when input parameters are invalid."""

    pass


class NotFoundError(ServiceError):
    """Raised when a resource (notebook, source, etc.) is not found."""

    def __init__(
        self,
        message: str,
        user_message: str | None = None,
        hint: str | None = None,
        resource_type: str = "Resource",
        debug_code: str | None = None,
    ):
        if hint is None:
            cmd = "notebook" if resource_type.lower() == "notebook" else resource_type.lower()
            hint = f"Run 'nlm {cmd} list' to see available {cmd}s."
        super().__init__(message, user_message=user_message, hint=hint, debug_code=debug_code)


class CreationError(ServiceError):
    """Raised when a creation operation fails (e.g. fail-fast check)."""

    pass


class ConflictError(ServiceError):
    """Raised when a resource already exists or an operation conflicts with current state."""

    pass


class ExportError(ServiceError):
    """Raised when an export operation fails."""

    pass


# ---------------------------------------------------------------------------
# Re-exports from `core` so `cli/` and `mcp/` reach the low-level layer through
# `services/` (see the layering rules in AGENTS.md). Resolved lazily, like
# `services.auth`, so monkeypatching a `core.*` symbol still affects callers.
# ---------------------------------------------------------------------------

_CORE_ERROR_SOURCES = {
    "NLMError": "exceptions",
    "AuthenticationError": "exceptions",
    "AccountMismatchError": "exceptions",
    "ClientAuthenticationError": "errors",
    "ArtifactNotReadyError": "errors",
    "CredentialStoreError": "credential_store",
}

__all__ = [
    "AccountMismatchError",  # noqa: F822 - provided lazily via PEP 562 __getattr__
    "ArtifactNotReadyError",  # noqa: F822 - provided lazily via PEP 562 __getattr__
    "AuthenticationError",  # noqa: F822 - provided lazily via PEP 562 __getattr__
    "ClientAuthenticationError",  # noqa: F822 - provided lazily via PEP 562 __getattr__
    "ConflictError",
    "CreationError",
    "CredentialStoreError",  # noqa: F822 - provided lazily via PEP 562 __getattr__
    "ExportError",
    "NLMError",  # noqa: F822 - provided lazily via PEP 562 __getattr__
    "NotFoundError",
    "ServiceError",
    "ValidationError",
]


def __getattr__(name: str):
    """PEP 562 lazy re-export of error types from `core`."""
    source = _CORE_ERROR_SOURCES.get(name)
    if source is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f"notebooklm_tools.core.{source}"), name)
