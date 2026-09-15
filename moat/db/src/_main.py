"""Command-line interface for moat.db.src — source-package archive tracking.

Grammar (see ``docs/moat-db-src/PLAN.md``)::

    moat db src                          # list SPKGs
    moat db src list
    moat db src add SPKG [--comment …] [--prefix …]
    moat db src archive …                # global ArchiveRole registry
    moat db src branch …                 # global BranchRole registry
    moat db src at SPKG …                # per-SPKG scope
    moat db src import PATH --name SPKG  # bootstrap (local-git round trip)
    moat db src at SPKG import [PATH]     # re-sync
    moat db src at SPKG export --dest …   # materialise

Under ``at SPKG``: ``list`` (detail), ``set``, ``delete``, ``remote …``,
``branch …``, ``import``, ``export``.
"""

from __future__ import annotations

import sys

import asyncclick as click
from sqlalchemy import select

from moat.util import NotGiven, yprint
from moat.db import database
from moat.lib.run import load_subgroup, option_ng

from .model import Archive, ArchiveRole, BranchRole, LocalBranch, Spkg


@load_subgroup(
    sub_pre="moat.db.src",
    sub_post="cli",
    ext_pre="moat.db.src",
    ext_post="_main.cli",
    invoke_without_command=True,
)
@click.pass_context
async def cli(ctx):
    """Track source packages, their archive remotes, and local branches."""
    obj = ctx.obj
    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())
    obj.session = sess

    if ctx.invoked_subcommand is None:
        await _list_spkgs(obj)


# ---------------------------------------------------------------------------
# Top-level SPKG verbs
# ---------------------------------------------------------------------------


async def _list_spkgs(obj) -> None:
    """Print every SPKG name, one per line."""
    sess = obj.session
    seen = False
    with sess.execute(select(Spkg).order_by(Spkg.name)) as rows:
        for (sp,) in rows:
            seen = True
            print(sp.name, file=obj.stdout)
    if not seen:
        print("No source packages defined yet. Use '--help'?", file=sys.stderr)


@cli.command(name="list")
@click.pass_obj
async def list_(obj):
    """List all source packages."""
    await _list_spkgs(obj)


def _spkg_common(c):
    c = option_ng("--comment", "-c", "comment", type=str, help="Free-text description")(c)
    c = option_ng("--prefix", type=str, help="Token for Beads issue targeting")(c)
    return c


@cli.command(name="add")
@_spkg_common
@click.argument("name", type=str)
@click.pass_obj
async def add(obj, name, **kw):
    """Create a new source package (SPKG).

    Refuses if a package with this name already exists.
    """
    try:
        obj.session.one(Spkg, name=name)
    except KeyError:
        pass
    else:
        raise click.UsageError(f"Source package {name!r} already exists") from None

    sp = Spkg(name=name)
    obj.session.add(sp)
    sp.apply(**kw)


@cli.command(name="import")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--name",
    "iname",
    type=str,
    default=None,
    help="SPKG name (inferred from repo basename if omitted)",
)
@_spkg_common
@click.option(
    "--role",
    "iroles",
    type=str,
    multiple=True,
    metavar="REMOTE=ROLE",
    help="Force the role of git remote REMOTE to ROLE (repeatable)",
)
@click.option(
    "--mirror",
    "imirrors",
    type=str,
    multiple=True,
    metavar="REMOTE",
    help="Mark push-capable remote REMOTE as 'mirror' rather than 'local'",
)
@click.pass_obj
async def import_top(obj, path, iname, iroles, imirrors, **kw):
    """Bootstrap a NEW source package from an existing local git repo.

    Discovers remotes and branches via git plumbing (no network) and
    populates the DB record. Refuses if the SPKG already exists — use
    ``moat db src at SPKG import`` to re-sync instead.
    """
    from ._git import import_repo  # noqa: PLC0415

    if iname is None:
        from pathlib import Path  # noqa: PLC0415

        iname = Path(path).name
    try:
        obj.session.one(Spkg, name=iname)
    except KeyError:
        pass
    else:
        raise click.UsageError(
            f"Source package {iname!r} already exists. "
            f"Use 'moat db src at {iname} import' to re-sync."
        )

    sp = Spkg(name=iname)
    obj.session.add(sp)
    sp.apply(**kw)
    await import_repo(sp, path, iroles=iroles, imirrors=imirrors)


