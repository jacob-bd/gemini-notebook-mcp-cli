"""Drive freshness CLI must never mistake an unchecked source for fresh."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from typer.testing import CliRunner

from notebooklm_tools.cli.commands import source as commands


def _drive(source_id: str, stale: bool | None, can_sync: bool = True) -> dict:
    return {
        "id": source_id,
        "type": "google_drive",
        "title": source_id,
        "stale": stale,
        "can_sync": can_sync,
    }


def _setup(monkeypatch, drive_sources: list[dict]) -> list[list[str]]:
    calls: list[list[str]] = []

    @contextmanager
    def fake_client(_profile):
        yield SimpleNamespace()

    monkeypatch.setattr(
        commands, "get_alias_manager", lambda: SimpleNamespace(resolve=lambda value: value)
    )
    monkeypatch.setattr(commands, "get_client", fake_client)
    monkeypatch.setattr(
        commands.sources_service,
        "list_drive_sources",
        lambda _client, _id: {"drive_sources": drive_sources},
    )
    monkeypatch.setattr(
        commands.sources_service,
        "sync_drive_sources",
        lambda _client, ids: calls.append(list(ids)) or [{"synced": True} for _ in ids],
    )
    return calls


def test_stale_lists_confirmed_stale_and_reports_unknown(monkeypatch) -> None:
    _setup(monkeypatch, [_drive("a", True), _drive("b", None), _drive("c", False)])
    shown = []
    monkeypatch.setattr(
        commands,
        "get_formatter",
        lambda *_: SimpleNamespace(format_sources=lambda rows, **_: shown.extend(rows)),
    )
    result = CliRunner().invoke(commands.app, ["stale", "nb"])
    assert result.exit_code == 0, result.output
    assert [source["id"] for source in shown] == ["a"]
    assert "Freshness unknown for 1" in result.output


def test_unknown_freshness_does_not_claim_all_sources_fresh(monkeypatch) -> None:
    _setup(monkeypatch, [_drive("unknown", None)])
    result = CliRunner().invoke(commands.app, ["stale", "nb"])
    assert result.exit_code == 0, result.output
    assert "Freshness unavailable" in result.output
    assert "All Drive sources are up to date" not in result.output


def test_default_sync_only_targets_stale_syncable_drive_sources(monkeypatch) -> None:
    calls = _setup(
        monkeypatch,
        [_drive("a", True), _drive("b", None), _drive("c", False), _drive("d", True, False)],
    )
    result = CliRunner().invoke(commands.app, ["sync", "nb", "--confirm"])
    assert result.exit_code == 0, result.output
    assert calls == [["a"]]


def test_unknown_status_does_not_start_any_sync(monkeypatch) -> None:
    calls = _setup(monkeypatch, [_drive("unknown", None)])
    result = CliRunner().invoke(commands.app, ["sync", "nb", "--confirm"])
    assert result.exit_code == 0, result.output
    assert "freshness unknown" in result.output
    assert calls == []
