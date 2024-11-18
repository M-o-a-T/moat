# noqa: D100,RUF003  # compatibility with µPy
from __future__ import annotations

alphabet = "bcdfghjkmnopqrstvwxyzBCDFGHJKMNOPQRSTVWXYZ23456789"

import random

__all__ = ["gen_ident"]

def gen_ident(k=10, /):
	return "".join(random.choices(alphabet, k=k))