# ---------------------------------------------------------------------------
# Global registry: ArchiveRole (the `archive` group)
# ---------------------------------------------------------------------------


@cli.group(name="archive")
def archive_grp():
    """Manage the global archive-role registry."""


def _archive_role_common(c):
    c = option_ng("--comment", "-c", "comment", type=str, help="Free-text description")(c)
    c = option_ng("--rank", type=int, help="Display order, lower=earlier")(c)
    return c


@archive_grp.command(name="list")
@click.pass_obj
async def archive_list(obj):
    """List all archive roles."""
    sess = obj.session
    seen = False
    with sess.execute(select(ArchiveRole).order_by(ArchiveRole.rank, ArchiveRole.name)) as rows:
        for (ar,) in rows:
            seen = True
            print(ar.name, file=obj.stdout)
    if not seen:
        print("No archive roles defined yet. Use '--help'?", file=sys.stderr)


@archive_grp.command(name="show")
@click.argument("name", type=str)
@click.pass_obj
async def archive_show(obj, name):
    """Show details of one archive role."""
    try:
        ar = obj.session.one(ArchiveRole, name=name)
    except KeyError:
        raise click.UsageError(f"Archive role {name!r} doesn't exist") from None
    yprint(ar.dump(), stream=obj.stdout)


@archive_grp.command(name="add")
@_archive_role_common
@click.argument("name", type=str)
@click.pass_obj
async def archive_add(obj, name, **kw):
    """Add an archive role."""
    try:
        obj.session.one(ArchiveRole, name=name)
    except KeyError:
        pass
    else:
        raise click.UsageError(f"Archive role {name!r} already exists") from None
    ar = ArchiveRole(name=name)
    obj.session.add(ar)
    ar.apply(**kw)


@archive_grp.command(name="set")
@_archive_role_common
@click.argument("name", type=str)
@click.pass_obj
async def archive_set(obj, name, **kw):
    """Modify an archive role."""
    try:
        ar = obj.session.one(ArchiveRole, name=name)
    except KeyError:
        raise click.UsageError(f"Archive role {name!r} doesn't exist") from None
    ar.apply(**kw)


@archive_grp.command(name="delete")
@click.argument("name", type=str)
@click.pass_obj
async def archive_delete(obj, name):
    """Remove an archive role."""
    try:
        ar = obj.session.one(ArchiveRole, name=name)
    except KeyError:
        raise click.UsageError(f"Archive role {name!r} doesn't exist") from None
    obj.session.delete(ar)


# ---------------------------------------------------------------------------
# Global registry: BranchRole (the `branch` group)
# ---------------------------------------------------------------------------


@cli.group(name="branch")
def branch_grp():
    """Manage the global branch-role registry."""


def _branch_role_common(c):
    c = option_ng("--comment", "-c", "comment", type=str, help="Free-text description")(c)
    c = option_ng("--abstract", is_flag=True, help="Mark as short-lived (not long-lived)")(c)
    c = option_ng("--real", is_flag=True, help="Mark as long-lived (clears --abstract)")(c)
    return c


@branch_grp.command(name="list")
@click.pass_obj
async def branch_list(obj):
    """List all branch roles."""
    sess = obj.session
    seen = False
    with sess.execute(select(BranchRole).order_by(BranchRole.name)) as rows:
        for (br,) in rows:
            seen = True
            print(br.name, file=obj.stdout)
    if not seen:
        print("No branch roles defined yet. Use '--help'?", file=sys.stderr)


