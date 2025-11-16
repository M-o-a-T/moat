"""
This module contains list-to-kw mangling helpers.
"""

from __future__ import annotations

__all__ = ["pop_kw", "push_kw"]


def push_kw(args: list, kwargs: dict):
    """
    Add kwargs to the list, if required.

    This modifies the list.
    """
    if kwargs or (args and isinstance(args[-1], dict)):
        args.append(kwargs if isinstance(kwargs, dict) else {})


def pop_kw(ak: list) -> dict:
    """
    Unpack an args-and-maybe-trailing-kwargs list.

    This modifies the list and returns the trailing dict, if any.
    Otherwise an empty dict is returned.
    """
    if ak and isinstance(ak[-1], dict):
        kw = ak.pop()
        return kw
    return {}
