#   Copyright 2000-2008 Michael Hudson-Doyle <micahel@gmail.com>  # noqa: D100
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
from __future__ import annotations

from .base_eventqueue import BaseEventQueue
from .trace import trace

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .terminfo import TermInfo

__all__ = ["EventQueue"]

# Mapping of human-readable key names to their terminal-specific codes
TERMINAL_KEYNAMES = {
    "delete": "kdch1",
    "down": "kcud1",
    "end": "kend",
    "enter": "kent",
    "home": "khome",
    "insert": "kich1",
    "left": "kcub1",
    "page down": "knp",
    "page up": "kpp",
    "right": "kcuf1",
    "up": "kcuu1",
}


# Function keys F1-F20 mapping
TERMINAL_KEYNAMES.update(("f%d" % i, "kf%d" % i) for i in range(1, 21))  # noqa: UP031

# Known CTRL-arrow keycodes
CTRL_ARROW_KEYCODES = {
    # for xterm, gnome-terminal, xfce terminal, etc.
    b"\033[1;5D": "ctrl left",
    b"\033[1;5C": "ctrl right",
    # for rxvt
    b"\033Od": "ctrl left",
    b"\033Oc": "ctrl right",
}


def get_terminal_keycodes(ti: TermInfo) -> dict[bytes, str]:
    """
    Generates a dictionary mapping terminal keycodes to human-readable names.
    """
    keycodes = {}
    for key, terminal_code in TERMINAL_KEYNAMES.items():
        keycode = ti.get(terminal_code)
        trace("key {key} tiname {terminal_code} keycode {keycode!r}", **locals())
        if keycode:
            keycodes[keycode] = key
    keycodes.update(CTRL_ARROW_KEYCODES)
    return keycodes


class EventQueue(BaseEventQueue):  # noqa: D101
    def __init__(self, encoding: str, ti: TermInfo, backspace: bytes | None = None) -> None:
        keycodes = get_terminal_keycodes(ti)
        if backspace is not None:
            keycodes[backspace] = "backspace"
        BaseEventQueue.__init__(self, encoding, keycodes)
