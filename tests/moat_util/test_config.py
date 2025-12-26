"""
Some rudimentary tests for config loading
"""

# ruff:noqa:D103 pylint: disable=missing-function-docstring
from __future__ import annotations

from moat.util import yload
from moat.lib import config
from moat.lib.config import CfgStore

c1 = """\
bar: baz
"""
c2 = """
foo:
    one: two
ext:
    three: four
"""

c3 = """
path:
    ref:
        bar: !P :@.foo.bar
base:
    - $base:
      - "tests/cfg/foo1.cfg"
      - !P :@.what.is
    - port:
        $base: "tests/cfg/foo.cfg"
        in_the: storm
ext:
    three: four
"""

config.TEST = True


def test_basic(tmp_path):
    "basic config file loading"
    c = CfgStore("foo")
    assert c.result.foo.some.thing.to == "do"
    assert "foo" not in c.result.foo
    assert "bar" not in c.result.foo
    assert "three" not in c.result.foo

    tf1 = tmp_path / "c1"
    tf1.write_text(c1)
    c.add(tf1)

    assert c.result.foo.bar == "baz"


def test_tagged(tmp_path):
    tf3 = tmp_path / "c3"
    tf3.write_text(c3)
    d = yload(tf3, attr=True)
    assert d.needs_post_
    assert not d.ext.needs_post_
    assert d.path.needs_post_
    assert d.base[0].needs_post_


def test_refs(tmp_path):
    "test config file mangling"
    c = CfgStore("foo")
    tf1 = tmp_path / "c1"
    tf1.write_text(c1)
    tf3 = tmp_path / "c3"
    tf3.write_text(c3)
    c.add(tf1)
    c.add(tf3)

    assert c.result.foo.base[0].new == "today"
    assert c.result.foo.base[1].port.in_the == "storm"
    assert c.result.foo.base[1].port.some.thing.to == "do"
