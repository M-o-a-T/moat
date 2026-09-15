"""Tests for the local-git ``import`` / ``export`` round trip (NOT moat.src)."""

from __future__ import annotations

import os
import subprocess

import asyncclick as click

from moat.src.test import raises as _raises


def _msg(err) -> str:
    """Lowercased message of a caught UsageError."""
    return str(err.value).lower()


def _clean_env() -> dict[str, str]:
    """A git env scrubbed of pre-commit's GIT_DIR/index/quarantine leakage.

    Pre-commit stages files with ``GIT_DIR``/``GIT_INDEX_FILE`` etc. pointing
    at the main repo's staging area; inheriting those would make throwaway
    test repos act on the wrong work tree. We drop every ``GIT_*`` var
    (author/committer identity is set explicitly by callers).
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(*a, **kw):
    """Run git synchronously, returning CompletedProcess-like result."""
    kw.setdefault("env", _clean_env())
    return subprocess.run(("git", *a), check=True, capture_output=True, text=True, **kw)


def _make_repo(parent, name, *, remotes=()):
    """Create a throwaway git repo with a commit and the given remotes.

    ``remotes`` is a list of (remote_name, fetch_url, push_url_or_None).
    Returns the repo path.
    """
    repo = parent / name
    repo.mkdir()
    env = {
        **_clean_env(),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(("git", "init", "-q"), cwd=repo, check=True, env=env)
    (repo / "README.md").write_text("hi\n")
    subprocess.run(("git", "add", "README.md"), cwd=repo, check=True, env=env)
    subprocess.run(("git", "commit", "-qm", "initial"), cwd=repo, check=True, env=env)
    for rn, fetch, push in remotes:
        subprocess.run(("git", "remote", "add", rn, fetch), cwd=repo, check=True, env=env)
        if push is not None:
            subprocess.run(
                ("git", "remote", "set-url", "--push", rn, push), cwd=repo, check=True, env=env
            )
    return repo


def _bare(parent, name):
    """Create a bare repo and return its path (string URL for cloning)."""
    p = parent / name
    p.mkdir()
    subprocess.run(("git", "init", "-q", "--bare"), cwd=p, check=True, env=_clean_env())
    return str(p)


async def test_toplevel_import_creates_spkg(src, seed_roles, tmp_path):  # noqa:ARG001
    """Bootstrapping import creates the SPKG + archives + branches."""
    origin = _bare(tmp_path, "origin.git")
    # Push a commit so the clone later has a ref.
    repo = _make_repo(tmp_path, "wk", remotes=[("origin", origin, None)])
    _git("-C", str(repo), "push", "-q", "origin", "main")

    await src("import", str(repo), "--name", "impkg", "--comment", "c")
    res = await src("at", "impkg")
    assert "impkg" in res.stdout
    # origin remote → upstream role, default
    res_rl = await src("at", "impkg", "remote", "list")
    assert "* origin\tupstream\t" in res_rl.stdout
    # main branch recorded
    res_bl = await src("at", "impkg", "branch", "list")
    assert "main" in res_bl.stdout


async def test_toplevel_import_refuses_existing(src, seed_roles, tmp_path):  # noqa:ARG001
    """Importing into an existing SPKG raises with a re-sync hint."""
    await src("add", "exists")
    repo = _make_repo(tmp_path, "wk2")
    with _raises(click.UsageError) as err:
        await src("import", str(repo), "--name", "exists")
    assert "import" in _msg(err)


async def test_resync_preserves_status_role_comment(src, seed_roles, tmp_path):  # noqa:ARG001
    """``at SPKG import`` re-syncs but keeps DB-only status/role/comment."""
    origin = _bare(tmp_path, "o2.git")
    repo = _make_repo(tmp_path, "wk3", remotes=[("origin", origin, None)])
    _git("-C", str(repo), "push", "-q", "origin", "main")

    await src("import", str(repo), "--name", "syn")
    await src("at", "syn", "branch", "set", "main", "--role", "main", "--status", "keep-me")
    await src("at", "syn", "remote", "set", "origin", "--comment", "saved-comment")

    # Re-sync.
    await src("at", "syn", "import", str(repo))
    res = await src("at", "syn", "branch", "show", "main")
    assert "keep-me" in res.stdout
    assert "main" in res.stdout  # role preserved
    res = await src("at", "syn", "remote", "show", "origin")
    assert "saved-comment" in res.stdout


async def test_role_resolution_cli_beats_heuristic(src, seed_roles, tmp_path):  # noqa:ARG001
    """``--role origin=fork`` overrides the origin→upstream heuristic."""
    origin = _bare(tmp_path, "o3.git")
    repo = _make_repo(tmp_path, "wk4", remotes=[("origin", origin, None)])
    _git("-C", str(repo), "push", "-q", "origin", "main")
    await src("import", str(repo), "--name", "ro1", "--role", "origin=fork")
    res = await src("at", "ro1", "remote", "list")
    assert "origin\tfork\t" in res.stdout


async def test_role_resolution_mirror_flag(src, seed_roles, tmp_path):  # noqa:ARG001
    """``--mirror NAME`` promotes a push-capable remote to 'mirror'."""
    a = _bare(tmp_path, "a.git")
    b = _bare(tmp_path, "b.git")
    repo = _make_repo(tmp_path, "wk5", remotes=[("origin", a, None), ("alt", b, None)])
    _git("-C", str(repo), "push", "-q", "origin", "main")
    await src("import", str(repo), "--name", "ro2", "--mirror", "alt")
    res = await src("at", "ro2", "remote", "list")
    assert "alt\tmirror\t" in res.stdout


async def test_role_resolution_git_config(src, seed_roles, tmp_path):  # noqa:ARG001
    """``moat.src.roles.<remote>`` git-config beats the heuristic."""
    origin = _bare(tmp_path, "o4.git")
    repo = _make_repo(tmp_path, "wk6", remotes=[("origin", origin, None)])
    _git("-C", str(repo), "config", "moat.src.roles.origin", "internal")
    _git("-C", str(repo), "push", "-q", "origin", "main")
    await src("import", str(repo), "--name", "ro3")
    res = await src("at", "ro3", "remote", "list")
    assert "origin\tinternal\t" in res.stdout


async def test_unmarked_push_capable_remote_is_local(src, seed_roles, tmp_path):  # noqa:ARG001
    """A push-capable remote (not origin/upstream, no --mirror) ⇒ 'local'.

    Git always synthesises a push URL equal to the fetch URL, so the
    'fetch-only ⇒ fork' branch of the heuristic is only reachable via an
    explicit empty push URL or a ``--role``/git-config override; the
    default for an ordinary extra remote is therefore 'local'.
    """
    origin = _bare(tmp_path, "lo.git")
    alt = _bare(tmp_path, "alt.git")
    repo = _make_repo(tmp_path, "wl", remotes=[("origin", origin, None), ("alt", alt, None)])
    _git("-C", str(repo), "push", "-q", "origin", "main")
    await src("import", str(repo), "--name", "ro4")
    res = await src("at", "ro4", "remote", "list")
    assert "alt	local\t" in res.stdout
    assert "* origin\tupstream\t" in res.stdout


async def test_export_materialises_topology(src, seed_roles, tmp_path):  # noqa:ARG001
    """Export clones the default, wires other remotes, restores branches."""
    origin = _bare(tmp_path, "ox.git")
    mirror = _bare(tmp_path, "mx.git")
    repo = _make_repo(
        tmp_path, "wkx", remotes=[("origin", origin, None), ("mirror", mirror, None)]
    )
    _git("-C", str(repo), "push", "-q", "origin", "main")
    _git("-C", str(repo), "push", "-q", "mirror", "main")

    await src("import", str(repo), "--name", "expkg", "--mirror", "mirror")
    dest = tmp_path / "exported"
    await src("at", "expkg", "export", "--dest", str(dest))

    remotes = subprocess.run(  # noqa: ASYNC221
        ("git", "-C", str(dest), "remote", "-v"),
        capture_output=True,
        text=True,
        check=True,
        env=_clean_env(),
    ).stdout
    assert "origin" in remotes
    assert "mirror" in remotes
    branches = subprocess.run(  # noqa: ASYNC221
        ("git", "-C", str(dest), "for-each-ref", "--format=%(refname:short)", "refs/heads/"),
        capture_output=True,
        text=True,
        check=True,
        env=_clean_env(),
    ).stdout
    assert "main" in branches


async def test_export_refuses_non_empty_dest(src, seed_roles, tmp_path):  # noqa:ARG001
    """Export refuses a non-empty destination."""
    origin = _bare(tmp_path, "oy.git")
    repo = _make_repo(tmp_path, "wky", remotes=[("origin", origin, None)])
    _git("-C", str(repo), "push", "-q", "origin", "main")
    await src("import", str(repo), "--name", "ex2")
    dest = tmp_path / "blocked"
    dest.mkdir()
    (dest / "blocker").write_text("x")
    with _raises(click.UsageError) as err:
        await src("at", "ex2", "export", "--dest", str(dest))
    assert "not empty" in _msg(err)
