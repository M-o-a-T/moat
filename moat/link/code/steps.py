"""
The action language of code snippet tests.

A test case's ``steps`` are stored as lists (``[verb, arg, …]``). The
editor shows them one per line: the verb, then its arguments separated
by spaces. Values use the syntax of ``moat link data PATH set -s KEY
VALUE`` (``~str``, ``=expr``, ``.path``, …); an expression is the rest of
the line; a line starting with ``#`` is a comment.

The editor text consists of the test's header (``info``, ``timeout``,
``data``, ``args``) as one YAML document, a ``---`` line, and the
actions.

See ``TODO/codetest.md``, sections "Actions" and "Editor format".
"""

from __future__ import annotations

import ast
import io
import keyword
import shlex

from moat.util import NotGiven, yload, yprint
from moat.lib.path import P, Path
from moat.lib.run import process_args

from typing import Any

__all__ = [
    "EXPR_NAMES",
    "HEADER_KEYS",
    "StepSyntaxError",
    "format_editor",
    "format_step",
    "format_steps",
    "format_value",
    "parse_editor",
    "parse_step",
    "parse_steps",
    "parse_value",
]

#: Names the expression evaluator provides; monitors may not use them.
EXPR_NAMES = frozenset({"P", "len", "abs", "min", "max", "result", "error"})

#: The keys of the header, in editor order.
HEADER_KEYS = ("info", "timeout", "data", "args")

SEPARATOR = "---"


class StepSyntaxError(ValueError):
    """
    A step (or the editor text) could not be parsed or formatted.

    ``line`` is the 1-based line number in the text, if known.
    """

    def __init__(self, msg: str, line: int | None = None):
        self.msg = msg
        self.line = line
        super().__init__(msg if line is None else f"line {line}: {msg}")

    def at(self, line: int) -> StepSyntaxError:
        "Return a copy that points at this line."
        return StepSyntaxError(self.msg, line)


# Values


def _quote(s: str) -> str:
    "Shell-quote a word, but only if shlex.split would not keep it as is."
    if s and not any(c.isspace() or c in "'\"\\" for c in s):
        return s
    return shlex.quote(s)


def parse_value(text: str) -> Any:
    """
    Parse a value in ``moat link data … set -s`` syntax.
    """
    if text == "":
        raise StepSyntaxError("empty value (use '~' for an empty string)")
    if text == "=-":
        return NotGiven  # process_args would delete the key
    try:
        return process_args({}, set_=[(P("v"), text)])["v"]
    except Exception as exc:
        raise StepSyntaxError(f"bad value {text!r}: {exc}") from exc


def _parses_as_other(s: str) -> bool:
    "Would this string, written bare, be read back as something else?"
    if s == "" or s[0] in "~=:.^":
        return True
    for typ in (int, float):
        try:
            typ(s)
        except ValueError:
            pass
        else:
            return True
    return False


