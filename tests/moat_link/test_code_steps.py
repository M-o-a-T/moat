"""code test action language: editor text <-> steps"""

from __future__ import annotations

import pytest

from moat.util import NotGiven
from moat.lib.path import P
from moat.link.code.steps import (
    VERBS,
    StepSyntaxError,
    format_editor,
    format_step,
    format_steps,
    format_value,
    parse_editor,
    parse_step,
    parse_steps,
    parse_value,
)

# (editor line, stored step); the line is the canonical form.
STEPS = [
    ("start", ["start"]),
    ("set in 2", ["set", P("in"), 2]),
    ("set :R.foo.bar hello", ["set", P(":R.foo.bar"), "hello"]),
    ("set x ~12", ["set", P("x"), "12"]),
    ("set a:1 'hello world'", ["set", P("a:1"), "hello world"]),
    ("set in '=[1, P('\"'\"'a.b'\"'\"'), (2, 3)]'", ["set", P("in"), [1, P("a.b"), (2, 3)]]),
    ("update in x 1 y.z =t", ["update", P("in"), P("x"), 1, P("y.z"), True]),
    ("delete out", ["delete", P("out")]),
    ("send some.topic 42", ["send", P("some.topic"), 42]),
    ("send some.topic ~42 std-json", ["send", P("some.topic"), "42", "std-json"]),
    ("monitor out out", ["monitor", "out", P("out")]),
    ("monitor raw :R.x.y mqtt", ["monitor", "raw", P(":R.x.y"), "mqtt"]),
    ("monitor raw x mqtt noop", ["monitor", "raw", P("x"), "mqtt", "noop"]),
    ("wait 1", ["wait", 1]),
    ("wait 0.5 out[-1] == 2 and len(out) > 1", ["wait", 0.5, "out[-1] == 2 and len(out) > 1"]),
    ("check len(out) == 2", ["check", "len(out) == 2"]),
    ("sleep 0.2", ["sleep", 0.2]),
    ("result", ["result"]),
    ("result result is None", ["result", "result is None"]),
    ("error", ["error"]),
    ("error isinstance(error, int)", ["error", "isinstance(error, int)"]),
    ("# some text  here", ["comment", "some text  here"]),
    ("#", ["comment", ""]),
]


def test_all_verbs_covered():
    "Every action appears in the round-trip table."
    assert {s[0] for _, s in STEPS} == VERBS


@pytest.mark.parametrize(("line", "step"), STEPS, ids=[x[0] for x in STEPS])
def test_roundtrip(line, step):
    "text -> step -> text, and step -> text -> step"
    assert parse_step(line) == step
    assert format_step(step) == line
    assert parse_step(format_step(step)) == step


@pytest.mark.parametrize(
    ("line", "step"),
    [
        ("  set   in    2  ", ["set", P("in"), 2]),
        ("set in .a.b", ["set", P("in"), P("a.b")]),
        ("set in =n", ["set", P("in"), None]),
        ("set in =-", ["set", P("in"), NotGiven]),
        ("set in =1+2", ["set", P("in"), 3]),
        ("comment hello", ["comment", "hello"]),
        ("#hello", ["comment", "hello"]),
        ("wait 2   x  ", ["wait", 2, "x"]),
    ],
)
def test_parse_variants(line, step):
    "Non-canonical input."
    assert parse_step(line) == step


@pytest.mark.parametrize(
    "value",
    [
        0,
        -3,
        1.5,
        "",
        "plain",
        "12",
        "1e5",
        "=x",
        ".x",
        ":x",
        "^x",
        "~x",
        "two words",
        "it's",
        True,
        False,
        None,
        NotGiven,
        P("a.b"),
        P(":R.a"),
        P("a:1"),
        [1, "x", None],
        (1,),
        {"a": 1, "b": [P("c"), b"xy"]},
        float("inf"),
    ],
    ids=repr,
)
def test_value_roundtrip(value):
    "Values in set -s syntax."
    import shlex  # noqa:PLC0415

    (word,) = shlex.split(format_value(value))
    res = parse_value(word)
    assert res == value or (res is value)
    assert type(res) is type(value) or isinstance(value, dict)


