#   Copyright 2000-2008 Michael Hudson-Doyle <micahel@gmail.com>  # noqa: D104
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

# Lazy import mapping: maps exported names to (module, attribute) tuples
_imports = {
    # base_eventqueue
    "BaseEventQueue": "base_eventqueue",
    # commands
    "Command": "commands",
    "KillCommand": "commands",
    "YankCommand": "commands",
    "MotionCommand": "commands",
    "EditCommand": "commands",
    "FinishCommand": "commands",
    "is_kill": "commands",
    "is_yank": "commands",
    # completing_reader
    "CompletingReader": "completing_reader",
    # console
    "Event": "console",
    "Console": "console",
    "InteractiveColoredConsole": "console",
    "Readline": "console",
    # fancy_termios
    "TermState": "fancy_termios",
    "Term": "fancy_termios",
    "tcgetattr": "fancy_termios",
    "tcsetattr": "fancy_termios",
    # historical_reader
    "HistoricalReader": "historical_reader",
    # input
    "InputTranslator": "input_",
    "KeymapTranslator": "input_",
    # keymap
    "compile_keymap": "keymap",
    # pager
    "plain_pager": "pager",
    "pipe_pager": "pager",
    "tempfile_pager": "pager",
    # reader
    "Reader": "reader",
    # readline - multiline input functions
    "ReadlineAlikeReader": "readline",
    "add_history": "readline",
    "append_history_file": "readline",
    "clear_history": "readline",
    "get_begidx": "readline",
    "get_completer": "readline",
    "get_completer_delims": "readline",
    "get_current_history_length": "readline",
    "get_endidx": "readline",
    "get_history_item": "readline",
    "get_history_length": "readline",
    "get_line_buffer": "readline",
    "input": "readline",
    "insert_text": "readline",
    "multiline_input": "readline",
    "parse_and_bind": "readline",
    "read_history_file": "readline",
    "remove_history_item": "readline",
    "replace_history_item": "readline",
    "set_auto_history": "readline",
    "set_completer": "readline",
    "set_completer_delims": "readline",
    "set_history_length": "readline",
    "set_startup_hook": "readline",
    "write_history_file": "readline",
    # rpc
    "MsgTerm": "rpc",
    # simple_interact
    "run_multiline_interactive_console": "simple_interact",
    # terminfo
    "TermInfo": "terminfo",
    "tparm": "terminfo",
    # unix_console
    "UnixConsole": "unix_console",
    # unix_eventqueue
    "EventQueue": "unix_eventqueue",
    # utils
    "THEME": "utils",
    "disp_str": "utils",
    "gen_colors": "utils",
    "unbracket": "utils",
    "wlen": "utils",
    # windows_console
    "WindowsConsole": "windows_console",
}

__all__ = list(_imports.keys())


def __getattr__(attr: str):
    try:
        mod = _imports[attr]
    except KeyError:
        raise AttributeError(attr) from None
    value = getattr(__import__(mod, globals(), None, [attr], 1), attr)
    globals()[attr] = value
    return value


def __dir__():
    return __all__
