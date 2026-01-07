"""
MoaT Path module - hierarchical path representation and manipulation.

This module provides the Path class for representing and manipulating
hierarchical paths in MoaT systems.
"""

from __future__ import annotations

from ._impl import (
    PS,
    P,
    P_Root,
    Path,
    PathElem,
    PathElemI,
    PathLongener,
    PathShortener,
    Q_Root,
    Root,
    RootPath,
    S_Root,
    logger_for,
    path_eval,
    set_root,
)

__all__ = [
    "PS",
    "P",
    "P_Root",
    "Path",
    "PathElem",
    "PathElemI",
    "PathLongener",
    "PathShortener",
    "Q_Root",
    "Root",
    "RootPath",
    "S_Root",
    "logger_for",
    "path_eval",
    "set_root",
]
