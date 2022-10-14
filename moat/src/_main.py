# command line interface
# pylint: disable=missing-module-docstring

import io
import logging
import subprocess
from collections import defaultdict
from configparser import RawConfigParser
from pathlib import Path

import asyncclick as click
import git
import tomlkit
from moat.util import P, make_proc, to_attrdict, yload, yprint, add_repr
from packaging.requirements import Requirement

logger = logging.getLogger(__name__)


class Repo(git.Repo):
    """Amend git.Repo with submodule and tag caching"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._subrepo_cache = {}
        self._commit_tags = defaultdict(list)
        self._commit_topo = {}

        for t in self.tags:
            self._commit_tags[t.commit].append(t)

    def subrepos(self):
        """List subrepositories (and cache them)."""
        for r in self.submodules:
            try:
                yield self._subrepo_cache[r.path]
            except KeyError:
                self._subrepo_cache[r.path] = res = Repo(r.path)
                yield res

    def commits(self, ref=None):
        """Iterate over topo sort of commits following @ref, or HEAD"""
        if ref is None:
            ref = self.head.commit
        try:
            res = self._commit_topo[ref]
        except KeyError:
            visited = set()
            res = []

            def _it(c):
                return iter(sorted(c.parents, key=lambda x: x.committed_date))

            work = [(ref, _it(ref))]

            while work:
                c, gen = work.pop()
                visited.add(c)
                for n in gen:
                    if n not in visited:
                        work.append((c, gen))
                        work.append((n, _it(n)))
                        break
                else:
                    res.append(c)
            self._commit_topo[ref] = res

        n = len(res)
        while n:
            n -= 1
            yield res[n]

    def tagged(self, c=None) -> str:
        """Return a commit's tag.
        Defaults to the head commit.
        Returns None if no tag, raises ValueError if more than one is found.
        """
        if c is None:
            c = self.head.commit
        if c not in self._commit_tags:
            return None
        tt = self._commit_tags[c]
        if len(tt) > 1:
            raise ValueError(f"multiple tags: {tt}")
        return tt[0]


@click.group(short_help="Manage MoaT itself")
async def cli():
    """
    This collection of commands is useful for managing and building MoaT itself.
    """
    pass  # pylint: disable=unnecessary-pass


def fix_deps(deps: list[str], tags: dict[str, str]) -> bool:
    """Adjust dependencies"""
    work = False
    for i, dep in enumerate(deps):
        r = Requirement(dep)
        if r.name in tags:
            deps[i] = f"{r.name}~={tags[r.name]}"
            work = True
    return work


def run_tests(repo: Repo) -> bool:
    """Run tests (i.e., 'tox') in this repository."""
    try:
        print("\n*** Testing:", repo.working_dir)
        subprocess.run(["python3", "-mtox"], cwd=repo.working_dir, check=True)
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
                    vv = repl(vv)
                    if vv not in vb:
                        vb.insert(0, vv)
                        mod = True
            if vc:
                for vv in vc:
                    vv = repl(vv)
                    if vv not in vb:
                        vb.insert(0, vv)
                        mod = True
        else:
            v = repl(va) or vb or repl(vc)
            if vb != v:
                b[k] = v
                mod = True
    return mod


def is_clean(repo: Repo, skip: bool = True) -> bool:
    """Check if this repository is clean."""
    skips = " Skipping." if skip else ""
    if repo.head.is_detached:
        print(f"{repo.working_dir}: detached.{skips}")
        return False
    if repo.head.ref.name not in {"main", "moat"}:
        print(f"{repo.working_dir}: on branch {repo.head.ref.name}.{skips}")
        return False
    elif repo.is_dirty(index=True, working_tree=True, untracked_files=False, submodules=False):
        print(f"{repo.working_dir}: Dirty.{skips}")
        return False
    return True


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


def apply_templates(repo):
    """
    Apply templates to this repo.
    """
    commas = (
        P("tool.tox.tox.envlist"),
        P("tool.pylint.messages_control.enable"),
        P("tool.pylint.messages_control.disable"),
    )

    rpath = Path(repo.working_dir)
    if rpath.parent.name == "lib":
        rname = f"{rpath.parent.name}-{rpath.name}"
        rdot = f"{rpath.parent.name}.{rpath.name}"
        rpath = f"{rpath.parent.name}/{rpath.name}"
    else:
        rname = str(rpath.name)
        rdot = str(rpath.name)
        rpath = str(rpath.name)
    repl = Replace(
        SUBNAME=rname,
        SUBDOT=rdot,
        SUBPATH=rpath,
    )
    pt = (Path(__file__).parent / "_templates").joinpath
    pr = Path(repo.working_dir).joinpath
    with pt("pyproject.forced.yaml").open("r") as f:
        t1 = yload(f)
    with pt("pyproject.default.yaml").open("r") as f:
        t2 = yload(f)
    try:
        with pr("pyproject.toml").open("r") as f:
            proj = tomlkit.load(f)
        try:
            tx = proj["tool"]["tox"]["legacy_tox_ini"]
        except KeyError:
            pass
        else:
            txp = RawConfigParser()
            txp.read_string(tx)
            td = {}
            for k, v in txp.items():
                td[k] = ttd = dict()
                for kk, vv in v.items():
                    if isinstance(vv, str) and vv[0] == "\n":
                        vv = [x.strip() for x in vv.strip().split("\n")]
                    ttd[kk] = vv
            proj["tool"]["tox"] = td

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
        proc = make_proc(proc, ("toml",), f"{pr('pyproject.toml')}:tool.moat.fixup")
        s1 = proj.as_string()
        proc(proj)
        s2 = proj.as_string()
        mod |= s1 != s2

    if mod:
        for p in commas:
            encomma(proj, p)

        try:
            tx = proj["tool"]["tox"]
        except KeyError:
            pass
        else:
            txi = io.StringIO()
            txp = RawConfigParser()
            for k, v in tx.items():
                if k != "DEFAULT":
                    txp.add_section(k)
                for kk, vv in v.items():
                    if isinstance(vv, (tuple, list)):
                        vv = "\n   " + "\n   ".join(str(x) for x in vv)
                    txp.set(k, kk, vv)
            txp.write(txi)
            txi = txi.getvalue()
            txi = "\n" + txi.replace("\n\t", "\n ")
            proj["tool"]["tox"] = dict(
                legacy_tox_ini=tomlkit.items.String.from_raw(
                    txi, type_=tomlkit.items.StringType.MLB
                )
            )

        (Path(repo.working_dir) / "pyproject.toml").write_text(proj.as_string())
        repo.index.add(Path(repo.working_dir) / "pyproject.toml")

    mkt = repl(pt("Makefile").read_text())
    try:
        mk = pr("Makefile").read_text()
    except FileNotFoundError:
        mk = ""
    if mkt != mk:
        pr("Makefile").write_text(mkt)
        repo.index.add(pr("Makefile"))

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


@cli.command()
@click.option("-A", "--amend", is_flag=True, help="Fixup previous commit (DANGER)")
@click.option("-N", "--no-amend", is_flag=True, help="Don't fixup even if same text")
@click.option("-D", "--no-dirty", is_flag=True, help="don't check for dirtiness (DANGER)")
@click.option("-C", "--no-commit", is_flag=True, help="don't commit")
@click.option("-s", "--skip", type=str, multiple=True, help="skip this repo")
@click.option(
    "-m",
    "--message",
    type=str,
    help="commit message if changed",
    default="Update from MoaT template",
)
@click.option("-o", "--only", type=str, multiple=True, help="affect only this repo")
async def setup(no_dirty, no_commit, skip, only, message, amend, no_amend):
    """
    Set up projects using templates.

    Default: amend if the text is identical and the prev head isn't tagged.
    """
    repo = Repo()
    skip = set(skip)
    if only:
        repos = (Repo(x) for x in only)
    else:
        repos = (x for x in repo.subrepos() if Path(x.working_tree_dir).name not in skip)

    for r in repos:
        if not is_clean(r, not no_dirty):
            if not no_dirty:
                continue

        apply_templates(r)

        if no_commit:
            continue
        if r.is_dirty(index=True, working_tree=False, untracked_files=False, submodules=False):
            if no_amend or r.tagged():
                a = False
            elif amend:
                a = True
            else:
                a = r.head.commit.message == message

            if a:
                p = r.head.commit.parents
            else:
                p = (r.head.commit,)
            r.index.commit(message, parent_commits=p)


@cli.command()
@click.option("-T", "--no-test", is_flag=True, help="Skip testing")
@click.option(
    "-v",
    "--version",
    type=(str, str),
    multiple=True,
    help="Update external dep version",
)
@click.option("-C", "--no-commit", is_flag=True, help="don't commit")
@click.option("-D", "--no-dirty", is_flag=True, help="don't check for dirtiness (DANGER)")
async def build(version, no_test, no_commit, no_dirty):
    """
    Rebuild all modified packages.
    """
    bad = False
    repo = Repo()
    tags = dict(version)
    skip = set()

    for r in repo.subrepos():
        if not is_clean(r, not no_dirty):
            if not no_dirty:
                skip.add(r)
                continue

        if not no_test and not run_tests(r):
            print("FAIL", Path(r.working_dir).name)
            return  # abort immediately

        if r.is_dirty():
            print("DIRTY", Path(r.working_dir).name)
            if Path(r.working_dir).name != "src":
                bad = True
            continue
        t = r.tagged(r.head.commit)
        if t is None:
            for c in r.commits():
                t = r.tagged(c)
                if t is not None:
                    break
            print("UNTAGGED", t, Path(r.working_dir).name)
            xt, t = t.name.rsplit(".", 1)
            t = f"{xt}.{str(int(t)+1)}"
            # t = r.create_tag(t)
            # do not create the tag yet
        else:
            print("TAG", t, Path(r.working_dir).name)
        tags[f"moat-{Path(r.working_dir).name}"] = t
    if bad:
        print("No work done. Fix and try again.")
        return
    print("All tests passed. Yay!")

    dirty = set()

    check = True
    while check:
        check = False

        # Next: fix versioned dependencies
        for r in repo.subrepos():
            if r in skip:
                continue
            p = Path(r.working_dir) / "pyproject.toml"
            if not p.is_file():
                # bad=True
                print("Skip:", r.working_dir)
                continue
            with p.open("r") as f:
                pr = tomlkit.load(f)

            print("***", r.working_dir)
            yprint(to_attrdict(pr))

            work = False
            try:
                deps = pr["project"]["dependencies"]
            except KeyError:
                pass
            else:
                work = fix_deps(deps, tags) | work
            try:
                deps = pr["project"]["optional_dependencies"]
            except KeyError:
                pass
            else:
                for v in deps.values():
                    work = fix_deps(v, tags) | work
            if work:
                p.write_text(pr.as_string())
                r.index.add(p)
                dirty.add(r)
                t = tags[r.working_dir]
                if not isinstance(t, str):
                    xt, t = t.name.rsplit(".", 1)
                    t = f"{xt}.{str(int(t)+1)}"
                    tags[r.working_dir] = t
                check = True

    if bad:
        print("Partial work done. Fix and try again.")
        return

    if not no_commit:
        for r in dirty:
            r.index.commit("Update MoaT requirements")
        for r in repo.subrepos():
            t = tags[r.working_dir]
            if isinstance(t, str):
                r.create_tag(t)

add_repr(tomlkit.items.String)
add_repr(tomlkit.items.Integer)
add_repr(tomlkit.items.Bool, bool)
add_repr(tomlkit.items.MutableMapping)
add_repr(tomlkit.items.MutableSequence)
