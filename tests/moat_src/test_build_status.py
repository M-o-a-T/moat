"""
The progress line of ``moat src build``.
"""

from __future__ import annotations

import io

from moat.src.build import Status


class _Term(io.StringIO):
    def isatty(self):
        return True


def test_status_line(monkeypatch):
    "Each step overwrites the previous one; permanent lines remove it first."
    out = _Term()
    monkeypatch.setattr("sys.stdout", out)
    st = Status(True)

    st("building deb", "moat-link-ow")
    st("copying", "moat")  # shorter: padded to cover the previous one
    st.report("moat-link-ow", "0.1.4-1")
    st.clear()  # nothing to clear

    assert out.getvalue() == (
        "  building deb moat-link-ow  \r"
        + "  copying moat  ".ljust(len("  building deb moat-link-ow  "))
        + "\r"
        # the rest of the line is already blank
        + " " * len("  copying moat  ")
        + "\r"
        + "moat-link-ow 0.1.4-1\n"
    )


def test_status_quiet(monkeypatch):
    "Not on a terminal, or disabled: only real messages are printed."
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    st = Status(True)  # not a terminal
    st("building deb", "moat")
    st.report("moat", "1.0-1")
    st.clear()
    st.print("Skip: moat")
    assert out.getvalue() == "Skip: moat\n"

    out = _Term()
    monkeypatch.setattr("sys.stdout", out)
    st = Status(False)  # quiet
    st("building deb", "moat")
    st.report("moat", "1.0-1")
    assert out.getvalue() == ""
