"""
Placeholder for data that does schema verification
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import Path

__all__ = ["Data", "Schema"]


class Data(dict):
    "Schema-verified data (dict)"


class _SchemaName(str):
    __slots__ = ()

    def __getattr__(self, x):
        if len(self):
            return _SchemaName(f"{self}.{x}")
        return _SchemaName(x)


Schema = _SchemaName("")
