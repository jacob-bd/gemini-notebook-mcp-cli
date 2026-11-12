"""nlm login: storage mode decided before the browser; committed only on success."""

import pytest
import typer
from typer.testing import CliRunner

from notebooklm_tools.cli import main
from notebooklm_tools.core.auth import AuthManager
from notebooklm_tools.core.exceptions import NLMError
from notebooklm_tools.core.notices import get_protect_answer, record_protect_answer
from notebooklm_tools.utils.config import get_auth_storage_mode, get_profile_dir, reset_config

ST = "notebooklm_tools.services.auth_storage"


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch, fake_credential_store):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    monkeypatch.delenv("NLM_AUTH_STORAGE", raising=False)
    reset_config()
    monkeypatch.setattr(main, "_is_terminal", lambda: True)
    monkeypatch.setattr(f"{ST}.is_desktop_session", lambda: True)
    monkeypatch.setattr(f"{ST}.keystore_available", lambda: True)
    yield
    reset_config()


def _answer(monkeypatch, value):
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: value)


def _never_ask(monkeypatch):
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: pytest.fail("must not ask"))


# --- deciding (no disk writes) ---------------------------------------------


def test_new_profile_choice_1_is_protected(monkeypatch):
    _answer(monkeypatch, 1)
    assert main._choose_storage_mode("work", None) == main.StorageChoice("protected", True, True)


def test_new_profile_choice_2_is_plain(monkeypatch):
    _answer(monkeypatch, 2)
    assert main._choose_storage_mode("work", None) == main.StorageChoice("file", True, True)


def test_deciding_writes_nothing(monkeypatch):
    _answer(monkeypatch, 1)
    main._choose_storage_mode("work", None)
    assert get_protect_answer("work") is None
    assert not get_profile_dir("work", create=False).exists()


def test_existing_profile_keeps_mode_and_never_asks(monkeypatch):
    AuthManager("work").save_profile(cookies={"SID": "w"}, email="w@example.com")
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("work", None) == main.StorageChoice("file", False, False)


def test_reused_name_with_stale_answer_is_still_asked(monkeypatch):
    record_protect_answer("work", "no")  # left over from a deleted profile
    _answer(monkeypatch, 1)
    assert main._choose_storage_mode("work", None).mode == "protected"


def test_env_override_wins_without_asking(monkeypatch):
    monkeypatch.setenv("NLM_AUTH_STORAGE", "protected")
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("work", None).mode == "protected"


def test_non_interactive_is_plain_without_asking(monkeypatch):
    monkeypatch.setattr(main, "_is_terminal", lambda: False)
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("work", None) == main.StorageChoice("file", False, True)


def test_ssh_or_headless_is_plain_without_asking(monkeypatch):
    monkeypatch.setattr(f"{ST}.is_desktop_session", lambda: False)
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("work", None).mode == "file"


@pytest.mark.parametrize("name", ["john@work.com", "my work"])
def test_unprotectable_name_offers_a_working_name(monkeypatch, capsys, name):
    _answer(monkeypatch, 1)
    choice = main._choose_storage_mode(name, None)
    assert choice.mode == "protected" and choice.asked and choice.is_new
    assert choice.rename_to == {"john@work.com": "john-work.com", "my work": "my-work"}[name]
    assert "can't be used with protected storage" in capsys.readouterr().out


def test_unprotectable_name_can_stay_plain_under_its_own_name(monkeypatch):
    _answer(monkeypatch, 2)
    choice = main._choose_storage_mode("my work", None)
    assert choice == main.StorageChoice("file", True, True)


def test_unprotectable_name_but_keystore_locked_falls_back_to_plain(monkeypatch, capsys):
    _answer(monkeypatch, 1)
    monkeypatch.setattr(f"{ST}.keystore_available", lambda: False)
    choice = main._choose_storage_mode("my work", None)
    assert choice == main.StorageChoice("file", False, True)
    assert "keystore isn't available" in capsys.readouterr().out


def test_unprotectable_name_with_no_usable_suggestion_is_plain_without_asking(monkeypatch, capsys):
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("@@@", None) == main.StorageChoice("file", False, True)
    assert "can't be used for protected storage" in capsys.readouterr().out


