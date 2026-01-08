"""
Placeholder for data that does schema verification
"""

from __future__ import annotations

__all__ = ["Data", "Schema"]


class Data(dict):
    "Schema-verified data (dict)"


class SchemaName(str):
    __slots__ = ()

    def __getattr__(self, x):
        if len(self):
            return SchemaName(f"{self}.{x}")
        return SchemaName(x)


Schema = SchemaName("")
