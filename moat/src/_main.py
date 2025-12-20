# command line interface
# pylint: disable=missing-module-docstring
from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

import asyncclick as click
import git
import tomlkit
from packaging.requirements import Requirement

from moat.util import P, attrdict, load_subgroup, make_proc, yload
from moat.util.exec import run as run_

from ._repo import Repo
from ._util import dash, undash

from collections import defaultdict

logger = logging.getLogger(__name__)

PACK = Path("packaging")
ARCH = subprocess.check_output(["/usr/bin/dpkg", "--print-architecture"]).decode("utf-8").strip()
SRC = re.compile(r"^Source:\s+(\S+)\s*$", re.MULTILINE)


@load_subgroup(sub_pre="moat.src", sub_post="cli")
async def cli():
    """
    This collection of commands is useful for managing and building MoaT itself.
    """
    pass


@cli.command("rerepo")
@click.option("-a", "--all", is_flag=True, help="Move all your repositories.")
@click.argument("names", type=str, nargs=-1)
@click.pass_obj
async def move_repo(obj, **kw):
    """Move from forge A to forge B.

    This command moves your repositories from A (github …) to a local copy,
    B (codeberg,or any other forgejo instance), and/or Radicle.

    It adds a "migrated" branch and (optionally) deletes
    all other branches and tags.

    By default, the '--all' option does not touch forked repositores.

    For access tokens and configuration, load a private config file.
    See `moat util cfg -l moat.src src` for defaults.

    If the local copy is present, it will be refreshed via `git fetch`.
    """
    from .move import mv_repos  # noqa: PLC0415

    await mv_repos(obj.cfg.src.move, **kw)


def fix_deps(deps: list[str], tags: dict[str, str]) -> bool:
    """Adjust dependencies"""
    work = False
    for i, dep in enumerate(deps):
        r = Requirement(dep)
        if r.name in tags:
            dep = f"{r.name} ~= {tags[r.name]}"  # noqa:PLW2901
            if deps[i] != dep:
                deps[i] = dep
                work = True
    return work


