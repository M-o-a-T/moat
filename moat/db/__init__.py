"""
MoaT database supprt
"""

from __future__ import annotations


def load(cfg):
    from .util import load as load_

    return load_(cfg)


def database(cfg):
    from .util import database as database_

    return database_(cfg)
