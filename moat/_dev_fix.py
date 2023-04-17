"""
This module exports the procedure ``_fix()``, required to run MoaT from its
development tree.

This call is auto-added to a ``moat/__init__.py`` file when the MoaT
template is applied to a MoaT submodule.
"""

_fixed = False


def _fix():
    # pylint: disable=import-outside-toplevel
    global _fixed  # pylint: disable=global-statement
    if _fixed:
        return
    _fixed = True

    from pathlib import Path

    md = Path(__file__).absolute().parents[1]
    if (md / ".git").exists():
        import git

        def _get_sub(r):
            if "lib" in r.parts and not r.is_relative_to(md / "lib"):
                return
            rs = r / "src"
            yield (rs if rs.is_dir() else r)
            try:
                rp = git.Repo(r)
            except Exception as exc:
                raise RuntimeError(r) from exc
            for rr in rp.submodules:
                yield from _get_sub(r / rr.path)

        _pp = list(_get_sub(md))
        _pp.append(str(md))

        # assume that sys.path[0] is the main …/moat directory
        import sys

        sys.path[0:0] = (str(x) for x in _pp)

        import pkgutil

        import moat

        # only consider local packages
        moat.__path__ = [
            p
            for p in pkgutil.extend_path([moat.__path__[0]], "moat")
            if Path(p).is_relative_to(md)
        ]

        import os

        os.environ["PYTHONPATH"] = os.pathsep.join(str(Path(x).parent) for x in _pp)
