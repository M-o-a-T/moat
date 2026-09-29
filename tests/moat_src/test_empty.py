"""
Tests for the ``empty`` package flag handled by :mod:`moat.src._repo`
and :mod:`moat.src.build`.

Packages flagged ``empty`` in ``versions.yaml`` ship no Python source of
their own -- only packaging scaffolding (Debian metadata, systemd units,
a ``pyproject.toml`` …).  The build machinery must therefore not require
a source-evolution tag for them, must not try to copy a non-existent
source tree, and must refuse to silently ship stray files under the flag.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from moat.util import attrdict
from moat.src._repo import Package


def _pkg(vers: attrdict) -> Package:
    """Build a :class:`Package` backed by a stub repo carrying *vers*."""
    repo = MagicMock()
    repo.versions = attrdict()
    p = Package(repo, "moat.foo.bar")
    repo.versions[p.dash] = vers
    return p


def test_empty_false_without_flag() -> None:
    """A package with no ``empty`` key is not empty."""
    assert _pkg(attrdict()).empty is False


def test_empty_true_with_flag() -> None:
    """Setting ``empty: True`` marks the package as source-less."""
    assert _pkg(attrdict(empty=True)).empty is True


def test_has_changes_source_short_circuits_when_empty() -> None:
    """An empty package has no source, so source changes are always False."""
    p = _pkg(attrdict(empty=True))
    # main=True (source) and main=None both short-circuit.
    assert p.has_changes(True) is False
    assert p.has_changes(None) is False


def test_has_changes_packaging_still_tracked_when_empty() -> None:
    """Packaging changes (``main=False``) are not masked by the flag.

    The short-circuit only covers the source axis; the packaging axis must
    still defer to the real diff so that edits to ``debian/`` etc. are
    noticed.  With no recorded commit the underlying guard returns True.
    """
    p = _pkg(attrdict(empty=True))
    assert p.has_changes(False) is True


def test_copy_is_noop_when_empty() -> None:
    """Copying an empty package does nothing and needs no files."""
    p = _pkg(attrdict(empty=True))
    p.files = set()
    p.copy()  # must not raise


def test_copy_requires_files_when_not_empty() -> None:
    """A non-empty package without files is still an error."""
    p = _pkg(attrdict())  # not empty
    p.files = set()
    with pytest.raises(ValueError, match=r"No files in moat\.foo\.bar"):
        p.copy()
