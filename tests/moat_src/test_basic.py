"""
Tests for ``moat.src.submodule``.
"""

from __future__ import annotations

import anyio
import subprocess

from moat.src.submodule import (
    EDIT_REMOTES,
    REMOTES,
    _config_get,
    _https_to_ssh,
    _immediate_submodule_paths,
    _is_http_url,
    _maybe_ssh_upgrade,
    _prefer_ssh,
    _remote_urls,
)
from moat.src.test import raises


def _git(*args: str) -> None:
    """Run ``git`` synchronously for test setup."""
    subprocess.run(["git", *args], check=True, capture_output=True)


def test_nothing():
    """
    Empty test
    """
    pass  # pylint: disable=unnecessary-pass
    with raises(SyntaxError):
        raise SyntaxError("foo")


def test_remote_urls_read_default():
    """Default mode produces read-only HTTPS URLs and skips unknown keys."""
    info = {
        "github": "M-o-a-T/micropython.git",
        "rev": "fa6f764ff40b262081f897d09c867d8ac93463ca",
        "comment": "ignored",
    }
    assert _remote_urls(info) == [("github", "https://github.com/M-o-a-T/micropython.git")]
    # Non-remote keys (only 'rev') yield no candidates.
    assert _remote_urls({"rev": "abc"}) == []


def test_remote_urls_edit_uses_ssh_table():
    """Edit mode swaps in :data:`EDIT_REMOTES` for SSH-style URLs."""
    info = {"github": "M-o-a-T/micropython.git"}
    assert _remote_urls(info, edit=True) == [
        ("github", "git@github.com:M-o-a-T/micropython.git"),
    ]


def test_remote_urls_edit_skips_http():
    """Edit mode skips http(s) URLs, e.g. a passthrough ``url`` key."""
    assert _remote_urls({"url": "https://github.com/M-o-a-T/micropython.git"}, edit=True) == []
    assert _remote_urls({"url": "http://example.com/foo.git"}, edit=True) == []
    # Uppercase scheme is still detected as http(s).
    assert _remote_urls({"url": "HTTPS://example.com/foo.git"}, edit=True) == []


def test_remote_urls_edit_skips_http_keeps_ssh():
    """Edit mode drops http(s) candidates but keeps pushable ones."""
    info = {
        "url": "https://github.com/M-o-a-T/micropython.git",
        "github": "M-o-a-T/micropython.git",
    }
    assert _remote_urls(info, edit=True) == [
        ("github", "git@github.com:M-o-a-T/micropython.git"),
    ]


def test_remote_urls_edit_accepts_explicit_ssh():
    """An explicit SSH ``url`` is accepted in edit mode."""
    info = {"url": "git@github.com:M-o-a-T/micropython.git"}
    assert _remote_urls(info, edit=True) == [("url", "git@github.com:M-o-a-T/micropython.git")]
    info = {"url": "ssh://git@github.com/M-o-a-T/micropython.git"}
    assert _remote_urls(info, edit=True) == [
        ("url", "ssh://git@github.com/M-o-a-T/micropython.git"),
    ]


def test_remote_urls_read_allows_http():
    """Non-edit mode happily returns http(s) URLs (read-only fetch)."""
    info = {"url": "https://github.com/M-o-a-T/micropython.git"}
    assert _remote_urls(info) == [("url", "https://github.com/M-o-a-T/micropython.git")]


def test_is_http_url():
    """:func:`_is_http_url` recognises http(s) schemes and ignores others."""
    assert _is_http_url("https://github.com/foo/bar.git")
    assert _is_http_url("http://example.com/foo.git")
    assert not _is_http_url("git@github.com:foo/bar.git")
    assert not _is_http_url("ssh://git@github.com/foo/bar.git")


def test_edit_remotes_table():
    """:data:`EDIT_REMOTES` mirrors :data:`REMOTES` keys but yields SSH URLs."""
    assert set(EDIT_REMOTES) == set(REMOTES)
    assert EDIT_REMOTES["github"]("M-o-a-T/foo.git") == "git@github.com:M-o-a-T/foo.git"
    # 'url' is passthrough in both tables.
    assert EDIT_REMOTES["url"]("ssh://x/y.git") == "ssh://x/y.git"


