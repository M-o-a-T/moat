"""SQLAlchemy declarations for the source-package archive schema.

All tables carry a ``src_`` prefix (overriding :class:`Base`'s
auto-lowercased ``__tablename__``) to stay tidy in the shared
:class:`~moat.db.schema.Base` metadata alongside the ``rain_*`` tables.

Relationships and the rich ``apply()`` overrides live in
:mod:`moat.db.src.model_` to break the import cycle between
:class:`Spkg`/:class:`Archive`/:class:`LocalBranch` and their role
registries, mirroring the ``box``/``thing``/``label`` layout.
Scalar-column ``apply()`` forwarding is inherited from
:meth:`Base.apply`.
"""

from __future__ import annotations

from datetime import datetime  # noqa:TC003  — SQLAlchemy resolves Mapped[datetime] at runtime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from moat.db.schema import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class Spkg(Base):
    """A named source package backed by one or more git archives.

    The anchor entity of this schema: :class:`Archive` remotes and
    :class:`LocalBranch` records hang off it. ``prefix`` carries an
    optional short token used to target this package in the Beads issue
    tracker.
    """

    __tablename__ = "src_spkg"

    name: Mapped[str] = mapped_column(unique=True, type_=String(60))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    prefix: Mapped[str | None] = mapped_column(
        type_=String(20), nullable=True, comment="Token for Beads issue targeting"
    )

    if TYPE_CHECKING:
        archives: set[Archive]
        branches: set[LocalBranch]

    def dump(self) -> dict[str, Any]:
        """Detail dump: scalars, then nested archives and branches."""
        res = super().dump()
        if self.archives:
            res["archives"] = [
                {
                    "role": ar.archiverole.name,
                    "name": ar.name,
                    "url": ar.url,
                    "default": ar.default,
                }
                for ar in sorted(self.archives, key=lambda a: a.name)
            ]
        if self.branches:
            res["branches"] = [
                {
                    "name": br.name,
                    "role": br.branchrole.name if br.branchrole is not None else None,
                    "status": br.status,
                    "updated": br.updated,
                    "commit": br.commit,
                }
                for br in sorted(self.branches, key=lambda b: b.name)
            ]
        return res


class ArchiveRole(Base):
    """A named role classifying a source archive (global registry).

    E.g. ``upstream``, ``mirror``, ``fork``, ``local``, ``internal``.
    """

    __tablename__ = "src_archive_role"

    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    rank: Mapped[int | None] = mapped_column(
        type_=Integer, nullable=True, comment="Display order, lower=earlier"
    )

    if TYPE_CHECKING:
        archives: set[Archive]

    def dump(self) -> dict[str, Any]:
        """Registry dump: scalars plus the count of archives using this role."""
        res = super().dump()
        res["count"] = len(self.archives)
        return res


class BranchRole(Base):
    """A named role classifying a local branch (global registry).

    E.g. ``main``, ``release``, ``develop``, ``feature``. ``abstract``
    marks short-lived roles (``feature``) versus long-lived ones.
    """

    __tablename__ = "src_branch_role"

    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    abstract: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="0",
        comment="True ⇒ not a long-lived role",
    )

    if TYPE_CHECKING:
        branches: set[LocalBranch]

    def dump(self) -> dict[str, Any]:
        """Registry dump: scalars plus the count of branches using this role."""
        res = super().dump()
        res["count"] = len(self.branches)
        return res


class Archive(Base):
    """One known archive (git remote) of a :class:`Spkg`.

    Exposed via the ``remote`` verb under ``at SPKG``. Exactly one
    archive per SPKG may carry ``default=True`` (enforced in
    :func:`archive_apply`, not by a DB constraint).
    """

    __tablename__ = "src_archive"
    __table_args__ = (UniqueConstraint("spkg_id", "name", name="uq_archive_spkg_name"),)

    spkg_id: Mapped[int] = mapped_column(
        ForeignKey("src_spkg.id", name="fk_archive_spkg", ondelete="CASCADE"),
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("src_archive_role.id", name="fk_archive_role"),
    )
    name: Mapped[str] = mapped_column(type_=String(40), comment="Label: github/codeberg/…")
    url: Mapped[str] = mapped_column(type_=String(200))
    ext_url: Mapped[str | None] = mapped_column(
        type_=String(200), nullable=True, comment="Human-facing web URL"
    )
    api: Mapped[str | None] = mapped_column(
        type_=String(40), nullable=True, comment="github|forgejo|radicle|localgit"
    )
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    default: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="0",
        comment="≤1 TRUE per spkg (enforced in code)",
    )

    if TYPE_CHECKING:
        spkg: Spkg
        archiverole: ArchiveRole

    def dump(self) -> dict[str, Any]:
        """Remote dump: role name plus scalars."""
        res = super().dump()
        res.pop("default", None)
        res["default"] = self.default
        res["role"] = self.archiverole.name
        # reorder for readability: role, name, url, ext_url, api, default, comment
        ordered: dict[str, Any] = {}
        for k in ("role", "name", "url", "ext_url", "api", "default", "comment"):
            if k in res:
                ordered[k] = res.pop(k)
        ordered.update(res)
        return ordered


class LocalBranch(Base):
    """One local branch of a :class:`Spkg` with free-text status.

    Exposed via the ``branch`` verb under ``at SPKG``. ``status`` is
    DB-only free text (possibly long); ``commit`` pins a tip SHA;
    ``updated`` is stamped whenever ``status`` or ``commit`` changes.
    """

    __tablename__ = "src_branch"
    __table_args__ = (UniqueConstraint("spkg_id", "name", name="uq_branch_spkg_name"),)

    spkg_id: Mapped[int] = mapped_column(
        ForeignKey("src_spkg.id", name="fk_branch_spkg", ondelete="CASCADE"),
    )
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("src_branch_role.id", name="fk_branch_role"), nullable=True
    )
    name: Mapped[str] = mapped_column(type_=String(80))
    status: Mapped[str | None] = mapped_column(type_=Text, nullable=True)
    commit: Mapped[str | None] = mapped_column(
        type_=String(64), nullable=True, comment="Pinned sha (40/64 chars)"
    )
    updated: Mapped[datetime | None] = mapped_column(
        type_=DateTime, nullable=True, comment="Stamped on status/commit change"
    )

    if TYPE_CHECKING:
        spkg: Spkg
        branchrole: BranchRole | None

    def dump(self) -> dict[str, Any]:
        """Branch dump: name, role, status, updated, commit."""
        res = super().dump()
        res["role"] = self.branchrole.name if self.branchrole is not None else None
        ordered: dict[str, Any] = {}
        for k in ("name", "role", "status", "updated", "commit"):
            if k in res:
                ordered[k] = res.pop(k)
        ordered.update(res)
        return ordered
