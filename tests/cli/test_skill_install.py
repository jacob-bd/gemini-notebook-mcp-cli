"""Tests for safe skill installation."""

from unittest.mock import patch

import pytest

from notebooklm_tools.cli.commands import skill


class TestSkillInstallSafety:
    """Skill installation must not create targets for missing tools."""

    def test_does_not_offer_install_anyway_when_tool_is_missing(self, tmp_path):
        config = {
            **skill.TOOL_CONFIGS["claude-code"],
            "user": tmp_path / ".claude" / "skills" / "nlm-skill",
            "project": tmp_path / ".claude-project" / "skills" / "nlm-skill",
        }

        with (
            patch.dict(skill.TOOL_CONFIGS, {"claude-code": config}),
            patch.object(skill, "_is_tool_installed", return_value=False),
            patch.object(skill.typer, "prompt", return_value=1) as prompt,
            patch.object(skill, "install_skill_md") as install_skill,
            pytest.raises(skill.typer.Exit),
        ):
            skill.install("claude-code", level="user")

        prompt.assert_not_called()
        install_skill.assert_not_called()
        assert not config["user"].exists()
