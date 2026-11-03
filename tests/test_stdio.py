"""The installed command, launched over stdio the way an MCP host such as Claude Code runs it."""

from __future__ import annotations

import shutil
from importlib.metadata import version

import pytest
from mcp import Client, StdioServerParameters

pytestmark = pytest.mark.anyio


async def test_the_installed_command_serves_check_answer_over_stdio() -> None:
    command = shutil.which("answer-check-mcp")
    assert command, "install the package first: uv sync"

    async with Client(StdioServerParameters(command=command)) as client:
        result = await client.call_tool(
            "check_answer",
            {
                "answer": "The Pro plan costs $25 a month.",
                "sources": [{"text": "The Pro plan costs $20 a month."}],
            },
        )

    assert result.structured_content is not None
    assert result.structured_content["passed"] is False
    assert result.structured_content["sentences"][0]["suggested"] == ["$20"]


async def test_the_installed_command_judges_over_stdio(judge_stub) -> None:
    command = shutil.which("answer-check-mcp")
    assert command, "install the package first: uv sync"

    async with Client(
        StdioServerParameters(command=command, args=["--judge-url", judge_stub.url])
    ) as client:
        result = await client.call_tool(
            "check_answer",
            {
                "answer": "Support is friendly and fast.",
                "sources": [{"text": "The Pro plan costs $20 a month."}],
            },
        )

    assert result.structured_content is not None
    assert result.structured_content["sentences"][0]["checked_by"] == "judge"
    assert result.structured_content["judge"]["measured"] is True


async def test_the_installed_command_reports_its_package_version() -> None:
    command = shutil.which("answer-check-mcp")
    assert command, "install the package first: uv sync"

    async with Client(StdioServerParameters(command=command)) as client:
        info = client.server_info

    assert info is not None
    assert info.name == "answer-check"
    assert info.version == version("answer-check-mcp")
