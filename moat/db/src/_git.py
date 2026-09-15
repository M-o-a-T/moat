"""Local-git interplay for moat.db.src: import / export (NOT moat.src).

Bridges the DB record and a local git working tree via plain ``git``
plumbing (subprocess). Deliberately narrower than the :mod:`moat.src`
forge-move stack: no authentication, no remote-repo creation, no
branch/tag deletion, no README rewriting. ``import`` touches no network;
``export`` only clones the default archive's URL.

See ``docs/moat-db-src/PLAN.md`` §4a for the design.
"""

from __future__ import annotations

import re
import shutil
import sys

import asyncclick as click

from moat.db.util import session
from moat.util.exec import DetailedCalledProcessError, run

from .model import Archive, ArchiveRole, LocalBranch, Spkg

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

# Known ``api`` guesses, keyed by a substring of the remote URL. Order
# matters: the first match wins. Anything unmatched falls back to
# ``localgit``.
_API_HINTS: tuple[tuple[str, str], ...] = (
    ("github.com", "github"),
    ("codeberg.org", "forgejo"),
    ("/rad:", "radicle"),
    ("rad://", "radicle"),
)


def guess_api(url: str) -> str:
    """Guess an ``api`` token from a remote URL's scheme/host.

    Returns one of ``github``/``forgejo``/``radicle``/``localgit``. The
    result is advisory — overridable later via ``remote set --api``.
    """
    for needle, api in _API_HINTS:
        if needle in url:
            return api
    return "localgit"


async def _git(repo: str | Path, *args: str, capture: bool = True) -> str:
    """Run ``git`` in ``repo`` and return trimmed stdout.

    Raises:
        moat.util.exec.DetailedCalledProcessError: on a nonzero exit.
    """
    out = await run("git", "-C", str(repo), *args, capture=capture)
    return out.strip() if isinstance(out, str) else out.decode().strip()


async def _git_lines(repo: str | Path, *args: str) -> list[str]:
    """Run ``git`` in ``repo`` and return stdout split into non-empty lines."""
    out = await _git(repo, *args)
    return [ln for ln in out.splitlines() if ln]


_REMOTE_VLINE = re.compile(r"^(\S+)\s+(\S+)\s+\((fetch|push)\)$")


async def discover_remotes(repo: str | Path) -> dict[str, dict[str, str]]:
    """Return ``{remote_name: {"fetch": url, "push": url|""}}`` for ``repo``.

    A remote with no configured push URL shares its fetch URL per git's
    convention, but for role-heuristic purposes we distinguish "no
    *separate* push" from "push==fetch": the dict stores the raw push
    line value (``""`` if absent). Callers treating fetch-only as
    "fork" should check ``push == ""``.
    """
    lines = await _git_lines(repo, "remote", "-v")
    remotes: dict[str, dict[str, str]] = {}
    for ln in lines:
        m = _REMOTE_VLINE.match(ln)
        if m is None:
            continue
        name, url, kind = m.group(1), m.group(2), m.group(3)
        slot = remotes.setdefault(name, {"fetch": "", "push": ""})
        slot[kind] = url
    return remotes


async def discover_branches(repo: str | Path) -> list[tuple[str, str]]:
    """Return ``[(branch_name, tip_sha)]`` for local branches of ``repo``."""
    lines = await _git_lines(
        repo, "for-each-ref", "--format=%(refname:short)%09%(objectname)", "refs/heads/"
    )
    out = []
    for ln in lines:
        name, _, sha = ln.partition("\t")
        out.append((name, sha))
    return out


