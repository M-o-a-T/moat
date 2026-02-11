"""Random identifier generation utilities, compatible with µPy."""

from __future__ import annotations

import os

rs = os.environ.get("PYTHONHASHSEED", None)
if rs is None:
    import random
else:  # pragma: no cover
    try:
        import trio._core._run as tcr
    except ImportError:
        import random
    else:
        random = tcr._r  # noqa: SLF001

al_unique: str = "bcdfghjkmnpqrstvwxyzBCDFGHJKMNPQRSTVWXYZ23456789"
"An alphabet intended to be unambiguous: both cases, no special characters, no vowels"

al_lower: str = "abcdefghijklmnopqrstuvwxyz0123456789"
"Lowercase letters and digits, e.g. for restricted-alphabet labels"

al_ascii: str = bytes(x for x in range(33, 127) if x != 92).decode("ascii")
"all printable ASCII characters (except for backslash, just to be safe)"

al_az: str = "abcdefghijklmnopqrstuvwxyz"
"lowercase letters"

__all__ = ["al_ascii", "al_az", "al_lower", "al_unique", "gen_ident", "id2str"]


def gen_ident(k: int = 10, /, *, alphabet: str = al_unique) -> str:
    """
    Generate a random identifier / password.
    """
    return "".join(random.choices(alphabet, k=k))


def id2str(k: int, /, *, alphabet: str = al_unique) -> str:
    """
    Given a non-numeric identifier, returns a string representing it.
    """
    assert k > 0
    if k == 0:
        return alphabet[0]
    res: list[str] = []
    la = len(alphabet)
    while k:
        res.append(alphabet[k % la])
        k //= la
    return "".join(res)