def _literal(v: Any) -> str:
    "Python source for a value, for the ``=expr`` syntax."
    if isinstance(v, Path):
        return f"P({str(v)!r})"
    if isinstance(v, bool) or v is None or isinstance(v, (int, str, bytes)):
        return repr(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise StepSyntaxError(f"cannot write {v!r} inside a structure")
        return repr(v)
    if isinstance(v, tuple):
        if len(v) == 1:
            return f"({_literal(v[0])},)"
        return "(" + ", ".join(_literal(x) for x in v) + ")"
    if isinstance(v, list):
        return "[" + ", ".join(_literal(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_literal(k)}: {_literal(x)}" for k, x in v.items()) + "}"
    raise StepSyntaxError(f"cannot write a value of type {type(v).__name__}")


def format_value(v: Any) -> str:
    """
    Format a value in ``moat link data … set -s`` syntax.

    The result is a single, possibly shell-quoted, word.
    """
    if v is NotGiven:
        s = "=-"
    elif v is True:
        s = "=t"
    elif v is False:
        s = "=f"
    elif v is None:
        s = "=n"
    elif isinstance(v, Path):
        s = str(v)
        if s[0] != ":":
            s = "." + s
    elif isinstance(v, str):
        s = "~" + v if _parses_as_other(v) else v
    elif isinstance(v, int):
        s = str(v)
    elif isinstance(v, float):
        s = repr(v)
    else:
        s = "=" + _literal(v)
    return _quote(s)


# Arguments


def _parse_path(text: str) -> Path:
    try:
        return P(text)
    except Exception as exc:
        raise StepSyntaxError(f"bad path {text!r}: {exc}") from exc


def _format_path(p: Any) -> str:
    if not isinstance(p, Path):
        raise StepSyntaxError(f"not a path: {p!r}")
    return _quote(str(p))


def _parse_num(text: str) -> int | float:
    try:
        v = int(text)
    except ValueError:
        try:
            v = float(text)
        except ValueError:
            raise StepSyntaxError(f"not a number: {text!r}") from None
    if not v >= 0:
        raise StepSyntaxError(f"must not be negative: {text!r}")
    return v


def _format_num(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v >= 0:
        raise StepSyntaxError(f"not a non-negative number: {v!r}")
    return str(v) if isinstance(v, int) else repr(v)


def _check_expr(expr: Any) -> str:
    if not isinstance(expr, str):
        raise StepSyntaxError(f"not an expression: {expr!r}")
    expr = expr.strip()
    if not expr:
        raise StepSyntaxError("empty expression")
    if "\n" in expr:
        raise StepSyntaxError("expression spans lines")
    try:
        ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise StepSyntaxError(f"bad expression {expr!r}: {exc.msg}") from None
    return expr


def _check_name(name: Any) -> str:
    if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name):
        raise StepSyntaxError(f"not a valid monitor name: {name!r}")
    if name in EXPR_NAMES:
        raise StepSyntaxError(f"monitor name {name!r} is reserved")
    return name


def _check_word(word: Any, what: str) -> str:
    if not isinstance(word, str) or not word or any(c.isspace() for c in word):
        raise StepSyntaxError(f"not a valid {what}: {word!r}")
    return word


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise StepSyntaxError(str(exc)) from None


def _nargs(verb: str, args: list, lo: int, hi: int | None = None) -> None:
    if hi is None:
        hi = lo
    if lo <= len(args) <= hi:
        return
    if lo == hi:
        want = f"{lo} argument{'' if lo == 1 else 's'}"
    else:
        want = f"{lo} to {hi} arguments"
    raise StepSyntaxError(f"{verb!r} takes {want}, not {len(args)}")


# Steps
#
# Each verb has a parser (rest of line -> step list) and a formatter
# (step args -> rest of line). The formatter validates the stored form.


def _p_none(verb, text):
    _nargs(verb, _split(text), 0)
    return [verb]


def _f_none(verb, args):
    _nargs(verb, args, 0)
    return ""


def _p_path(verb, text):
    a = _split(text)
    _nargs(verb, a, 1)
    return [verb, _parse_path(a[0])]


def _f_path(verb, args):
    _nargs(verb, args, 1)
    return _format_path(args[0])


def _p_set(verb, text):
    a = _split(text)
    _nargs(verb, a, 2)
    return [verb, _parse_path(a[0]), parse_value(a[1])]


def _f_set(verb, args):
    _nargs(verb, args, 2)
    return f"{_format_path(args[0])} {format_value(args[1])}"


def _p_update(verb, text):
    a = _split(text)
    if len(a) < 3 or len(a) % 2 == 0:
        raise StepSyntaxError(f"{verb!r} takes a path and KEY VALUE pairs")
    res = [verb, _parse_path(a[0])]
    for k, v in zip(a[1::2], a[2::2], strict=True):
        res.append(_parse_path(k))
        res.append(parse_value(v))
    return res


def _f_update(verb, args):
    if len(args) < 3 or len(args) % 2 == 0:
        raise StepSyntaxError(f"{verb!r} takes a path and KEY VALUE pairs")
    res = [_format_path(args[0])]
    for k, v in zip(args[1::2], args[2::2], strict=True):
        res.append(_format_path(k))
        res.append(format_value(v))
    return " ".join(res)


def _p_send(verb, text):
    a = _split(text)
    _nargs(verb, a, 2, 3)
    res = [verb, _parse_path(a[0]), parse_value(a[1])]
    if len(a) > 2:
        res.append(_check_word(a[2], "codec"))
    return res


def _f_send(verb, args):
    _nargs(verb, args, 2, 3)
    res = f"{_format_path(args[0])} {format_value(args[1])}"
    if len(args) > 2:
        res += " " + _check_word(args[2], "codec")
    return res


def _mon_tail(a):
    if not a:
        return []
    if a[0] != "mqtt":
        raise StepSyntaxError(f"expected 'mqtt', not {a[0]!r}")
    if len(a) > 1:
        return ["mqtt", _check_word(a[1], "codec")]
    return ["mqtt"]


def _p_monitor(verb, text):
    a = _split(text)
    _nargs(verb, a, 2, 4)
    return [verb, _check_name(a[0]), _parse_path(a[1]), *_mon_tail(a[2:])]


def _f_monitor(verb, args):
    _nargs(verb, args, 2, 4)
    res = f"{_check_name(args[0])} {_format_path(args[1])}"
    tail = _mon_tail(list(args[2:]))
    if tail:
        res += " " + " ".join(tail)
    return res


def _p_wait(verb, text):
    a = text.split(None, 1)
    if not a:
        raise StepSyntaxError(f"{verb!r} needs a timeout")
    res = [verb, _parse_num(a[0])]
    if len(a) > 1:
        res.append(_check_expr(a[1]))
    return res


def _f_wait(verb, args):
    _nargs(verb, args, 1, 2)
    res = _format_num(args[0])
    if len(args) > 1:
        res += " " + _check_expr(args[1])
    return res


def _p_num(verb, text):
    a = _split(text)
    _nargs(verb, a, 1)
    return [verb, _parse_num(a[0])]


def _f_num(verb, args):
    _nargs(verb, args, 1)
    return _format_num(args[0])


def _p_expr(verb, text):
    return [verb, _check_expr(text)]


def _f_expr(verb, args):
    _nargs(verb, args, 1)
    return _check_expr(args[0])


def _p_opt_expr(verb, text):
    if not text.strip():
        return [verb]
    return [verb, _check_expr(text)]


def _f_opt_expr(verb, args):
    _nargs(verb, args, 0, 1)
    return _check_expr(args[0]) if args else ""


def _p_comment(verb, text):
    return [verb, text.strip()]


def _f_comment(verb, args):
    _nargs(verb, args, 1)
    if not isinstance(args[0], str) or "\n" in args[0]:
        raise StepSyntaxError(f"not a one-line comment: {args[0]!r}")
    return args[0].strip()


_VERBS = {
    "start": (_p_none, _f_none),
    "set": (_p_set, _f_set),
    "update": (_p_update, _f_update),
    "delete": (_p_path, _f_path),
    "send": (_p_send, _f_send),
    "monitor": (_p_monitor, _f_monitor),
    "wait": (_p_wait, _f_wait),
    "check": (_p_expr, _f_expr),
    "sleep": (_p_num, _f_num),
    "result": (_p_opt_expr, _f_opt_expr),
    "error": (_p_opt_expr, _f_opt_expr),
    "comment": (_p_comment, _f_comment),
}

#: The known actions.
VERBS = frozenset(_VERBS)


def parse_step(line: str) -> list:
    """
    Parse one editor line into a step.
    """
    line = line.strip()
    if line.startswith("#"):
        return ["comment", line[1:].strip()]
    verb, _, rest = line.partition(" ")
    try:
        parse, _fmt = _VERBS[verb]
    except KeyError:
        raise StepSyntaxError(f"unknown action {verb!r}") from None
    return parse(verb, rest.strip())


def format_step(step: list | tuple) -> str:
    """
    Format a step as one editor line.
    """
    if not isinstance(step, (list, tuple)) or not step:
        raise StepSyntaxError(f"not a step: {step!r}")
    verb, *args = step
    try:
        _parse, fmt = _VERBS[verb]
    except (KeyError, TypeError):
        raise StepSyntaxError(f"unknown action {verb!r}") from None
    rest = fmt(verb, args)
    if verb == "comment":
        return f"# {rest}" if rest else "#"
    return f"{verb} {rest}" if rest else verb


def parse_steps(text: str, first_line: int = 1) -> list[list]:
    """
    Parse editor lines into a list of steps. Empty lines are skipped.

    Errors carry the line number, counting from ``first_line``.
    """
    res = []
    for n, line in enumerate(text.splitlines(), start=first_line):
        if not line.strip():
            continue
        try:
            res.append(parse_step(line))
        except StepSyntaxError as exc:
            raise exc.at(n) from exc
    return res


def format_steps(steps: list) -> str:
    """
    Format a list of steps as editor lines.

    Errors carry the (1-based) index of the offending step as its line.
    """
    res = []
    for n, step in enumerate(steps, start=1):
        try:
            res.append(format_step(step) + "\n")
        except StepSyntaxError as exc:
            raise exc.at(n) from exc
    return "".join(res)


# The whole editor text


def parse_editor(text: str) -> tuple[dict, list[list]]:
    """
    Parse the editor text into the header (a dict) and the steps.

    The header is the YAML document before the first ``---`` line. If
    there is no such line, there are no steps.
    """
    lines = text.splitlines(keepends=True)
    sep = next((i for i, ln in enumerate(lines) if ln.rstrip() == SEPARATOR), len(lines))

    try:
        hdr = yload("".join(lines[:sep]))
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        line = mark.line + 1 if mark is not None else 1
        msg = getattr(exc, "problem", None) or str(exc)
        raise StepSyntaxError(f"header: {msg}", line) from exc
    if hdr is None:
        hdr = {}
    if not isinstance(hdr, dict):
        raise StepSyntaxError("the header must be a mapping", 1)
    for k in hdr:
        if k not in HEADER_KEYS:
            n = next(
                (i for i, ln in enumerate(lines[:sep], start=1) if ln.startswith(f"{k}:")),
                1,
            )
            raise StepSyntaxError(f"unknown header key {k!r}", n)

    steps = parse_steps("".join(lines[sep + 1 :]), first_line=sep + 2)
    return hdr, steps


def format_editor(hdr: dict, steps: list) -> str:
    """
    Format a test's header and steps as editor text.
    """
    h = {k: hdr[k] for k in HEADER_KEYS if hdr.get(k) is not None}
    extra = set(hdr) - set(HEADER_KEYS) - {"steps"}
    if extra:
        raise StepSyntaxError(f"unknown header keys: {', '.join(sorted(map(str, extra)))}")
    buf = io.StringIO()
    if h:
        yprint(h, stream=buf)
    return buf.getvalue() + SEPARATOR + "\n" + format_steps(steps)
