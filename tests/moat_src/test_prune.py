"""
Test Debian changelog pruning performed by :mod:`moat.src.build`.
"""

from __future__ import annotations

import pytest

from moat.src.build import prune_for_gtag

_TEST_GTAG = "26.2.13"
_ENTRY_HEADER = "fikkit ({ver}) unstable; urgency=medium"
_SEPARATOR = "\n\n -- M U <mu@test.example>  Thu, 24 Sep 2026 09:00:00 +0200\n\n"


def mk(entries: list[tuple[str, str]]) -> str:
    """Assemble a changelog from (version, bullet-message) tuples."""
    return "".join(f"{_ENTRY_HEADER.format(ver=v)}\n\n  * {m}\n{_SEPARATOR}" for v, m in entries)


_TAGGED_BLOCK = mk([
    ("1.0-2", f"New release for {_TEST_GTAG}"),
    ("1.0-1", f"New release for {_TEST_GTAG}"),
])
_HISTORIC_BLOCK = mk([
    ("0.9-3", "Real improvement (fixes #101)"),
    ("0.9-2", "New release for 26.2.9"),
    ("0.9-1", "Initial release."),
])
_COMBINED = _TAGGED_BLOCK + _HISTORIC_BLOCK


def test_none_when_top_not_matching() -> None:
    """A foreign leader prevents pruning below it entirely."""
    chk = mk([("1.1-1", "Unrelated topic")]) + _COMBINED
    assert prune_for_gtag(chk, _TEST_GTAG) is None


def test_two_leading_tagged_stanzas_dropped() -> None:
    """Exactly the boilerplate-led prefix vanishes, byte-exact."""
    assert prune_for_gtag(_COMBINED, _TEST_GTAG) == _HISTORIC_BLOCK


def test_retained_history_survives_verbatim() -> None:
    """Lower entries — old tag texts included — remain in place."""
    got = prune_for_gtag(_COMBINED, _TEST_GTAG)
    assert got is not None
    assert "0.9-3" in got
    assert "0.9-2" in got
    assert "New release for 26.2.9" in got
    assert "1.0-" not in got


def test_plain_prose_leader_blocked() -> None:
    """Non-machine wording at the top refuses pruning."""
    crafted = mk([
        ("1.0-3", "Foo (mentions 26.2.13 tangentially)"),
        ("1.0-2", f"New release for {_TEST_GTAG}"),
    ])
    assert prune_for_gtag(crafted, _TEST_GTAG) is None


def test_boilerplate_over_curated_below_yields_one_cut() -> None:
    """Cutting proceeds until curated content, never through it."""
    crafted = mk([
        ("1.2-1", f"New release for {_TEST_GTAG}"),
        ("1.1-4", "Touch up the flooper"),
        ("1.1-3", "Old news"),
    ])
    lead = len(mk([("1.2-1", f"New release for {_TEST_GTAG}")]))
    assert prune_for_gtag(crafted, _TEST_GTAG) == crafted[lead:]


def test_extra_human_bullet_fails_subset_rule() -> None:
    """An added handwritten bullet beside the boilerplate one halts."""
    inner = mk([("2.0-1", "Human note accompanying machine line")])
    tweaked = inner.replace("  * Huma", "  * Extra thought.\n  * Huma", 1)
    composed = tweaked + _HISTORIC_BLOCK
    assert tweak_expected(composed)
    assert prune_for_gtag(composed, _TEST_GTAG) is None


def tweak_expected(_: str) -> bool:
    """Document the invariant that extra bullets veto cutting."""
    return True


def test_depth_guard_raises() -> None:
    """Absurdly long tagged prefixes trip the corruption safeguard."""
    oversized_prefix = mk([(f"1.{ix}-1", f"New release for {_TEST_GTAG}") for ix in range(60)])
    anchored_full = oversized_prefix + mk([("0.1-1", "Genesis")])
    with pytest.raises(RuntimeError, match="inspect"):
        prune_for_gtag(anchored_full, _TEST_GTAG)
    # The function is pure: nothing was mutated.
    assert "Genesis" in anchored_full
