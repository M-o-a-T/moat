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

        roots = set()

        def _get_sub(r):
            rs = r / "src"
            if "lib" in r.parts and not r.is_relative_to(md / "lib"):
                yield (rs if (rs / "__init__.py").is_file() else r)
                return
            yield (rs if rs.is_dir() else r)
            try:
                rp = git.Repo(r)
            except git.exc.InvalidGitRepositoryError:
                return
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
        paths = []
        for p_ in pkgutil.extend_path([moat.__path__], "moat"):
            if not isinstance(p_, (list, tuple)):
                p_ = (p_,)
            for p in p_:
                pp = Path(p)
                if pp.is_relative_to(md):
                    pu = str(pp.parent)
                    if pu not in roots:
                        roots.add(pu)
                        paths.append(p)
        moat.__path__ = paths

        import os

        if "_MOAT_ADJ" in os.environ:
            return
        os.environ["_MOAT_ADJ"] = "1"

        os.environ["PYTHONPATH"] = os.pathsep.join(roots) + (
            ":" + os.environ["PYTHONPATH"] if "PYTHONPATH" in os.environ else ""
        )