@branch_grp.command(name="show")
@click.argument("name", type=str)
@click.pass_obj
async def branch_show(obj, name):
    """Show details of one branch role."""
    try:
        br = obj.session.one(BranchRole, name=name)
    except KeyError:
        raise click.UsageError(f"Branch role {name!r} doesn't exist") from None
    yprint(br.dump(), stream=obj.stdout)


@branch_grp.command(name="add")
@_branch_role_common
@click.argument("name", type=str)
@click.pass_obj
async def branch_add(obj, name, **kw):
    """Add a branch role."""
    try:
        obj.session.one(BranchRole, name=name)
    except KeyError:
        pass
    else:
        raise click.UsageError(f"Branch role {name!r} already exists") from None
    br = BranchRole(name=name)
    obj.session.add(br)
    br.apply(**kw)


@branch_grp.command(name="set")
@_branch_role_common
@click.argument("name", type=str)
@click.pass_obj
async def branch_set(obj, name, **kw):
    """Modify a branch role."""
    try:
        br = obj.session.one(BranchRole, name=name)
    except KeyError:
        raise click.UsageError(f"Branch role {name!r} doesn't exist") from None
    br.apply(**kw)


@branch_grp.command(name="delete")
@click.argument("name", type=str)
@click.pass_obj
async def branch_delete(obj, name):
    """Remove a branch role."""
    try:
        br = obj.session.one(BranchRole, name=name)
    except KeyError:
        raise click.UsageError(f"Branch role {name!r} doesn't exist") from None
    obj.session.delete(br)


# ---------------------------------------------------------------------------
# Per-SPKG scope: the `at SPKG` group
# ---------------------------------------------------------------------------


@cli.group(name="at", invoke_without_command=True)
@click.argument("spkg", type=str)
@click.pass_obj
async def at_grp(obj, spkg):
    """Scope subsequent verbs to one source package.

    Verifies the SPKG exists and stashes it on ``obj.spkg``. With no
    subcommand, shows the package detail.
    """
    try:
        obj.spkg = obj.session.one(Spkg, name=spkg)
    except KeyError:
        raise click.UsageError(
            f"Source package {spkg!r} doesn't exist. Use 'moat db src add {spkg}'."
        ) from None

    ctx = click.get_current_context()
    if ctx.invoked_subcommand is None:
        yprint(obj.spkg.dump(), stream=obj.stdout)


@at_grp.command(name="list")
@click.pass_obj
async def at_list(obj):
    """Show this source package's detail."""
    yprint(obj.spkg.dump(), stream=obj.stdout)


@at_grp.command(name="set")
@_spkg_common
@click.pass_obj
async def at_set(obj, **kw):
    """Modify this source package."""
    obj.spkg.apply(**kw)


@at_grp.command(name="delete")
@click.pass_obj
async def at_delete(obj):
    """Remove this source package (cascades to remotes and branches)."""
    obj.session.delete(obj.spkg)


@at_grp.command(name="import")
@click.argument("path", type=click.Path(exists=True, file_okay=False), default=".")
@click.option(
    "--role",
    "iroles",
    type=str,
    multiple=True,
    metavar="REMOTE=ROLE",
    help="Force the role of git remote REMOTE to ROLE (repeatable)",
)
@click.option(
    "--mirror",
    "imirrors",
    type=str,
    multiple=True,
    metavar="REMOTE",
    help="Mark push-capable remote REMOTE as 'mirror' rather than 'local'",
)
@click.pass_obj
async def at_import(obj, path, iroles, imirrors):
    """Re-sync THIS package from an existing local git repo.

    Updates remotes/branches to match the repo, preserving DB-only
    ``status``/``role``/``comment``. Reports (doesn't delete) vanished
    remotes/branches.
    """
    from ._git import import_repo  # noqa: PLC0415

    await import_repo(obj.spkg, path, iroles=iroles, imirrors=imirrors)


