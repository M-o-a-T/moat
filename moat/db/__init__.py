"""
MoaT database supprt
"""

from __future__ import annotations


def load(cfg):  # noqa:D103
    from .util import load as load_  # noqa: PLC0415

    return load_(cfg)


def database(cfg):  # noqa:D103
    from .util import database as database_  # noqa: PLC0415

    return database_(cfg)
