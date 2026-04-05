"""Tests for MCP config wiring — BED-86.

Validates that:
- .claude/mcp.json exists with correct MCP server configuration
- Skill SKILL.md files include MCP integration instructions
- read-next and read-flagged have MCP tool usage with graceful fallback
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SKILL_PKG = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_PKG.parent.parent


# --- MCP config file ---


class TestMcpConfigFile:
    """The .claude/mcp.json file must exist and configure the extension server."""

    def test_mcp_json_exists(self) -> None:
        mcp_json = REPO_ROOT / ".claude" / "mcp.json"
        assert mcp_json.is_file(), (
            ".claude/mcp.json not found — Claude Code cannot discover the MCP server"
        )

    def test_mcp_json_is_valid_json(self) -> None:
        mcp_json = REPO_ROOT / ".claude" / "mcp.json"
        if not mcp_json.is_file():
            return
        content = mcp_json.read_text()
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise AssertionError(f".claude/mcp.json is not valid JSON: {exc}") from exc

    def test_mcp_json_has_mcp_servers_key(self) -> None:
        mcp_json = REPO_ROOT / ".claude" / "mcp.json"
        if not mcp_json.is_file():
            return
        config = json.loads(mcp_json.read_text())
        assert "mcpServers" in config, (
            ".claude/mcp.json must have a 'mcpServers' key"
        )

    def test_mcp_json_has_no_longer_vibe_server(self) -> None:
        mcp_json = REPO_ROOT / ".claude" / "mcp.json"
        if not mcp_json.is_file():
            return
        config = json.loads(mcp_json.read_text())
        servers = config.get("mcpServers", {})
        assert "no-longer-vibe" in servers, (
            ".claude/mcp.json must define a 'no-longer-vibe' server"
        )

    def test_server_uses_node_command(self) -> None:
        mcp_json = REPO_ROOT / ".claude" / "mcp.json"
        if not mcp_json.is_file():
            return
        config = json.loads(mcp_json.read_text())
        server = config.get("mcpServers", {}).get("no-longer-vibe", {})
        assert server.get("command") == "node", (
            "MCP server command must be 'node'"
        )

    def test_server_args_point_to_mcp_server_js(self) -> None:
        mcp_json = REPO_ROOT / ".claude" / "mcp.json"
        if not mcp_json.is_file():
            return
        config = json.loads(mcp_json.read_text())
        server = config.get("mcpServers", {}).get("no-longer-vibe", {})
        args = server.get("args", [])
        assert len(args) >= 1, "MCP server args must include the script path"
        assert "mcpServer" in args[0], (
            "MCP server args must reference the mcpServer entry point"
        )

    def test_server_type_is_stdio(self) -> None:
        mcp_json = REPO_ROOT / ".claude" / "mcp.json"
        if not mcp_json.is_file():
            return
        config = json.loads(mcp_json.read_text())
        server = config.get("mcpServers", {}).get("no-longer-vibe", {})
        assert server.get("type") == "stdio", (
            "MCP server transport type must be 'stdio'"
        )


# --- Skill MCP integration in read-next ---


class TestReadNextMcpIntegration:
    """read-next SKILL.md must include MCP integration instructions."""

    def _read_skill(self) -> str:
        skill_file = SKILL_PKG / "read-next" / "SKILL.md"
        assert skill_file.is_file()
        return skill_file.read_text()

    def test_mentions_mcp_tools(self) -> None:
        content = self._read_skill()
        assert "MCP" in content, (
            "read-next SKILL.md must mention MCP tools"
        )

    def test_mentions_open_file_tool(self) -> None:
        content = self._read_skill()
        assert "open_file" in content, (
            "read-next SKILL.md must reference the open_file MCP tool"
        )

    def test_mentions_highlight_range_tool(self) -> None:
        content = self._read_skill()
        assert "highlight_range" in content, (
            "read-next SKILL.md must reference the highlight_range MCP tool"
        )

    def test_mentions_mark_read_tool(self) -> None:
        content = self._read_skill()
        assert "mark_read" in content, (
            "read-next SKILL.md must reference the mark_read MCP tool"
        )

    def test_mentions_mark_flagged_tool(self) -> None:
        content = self._read_skill()
        assert "mark_flagged" in content, (
            "read-next SKILL.md must reference the mark_flagged MCP tool"
        )

    def test_mentions_clear_highlights_tool(self) -> None:
        content = self._read_skill()
        assert "clear_highlights" in content, (
            "read-next SKILL.md must reference the clear_highlights MCP tool"
        )

    def test_has_fallback_instructions(self) -> None:
        content = self._read_skill().lower()
        has_fallback = (
            "fallback" in content
            or "not available" in content
            or "without mcp" in content
        )
        assert has_fallback, (
            "read-next SKILL.md must describe fallback behavior "
            "when MCP is unavailable"
        )

    def test_has_mcp_section(self) -> None:
        content = self._read_skill()
        assert re.search(r"^##+ .*MCP", content, re.MULTILINE | re.IGNORECASE), (
            "read-next SKILL.md must have a dedicated MCP section heading"
        )


# --- Skill MCP integration in read-flagged ---


class TestReadFlaggedMcpIntegration:
    """read-flagged SKILL.md must include MCP integration instructions."""

    def _read_skill(self) -> str:
        skill_file = SKILL_PKG / "read-flagged" / "SKILL.md"
        assert skill_file.is_file()
        return skill_file.read_text()

    def test_mentions_mcp_tools(self) -> None:
        content = self._read_skill()
        assert "MCP" in content, (
            "read-flagged SKILL.md must mention MCP tools"
        )

    def test_mentions_open_file_tool(self) -> None:
        content = self._read_skill()
        assert "open_file" in content, (
            "read-flagged SKILL.md must reference the open_file MCP tool"
        )

    def test_has_fallback_instructions(self) -> None:
        content = self._read_skill().lower()
        has_fallback = (
            "fallback" in content
            or "not available" in content
            or "without mcp" in content
        )
        assert has_fallback, (
            "read-flagged SKILL.md must describe fallback "
            "behavior when MCP is unavailable"
        )


# --- Setup documentation ---


class TestSetupDocumentation:
    """MCP config must include setup instructions or comments."""

    def test_mcp_json_or_skill_has_setup_reference(self) -> None:
        """At least one skill file or a dedicated doc references MCP setup."""
        read_next = (SKILL_PKG / "read-next" / "SKILL.md").read_text()
        mcp_json_path = REPO_ROOT / ".claude" / "mcp.json"
        lower = read_next.lower()
        has_setup_in_skill = (
            "setup" in lower or "install" in lower
        )
        has_mcp_config = mcp_json_path.is_file()
        assert has_setup_in_skill or has_mcp_config, (
            "Must have either setup instructions in the skill or the MCP config file"
        )