def test_unprotectable_name_non_interactive_stays_plain_silently(monkeypatch):
    monkeypatch.setattr(main, "_is_terminal", lambda: False)
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("my work", None) == main.StorageChoice("file", False, True)


def test_suggested_name_that_already_exists_is_not_offered(monkeypatch):
    AuthManager("my-work").save_profile(cookies={"SID": "w"}, email="w@example.com")
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("my work", None).mode == "file"


def test_picked_protected_but_keystore_locked_falls_back_unrecorded(monkeypatch, capsys):
    _answer(monkeypatch, 1)
    monkeypatch.setattr(f"{ST}.keystore_available", lambda: False)
    assert main._choose_storage_mode("work", None) == main.StorageChoice("file", False, True)
    assert "keystore isn't available" in capsys.readouterr().out


# --- the real prompt (no typer.prompt stub) -----------------------------------


def _choose_with_real_prompt(profile, keyboard):
    """Run the storage question with `keyboard` typed on stdin; return (choices made, CLI result)."""
    picked = []
    app = typer.Typer()

    @app.command()
    def ask():
        picked.append(main._choose_storage_mode(profile, None))

    result = CliRunner().invoke(app, [], input=keyboard)
    return picked, result


def test_real_prompt_asks_again_until_1_or_2():
    picked, result = _choose_with_real_prompt("work", "5\nx\n2\n")
    assert result.exit_code == 0, result.output
    assert picked == [main.StorageChoice("file", True, True)]
    assert result.output.count("Please enter 1 or 2.") == 1  # for 5; x is Typer's own error
    assert result.output.count("Choose 1 or 2") == 3


def test_real_prompt_enter_takes_the_default_protected():
    picked, result = _choose_with_real_prompt("work", "\n")
    assert result.exit_code == 0, result.output
    assert picked == [main.StorageChoice("protected", True, True)]
    assert "Please enter 1 or 2." not in result.output


def test_real_prompt_rename_offer_after_a_wrong_answer():
    picked, result = _choose_with_real_prompt("my work", "0\n1\n")
    assert result.exit_code == 0, result.output
    assert picked == [main.StorageChoice("protected", True, True, "my-work")]
    assert "Please enter 1 or 2." in result.output


# --- the --storage flag -------------------------------------------------------


def test_flag_skips_the_question_for_new_profiles(monkeypatch):
    _never_ask(monkeypatch)
    assert main._choose_storage_mode("work", "file").mode == "file"
    assert main._choose_storage_mode("work", "protected").mode == "protected"


def test_flag_protected_with_locked_keystore_fails_loudly(monkeypatch):
    monkeypatch.setattr(f"{ST}.keystore_available", lambda: False)
    with pytest.raises(typer.Exit) as exc:
        main._choose_storage_mode("work", "protected")
    assert exc.value.exit_code == 1


def test_flag_protected_with_unprotectable_name_fails_and_suggests_a_name(capsys):
    with pytest.raises(typer.Exit):
        main._choose_storage_mode("john@work.com", "protected")
    assert "--profile john-work.com" in capsys.readouterr().out


def test_flag_contradicting_existing_profile_fails(capsys):
    AuthManager("work").save_profile(cookies={"SID": "w"}, email="w@example.com")
    with pytest.raises(typer.Exit):
        main._choose_storage_mode("work", "protected")
    assert "nlm auth storage set protected --profile work" in capsys.readouterr().out
    assert get_auth_storage_mode("work") == "file"


def test_flag_matching_existing_profile_is_fine():
    AuthManager("work").save_profile(cookies={"SID": "w"}, email="w@example.com")
    assert main._choose_storage_mode("work", "file").mode == "file"


def test_flag_contradicting_env_fails(monkeypatch):
    monkeypatch.setenv("NLM_AUTH_STORAGE", "file")
    with pytest.raises(typer.Exit):
        main._choose_storage_mode("work", "protected")


def test_bad_flag_value_is_rejected():
    with pytest.raises(typer.Exit):
        main._choose_storage_mode("work", "banana")


# --- committing ----------------------------------------------------------------


