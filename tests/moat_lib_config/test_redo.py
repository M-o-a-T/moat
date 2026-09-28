# noqa:D100
from __future__ import annotations

import copy
import sys

from moat.util import NotGiven, attrdict
from moat.lib.config import CfgStore
from moat.lib.config._impl import _has_notgiven
from moat.lib.path import P


def test_has_notgiven():
    """``_has_notgiven`` recurses through mappings and sequences."""
    assert _has_notgiven(NotGiven) is True
    assert _has_notgiven("scalar") is False
    assert _has_notgiven(attrdict(a=1)) is False
    assert _has_notgiven(attrdict(a=NotGiven)) is True
    assert _has_notgiven([1, 2]) is False
    assert _has_notgiven([1, NotGiven]) is True
    assert _has_notgiven((NotGiven,)) is True
    assert _has_notgiven(attrdict(a=[1, attrdict(b=NotGiven)])) is True


def test_with_loads_submodule(tmp_path, monkeypatch):
    """``with_`` loads a fresh submodule's ``_cfg.yaml`` and redoes known stores."""
    pkg = tmp_path / "tmpkg_redo"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "_cfg.yaml").write_text("hello: world\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "tmpkg_redo", raising=False)

    saved_static = copy.deepcopy(CfgStore.static)
    saved_updated = CfgStore.updated
    try:
        store = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
        before = CfgStore.updated
        CfgStore.with_("tmpkg_redo")
        # fresh load bumped the update counter (the ``changed`` path)
        assert CfgStore.updated > before
        assert CfgStore.static.tmpkg_redo.hello == "world"
        # the known store was redone, so it sees the newly-loaded config
        assert store.result.tmpkg_redo.hello == "world"

        # second call: already registered, fast path, no reload / no redo
        before2 = CfgStore.updated
        CfgStore.with_("tmpkg_redo")
        assert CfgStore.updated == before2
    finally:
        CfgStore.static = saved_static
        CfgStore.updated = saved_updated


def test_mod_does_not_leak():
    """A store's ``mod`` changes neither the static config nor other stores."""
    saved_static = copy.deepcopy(CfgStore.static)
    try:
        CfgStore.static.leaktest = attrdict(sub=attrdict(val=0, other=1))
        a = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
        b = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
        a.mod(P("leaktest.sub.val"), 1)
        b.mod(P("leaktest.sub.val"), 2)
        assert a.leaktest.sub.val == 1
        assert b.leaktest.sub.val == 2
        assert CfgStore.static.leaktest.sub.val == 0

        # rebuilding one store must not change the other
        a.redo()
        assert b.leaktest.sub.val == 2
        assert a.leaktest.sub.other == 1
    finally:
        CfgStore.static = saved_static
