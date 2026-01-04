#   Copyright 2000-2004 Michael Hudson-Doyle <micahel@gmail.com>  # noqa: D100
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
from __future__ import annotations

import termios

TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import cast
else:
    cast = lambda typ, val: val  # noqa: ARG005, E731

__all__ = ["Term", "TermState", "tcgetattr", "tcsetattr"]


class TermState:  # noqa: D101
    def __init__(self, attrs: list[int | list[bytes]]) -> None:
        self.iflag = cast(int, attrs[0])
        self.oflag = cast(int, attrs[1])
        self.cflag = cast(int, attrs[2])
        self.lflag = cast(int, attrs[3])
        self.ispeed = cast(int, attrs[4])
        self.ospeed = cast(int, attrs[5])
        self.cc = cast(list[bytes], attrs[6])

    def as_list(self) -> list[int | list[bytes]]:  # noqa: D102
        return [
            self.iflag,
            self.oflag,
            self.cflag,
            self.lflag,
            self.ispeed,
            self.ospeed,
            # Always return a copy of the control characters list to ensure
            # there are not any additional references to self.cc
            self.cc[:],
        ]

    def copy(self) -> TermState:  # noqa: D102
        return self.__class__(self.as_list())


try:
    from moat.lib.proxy import as_proxy
except ImportError:
    pass
else:
    as_proxy("_TermSt", TermState)


def tcgetattr(fd: int) -> TermState:  # noqa: D103
    return TermState(termios.tcgetattr(fd))


def tcsetattr(fd: int, when: int, attrs: TermState) -> None:  # noqa: D103
    termios.tcsetattr(fd, when, attrs.as_list())


class Term(TermState):  # noqa: D101
    TS__init__ = TermState.__init__

    def __init__(self, fd: int = 0) -> None:
        self.TS__init__(termios.tcgetattr(fd))
        self.fd = fd
        self.stack: list[list[int | list[bytes]]] = []

    def save(self) -> None:  # noqa: D102
        self.stack.append(self.as_list())

    def set(self, when: int = termios.TCSANOW) -> None:  # noqa: D102
        termios.tcsetattr(self.fd, when, self.as_list())

    async def restore(self) -> None:  # noqa: D102
        self.TS__init__(self.stack.pop())
        self.set()
