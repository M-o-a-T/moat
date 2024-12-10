# noqa: D100,RUF003  # compatibility with µPy
from __future__ import annotations

import random

alphabet = "bcdfghjkmnopqrstvwxyzBCDFGHJKMNOPQRSTVWXYZ23456789"

__all__ = ["gen_ident"]


def gen_ident(k=10, /):
    """
    Generate a random identifier / password.
    """
    return "".join(random.choices(alphabet, k=k))  # noqa:S311
