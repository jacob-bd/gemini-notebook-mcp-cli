from unittest.mock import MagicMock

from notebooklm_tools.core.client import NotebookLMClient


def test_delete_clears_same_client_cache_and_disables_replay():
    client = NotebookLMClient(cookies={"SID": "synthetic"}, csrf_token="synthetic")
    client._conversation_cache["conversation"] = [{"query": "old", "answer": "old"}]
    client._call_rpc = MagicMock(return_value=[])

    assert client.delete_chat_history("notebook", "conversation") is True
    assert "conversation" not in client._conversation_cache
    assert client._call_rpc.call_args.kwargs["retry_server_errors"] is False