@at_grp.command(name="export")
@click.option(
    "--dest",
    type=click.Path(file_okay=False),
    required=True,
    help="Directory to clone into",
)
@click.option("--bare", is_flag=True, help="Clone a bare repository")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite a non-empty destination (still refuses dirty git trees)",
)
@click.pass_obj
async def at_export(obj, dest, bare, force):
    """Materialise a repo from this package's DB record.

    Clones the default remote, wires up the other remotes, and restores
    local branches. Refuses a non-empty or dirty destination.
    """
    from ._git import export_repo  # noqa: PLC0415

    await export_repo(obj.spkg, dest, bare=bare, force=force)


# ----- remotes (Archive) under `at SPKG` -----


@at_grp.group(name="remote")
def remote_grp():
    """Manage this package's archive remotes."""


def _parse_clearable(value, *, allow_dash=True):
    """Translate a CLI value per the ``--status``/``--ext-url`` convention.

    ``@file`` reads the rest as a file (``@-`` ⇒ stdin); a lone ``-`` ⇒
    ``None`` (clear); otherwise the literal string. ``NotGiven`` passes
    through unchanged.
    """
    if value is NotGiven or value is None:
        return value
    if allow_dash and value == "-":
        return None
    if value.startswith("@"):
        fname = value[1:]
        if fname == "-":
            return sys.stdin.read()
        with open(fname, "r") as fh:
            return fh.read()
    return value


def _remote_common(c):
    c = option_ng("--role", type=str, help="ArchiveRole name (immutable after create)")(c)
    c = option_ng("--url", type=str, help="Fetch URL")(c)
    c = option_ng("--ext-url", type=str, help="Human-facing web URL (- to clear)")(c)
    c = option_ng("--api", type=str, help="github|forgejo|radicle|localgit")(c)
    c = option_ng("--comment", "-c", "comment", type=str, help="Free-text description")(c)
    return c


@remote_grp.command(name="list")
@click.pass_obj
async def remote_list(obj):
    """List this package's remotes."""
    sp = obj.spkg
    seen = False
    for ar in sorted(sp.archives, key=lambda a: a.name):
        seen = True
        mark = "*" if ar.default else " "
        print(f"{mark} {ar.name}\t{ar.archiverole.name}\t{ar.url}", file=obj.stdout)
    if not seen:
        print("No remotes defined yet. Use '--help'?", file=sys.stderr)


@remote_grp.command(name="show")
@click.argument("name", type=str)
@click.pass_obj
async def remote_show(obj, name):
    """Show one remote of this package."""
    try:
        ar = obj.session.one(Archive, spkg=obj.spkg, name=name)
    except KeyError:
        raise click.UsageError(f"Remote {name!r} doesn't exist") from None
    yprint(ar.dump(), stream=obj.stdout)


@remote_grp.command(name="add")
@_remote_common
@click.option(
    "--default/--no-default",
    "default",
    default=None,
    help="Mark this the package's default remote",
)
@click.argument("name", type=str)
@click.pass_obj
async def remote_add(obj, name, default, **kw):
    """Add a remote (archive) to this package.

    ``--role`` and ``--url`` are required on create.
    """
    if kw.get("role") in (None, NotGiven):
        raise click.UsageError("New remotes need a role (--role NAME)") from None
    if kw.get("url") in (None, NotGiven):
        raise click.UsageError("New remotes need a url (--url URL)") from None
    try:
        obj.session.one(Archive, spkg=obj.spkg, name=name)
    except KeyError:
        pass
    else:
        raise click.UsageError(f"Remote {name!r} already exists") from None
    ar = Archive(name=name, spkg=obj.spkg)
    obj.session.add(ar)
    kw["ext_url"] = _parse_clearable(kw.get("ext_url", NotGiven))
    if default is not None:
        kw["default"] = default
    ar.apply(**kw)


