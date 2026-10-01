"""
``moat src build`` must not rebuild packages in the next build because of
edits it made itself, and must rebuild a package whose dependencies it
rewrites right away.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from moat.util import attrdict
from moat.src._repo import only_build_changes, pyproject_key
from moat.src.build import do_versions

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

INTERNAL = {"moat-util", "moat-link"}

BASE = """\
[project]
name = "moat-foo"
version = "0.2.0"
dependencies = [
	"anyio ~= 4.0",
	"moat-util ~= 0.63.0",
	"moat-link ~= 0.10.0",
]
"""


def test_key_ignores_generated():
    "The version and internal dependency specifiers don't matter."
    gen = BASE.replace('"0.2.0"', '"0.2.1"').replace("0.63.0", "0.64.0")
    assert pyproject_key(BASE, INTERNAL) == pyproject_key(gen, INTERNAL)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"anyio ~= 4.0"', '"anyio ~= 4.1"'),  # external dependency
        ('"moat-link ~= 0.10.0",\n', '"moat-link ~= 0.10.0",\n\t"moat-lib-x",\n'),  # added
        ('name = "moat-foo"', 'name = "moat-bar"'),
    ],
)
def test_key_sees_real_changes(old, new):
    "Anything else is a change."
    assert old in BASE
    assert pyproject_key(BASE, INTERNAL) != pyproject_key(BASE.replace(old, new), INTERNAL)


def _diff(a: str | None, b: str | None):
    def blob(t):
        if t is None:
            return None
        m = MagicMock()
        m.data_stream.read.return_value = t.encode("utf-8")
        return m

    d = MagicMock()
    d.a_blob = blob(a)
    d.b_blob = blob(b)
    return d


def test_only_build_changes():
    "Diffs of pyproject.toml files."
    gen = BASE.replace('"0.2.0"', '"0.2.1"')
    assert only_build_changes(_diff(BASE, gen), INTERNAL)
    assert not only_build_changes(_diff(BASE, BASE.replace("4.0", "4.1")), INTERNAL)
    assert not only_build_changes(_diff(BASE, None), INTERNAL)  # deleted
    assert not only_build_changes(_diff(BASE, "garbage = ["), INTERNAL)


def _setup(tmp_path: Path, monkeypatch, deps: str, deb: str):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "packaging" / "moat-foo"
    p.mkdir(parents=True)
    (p / "pyproject.toml").write_text(BASE.replace("0.63.0", deps))

    r = MagicMock()
    r.dash = "moat-foo"
    r.empty = False
    r.vers = attrdict(new="0.2.0", tag="0.2.0", deb=deb, pkg=1)
    r.has_changes.return_value = False
    r.next_tag.return_value = "0.2.0"
    repo = MagicMock()
    repo.head.commit.hexsha = "abc"
    return repo, r


async def _run(repo, r):
    await do_versions(repo, [r], {"moat-util": "0.64.0"}, attrdict(version=False), MagicMock())


@pytest.mark.anyio
async def test_rebuild_on_dep_change(tmp_path, monkeypatch):
    "Rewriting a dependency rebuilds the package now."
    repo, r = _setup(tmp_path, monkeypatch, "0.63.0", "0.2.0-1")
    await _run(repo, r)
    assert "moat-util ~= 0.64.0" in (tmp_path / "packaging/moat-foo/pyproject.toml").read_text()
    assert r.vers.pkg == 2
    assert r.vers.pkgrev == "abc"


@pytest.mark.anyio
async def test_no_double_bump(tmp_path, monkeypatch):
    "A package that's rebuilt anyway isn't bumped again."
    repo, r = _setup(tmp_path, monkeypatch, "0.63.0", "0.1.9-1")
    await _run(repo, r)
    assert r.vers.pkg == 1


@pytest.mark.anyio
async def test_no_bump_without_change(tmp_path, monkeypatch):
    "Dependencies that are current don't cause a rebuild."
    repo, r = _setup(tmp_path, monkeypatch, "0.64.0", "0.2.0-1")
    await _run(repo, r)
    assert r.vers.pkg == 1
    assert "pkgrev" not in r.vers
