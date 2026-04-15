"""
Helpers for editing text and YAML data via an external editor.
"""

from __future__ import annotations

import anyio
import sys

from .exec import run
from .yaml import yformat, yload

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


async def edit_text(editor: str, text: str, *, suffix: str) -> str:
    """
    Open a tempfile in an editor and return its content.
    """
    async with anyio.NamedTemporaryFile(mode="w+", suffix=suffix) as f:
        if text and not text.endswith("\n"):
            text += "\n"
        await f.write(text)
        await f.flush()
        await f.seek(0)
        await run(editor, f.name, stdin=sys.stdin, stdout=sys.stdout)
        await f.seek(0)
        return await f.read()


async def edit_yaml(editor: str, data: Mapping[str, Any], *, suffix: str = ".yaml") -> dict:
    """
    Edit YAML content and parse the result.
    """
    txt = await edit_text(editor, yformat(data, compact=False) + "\n", suffix=suffix)
    return yload(txt)