async def resolve_role(
    remote_name: str,
    has_push: bool,
    iroles: dict[str, str],
    imirrors: set[str],
    repo: str | Path,
) -> str:
    """Resolve an :class:`ArchiveRole` name for a git remote (three-tier).

    Precedence (highest wins):

    1. CLI override ``iroles[remote_name]``.
    2. Git config ``moat.src.roles.<remote_name>``.
    3. Heuristic: ``origin``/``upstream`` ⇒ ``upstream``; no push URL
       (fetch-only) ⇒ ``fork``; push-capable + ``--mirror`` ⇒ ``mirror``;
       else ``local``.

    ``has_push`` is True iff the remote has any configured push URL
    (whether or not it equals the fetch URL).
    """
    if remote_name in iroles:
        return iroles[remote_name]
    try:
        cfg = await _git(repo, "config", "--get", f"moat.src.roles.{remote_name}")
    except DetailedCalledProcessError:
        cfg = ""
    if cfg:
        return cfg
    if remote_name in ("origin", "upstream"):
        return "upstream"
    if not has_push:
        return "fork"
    if remote_name in imirrors:
        return "mirror"
    return "local"


def _validate_role(sess: Any, role: str) -> ArchiveRole:
    """Look up an :class:`ArchiveRole` by name or raise a clean error."""
    try:
        return sess.one(ArchiveRole, name=role)
    except KeyError:
        raise click.UsageError(
            f"Unknown archive role {role!r}. Add it with 'moat db src archive add {role}'."
        ) from None


def _pick_default_remote(names: list[str]) -> str | None:
    """Choose the default remote: ``origin`` if present, else alphabetical first."""
    if not names:
        return None
    if "origin" in names:
        return "origin"
    return sorted(names)[0]


async def import_repo(
    sp: Spkg,
    path: str | Path,
    *,
    iroles: tuple[str, ...] = (),
    imirrors: tuple[str, ...] = (),
) -> None:
    """Discover remotes/branches in ``path`` and upsert them onto ``sp``.

    Used by both the top-level ``import`` (bootstrapping a new SPKG) and
    the ``at SPKG import`` re-sync. Preserves DB-only
    ``LocalBranch.status``/``role`` and ``Archive.comment`` across re-sync
    (comment resets only if the URL changed). Vanished remotes/branches
    are reported, not deleted.
    """
    sess = session.get()
    role_overrides = {}
    for pair in iroles:
        rn, _, rol = pair.partition("=")
        if not rol:
            raise click.UsageError(f"--role needs REMOTE=ROLE, got {pair!r}")
        role_overrides[rn] = rol
    mirror_set = set(imirrors)

    remotes = await discover_remotes(path)
    branches = await discover_branches(path)

    # Upsert remotes → Archive.
    existing_archives = {a.name: a for a in sp.archives}
    default_name = _pick_default_remote(list(remotes))
    for rn, urls in sorted(remotes.items()):
        has_push = bool(urls["push"])
        role = await resolve_role(rn, has_push, role_overrides, mirror_set, path)
        _validate_role(sess, role)  # raises cleanly if the role is unknown
        url = urls["fetch"] or urls["push"]
        ar = existing_archives.get(rn)
        if ar is None:
            ar = Archive(name=rn, spkg=sp)
            sess.add(ar)
            ar.apply(role=role, url=url, api=guess_api(url), default=(rn == default_name))
        else:
            url_changed = ar.url != url
            kw: dict[str, Any] = {"role": role, "url": url, "api": guess_api(url)}
            if url_changed:
                kw["comment"] = None  # old comment no longer applies
            if rn == default_name and not any(o.default for o in sp.archives if o is not ar):
                kw["default"] = True
            ar.apply(**kw)

    # Report (don't delete) vanished remotes.
    vanished_re = sorted(set(existing_archives) - set(remotes))
    for rn in vanished_re:
        print(
            f"Note: remote {rn!r} is in the DB but not in the repo; keeping. "
            f"(Use 'moat db src at {sp.name} remote delete {rn}' to remove.)",
            file=sys.stderr,
        )

    # Upsert branches → LocalBranch.
    existing_branches = {b.name: b for b in sp.branches}
    for bn, sha in branches:
        br = existing_branches.get(bn)
        if br is None:
            br = LocalBranch(name=bn, spkg=sp)
            sess.add(br)
            br.apply(commit=sha)
        else:
            if br.commit != sha:
                br.apply(commit=sha)

    vanished_br = sorted(set(existing_branches) - set(dict(branches)))
    for bn in vanished_br:
        print(
            f"Note: branch {bn!r} is in the DB but not in the repo; keeping. "
            f"(Use 'moat db src at {sp.name} branch delete {bn}' to remove.)",
            file=sys.stderr,
        )