@pytest.mark.parametrize(
    ("line", "msg"),
    [
        ("frobnicate x", "unknown action"),
        ("start now", "takes 0 arguments"),
        ("set in", "takes 2 arguments"),
        ("set in 'unterminated", "quotation"),
        ("set in =1+", "bad value"),
        ("update in x", "KEY VALUE"),
        ("delete", "takes 1 argument"),
        ("monitor 1x out", "monitor name"),
        ("monitor len out", "reserved"),
        ("monitor x out kv", "expected 'mqtt'"),
        ("wait", "needs a timeout"),
        ("wait soon", "not a number"),
        ("wait -1", "negative"),
        ("wait 1 out[", "bad expression"),
        ("check", "empty expression"),
        ("check a ==", "bad expression"),
        ("sleep", "takes 1 argument"),
        ("result )", "bad expression"),
    ],
)
def test_parse_errors(line, msg):
    "Syntax errors."
    with pytest.raises(StepSyntaxError, match=msg):
        parse_step(line)


@pytest.mark.parametrize(
    "step",
    [
        [],
        "start",
        ["nope"],
        ["set", "in", 1],
        ["set", P("in")],
        ["wait", "1"],
        ["wait", True],
        ["check", "x ="],
        ["monitor", "x", P("y"), "kv"],
        ["comment", "two\nlines"],
        ["set", P("x"), object()],
    ],
    ids=lambda s: repr(s).split(" at 0x")[0],
)
def test_format_errors(step):
    "Malformed stored steps are rejected."
    with pytest.raises(StepSyntaxError):
        format_step(step)


def test_steps_line_numbers():
    "Errors point at the line."
    text = "start\n\nset in 1\n# fine\nwait x\n"
    with pytest.raises(StepSyntaxError) as exc:
        parse_steps(text)
    assert exc.value.line == 5
    assert str(exc.value).startswith("line 5: ")

    with pytest.raises(StepSyntaxError) as exc:
        format_steps([["start"], ["bad"]])
    assert exc.value.line == 2


HEADER = {
    "info": "copy a value",
    "timeout": 10,
    "data": {"in": {"_": 1}, "out": {"_": 0}},
    "args": {"src": P("in"), "dst": P("out"), "seconds": 0.2},
}
EXAMPLE_STEPS = [
    ["monitor", "out", P("out")],
    ["start"],
    ["set", P("in"), 2],
    ["wait", 1, "out[-1] == 2"],
    ["check", "len(out) == 2"],
]


def test_editor_roundtrip():
    "header + steps -> text -> header + steps -> text"
    text = format_editor(HEADER, EXAMPLE_STEPS)
    assert "\n---\nmonitor out out\nstart\nset in 2\n" in text
    assert "src: !P in" in text
    hdr, steps = parse_editor(text)
    assert hdr == HEADER
    assert steps == EXAMPLE_STEPS
    assert format_editor(hdr, steps) == text


def test_editor_edge_cases():
    "empty header, no separator, extra steps key"
    assert parse_editor("---\nstart\n") == ({}, [["start"]])
    assert parse_editor("info: x\n") == ({"info": "x"}, [])
    assert parse_editor("") == ({}, [])
    assert format_editor({}, [["start"]]) == "---\nstart\n"
    assert format_editor({"info": "x", "timeout": None, "steps": []}, []) == "info: x\n---\n"


def test_editor_errors():
    "Errors in the editor text point at the line."
    with pytest.raises(StepSyntaxError) as exc:
        parse_editor("info: x\ntimeout: 3\n---\nstart\n\nset in\n")
    assert exc.value.line == 6

    with pytest.raises(StepSyntaxError) as exc:
        parse_editor("info: x\ndata: [1\nargs: {}\n---\n")
    assert exc.value.line in (2, 3)

    with pytest.raises(StepSyntaxError) as exc:
        parse_editor("info: x\nsteps: []\n---\n")
    assert exc.value.line == 2
    assert "unknown header key" in exc.value.msg

    with pytest.raises(StepSyntaxError, match="mapping"):
        parse_editor("- 1\n---\n")

    with pytest.raises(StepSyntaxError, match="unknown header keys"):
        format_editor({"what": 1}, [])
