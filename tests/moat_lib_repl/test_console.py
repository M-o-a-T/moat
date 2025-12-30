"""Tests for moat.lib.repl console functionality."""

from __future__ import annotations

import pytest
from contextlib import AsyncExitStack

from moat.util import Path
from moat.lib.repl._test import MockConsole
from moat.lib.repl.console import Readline
from moat.lib.repl.rpc import MsgConsole
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
    assert ("rd", b"hello") in console.record
    assert ("wr", b"output") in console.record


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
async def test_rpc_sender_remote():
    """Test remote console access via MsgSender."""
    # Create a mock console
    user_actions = [b"remote input"]
    mock = MockConsole(user_actions=user_actions)

    # Wrap with MsgConsole handler
    msg_handler = MsgConsole(mock)

    # Create MsgSender (simulating RPC layer)
    sender = MsgSender(msg_handler).sub_at(Path())

    # Test rd through the chain: sender -> msg_handler -> mock
    result = await sender.rd(n=6)
    assert result == b"remote"

    # Test wr through the chain
    await sender.wr(data=b"remote output")
    assert mock.output_buffer == b"remote output"


@pytest.mark.anyio
async def test_readline_iterator():
    """Test Readline async iterator interface."""
    # Create console with input ending in newline (to trigger accept)
    user_actions = [
        b"test line\n",
        b"another line\n",
    ]
    console = MockConsole(user_actions=user_actions)

    # Use Readline as async iterator
    async with console, Readline(console, prompt=">>> ") as lines:
        line = await anext(lines)
        assert line == "test line"
        line = await anext(lines)
        assert line == "another line"


@pytest.mark.anyio
async def test_full_stack():
    """Test complete RPC stack."""
    user_actions = [
        b"print('hello')\n",
    ]
    mock = MockConsole(user_actions=user_actions)

    # Build the stack: MockConsole -> MsgConsole -> MsgSender
    msg_handler = MsgConsole(mock)
    sender = MsgSender(msg_handler).sub_at(Path())

    result = await sender.rd(n=5)
    assert result == b"print"

    await sender.wr(data=b"test")
    assert mock.output_buffer == b"test"

    # Verify actions were recorded
    assert ("rd", b"print") in mock.record
    assert ("wr", b"test") in mock.record


@pytest.mark.anyio
async def test_readline_iterator_full():
    """Test Readline async iterator with multiple lines."""
    # Create mock console with multiple lines of input
    user_actions = [
        b"first line\n",
        b"second line\n",
        b"third line\n",
    ]
    console = MockConsole(user_actions=user_actions)

    lines = []
    # Use the full pattern: async with console, Readline as iterator
    async with console, Readline(console, prompt=">>> ") as inp:
        async for line in inp:
            lines.append(line)
            if len(lines) >= 3:  # Stop after 3 lines
                break

    assert len(lines) == 3
    assert "first" in lines[0]
    assert "second" in lines[1]
    assert "third" in lines[2]

    # Verify console was prepared and restored
    assert ("action", "enter") in console.record
    assert ("action", "exit") in console.record


@pytest.mark.anyio
@pytest.mark.parametrize("remote", (False, True))
async def test_readline_multiline(remote):
    """Test Readline with multiline input support."""

    def more_lines(text: str) -> bool:
        """Check if we need more lines (simple continuation check)."""
        # Continue if the text (without trailing newline) ends with backslash
        text = text.rstrip("\n")
        return text.endswith("\\")

    # Create mock console with multiline input
    user_actions = [
        b"line 1\\\n",  # Continuation
        b"line 2\n",  # Complete
    ]
    async with AsyncExitStack() as acm:
        ac = acm.enter_async_context
        console = await ac(MockConsole(user_actions=user_actions))

        if remote:
            # Wrap with MsgConsole handler
            msg_handler = MsgConsole(console)

            # Create MsgSender (simulating RPC layer)
            console = await ac(MsgSender(msg_handler).sub_at(Path()))

        inp = await ac(Readline(console, prompt=">>> ", more_lines=more_lines))
        line = await anext(inp)

    # Should have received the complete multiline input
    assert "line 1" in line
    assert "line 2" in line
