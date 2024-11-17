from __future__ import annotations

from moat.util import Path

__all__ = ["Data"]


class Data(dict):
    def __class_getitem__(cls, path: str | Path):
        return cls  # for now
