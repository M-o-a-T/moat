"""
Legacy packages are skipped by ``moat src build`` unless explicitly
requested: named on the command line, or selected with ``--legacy``.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from moat.src.build import select_parts


@pytest.fixture(autouse=True)
def _noskip(monkeypatch):
    """No SKIP marker anywhere.

    Patches ``anyio.Path.exists`` so that no package under test carries
    a SKIP file; hiding and skipping are exercised via attributes.
    """
    from anyio import Path  # noqa: PLC0415

    async def _exists(self):  # noqa: ARG001
        "Never a SKIP marker."
        return False

    monkeypatch.setattr(Path, "exists", _exists)


def _pkg(name: str, *, hidden: bool = False, legacy: bool = False) -> MagicMock:
    "A stand-in package with the attributes select_parts looks at."
    p = MagicMock()
    p.dash = name
    p.hidden = hidden
    p.legacy = legacy
    return p


def _repo(*pkgs: MagicMock) -> MagicMock:
    r = MagicMock()
    r.parts = list(pkgs)
    return r


@pytest.mark.anyio
async def test_legacy_skipped():
    "Legacy packages are not selected by default."
    a, leg = _pkg("moat-a"), _pkg("moat-leg", legacy=True)
    res = await select_parts(_repo(a, leg), (), set(), False)
    assert [x.dash for x in res] == ["moat-a"]


@pytest.mark.anyio
async def test_legacy_included_with_flag():
    "--legacy selects them."
    a, leg = _pkg("moat-a"), _pkg("moat-leg", legacy=True)
    res = await select_parts(_repo(a, leg), (), set(), True)
    assert [x.dash for x in res] == ["moat-a", "moat-leg"]


@pytest.mark.anyio
async def test_explicit_part_overrides_legacy():
    "Naming a legacy package on the command line builds it."
    leg = _pkg("moat-leg", legacy=True)
    repo = _repo(leg)
    repo.part.side_effect = lambda name: leg if name == "moat-leg" else None
    res = await select_parts(repo, ("moat-leg",), set(), False)
    assert [x.dash for x in res] == ["moat-leg"]


@pytest.mark.anyio
async def test_hidden_and_skip_still_filtered():
    "Hidden and skipped packages stay out, legacy or not."
    a = _pkg("moat-a")
    hid = _pkg("moat-hidden", hidden=True)
    skp = _pkg("moat-skipped")
    leg = _pkg("moat-leg", legacy=True)
    res = await select_parts(_repo(a, hid, skp, leg), (), {"moat-skipped"}, True)
    assert [x.dash for x in res] == ["moat-a", "moat-leg"]


@pytest.mark.anyio
async def test_non_legacy_unaffected():
    "Without legacy packages, --legacy changes nothing."
    a, b = _pkg("moat-a"), _pkg("moat-b")
    assert [x.dash for x in await select_parts(_repo(a, b), (), set(), False)] == [
        "moat-a",
        "moat-b",
    ]
    assert [x.dash for x in await select_parts(_repo(a, b), (), set(), True)] == [
        "moat-a",
        "moat-b",
    ]
