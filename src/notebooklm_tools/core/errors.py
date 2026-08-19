# src/notebooklm_tools/core/errors.py
"""Exception classes for NotebookLM API artifacts and client errors.

This module contains exception classes used throughout the NotebookLM API client
for artifact operations (download, parse, status) and authentication errors.

For CLI-specific exceptions (with hint messages), see exceptions.py.
"""

from .exceptions import NLMError


class NotebookLMError(NLMError):
    """Base exception for NotebookLM errors.

    All artifact-related and client-level errors inherit from this class.
    """

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message=message, hint=hint)


class ArtifactError(NotebookLMError):
    """Base exception for artifact errors.

    Covers all errors related to studio artifacts (audio, video, reports, etc.)
    including generation, download, and parsing failures.
    """

    pass


class ArtifactNotReadyError(ArtifactError):
    """Raised when an artifact is not ready for download.

    This occurs when attempting to download an artifact that:
    - Is still being generated
    - Does not exist
    - Has failed generation
    """

    def __init__(self, artifact_type: str, artifact_id: str | None = None):
        msg = f"{artifact_type} is not ready or does not exist"
        if artifact_id:
            msg += f" (ID: {artifact_id})"
        super().__init__(msg)
        self.artifact_type = artifact_type
        self.artifact_id = artifact_id


class ArtifactParseError(ArtifactError):
    """Raised when artifact metadata cannot be parsed.

    This occurs when the API response structure has changed or
    contains unexpected data that cannot be processed.
    """

    def __init__(self, artifact_type: str, details: str = "", cause: Exception | None = None):
        msg = f"Failed to parse {artifact_type} metadata: {details}"
        super().__init__(msg)
        self.__cause__ = cause
        self.artifact_type = artifact_type
        self.details = details


class ArtifactDownloadError(ArtifactError):
    """Raised when artifact download fails.

    This occurs during HTTP download of binary artifacts when:
    - Server returns an error status
    - Network issues occur
    - Response is invalid
    """

    def __init__(self, artifact_type: str, details: str = ""):
        super().__init__(f"Failed to download {artifact_type}: {details}")
        self.artifact_type = artifact_type
        self.details = details


class ArtifactNotFoundError(ArtifactError):
    """Raised when a specific artifact ID is not found.

    This occurs when requesting a specific artifact by ID that
    doesn't exist in the notebook's studio artifacts.
    """

    def __init__(self, artifact_id: str, artifact_type: str = "artifact"):
        super().__init__(f"{artifact_type} not found: {artifact_id}")
        self.artifact_id = artifact_id
        self.artifact_type = artifact_type


class TransientBackendError(NotebookLMError):
    """Raised when the backend cannot be reached to verify authentication.

    This is deliberately not an authentication error: the saved credentials
    may still be valid, and asking the user to log in again cannot repair a
    transport or backend outage.
    """


class ClientAuthenticationError(Exception):
    """Raised when authentication fails (HTTP 401/403 or RPC Error 16).

    This is a client-level exception separate from NotebookLMError hierarchy.
    It indicates that the session/cookies have expired and re-authentication
    is required.

    Note: This class is aliased to `AuthenticationError` in client.py for
    backward compatibility, but that name also exists in exceptions.py with
    a different implementation (CLI-focused with hints).
    """

    pass


class RPCError(NotebookLMError):
    """Raised when a batchexecute RPC returns a structured error payload.

    Google's batchexecute protocol can return errors inside HTTP 200 responses.
    The error is encoded in item[5] of the response array, with structure:
        [error_code, null, [[detail_type_url, [sub_codes...]]]]

    Known error codes:
        3  — Transient/service error (e.g., DeepResearchErrorDetail)
        8  — Resource exhausted / rate limited (raised as ResourceExhaustedError)
        16 — Authentication expired (handled separately as ClientAuthenticationError)

    Attributes:
        error_code: The top-level error code from item[5][0]
        detail_type: The protobuf type URL from item[5][2] (e.g., "...DeepResearchErrorDetail")
        detail_data: Sub-error data from the detail payload (e.g., [4])
    """

    def __init__(self, message: str, error_code: int = 0, detail_type: str = "", detail_data=None):
        super().__init__(message)
        self.error_code = error_code
        self.detail_type = detail_type
        self.detail_data = detail_data


class ResourceExhaustedError(RPCError):
    """Raised when a batchexecute RPC returns error code 8 (RESOURCE_EXHAUSTED).

    This typically indicates rate limiting or capacity throttling from the
    NotebookLM backend (e.g., infographic generation during peak hours).

    Subclass of RPCError so existing ``except RPCError`` handlers still catch it.
    """

    def __init__(self, message: str, detail_type: str = "", detail_data=None):
        super().__init__(message, error_code=8, detail_type=detail_type, detail_data=detail_data)


class RPCDriftError(NotebookLMError):
    """Raised when the response contains other RPC IDs but not the one requested.

    The usual cause is Google rotating the batchexecute method ID. The message
    names the missing id, lists the ids the server *did* return, and points the
    user at NOTEBOOKLM_RPC_OVERRIDES to hot-patch it without a release.

    Deliberately extends NotebookLMError directly, NOT RPCError: drift must
    bypass the service-layer ``except RPCError`` handlers so its actionable
    NOTEBOOKLM_RPC_OVERRIDES guidance reaches the user verbatim instead of
    being reformatted into a generic service error. (Contrast with
    ResourceExhaustedError, which subclasses RPCError on purpose so existing
    handlers still catch it.)
    """

    def __init__(self, rpc_id: str, present_ids: list[str] | None = None):
        present = ", ".join(present_ids) if present_ids else "(none)"
        super().__init__(
            f"No result for RPC '{rpc_id}' — the method ID may have been rotated by Google. "
            f"RPC IDs present in the response: {present}. "
            f'Hot-patch it by setting NOTEBOOKLM_RPC_OVERRIDES=\'{{"<ATTR_NAME>": "<new_id>"}}\' '
            f"(run with --debug to inspect the response)."
        )
        self.rpc_id = rpc_id
        self.present_ids = present_ids or []