def test_https_to_ssh():
    """:func:`_https_to_ssh` rewrites HTTP(S) URLs to ``ssh://git@…``."""
    assert _https_to_ssh("https://github.com/M-o-a-T/micropython.git") == (
        "ssh://git@github.com/M-o-a-T/micropython.git"
    )
    assert _https_to_ssh("http://example.com/foo/bar.git") == "ssh://git@example.com/foo/bar.git"
    # A port is preserved; embedded user info is replaced by ``git``.
    assert _https_to_ssh("https://alice@git.example.com:2222/x/y.git") == (
        "ssh://git@git.example.com:2222/x/y.git"
    )
    # Non-HTTP(S) URLs are not converted.
    assert _https_to_ssh("git@github.com:foo/bar.git") is None
    assert _https_to_ssh("ssh://git@github.com/foo/bar.git") is None


def test_prefer_ssh_prepends_ssh_before_https():
    """Each HTTP(S) candidate gains an SSH predecessor."""
    assert _prefer_ssh([("github", "https://github.com/M-o-a-T/foo.git")]) == [
        ("github", "ssh://git@github.com/M-o-a-T/foo.git"),
        ("github", "https://github.com/M-o-a-T/foo.git"),
    ]


def test_prefer_ssh_leaves_non_http_alone():
    """Already-SSH or other non-HTTP candidates are returned unchanged."""
    assert _prefer_ssh([("url", "git@github.com:M-o-a-T/foo.git")]) == [
        ("url", "git@github.com:M-o-a-T/foo.git"),
    ]
    assert _prefer_ssh([("url", "ssh://git@github.com/M-o-a-T/foo.git")]) == [
        ("url", "ssh://git@github.com/M-o-a-T/foo.git"),
    ]


async def test_immediate_submodule_paths_reads_gitmodules(tmp_path):
    """:func:`_immediate_submodule_paths` parses ``.gitmodules`` via git config."""
    (tmp_path / ".gitmodules").write_text(
        '[submodule "a"]\n\tpath = lib/a\n\turl = https://x/a.git\n'
        '[submodule "my sub"]\n\tpath = sub dir/b\n\turl = https://x/b.git\n',
        encoding="utf-8",
    )
    paths = await _immediate_submodule_paths(anyio.Path(tmp_path))
    assert sorted(paths) == ["lib/a", "sub dir/b"]


async def test_immediate_submodule_paths_no_gitmodules(tmp_path):
    """No ``.gitmodules`` → empty list (no error)."""
    assert await _immediate_submodule_paths(anyio.Path(tmp_path)) == []


async def test_maybe_ssh_upgrade_skips_when_no_ssh_set(tmp_path):
    """``moat.no-ssh=true`` suppresses probing; the URL is left untouched."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git("init", "-q", str(repo))
    _git("-C", str(repo), "config", "moat.no-ssh", "true")
    _git("-C", str(repo), "config", "remote.origin.url", "https://github.com/x/y.git")

    await _maybe_ssh_upgrade(anyio.Path(repo), "r")

    assert await _config_get(anyio.Path(repo), "remote.origin.url") == "https://github.com/x/y.git"


async def test_maybe_ssh_upgrade_skips_non_http_origin(tmp_path):
    """A non-HTTP origin URL is left as-is and ``moat.no-ssh`` is not set."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git("init", "-q", str(repo))
    _git("-C", str(repo), "config", "remote.origin.url", "file:///tmp/x.git")

    await _maybe_ssh_upgrade(anyio.Path(repo), "r")

    assert await _config_get(anyio.Path(repo), "remote.origin.url") == "file:///tmp/x.git"
    assert await _config_get(anyio.Path(repo), "moat.no-ssh") is None


async def test_maybe_ssh_upgrade_skips_when_no_origin(tmp_path):
    """A repo with no ``origin`` remote is left untouched."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git("init", "-q", str(repo))

    await _maybe_ssh_upgrade(anyio.Path(repo), "r")

    assert await _config_get(anyio.Path(repo), "remote.origin.url") is None
    assert await _config_get(anyio.Path(repo), "moat.no-ssh") is None
