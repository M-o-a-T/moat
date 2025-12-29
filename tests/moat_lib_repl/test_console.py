"""Tests for moat.lib.repl console functionality."""

from __future__ import annotations

import pytest

from moat.util import Path
from moat.lib.repl._test import MockConsole
from moat.lib.repl.console import MoatConsole, MsgConsole, Readline
from moat.lib.rpc import MsgSender


@pytest.mark.anyio
async def test_mock_console_basic():
    """Test basic MockConsole functionality."""
    # Create console with scripted input
    user_actions = [
        b"hello",
        0.01,  # Small delay
        b" world\n",
    ]
    console = MockConsole(user_actions=user_actions)

    # Test rd() - read data
    data1 = await console.rd(5)
    assert data1 == b"hello"

    # Test wr() - write data
    await console.wr(b"output")
    assert console.output_buffer == b"output"

    # Test that actions are recorded
    assert ("rd", 5) in console.recorded_actions
    assert ("wr", b"output") in console.recorded_actions


@pytest.mark.anyio
async def test_msg_console_wrapper():
    """Test MsgConsole RPC wrapper."""
    # Create a mock console
    user_actions = [b"test input"]
    mock = MockConsole(user_actions=user_actions)

    # Wrap it with MsgConsole
    msg_console = MsgConsole(mock)

    # Test cmd_rd via direct call
    result = await msg_console.cmd_rd(4)
    assert result == b"test"

    # Test cmd_wr via direct call
    await msg_console.cmd_wr(b"test output")
    assert mock.output_buffer == b"test output"


@pytest.mark.anyio
async def test_moat_console_remote():
    """Test MoatConsole remote proxy."""
    # Create a mock console
    user_actions = [b"remote input"]
    mock = MockConsole(user_actions=user_actions)

    # Wrap with MsgConsole handler
    msg_handler = MsgConsole(mock)

    # Create MsgSender (simulating RPC layer)
    sender = MsgSender(msg_handler).sub_at(Path())

    # Create MoatConsole that uses the sender
    moat = MoatConsole(sender)

    # Test rd through the chain: moat -> sender -> msg_handler -> mock
    result = await moat.rd(6)
    assert result == b"remote"

    # Test wr through the chain
    await moat.wr(b"remote output")
    assert mock.output_buffer == b"remote output"


@pytest.mark.anyio
async def test_readline_iterator():
    """Test Readline async iterator interface."""
    # Create console with input ending in newline (to trigger accept)
    user_actions = [
        b"test line\n",
    ]
    console = MockConsole(user_actions=user_actions)

    # Use Readline as async iterator
    async with Readline(console, prompt=">>> ") as lines:
        line = await anext(lines)
        assert "test" in line or line == "test line"


@pytest.mark.anyio
async def test_full_stack():
    """Test complete RPC stack with Readline."""
    # Create mock console with scripted input
    user_actions = [
        b"print('hello')\n",
    ]
    mock = MockConsole(user_actions=user_actions)

    # Build the stack: MockConsole -> MsgConsole -> MsgSender -> MoatConsole
    msg_handler = MsgConsole(mock)
    sender = MsgSender(msg_handler).sub_at(Path())
    moat = MoatConsole(sender)

    # Test that rd/wr work through the stack
    result = await moat.rd(5)
    assert result == b"print"

    await moat.wr(b"test")
    assert mock.output_buffer == b"test"

    # Verify actions were recorded
    assert ("rd", 5) in mock.recorded_actions
    assert ("wr", b"test") in mock.recorded_actions