async def _dest_safe(dest: str | Path, force: bool) -> None:
    """Refuse a non-empty or dirty-git ``dest`` for export.

    Raises:
        click.UsageError: if ``dest`` is unsuitable.
    """
    from anyio import Path as APath  # noqa: PLC0415

    dp = APath(dest)
    if not await dp.exists():
        return
    if not await dp.is_dir():
        raise click.UsageError(f"Destination {str(dest)!r} exists and is not a directory.")
    entries = [p async for p in dp.iterdir()]
    if not entries:
        return
    if not force:
        raise click.UsageError(
            f"Destination {str(dest)!r} is not empty. Use --force to overwrite."
        )
    # Non-empty + --force: still refuse if it's a dirty git worktree.
    if await (dp / ".git").is_dir():
        out = await run("git", "-C", str(dest), "status", "--porcelain", capture=True)
        dirty = out.strip() if isinstance(out, str) else out.decode().strip()
        if dirty:
            raise click.UsageError(
                f"Destination {str(dest)!r} is a git worktree with uncommitted changes."
            )
        shutil.rmtree(dest)


async def export_repo(
    sp: Spkg,
    dest: str | Path,
    *,
    bare: bool = False,
    force: bool = False,
) -> None:
    """Materialise a repo at ``dest`` from the DB record of ``sp``.

    Clones the SPKG's default archive, adds the other remotes, and
    restores local branches (from the cloned default's refs, or from a
    recorded ``commit``). Refuses a non-empty/dirty ``dest``.
    """
    default = next((a for a in sp.archives if a.default), None)
    if default is None:
        raise click.UsageError(
            f"Source package {sp.name!r} has no default remote. "
            f"Set one with 'moat db src at {sp.name} remote set NAME --default'."
        )

    await _dest_safe(dest, force)

    clone_args = ["git", "clone"]
    if bare:
        clone_args.append("--bare")
    clone_args += [default.url, str(dest)]
    await run(*clone_args, capture=False)

    # Wire up the other remotes.
    others = [a for a in sp.archives if a is not default]
    for ar in sorted(others, key=lambda a: a.name):
        await run("git", "-C", str(dest), "remote", "add", ar.name, ar.url, capture=False)

    # Restore local branches (skip any the clone already created).
    existing_local = set(
        await _git_lines(dest, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    )
    for br in sorted(sp.branches, key=lambda b: b.name):
        if br.name in existing_local:
            continue
        ref = f"refs/remotes/{default.name}/{br.name}"
        try:
            sha = await _git(dest, "rev-parse", "--verify", "--quiet", ref)
        except DetailedCalledProcessError:
            sha = ""
        if sha:
            await run("git", "-C", str(dest), "branch", br.name, sha, capture=False)
        elif br.commit:
            # The recorded commit may not be present in the clone (e.g. the
            # default archive is a bare repo that was never pushed to). Treat
            # branch creation as best-effort: warn and skip on failure.
            try:
                await run("git", "-C", str(dest), "branch", br.name, br.commit, capture=False)
            except DetailedCalledProcessError:
                print(
                    f"Warning: branch {br.name!r} commit {br.commit!r} is not "
                    f"reachable in the cloned {default.name!r}; skipping.",
                    file=sys.stderr,
                )
        else:
            print(
                f"Warning: branch {br.name!r} has neither a ref on "
                f"{default.name!r} nor a recorded commit; skipping.",
                file=sys.stderr,
            )
