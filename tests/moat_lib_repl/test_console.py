"""Tests for moat.lib.repl console functionality."""

from __future__ import annotations

import pytest
from contextlib import AsyncExitStack

from moat.util import Path
from moat.lib.repl import MsgTerm, Readline, UnixConsole
from moat.lib.repl._test import MockTerm
from moat.lib.rpc import MsgSender


@pytest.mark.anyio
async def test_mock_term_basic():
    """Test basic MockTerm functionality."""
    # Create console with scripted input
    user_actions = [
        b"hello",
        0.01,  # Small delay
        b" world\n",
    ]
    term = MockTerm(user_actions=user_actions)

    # Test rd() - read data
    buf = bytearray(10)
    n = await term.rd(buf)
    assert buf[:n] == b"hello"

    # Test wr() - write data
    await term.wr(b"output")
    assert term.output_buffer == b"output"

    # Test that actions are recorded
    assert ("rd", b"hello") in term.record
    assert ("wr", b"output") in term.record


@pytest.mark.anyio
async def test_msg_console_wrapper():
    """Test MsgConsole RPC wrapper."""
    # Create a term console
    user_actions = [b"test input", b"putput"]
    term = MockTerm(user_actions=user_actions)

    # Wrap it with MsgConsole
    console = MsgTerm(term)

    # Test cmd_rd via direct call
    buf = bytearray(4)
    n = await console.cmd_rd(buf)
    assert buf[:n] == b"test"

    buf = bytearray(8)
    n = await console.cmd_rd(buf)
    assert buf[:n] == b" input"

    n = await console.cmd_rd(buf)
    assert buf[:n] == b"putput"

    # Test cmd_wr via direct call
    await console.cmd_wr(b"test output")
    assert term.output_buffer == b"test output"


@pytest.mark.anyio
async def test_rpc_sender_remote():
    """Test remote console access via MsgSender."""
    # Create a term console
    user_actions = [b"remote input"]
    term = MockTerm(user_actions=user_actions)

    # Wrap with MsgConsole handler
    msg_handler = MsgTerm(term)

    # Create MsgSender (simulating RPC layer)
    sender = MsgSender(msg_handler).sub_at(Path())

    # Test rd through the chain: sender -> msg_handler -> term
    buf = bytearray(6)
    n = await sender.rd(buf)
    assert buf[:n] == b"remote"

    # Test wr through the chain
    await sender.wr(data=b"remote output")
    assert term.output_buffer == b"remote output"


@pytest.mark.anyio
async def test_readline_iterator():
    """Test Readline async iterator interface."""
    user_actions = [
        b"test line\n",
        b"another line\n",
    ]
    term = MockTerm(user_actions=user_actions)
    console = UnixConsole(term)

    # Use Readline as async iterator
    async with console, Readline(console, prompt=">>> ") as lines:
        line = await anext(lines)
        assert line == "test line"
        line = await anext(lines)
        assert line == "another line"


@pytest.mark.anyio
async def test_rpc_stack():
    """Test basic RPC stack."""
    user_actions = [
        b"print('hello')\n",
    ]
    term = MockTerm(user_actions=user_actions)

    # Stack: MockTerm -> MsgTerm -> MsgSender
    msg_handler = MsgTerm(term)
    sender = MsgSender(msg_handler).sub_at(Path())

    buf = bytearray(5)
    n = await sender.rd(buf)
    assert buf[:n] == b"print"

    await sender.wr(data=b"test")
    assert term.output_buffer == b"test"

    # Verify actions were recorded
    assert ("rd", b"print") in term.record
    assert ("wr", b"test") in term.record


@pytest.mark.anyio
@pytest.mark.parametrize("remote", [False, True])
@pytest.mark.parametrize("multi", [False, True])
async def test_readline_iterator_full(remote, multi):
    """Test Readline async iterator with multiple lines."""
    # Create term console with multiple lines of input
    user_actions = [
        b"first line\n",
        b"second line\n",
        b"third line\n",
    ]
    user_actions_m = [
        b"line 1\\\n",  # Continuation
        b"line 2\n",  # Complete
    ]
    lines = []

    def more_lines(text: str) -> bool:
        """Continue if the text (without trailing newline) ends with backslash"""
        text = text.rstrip("\n")
        return text.endswith("\\")

    async with AsyncExitStack() as acm:
        ac = acm.enter_async_context
        term = tx = MockTerm(user_actions=user_actions_m if multi else user_actions)
        if remote:
            # await ac(term)
            hdl = MsgTerm(term)
            term = MsgSender(hdl).sub_at(Path())
        console = await ac(UnixConsole(term))
        inp = await ac(Readline(console, prompt=">>> ", more_lines=more_lines if multi else None))

        async for line in inp:
            lines.append(line)
            if len(lines) == (1 if multi else 3):
                break

    if multi:
        assert len(lines) == 1
        assert "line 1" in lines[0]
        assert "line 2" in lines[0]
    else:
        assert len(lines) == 3
        assert "first" in lines[0]
        assert "second" in lines[1]
        assert "third" in lines[2]

    # Verify console was prepared and restored
    assert ("switch", "raw") in tx.record
    assert ("switch", "orig") in tx.record
