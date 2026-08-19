# tests/core/test_errors.py
"""Tests for artifact exception classes."""

import pytest

from notebooklm_tools.core.errors import (
    ArtifactDownloadError,
    ArtifactError,
    ArtifactNotFoundError,
    ArtifactNotReadyError,
    ArtifactParseError,
    ClientAuthenticationError,
    NotebookLMError,
    ResourceExhaustedError,
    RPCError,
    TransientBackendError,
)


def test_artifact_not_ready_error():
    """Test ArtifactNotReadyError includes artifact type and ID."""
    err = ArtifactNotReadyError("audio", "abc-123")
    assert "audio" in str(err)
    assert "abc-123" in str(err)


def test_artifact_not_ready_error_no_id():
    """Test ArtifactNotReadyError without artifact ID."""
    err = ArtifactNotReadyError("video")
    assert "video" in str(err)
    assert "not ready" in str(err)


def test_artifact_parse_error():
    """Test ArtifactParseError includes type and details."""
    err = ArtifactParseError("video", details="Invalid structure")
    assert "video" in str(err)
    assert "Invalid structure" in str(err)


def test_artifact_download_error():
    """Test ArtifactDownloadError includes type and details."""
    err = ArtifactDownloadError("infographic", "HTTP 403")
    assert "infographic" in str(err)
    assert "HTTP 403" in str(err)


def test_artifact_not_found_error():
    """Test ArtifactNotFoundError stores artifact info."""
    err = ArtifactNotFoundError("abc-123", "report")
    assert "abc-123" in str(err)
    assert "report" in str(err)
    assert err.artifact_id == "abc-123"
    assert err.artifact_type == "report"


def test_client_authentication_error():
    """Test ClientAuthenticationError can be raised."""
    err = ClientAuthenticationError("Session expired")
    assert "Session expired" in str(err)


def test_transient_backend_error_is_not_authentication_error():
    """Transient backend failures expose a retry hint without prompting login."""
    err = TransientBackendError(
        "Could not reach NotebookLM.",
        hint="Check your connection and retry.",
    )

    assert isinstance(err, NotebookLMError)
    assert not isinstance(err, ClientAuthenticationError)
    assert err.message == "Could not reach NotebookLM."
    assert err.hint == "Check your connection and retry."


def test_exception_hierarchy():
    """Test exception inheritance chain."""
    assert issubclass(ArtifactError, NotebookLMError)
    assert issubclass(ArtifactNotReadyError, ArtifactError)
    assert issubclass(ArtifactParseError, ArtifactError)
    assert issubclass(ArtifactDownloadError, ArtifactError)
    assert issubclass(ArtifactNotFoundError, ArtifactError)
    # ClientAuthenticationError is separate from NotebookLMError
    assert issubclass(ClientAuthenticationError, Exception)
    assert issubclass(TransientBackendError, NotebookLMError)
    # ResourceExhaustedError is a subclass of RPCError
    assert issubclass(ResourceExhaustedError, RPCError)
    assert issubclass(ResourceExhaustedError, NotebookLMError)


def test_resource_exhausted_error():
    """Test ResourceExhaustedError stores attributes and has error_code=8."""
    err = ResourceExhaustedError(
        "Rate limited",
        detail_type="type.googleapis.com/UserDisplayableError",
        detail_data=["Please wait"],
    )
    assert err.error_code == 8
    assert "UserDisplayableError" in err.detail_type
    assert err.detail_data == ["Please wait"]
    assert "Rate limited" in str(err)


def test_resource_exhausted_caught_by_rpc_error_handler():
    """Catching RPCError should also catch ResourceExhaustedError."""
    try:
        raise ResourceExhaustedError("test")
    except RPCError as e:
        assert e.error_code == 8
    else:
        pytest.fail("ResourceExhaustedError was not caught by except RPCError")
