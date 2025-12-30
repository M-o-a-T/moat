#   Copyright 2000-2008 Michael Hudson-Doyle <micahel@gmail.com>
#                       Armin Rigo
#
#                        All Rights Reserved
#
#
# Permission to use, copy, modify, and distribute this software and
# its documentation for any purpose is hereby granted without fee,
# provided that the above copyright notice appear in all copies and
# that both that copyright notice and this permission notice appear in
# supporting documentation.
#
# THE AUTHOR MICHAEL HUDSON DISCLAIMS ALL WARRANTIES WITH REGARD TO
# THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS, IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL,
# INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER
# RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF
# CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
# CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""
OS-independent base for an event and VT sequence scanner

See unix_eventqueue and windows_eventqueue for subclasses.
"""

from __future__ import annotations

import anyio

from . import keymap
from .console import Event
from .trace import trace

__all__ = ["BaseEventQueue"]


class BaseEventQueue:  # noqa: D101
    def __init__(self, encoding: str, keymap_dict: dict[bytes, str]) -> None:
        self.compiled_keymap = keymap.compile_keymap(keymap_dict)
        self.keymap = self.compiled_keymap
        trace("keymap {k!r}", k=self.keymap)
        self.encoding = encoding
        self.ev_w, self.ev_r = anyio.create_memory_object_stream(9999)
        self.buf = bytearray()

    async def get(self) -> Event:
        """
        Retrieves the next event from the queue.
        """
        return await self.ev_r.receive()

    def empty(self) -> bool:
        """
        Checks if the queue is empty.
        """
        return self.ev_r.statistics().current_buffer_used == 0

    def flush_buf(self) -> bytearray:
        """
        Flushes the buffer and returns its contents.
        """
        old = self.buf
        self.buf = bytearray()
        return old

    def insert(self, event: Event) -> None:
        """
        Inserts an event into the queue.
        """
        trace("added event {event}", event=event)
        self.ev_w.send_nowait(event)

    def push(self, char: int | bytes) -> None:
        """
        Processes a character by updating the buffer and handling special key mappings.
        """
        assert isinstance(char, (int, bytes, bytearray)), char
        ord_char = char if isinstance(char, int) else ord(char)
        char = ord_char.to_bytes()
        self.buf.append(ord_char)

        if char in self.keymap:
            if self.keymap is self.compiled_keymap:
                # sanity check, buffer is empty when a special key comes
                assert len(self.buf) == 1
            k = self.keymap[char]
            trace("found map {k!r}", k=k)
            if isinstance(k, dict):
                self.keymap = k
            else:
                self.insert(Event("key", k, bytes(self.flush_buf())))
                self.keymap = self.compiled_keymap

        elif self.buf and self.buf[0] == 27:  # escape
            # escape sequence not recognized by our keymap: propagate it
            # outside so that i can be recognized as an M-... key (see also
            # the docstring in keymap.py
            trace("unrecognized escape sequence, propagating...")
            self.keymap = self.compiled_keymap
            self.insert(Event("key", "\033", b"\033"))
            for _c in self.flush_buf()[1:]:
                self.push(_c)

        else:
            try:
                decoded = bytes(self.buf).decode(self.encoding)
            except UnicodeError:
                return
            else:
                self.insert(Event("key", decoded, bytes(self.flush_buf())))
            self.keymap = self.compiled_keymap
