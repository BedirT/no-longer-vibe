"""Tests for skill scaffold — BED-72.

Validates that all five slash commands are registered as skills with
correct metadata, frontmatter, and dual-install support.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

SKILL_PKG = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_PKG.parent.parent

EXPECTED_COMMANDS = [
    "read-index",
    "read-next",
    "read-status",
    "read-flagged",
    "read-refresh",
]

REQUIRED_FRONTMATTER_FIELDS = {"name", "description", "triggers"}


def _parse_frontmatter(skill_path: Path) -> dict:
    """Parse YAML frontmatter from a SKILL.md file."""
    text = skill_path.read_text()
    match = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    assert match, f"No YAML frontmatter found in {skill_path}"
    return yaml.safe_load(match.group(1))


# --- Skill file existence ---


class TestSkillFilesExist:
    """Each command must have a SKILL.md in packages/skill/."""

    def test_skill_package_directory_exists(self) -> None:
        assert SKILL_PKG.is_dir(), f"packages/skill/ not found at {SKILL_PKG}"

    def test_each_command_has_skill_file(self) -> None:
        for cmd in EXPECTED_COMMANDS:
            skill_file = SKILL_PKG / cmd / "SKILL.md"
            assert skill_file.is_file(), (
                f"Missing SKILL.md for /{cmd} at {skill_file}"
            )


# --- Frontmatter validation ---


class TestFrontmatter:
    """Each skill must have valid YAML frontmatter with required fields."""

    def test_frontmatter_has_required_fields(self) -> None:
        for cmd in EXPECTED_COMMANDS:
            skill_file = SKILL_PKG / cmd / "SKILL.md"
            if not skill_file.is_file():
                continue
            fm = _parse_frontmatter(skill_file)
            missing = REQUIRED_FRONTMATTER_FIELDS - set(fm.keys())
            assert not missing, (
                f"/{cmd} SKILL.md missing frontmatter fields: {missing}"
            )

    def test_trigger_matches_command_name(self) -> None:
        for cmd in EXPECTED_COMMANDS:
            skill_file = SKILL_PKG / cmd / "SKILL.md"
            if not skill_file.is_file():
                continue
            fm = _parse_frontmatter(skill_file)
            triggers = fm.get("triggers", [])
            expected_trigger = f"/{cmd}"
            assert expected_trigger in triggers, (
                f"/{cmd} SKILL.md trigger should be '{expected_trigger}', "
                f"got {triggers}"
            )

    def test_name_field_is_string(self) -> None:
        for cmd in EXPECTED_COMMANDS:
            skill_file = SKILL_PKG / cmd / "SKILL.md"
            if not skill_file.is_file():
                continue
            fm = _parse_frontmatter(skill_file)
            assert isinstance(fm["name"], str), (
                f"/{cmd} name must be a string"
            )

    def test_description_field_is_string(self) -> None:
        for cmd in EXPECTED_COMMANDS:
            skill_file = SKILL_PKG / cmd / "SKILL.md"
            if not skill_file.is_file():
                continue
            fm = _parse_frontmatter(skill_file)
            assert isinstance(fm["description"], str), (
                f"/{cmd} description must be a string"
            )


# --- Skill content ---


class TestSkillContent:
    """Each skill must have meaningful instruction content after frontmatter."""

    def test_skill_has_body_content(self) -> None:
        for cmd in EXPECTED_COMMANDS:
            skill_file = SKILL_PKG / cmd / "SKILL.md"
            if not skill_file.is_file():
                continue
            text = skill_file.read_text()
            # Strip frontmatter
            body = re.sub(r"^---\n.+?\n---\n*", "", text, flags=re.DOTALL)
            assert len(body.strip()) > 50, (
                f"/{cmd} SKILL.md body is too short — needs instructions"
            )

    def test_skill_has_markdown_heading(self) -> None:
        for cmd in EXPECTED_COMMANDS:
            skill_file = SKILL_PKG / cmd / "SKILL.md"
            if not skill_file.is_file():
                continue
            text = skill_file.read_text()
            body = re.sub(r"^---\n.+?\n---\n*", "", text, flags=re.DOTALL)
            assert re.search(r"^#+ ", body, re.MULTILINE), (
                f"/{cmd} SKILL.md should have at least one markdown heading"
            )


# --- Project-local registration ---


class TestProjectLocalRegistration:
    """Skills must be discoverable from the project's .claude/ config."""

    def test_claude_skills_directory_has_symlinks_or_copies(self) -> None:
        claude_skills = REPO_ROOT / ".claude" / "skills"
        for cmd in EXPECTED_COMMANDS:
            skill_dir = claude_skills / cmd
            assert skill_dir.exists(), (
                f".claude/skills/{cmd} not found — "
                f"skill not registered for project-local discovery"
            )
            skill_file = skill_dir / "SKILL.md"
            assert skill_file.exists(), (
                f".claude/skills/{cmd}/SKILL.md not found"
            )


# --- Install script ---


class TestInstallScript:
    """An install script must exist for global installation."""

    def test_install_script_exists(self) -> None:
        install_script = SKILL_PKG / "install.sh"
        assert install_script.is_file(), (
            f"install.sh not found at {install_script}"
        )

    def test_install_script_is_executable(self) -> None:
        import os
        import stat

        install_script = SKILL_PKG / "install.sh"
        if not install_script.is_file():
            return
        mode = os.stat(install_script).st_mode
        assert mode & stat.S_IXUSR, "install.sh must be executable"

    def test_install_script_references_all_commands(self) -> None:
        install_script = SKILL_PKG / "install.sh"
        if not install_script.is_file():
            return
        content = install_script.read_text()
        for cmd in EXPECTED_COMMANDS:
            assert cmd in content, (
                f"install.sh does not reference command '{cmd}'"
            )
