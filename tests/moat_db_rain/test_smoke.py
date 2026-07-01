"""Smoke tests for the moat.db.rain CLI scaffold."""

from __future__ import annotations

import pytest

from asyncclick.testing import CliRunner

from moat.db.rain._main import cli as rain_cli


@pytest.mark.trio
async def test_rain_help_lists_subcommands():
    """`moat db rain --help` advertises its loader-discovered subcommands."""
    runner = CliRunner()
    result = await runner.invoke(rain_cli, ["--help"], obj={})
    assert result.exit_code == 0, result.output
    assert "controller" in result.output
