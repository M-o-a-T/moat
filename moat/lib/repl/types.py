from __future__ import annotations  # noqa: D100

from collections.abc import Callable, Iterator
from typing import TypeAlias

__all__ = []

Callback: TypeAlias = Callable[[], object]
SimpleContextManager: TypeAlias = Iterator[None]
KeySpec: TypeAlias = str  # like r"\C-c"
CommandName: TypeAlias = str  # like "interrupt"
EventTuple: TypeAlias = tuple[CommandName, str]
Completer: TypeAlias = Callable[[str, int], str | None]
CharBuffer: TypeAlias = list[str]
CharWidths: TypeAlias = list[int]