async def run_tests(pkg: str | None, *opts) -> bool:
    """Run subtests for subpackage @pkg."""

    if pkg is None:
        tests = Path("tests")
    else:
        tests = Path("tests") / pkg

    if not Path(tests).exists():
        # No tests. Assume it's OK.
        print("No tests:", pkg)
        return True
    try:
        print("\n*** Testing:", pkg)
        await run_(
            "/usr/bin/python3",
            "-mpytest",
            *opts,
            tests,
            capture=False,
            env=dict(PYTHONPATH="."),
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except subprocess.CalledProcessError:
        return False
    else:
        return True


class Replace:
    """Encapsulates a series of string replacements."""

    def __init__(self, **kw):
        self.changes = kw

    def __call__(self, s):
        if isinstance(s, str):
            for k, v in self.changes.items():
                s = s.replace(k, v)
        return s


_l_t = (list, tuple)


def default_dict(a, b, c, cls=dict, repl=lambda x: x) -> dict:
    """
    Returns a dict with all keys+values of all dict arguments.
    The first found value wins.

    This operation is recursive and non-destructive.

    Args:
    cls (type): a class to instantiate the result with. Default: dict.
            Often used: :class:`attrdict`.
    """
    keys = defaultdict(list)
    mod = False

    for kv in a, b, c:
        if kv is None:
            continue
        for k, v in kv.items():
            keys[k].append(v)

    for k, v in keys.items():
        va = a.get(k, None)
        vb = b.get(k, None)
        vc = c.get(k, None)
        if isinstance(va, str) and va == "DELETE":
            if vc is None:
                try:
                    del b[k]
                except KeyError:
                    pass
                else:
                    mod = True
                continue
            else:
                b[k] = {} if isinstance(vc, dict) else [] if isinstance(vc, _l_t) else 0
                vb = b[k]
            va = None
        if isinstance(va, dict) or isinstance(vb, dict) or isinstance(vc, dict):
            if vb is None:
                b[k] = {}
                vb = b[k]
                mod = True
            mod = default_dict(va or {}, vb, vc or {}, cls=cls, repl=repl) or mod
        elif isinstance(va, _l_t) or isinstance(vb, _l_t) or isinstance(vc, _l_t):
            if vb is None:
                b[k] = []
                vb = b[k]
                mod = True
            if va:
                for vv in va:
                    vv = repl(vv)  # noqa:PLW2901
                    if vv not in vb:
                        vb.insert(0, vv)
                        mod = True
            if vc:
                for vv in vc:
                    vv = repl(vv)  # noqa:PLW2901
                    if vv not in vb:
                        vb.insert(0, vv)
                        mod = True
        else:
            v = repl(va) or vb or repl(vc)  # noqa:PLW2901
            if vb != v:
                b[k] = v
                mod = True
    return mod


def _mangle(proj, path, mangler):
    try:
        for k in path[:-1]:
            proj = proj[k]
        k = path[-1]
        v = proj[k]
    except KeyError:
        return
    v = mangler(v)
    proj[k] = v


def decomma(proj, path):
    """comma-delimited string > list"""
    _mangle(proj, path, lambda x: x.split(","))


def encomma(proj, path):
    """list > comma-delimited string"""
    _mangle(proj, path, lambda x: ",".join(x))  # pylint: disable=unnecessary-lambda


def apply_hooks(repo, force=False):
    h = Path(repo.git_dir) / "hooks"
    drop = set()
    seen = set()
    for f in h.iterdir():
        if f.suffix == ".sample":
            drop.add(f)
            continue
        seen.add(f.name)
    for f in drop:
        f.unlink()

    pt = Path(__file__).parent / "_hooks"
    for f in pt.iterdir():
        if not force and f.name in seen:
            continue
        t = h / f.name
        d = f.read_text()
        t.write_text(d)
        t.chmod(0o755)


@cli.command
@click.argument("part", type=str)
@click.pass_obj
def setup(obj, part):
    """
    Create a new MoaT subcommand.
    """
    cfg = obj.cfg
    repo = Repo(cfg.src.toplevel, None)
    if "-" in part:
        part = undash(part)

    (Path("packaging") / dash(part)).mkdir()
    (Path("packaging") / dash(part)).mkdir()
    apply_templates(repo, part)


def apply_templates(repo: Repo, part):
    """
    Apply template files to this component.
    """
    commas = (
        P("tool.tox.tox.envlist"),
        P("tool.pylint.messages_control.enable"),
        P("tool.pylint.messages_control.disable"),
    )

    pt = part.split(".")
    rname = dash(part)
    rdot = part
    rpath = "/".join(pt)
    runder = "_".join(pt)
    repl = Replace(
        SUBNAME=rname,
        SUBDOT=rdot,
        SUBPATH=rpath,
        SUBUNDER=runder,
    )
    pt = (Path(__file__).parent / "_templates").joinpath
    pr = Path.cwd().joinpath
    with pt("pyproject.forced.yaml").open("r") as f:
        t1 = yload(f)
    with pt("pyproject.default.yaml").open("r") as f:
        t2 = yload(f)
    try:
        with pr("pyproject.toml").open("r") as f:
            proj = tomlkit.load(f)

        for p in commas:
            decomma(proj, p)

    except FileNotFoundError:
        proj = tomlkit.TOMLDocument()

    mod = default_dict(t1, proj, t2, repl=repl, cls=tomlkit.items.Table)
    try:
        proc = proj["tool"]["moat"]["fixup"]
    except KeyError:
        p = proj
    else:
        del proj["tool"]["moat"]["fixup"]
        proc = make_proc(proc, ("toml",), f"{pr('pyproject.toml')}:tool.moat.fixup")
        s1 = proj.as_string()
        proc(proj)
        s2 = proj.as_string()
        mod |= s1 != s2

    if mod:
        for p in commas:
            encomma(proj, p)

        projp = Path("packaging") / rname / "pyproject.toml"
        projp.write_text(proj.as_string())
        repo.index.add(projp)

    mkt = repl(pt("Makefile").read_text())
    try:
        mk = pr("Makefile").read_text()
    except FileNotFoundError:
        mk = ""
    if mkt != mk:
        pr("Makefile").write_text(mkt)
        repo.index.add(pr("Makefile"))

    init = repl(pt("moat", "__init__.py").read_text())
    try:
        mk = pr("moat", "__init__.py").read_text()
    except FileNotFoundError:
        mk = ""
    if mkt != mk:
        if not pr("moat").is_dir():
            pr("moat").mkdir(mode=0o755)
        pr("moat", "__init__.py").write_text(init)
        repo.index.add(pr("moat", "__init__.py"))

    if not pr("moat", "_main.py").exists():
        main = repl(pt("moat", "_main.py").read_text())
        pr("moat", "_main.py").write_text(main)
        repo.index.add(pr("moat", "_main.py"))

    tst = pr("tests")
    if not tst.is_dir():
        tst.mkdir()
    for n in tst.iterdir():
        if n.name.startswith("test_"):
            break
    else:
        tp = pt("test_basic_py").read_text()
        tb = pr("tests") / "test_basic.py"
        tb.write_text(repl(tp))
        repo.index.add(tb)

    try:
        with pr(".gitignore").open("r") as f:
            ign = f.readlines()
    except FileNotFoundError:
        ign = []
    o = len(ign)
    with pt("gitignore").open("r") as f:
        for li in f:
            if li not in ign:
                ign.append(li)
    if len(ign) != o:
        with pr(".gitignore").open("w") as f:
            for li in ign:
                f.write(li)
        repo.index.add(pr(".gitignore"))


@cli.command("path")
def path_():
    "Path to source templates"
    print(Path(__file__).parent / "_templates")


@cli.command()
@click.pass_obj
def tags(obj):
    """
    List all tags
    """
    repo = Repo(obj.cfg.src.toplevel, None)

    for r in repo.parts:
        try:
            tag = r.last_tag
        except AttributeError:
            continue
        if r.has_changes(True):
            print(f"{r.dash} {tag} STALE")
        elif r.has_changes(True):
            print(f"{r.dash} {tag} REBUILD")
        else:
            print(f"{r.dash} {tag}")


@cli.command()
@click.option("-r", "--run", is_flag=True, help="actually do the tagging")
@click.option("-m", "--minor", is_flag=True, help="create a new minor version")
@click.option("-M", "--major", is_flag=True, help="create a new major version")
@click.option("-s", "--subtree", type=str, help="Tag this partial module")
@click.option("-v", "--tag", "force", type=str, help="Use this explicit tag value")
@click.option("-q", "--query", "--show", "show", is_flag=True, help="Show the latest tag")
@click.option("-f", "--force", "FORCE", is_flag=True, help="replace an existing tag")
@click.option("-b", "--build", is_flag=True, help="set/increment the build number")
@click.pass_obj
def tag(obj, run, minor, major, subtree, force, FORCE, show, build):
    """
    Tag the repository (or a subtree).

    MoaT versions are of the form ``a.b.c``. Binaries also have a build
    number. This command auto-increments ``c`` and sets the build to ``1``,
    except when you use ``-M|-m|-b``.
    """
    if minor and major:
        raise click.UsageError("Can't change both minor and major!")
    if force and (minor or major):
        raise click.UsageError("Can't use an explicit tag with changing minor or major!")
    if FORCE and (minor or major):
        raise click.UsageError("Can't reuse a tag and also change minor or major!")
    if (build or force) and (minor or major or (build and force)):
        raise click.UsageError("Can't update both build and tag!")
    if show and (run or force or minor or major):
        raise click.UsageError("Can't display and change the tag at the same time!")
    if build and not subtree:
        raise click.UsageError("The main release number doesn't have a build")

    repo = Repo(obj.cfg.src.toplevel, None)

    if subtree:
        r = repo.part(subtree)
    else:
        r = repo

    if show:
        tag = r.vers
        if r.has_changes():
            print(f"{tag.tag}-{tag.pkg} STALE")
        else:
            print(f"{tag.tag}-{tag.pkg}")
        return

    if force:
        tag = force
    elif FORCE or build:
        tag = r.last_tag
    else:
        tag = r.next_tag(major, minor)

    if run or subtree:
        if subtree:
            sb = repo.part(r.dash)
            if build:
                sb.vers.pkg += 1
                sb.vers.rev = repo.head.commit.hexsha
            else:
                sb.vers = attrdict(
                    tag=tag,
                    pkg=1,
                    rev=repo.head.commit.hexsha,
                )
            print(f"{tag}-{sb.vers.pkg}")
            repo.write_tags()
        else:
            git.TagReference.create(repo, tag, force=FORCE)
            print(f"{tag}")
    else:
        print(f"{tag} DRY_RUN")
