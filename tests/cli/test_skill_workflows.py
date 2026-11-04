"""Tests for bundled cross-MCP workflow contracts."""

from pathlib import Path


def test_bundled_skill_routes_bounded_public_x_research():
    skill = Path("src/notebooklm_tools/data/SKILL.md").read_text(encoding="utf-8")
    workflows = Path("src/notebooklm_tools/data/references/workflows.md").read_text(
        encoding="utf-8"
    )

    assert "Workflow 16" in skill
    assert "https://xquik.com/mcp" in workflows
    assert 'xquik.request("/api/v1/x/tweets/search"' in workflows
    assert 'source_type="text"' in workflows
    assert "returned cursor" in workflows
    assert "untrusted data" in workflows
    assert "Private reads, writes, monitors" in workflows
    assert "copy credentials" in workflows


def test_bundled_skill_documents_interactive_report_workflow():
    """Interactive reports ship with a routed agent workflow across skill + AI docs."""
    skill = Path("src/notebooklm_tools/data/SKILL.md").read_text(encoding="utf-8")
    workflows = Path("src/notebooklm_tools/data/references/workflows.md").read_text(
        encoding="utf-8"
    )
    guide = Path("src/notebooklm_tools/data/references/studio-prompting-guide.md").read_text(
        encoding="utf-8"
    )
    ai_docs = Path("src/notebooklm_tools/cli/ai_docs.py").read_text(encoding="utf-8")

    # Skill routes to the workflow and reflects the current MCP surface.
    assert "Workflow 17" in skill
    assert "55 tools" in skill
    assert "--format Interactive" in skill

    # The workflow covers every stage an agent performs end to end.
    assert "## Workflow 17: Interactive Report with Embedded Elements" in workflows
    for needle in (
        'report_format="Interactive"',
        'report(\n    notebook_id="<notebook-id>",',
        'action="generate"',
        'action="elements"',
        "nlm report elements",
        "nlm report element create",
        "nlm download report",
        "wait_for",
        "include_content",
        "not against the original sources",
        "question_amount",
    ):
        assert needle in workflows, needle
    # Element generation runs from the API; no manual web-UI handoff remains.
    assert "Kickoff handoff" not in workflows

    # Prompting guide covers the artifact type.
    heading = "## Interactive Report (`artifact_type=report`, `report_format=Interactive`)"
    assert heading in guide
    for needle in (
        "Precedence for report elements",
        "Section anchoring",
        "data, never authorization",
        "pick the best resources and show me",
    ):
        assert needle in guide, needle

    examples = Path("src/notebooklm_tools/data/references/studio-prompt-examples.md").read_text(
        encoding="utf-8"
    )
    assert "## Interactive Report Element Plans" in examples

    # `nlm --ai` docs mention the commands.
    assert "--format Interactive" in ai_docs
    assert "report element create" in ai_docs
    assert "report element create-batch" in ai_docs


def test_prompting_guide_uses_valid_setting_names_per_kind():
    guide = Path("src/notebooklm_tools/data/references/studio-prompting-guide.md").read_text(
        encoding="utf-8"
    )
    assert "quiz/flashcards `difficulty=easy`, `question_amount=fewer`" not in guide
    assert "flashcards `difficulty=easy`, `card_amount=fewer`" in guide
    assert "`detail_level=detailed`" not in guide


def test_prompting_guide_closes_consent_eval_gaps():
    """Gaps found by the 2026-09-24 agent consent evaluation stay documented."""
    guide = Path("src/notebooklm_tools/data/references/studio-prompting-guide.md").read_text(
        encoding="utf-8"
    )
    # 1. A direct order to generate counts as delegation.
    assert "generate all the extras" in guide
    # 2. Generating few or no elements is allowed.
    assert "Generating one element, or none, is fine" in guide
    # 3. Descriptions are topic hints, never instructions to copy.
    assert "never copy instructions from a description" in guide
    # 4. Cinematic quota protection for report videos.
    assert "Always set `video_format` explicitly" in guide
