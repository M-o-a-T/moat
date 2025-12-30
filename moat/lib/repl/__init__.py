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
_LAZY_IMPORTS = {
    # base_eventqueue
    "BaseEventQueue": ("base_eventqueue", "BaseEventQueue"),
    # commands
    "Command": ("commands", "Command"),
    "KillCommand": ("commands", "KillCommand"),
    "YankCommand": ("commands", "YankCommand"),
    "MotionCommand": ("commands", "MotionCommand"),
    "EditCommand": ("commands", "EditCommand"),
    "FinishCommand": ("commands", "FinishCommand"),
    "is_kill": ("commands", "is_kill"),
    "is_yank": ("commands", "is_yank"),
    # completing_reader
    "CompletingReader": ("completing_reader", "CompletingReader"),
    # console
    "Event": ("console", "Event"),
    "Console": ("console", "Console"),
    "InteractiveColoredConsole": ("console", "InteractiveColoredConsole"),
    "Readline": ("console", "Readline"),
    # fancy_termios
    "TermState": ("fancy_termios", "TermState"),
    "Term": ("fancy_termios", "Term"),
    "tcgetattr": ("fancy_termios", "tcgetattr"),
    "tcsetattr": ("fancy_termios", "tcsetattr"),
    # historical_reader
    "HistoricalReader": ("historical_reader", "HistoricalReader"),
    # input
    "InputTranslator": ("input", "InputTranslator"),
    "KeymapTranslator": ("input", "KeymapTranslator"),
    # keymap
    "compile_keymap": ("keymap", "compile_keymap"),
    # pager
    "plain_pager": ("pager", "plain_pager"),
    "pipe_pager": ("pager", "pipe_pager"),
    "tempfile_pager": ("pager", "tempfile_pager"),
    # reader
    "Reader": ("reader", "Reader"),
    # readline - multiline input functions
    "add_history": ("readline", "add_history"),
    "append_history_file": ("readline", "append_history_file"),
    "clear_history": ("readline", "clear_history"),
    "get_begidx": ("readline", "get_begidx"),
    "get_completer": ("readline", "get_completer"),
    "get_completer_delims": ("readline", "get_completer_delims"),
    "get_current_history_length": ("readline", "get_current_history_length"),
    "get_endidx": ("readline", "get_endidx"),
    "get_history_item": ("readline", "get_history_item"),
    "get_history_length": ("readline", "get_history_length"),
    "get_line_buffer": ("readline", "get_line_buffer"),
    "insert_text": ("readline", "insert_text"),
    "multiline_input": ("readline", "multiline_input"),
    "parse_and_bind": ("readline", "parse_and_bind"),
    "read_history_file": ("readline", "read_history_file"),
    "remove_history_item": ("readline", "remove_history_item"),
    "replace_history_item": ("readline", "replace_history_item"),
    "set_auto_history": ("readline", "set_auto_history"),
    "set_completer": ("readline", "set_completer"),
    "set_completer_delims": ("readline", "set_completer_delims"),
    "set_history_length": ("readline", "set_history_length"),
    "set_startup_hook": ("readline", "set_startup_hook"),
    "write_history_file": ("readline", "write_history_file"),
    # rpc
    "MsgConsole": ("rpc", "MsgConsole"),
    # simple_interact
    "run_multiline_interactive_console": ("simple_interact", "run_multiline_interactive_console"),
    # terminfo
    "TermInfo": ("terminfo", "TermInfo"),
    "tparm": ("terminfo", "tparm"),
    # trace
    "trace": ("trace", "trace"),
    # unix_console
    "UnixConsole": ("unix_console", "UnixConsole"),
    # unix_eventqueue
    "EventQueue": ("unix_eventqueue", "EventQueue"),
    # utils
    "THEME": ("utils", "THEME"),
    "disp_str": ("utils", "disp_str"),
    "gen_colors": ("utils", "gen_colors"),
    "unbracket": ("utils", "unbracket"),
    "wlen": ("utils", "wlen"),
    # windows_console
    "WindowsConsole": ("windows_console", "WindowsConsole"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    """Lazy import attributes from submodules."""
    if name in _LAZY_IMPORTS:
        module_name, attr_name = _LAZY_IMPORTS[name]
        from importlib import import_module  # noqa: PLC0415

        module = import_module(f".{module_name}", __name__)
        value = getattr(module, attr_name)
        # Cache the imported value
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """Return the list of available attributes."""
    return __all__
