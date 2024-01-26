"""
Helpers for MoaT command interpreters et al.
"""

from __future__ import annotations

# Typing


# like get/set_part but without the attributes


def get_p(cur, p, add=False):
    "retrieve an item"
    for pp in p:
        try:
            cur = cur[pp]
        except KeyError:
            if not add:
                raise
            cur[pp] = nc = {}
            cur = nc
    return cur


def set_p(cur, p, v):
    "set an item"
    cur = get_p(cur, p[:-1], add=True)
    cur[p[-1]] = v


def del_p(cur, p):
    "delete an item"
    pp = p[0]
    if pp in cur:
        if len(p) > 1:
            del_p(cur[pp], p[1:])
        if cur[pp]:
            return
        del cur[pp]