def _save_work():
    return AuthManager("work").save_profile(cookies={"SID": "w"}, email="w@example.com")


def test_protected_save_is_encrypted_with_no_plain_files_and_records_yes():
    choice = main.StorageChoice("protected", True, True)
    main._save_with_storage_choice("work", choice, _save_work)
    pdir = get_profile_dir("work", create=False)
    assert get_auth_storage_mode("work") == "protected"
    assert (pdir / "credentials.enc").exists()
    assert not (pdir / "cookies.json").exists()
    assert get_protect_answer("work") == "yes"


def test_plain_save_records_no():
    main._save_with_storage_choice("work", main.StorageChoice("file", True, True), _save_work)
    assert get_auth_storage_mode("work") == "file"
    assert get_protect_answer("work") == "no"


def test_unasked_choice_records_nothing():
    main._save_with_storage_choice("work", main.StorageChoice("file", False, True), _save_work)
    assert get_protect_answer("work") is None


def test_failed_save_leaves_no_ghost_and_no_answer():
    def boom():
        raise RuntimeError("browser closed")

    with pytest.raises(RuntimeError):
        main._save_with_storage_choice("work", main.StorageChoice("protected", True, True), boom)
    assert not get_profile_dir("work", create=False).exists()
    assert get_protect_answer("work") is None
    assert "work" not in AuthManager.list_profiles()


def test_failed_resave_of_existing_profile_keeps_its_files():
    _save_work()

    def boom():
        raise RuntimeError("network")

    with pytest.raises(RuntimeError):
        main._save_with_storage_choice("work", main.StorageChoice("file", False, False), boom)
    assert (get_profile_dir("work", create=False) / "cookies.json").exists()


# --- whole command: cancelled browser leaves nothing behind -------------------


def test_cancelled_browser_login_leaves_nothing_and_asks_again(monkeypatch):
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: 1)
    monkeypatch.setattr("notebooklm_tools.utils.cdp.get_chrome_path", lambda: "chrome")
    monkeypatch.setattr("notebooklm_tools.utils.cdp.get_browser_display_name", lambda: "Chrome")
    monkeypatch.setattr("notebooklm_tools.utils.cdp.terminate_chrome", lambda: True)
    monkeypatch.setattr(
        "notebooklm_tools.utils.config.check_migration_sources",
        lambda: {"chrome_profiles": []},
    )

    def cancelled(**kwargs):
        raise NLMError("Login cancelled")

    monkeypatch.setattr("notebooklm_tools.utils.cdp.extract_cookies_via_cdp", cancelled)

    result = CliRunner().invoke(main.app, ["login", "--profile", "work"])

    assert result.exit_code == 1
    assert get_protect_answer("work") is None
    assert "work" not in AuthManager.list_profiles()
    assert not get_profile_dir("work", create=False).exists()


def test_login_with_unprotectable_name_uses_the_suggested_name_end_to_end(monkeypatch):
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: 1)
    monkeypatch.setattr("notebooklm_tools.utils.cdp.get_chrome_path", lambda: "chrome")
    monkeypatch.setattr("notebooklm_tools.utils.cdp.get_browser_display_name", lambda: "Chrome")
    monkeypatch.setattr("notebooklm_tools.utils.cdp.terminate_chrome", lambda: True)
    monkeypatch.setattr(
        "notebooklm_tools.utils.config.check_migration_sources",
        lambda: {"chrome_profiles": []},
    )
    monkeypatch.setattr(
        "notebooklm_tools.utils.cdp.extract_cookies_via_cdp",
        lambda **kwargs: {
            "cookies": {"SID": "sid"},
            "csrf_token": "csrf",
            "session_id": "session",
            "email": "user@example.com",
            "build_label": "build",
        },
    )

    result = CliRunner().invoke(main.app, ["login", "--profile", "my work"])

    assert result.exit_code == 0, result.output
    assert AuthManager.list_profiles() == ["my-work"]
    assert get_auth_storage_mode("my-work") == "protected"
    assert (get_profile_dir("my-work", create=False) / "credentials.enc").exists()
    assert not get_profile_dir("my work", create=False).exists()
    assert get_protect_answer("my-work") == "yes"
    assert "Profile: my-work" in result.output
