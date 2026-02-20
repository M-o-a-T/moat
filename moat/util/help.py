"""
Command help text formatting helpers.
"""

from __future__ import annotations


def _help_preserve_blocks(text: str | None) -> str | None:
    """Mark preformatted help paragraphs so Click does not reflow them."""

    if text is None:
        return None

    def _is_preformatted(paragraph: list[str]) -> bool:
        if not paragraph:
            return False
        if paragraph[0] == "\b":
            return False
        return any(
            line[:1].isspace() or line.startswith((">>>", "...", "* ", "- ", "+ "))
            for line in paragraph
            if line
        )

    out: list[str] = []
    paragraph: list[str] = []

    def _flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        if _is_preformatted(paragraph):
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

    return "\n".join(out)