@remote_grp.command(name="set")
@_remote_common
@click.option(
    "--default/--no-default",
    "default",
    default=None,
    help="Set/clear the package's default remote",
)
@click.argument("name", type=str)
@click.pass_obj
async def remote_set(obj, name, default, **kw):
    """Modify a remote of this package."""
    try:
        ar = obj.session.one(Archive, spkg=obj.spkg, name=name)
    except KeyError:
        raise click.UsageError(f"Remote {name!r} doesn't exist") from None
    kw["ext_url"] = _parse_clearable(kw.get("ext_url", NotGiven))
    if default is not None:
        kw["default"] = default
    ar.apply(**kw)


@remote_grp.command(name="delete")
@click.argument("name", type=str)
@click.pass_obj
async def remote_delete(obj, name):
    """Remove a remote from this package."""
    try:
        ar = obj.session.one(Archive, spkg=obj.spkg, name=name)
    except KeyError:
        raise click.UsageError(f"Remote {name!r} doesn't exist") from None
    obj.session.delete(ar)


# ----- local branches (LocalBranch) under `at SPKG` -----


@at_grp.group(name="branch")
def lb_grp():
    """Manage this package's local branches."""


def _branch_common(c):
    c = option_ng("--role", type=str, help="BranchRole name (- to clear)")(c)
    c = option_ng("--status", type=str, help="Free-text status (@file, - to clear)")(c)
    c = option_ng("--commit", type=str, help="Pinned tip sha (- to clear)")(c)
    return c


@lb_grp.command(name="list")
@click.pass_obj
async def lb_list(obj):
    """List this package's local branches."""
    sp = obj.spkg
    seen = False
    for br in sorted(sp.branches, key=lambda b: b.name):
        seen = True
        role = br.branchrole.name if br.branchrole is not None else "-"
        print(f"{br.name}\t{role}", file=obj.stdout)
    if not seen:
        print("No branches defined yet. Use '--help'?", file=sys.stderr)


@lb_grp.command(name="show")
@click.argument("name", type=str)
@click.pass_obj
async def lb_show(obj, name):
    """Show one local branch of this package."""
    try:
        br = obj.session.one(LocalBranch, spkg=obj.spkg, name=name)
    except KeyError:
        raise click.UsageError(f"Branch {name!r} doesn't exist") from None
    yprint(br.dump(), stream=obj.stdout)


@lb_grp.command(name="add")
@_branch_common
@click.argument("name", type=str)
@click.pass_obj
async def lb_add(obj, name, **kw):
    """Add a local branch to this package."""
    try:
        obj.session.one(LocalBranch, spkg=obj.spkg, name=name)
    except KeyError:
        pass
    else:
        raise click.UsageError(f"Branch {name!r} already exists") from None
    br = LocalBranch(name=name, spkg=obj.spkg)
    obj.session.add(br)
    kw["status"] = _parse_clearable(kw.get("status", NotGiven))
    kw["commit"] = _parse_clearable(kw.get("commit", NotGiven))
    br.apply(**kw)


@lb_grp.command(name="set")
@_branch_common
@click.argument("name", type=str)
@click.pass_obj
async def lb_set(obj, name, **kw):
    """Modify a local branch of this package."""
    try:
        br = obj.session.one(LocalBranch, spkg=obj.spkg, name=name)
    except KeyError:
        raise click.UsageError(f"Branch {name!r} doesn't exist") from None
    kw["status"] = _parse_clearable(kw.get("status", NotGiven))
    kw["commit"] = _parse_clearable(kw.get("commit", NotGiven))
    br.apply(**kw)


@lb_grp.command(name="delete")
@click.argument("name", type=str)
@click.pass_obj
async def lb_delete(obj, name):
    """Remove a local branch from this package."""
    try:
        br = obj.session.one(LocalBranch, spkg=obj.spkg, name=name)
    except KeyError:
        raise click.UsageError(f"Branch {name!r} doesn't exist") from None
    obj.session.delete(br)
