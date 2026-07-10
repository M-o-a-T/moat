"""
Command help text formatting helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import overload


@overload
def help_preserve_blocks(text: str) -> str: ...


@overload
def help_preserve_blocks(text: Callable) -> Callable: ...


def help_preserve_blocks(text: str | None | Callable) -> str | None | Callable:
    """Mark preformatted help paragraphs so Click does not reflow them."""

    func = None

    if isinstance(text, Callable):
        func = text
        text = func.__doc__
    if text is None:
        return func

    def is_preformatted(paragraph: list[str]) -> bool:
        if not paragraph:
            return False
        if paragraph[0] == "\b":
            return False
        return any(
            line[:1].isspace() or line.startswith((">>>", "...", "* ", "- ", "+ ")) or "  " in line
            for line in paragraph
        )

    out: list[str] = []
    paragraph: list[str] = []

    def _flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        if is_preformatted(paragraph):
            out.append("\b")
        out.extend(paragraph)
        paragraph = []

    for line in text.splitlines():
        if line.strip():
            paragraph.append(line)
        else:
            _flush_paragraph()
            out.append("")
    _flush_paragraph()

    text = "\n".join(out)
    if func is None:
        return text
    func.__doc__ = text
    return func
