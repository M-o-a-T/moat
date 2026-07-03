"""
Tests for ``moat.src.submodule``.
"""

from __future__ import annotations

from moat.src.submodule import EDIT_REMOTES, REMOTES, _is_http_url, _remote_urls
from moat.src.test import raises


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
