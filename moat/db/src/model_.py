"""Cross-table relationships and ``apply()`` overrides for moat.db.src.

Mirrors the ``box``/``thing``/``label`` layout: relationships are attached
here with :func:`sqlalchemy.orm.relationship` + ``back_populates`` to break
the import cycle between :class:`Spkg`/:class:`Archive`/:class:`LocalBranch`
and their role registries, and the rich ``apply()`` methods are monkey-
patched onto the classes via :func:`moat.util.cast` (matching the
established pattern, since :mod:`moat.db.src.model` must not reach across
submodules at import time).
"""

from __future__ import annotations

from sqlalchemy.orm import relationship

from moat.util import NotGiven
from moat.db.schema import Base
from moat.db.util import session
from moat.util.times import now

from .model import Archive, ArchiveRole, BranchRole, LocalBranch, Spkg

from typing import Any, cast

cast(Any, Spkg).archives = relationship(
    "Archive", back_populates="spkg", collection_class=set, passive_deletes=True
)
cast(Any, Spkg).branches = relationship(
    "LocalBranch", back_populates="spkg", collection_class=set, passive_deletes=True
)
cast(Any, ArchiveRole).archives = relationship(
    "Archive", back_populates="archiverole", collection_class=set, passive_deletes=True
)
cast(Any, BranchRole).branches = relationship(
    "LocalBranch", back_populates="branchrole", collection_class=set, passive_deletes=True
)

cast(Any, Archive).spkg = relationship("Spkg", back_populates="archives")
cast(Any, Archive).archiverole = relationship("ArchiveRole", back_populates="archives")
cast(Any, LocalBranch).spkg = relationship("Spkg", back_populates="branches")
cast(Any, LocalBranch).branchrole = relationship("BranchRole", back_populates="branches")


def spkg_apply(self, *, comment: Any = NotGiven, prefix: Any = NotGiven, **kw: Any) -> None:
    """Apply mutable SPKG properties.

    Args:
        comment: Free-text description, or ``None`` to clear.
        prefix: Short token for Beads issue targeting, or ``None`` to clear.
        **kw: Other scalar columns forwarded to :meth:`Base.apply`.
    """
    Base.apply(self, comment=comment, prefix=prefix, **kw)


Spkg.apply = cast(Any, spkg_apply)


def archiverole_apply(self, *, comment: Any = NotGiven, rank: Any = NotGiven, **kw: Any) -> None:
    """Apply mutable archive-role properties.

    Args:
        comment: Free-text description, or ``None`` to clear.
        rank: Display-order integer (lower=earlier), or ``None`` to clear.
        **kw: Other scalar columns forwarded to :meth:`Base.apply`.
    """
    Base.apply(self, comment=comment, rank=rank, **kw)


ArchiveRole.apply = cast(Any, archiverole_apply)


def branchrole_apply(
    self, *, comment: Any = NotGiven, abstract: bool = False, real: bool = False, **kw: Any
) -> None:
    """Apply mutable branch-role properties.

    Args:
        comment: Free-text description, or ``None`` to clear.
        abstract: Set ``abstract=True`` (short-lived role).
        real: Set ``abstract=False`` (long-lived role).
        **kw: Other scalar columns forwarded to :meth:`Base.apply`.

    Raises:
        ValueError: if both ``abstract`` and ``real`` are requested.
    """
    Base.apply(self, comment=comment, **kw)
    if abstract:
        if real:
            raise ValueError("A branch role can't be both abstract and real")
        self.abstract = True
    elif real:
        self.abstract = False


BranchRole.apply = cast(Any, branchrole_apply)


def archive_apply(
    self,
    *,
    role: Any = NotGiven,
    default: Any = NotGiven,
    **kw: Any,
) -> None:
    """Apply mutable archive (remote) properties.

    Scalar columns (``url``, ``ext_url``, ``api``, ``comment``) arrive in
    ``**kw`` and are forwarded to :meth:`Base.apply`; the CLI leaf
    translates a lone ``-`` to ``None`` for the nullable ones.

    Args:
        role: :class:`ArchiveRole` name. Required on create; immutable
            thereafter (renaming raises).
        default: Mark this archive the SPKG's default. Setting ``True`` clears
            ``default`` on sibling archives of the same SPKG (single-default
            invariant). ``False`` just unsets.
        **kw: Scalar columns (``url``, ``ext_url``, ``api``, ``comment``)
            forwarded to :meth:`Base.apply`.

    Raises:
        ValueError: if ``role`` is missing on create, renamed later, or
            ``url`` is missing on create.
    """
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if role is not NotGiven:
            if role is None:
                raise ValueError("Archives need a role")
            if self.archiverole is None:
                self.archiverole = sess.one(ArchiveRole, name=role)
            elif self.archiverole.name != role:
                raise ValueError("Archive roles cannot be changed")
        elif self.archiverole is None and self.id is None:
            raise ValueError("New archives need a role")

        if self.id is None and not self.url:
            raise ValueError("New archives need a url")

        if default is not NotGiven:
            if default:
                for other in self.spkg.archives:
                    if other is not self:
                        other.default = False
            self.default = bool(default)


Archive.apply = cast(Any, archive_apply)


def localbranch_apply(
    self,
    *,
    role: Any = NotGiven,
    status: Any = NotGiven,
    commit: Any = NotGiven,
    **kw: Any,
) -> None:
    """Apply mutable local-branch properties.

    ``status`` and ``commit`` are scalar columns but are intercepted here
    (rather than left in ``**kw``) so that an actual change — including
    clearing — stamps :attr:`updated`.

    Args:
        role: :class:`BranchRole` name, or ``None``/``"-"`` to clear the
            nullable role link.
        status: Free-text status (pre-parsed by the CLI leaf: ``@file``
            reads a file, ``-`` clears to ``None``). Stamps :attr:`updated`
            on any change.
        commit: Pinned tip SHA, or ``None``/``"-"`` to clear. Also stamps
            :attr:`updated` on change.
        **kw: Other scalar columns forwarded to :meth:`Base.apply`.
    """
    sess = session.get()
    with sess.no_autoflush:
        changed = False
        if status is not NotGiven and self.status != status:
            changed = True
        if commit is not NotGiven and self.commit != commit:
            changed = True

        fwd = dict(kw)
        if status is not NotGiven:
            fwd["status"] = status
        if commit is not NotGiven:
            fwd["commit"] = commit
        Base.apply(self, **fwd)

        if role is not NotGiven:
            if role is None or role == "-":
                self.branchrole = None
            else:
                self.branchrole = sess.one(BranchRole, name=role)

        if changed:
            self.updated = now()


LocalBranch.apply = cast(Any, localbranch_apply)
