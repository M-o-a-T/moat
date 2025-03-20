# command line interface
# pylint: disable=missing-module-docstring
from __future__ import annotations

import io
import logging
import subprocess
import sys
from collections import defaultdict, deque
from configparser import RawConfigParser
from pathlib import Path

import asyncclick as click
import git
import tomlkit
from anyio import run_process
from moat.util import P, add_repr, attrdict, make_proc, yload, yprint
from packaging.requirements import Requirement
from attrs import define,field
from shutil import rmtree,copyfile,copytree

logger = logging.getLogger(__name__)

def dash(n:str) -> str:
    """
    moat.foo.bar > foo-bar
    foo.bar > ext-foo-bar
    """
    if "." not in n:  # also applies to single-name packages
        return n

    if n in ("main","moat"):
        return "main"
    if not n.startswith("moat."):
        return "ext-"+n.replace("-",".")
    return n.replace(".","-")[5:]

def undash(n:str) -> str:
    """
    foo-bar > moat.foo.bar
    ext-foo-bar > foo.bar
    """
    if "." in n:
        return n

    if n in ("main","moat"):
        return "moat"
    if n.startswith("ext-"):
        return n.replace("-",".")[4:]
    return "moat."+n.replace("-",".")

class ChangedError(RuntimeError):
    def __init__(subsys,tag,head):
        self.subsys = subsys
        self.tag = tag
        self.head = head
    def __str__(self):
        s = self.subsys or "Something"
        if head is None:
            head="HEAD"
        else:
            head = head.hexsha[:9]
        return f"{s} changed between {tag.name} and {head}"

@define
class Package:
    _repo:Repo = field(repr=False)
    name:str = field()
    under:str = field(init=False,repr=False)
    path:Path = field(init=False,repr=False)
    files:set(Path) = field(init=False,factory=set,repr=False)
    subs:dict[str,Package] = field(factory=dict,init=False,repr=False)

    def __init__(self, repo, name):
        self.__attrs_init__(repo,name)
        self.under = name.replace(".","_")
        self.path = Path(*name.split("."))

    @property
    def dash(self):
        return dash(self.name)

    def next_tag(self,major:bool=False,minor:bool=False):
        tag = self.last_tag()
        try:
            n = [ int(x) for x in tag.split('.') ]
            if len(n) != 3:
                raise ValueError(n)
        except ValueError:
            raise ValueError(f"Tag {tag} not in major#.minor#.patch# form.") from None

        if major:
            n = [n[0]+1,0,0]
        elif minor:
            n = [n[0],n[1]+1,0]
        else:
            n = [n[0],n[1],n[2]+1]
        return ".".join(str(x) for x in n)

    def populate(self, path:Path):
        """
        Collect this package's file names.
        """
        self.path = path
        for name in path.iterdir():
            name=name.name
            if name == "__pycache__":
                continue
            if name in self.subs:
                self.subs[name].populate(path/name)
            else:
                self.files.add(name)

    def copy(self) -> None:
        """
        Copies the current version of this subsystem to its packaging area.
        """
        p = Path("packaging")/self.dash
        rmtree(p/"moat")
        dest = p/self.path
        dest.mkdir(parents=True)
        for f in self.files:
            if (self.path/f).is_dir():
                copytree(self.path/f, dest/f, symlinks=True, ignore_dangling_symlinks=True)
            else:
                copyfile(self.path/f, dest/f, follow_symlinks=False)

    def last_tag(self, head:Commit=None, unchanged:bool=False) -> Tag|None:
        """
        Return the most-recent tag
        """
        for c in self._repo.commits(head):
            t = self.tagged(c)
            if t is None:
                continue
            if unchanged and self.has_changes(c, head):
                raise ChangedError(subsys,t,ref)
            return t

        raise ValueError(f"No tags for {self.name}")

    def has_changes(self, tag:Commit=None, head:Commit=None) -> bool:
        """
        Test whether the given subsystem (or any subsystem)
        changed between @head and @tag commits
        """
        if tag is None:
            tag = self.last_tag(head)
        if head is None:
            head = self._repo.head.commit
        for d in head.diff(f"{self.dash}/{tag}"):
            if self._repo.repo_for(d.a_path) != self.name and self._repo.repo_for(d.b_path) != self.name:
                continue
            return True
        return False

    def tagged(self, c:Commit=None, subsys:str=None) -> Tag|None:
        """Return a commit's tag name.
        Defaults to the head commit.
        Returns None if no tag, raises ValueError if more than one is found.
        """
        if c is None:
            c = self._repo.head.commit
        tt = self._repo.tags_of(c)

        n = self.dash+"/"
        tt = [t for t in tt if t.name.startswith(n)]

        if not tt:
            return None
        if len(tt) > 1:
            raise ValueError(f"Multiple tags for {self.name}: {tt}")
        return tt[0].name[len(n):]



class Repo(git.Repo):
    """Amend git.Repo with tag caching and pseudo-submodule splitting"""

    moat_tag = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._commit_tags = defaultdict(list)
        self._commit_topo = {}

        self._repos = {}
        self._make_repos()

        for t in self.tags:
            self._commit_tags[t.commit].append(t)

        p = Path(self.working_dir)
        mi = p.parts.index("moat")
        self.moat_name = "-".join(p.parts[mi:])

    def repo(self, name):
        return self._repos[dash(name)]

    @property
    def parts(self):
        return self._repos.values()

    def tags_of(self, c:Commit) -> Sequence[Tag]:
        return self._commit_tags[c]

    def _add_repo(self, name):
        dn = dash(name)
        pn = undash(name)
        if dn in self._repos:
            return self._repos[dn]

        p = Package(self,pn)
        self._repos[dn] = p
        if "." in pn:
            par,nam = pn.rsplit(".",1)
            pp = self._add_repo(par)
            pp.subs[nam] = p
        return p

    def _make_repos(self) -> dict:
        """Collect subrepos"""
        for fn in Path("packaging").iterdir():
            if fn.name == "main":
                continue
            self._add_repo(str(fn.name))

        self._repos["moat"].populate(Path("moat"))

    def repo_for(self, path:Path|str) -> str:
        """
        Given a file path, returns the subrepo in question
        """
        name = "moat"
        sc = self._repos["moat"]
        path=Path(path)
        try:
            if path.parts[0] == "packaging":
                return path.parts[1].replace("-",".")
        except KeyError:
            return name

        if path.parts[0] != "moat":
            return name

        for p in path.parts[1:]:
            if p in sc.subs:
                name += "."+p
                sc = sc.subs[p]
            else:
                break
        return name

    def commits(self, ref=None):
        """Iterate over topo sort of commits following @ref, or HEAD.

        WARNING: this code does not do a true topological breadth-first
        search. Doesn't matter much for simple merges that are based on
        a mostly-current checkout, but don't expect correctness when branches
        span tags.
        """
        if ref is None:
            ref = self.head.commit

        visited = set()
        work = deque([ref])
        while work:
            ref = work.popleft()
            if ref in visited:
                continue
            visited.add(ref)
            yield ref
            work.extend(ref.parents)

    def last_tag(self, ref=None, unchanged:bool=False) -> Tag|None:
        """
        Return the most-recent tag for the given subsystem (or globally).
        """
        for c in self.commits(ref):
            t = self.tagged(c)
            if t is None:
                continue
            if unchanged and self.has_changes(ref,t.commit):
                raise ChangedError(subsys,t,ref)

    def has_changes(self, tag:Tag, head:Commit) -> bool:
        """
        Test whether any subsystem changed between @head and @tag commits
        """
        if head is None:
            head = self.head.commit
        if tag is None:
            tag = self.last_tag(head)
        for d in head.diff(tag):
            if repo_for(d.a_name) == "moat" and repo_for(d.b_name) == "moat":
                continue
            return True
        return False


    def tagged(self, c:Commit=None, subsys:str=None) -> Tag|None:
        """Return a commit's tag name.
        Defaults to the head commit.
        Returns None if no tag, raises ValueError if more than one is found.
        """
        if c is None:
            c = self.head.commit
        if c not in self._commit_tags:
            return None
        tt = self._commit_tags[c]

        if subsys is None:
            tt = [t for t in tt if "/" not in t.name]
        else:
            n = subsys+"/"
            tt = [t for t in tt if t.name.startswith(n)]

        if not tt:
            return None
        if len(tt) > 1:
            if subsys is not None:
                raise ValueError(f"Multiple tags for {subsys}: {tt}")
            raise ValueError(f"Multiple tags: {tt}")
        return tt[0].name



@click.group(short_help="Manage MoaT itself")
async def cli():
    """
    This collection of commands is useful for managing and building MoaT itself.
    """
    pass


def fix_deps(deps: list[str], tags: dict[str, str]) -> bool:
    """Adjust dependencies"""
    work = False
    for i, dep in enumerate(deps):
        r = Requirement(dep)
        if r.name in tags:
            dep = f"{r.name} ~= {tags[r.name]}"
            if deps[i] != dep:
                deps[i] = dep
                work = True
    return work


def run_tests(repo: Repo) -> bool:
    """Run tests (i.e., 'tox') in this repository."""

    proj = Path(repo.working_dir) / "Makefile"
    if not proj.is_file():
        # No Makefile. Assume it's OK.
        return True
    try:
        print("\n*** Testing:", repo.working_dir)
        # subprocess.run(["python3", "-mtox"], cwd=repo.working_dir, check=True)
        subprocess.run(["make", "test"], cwd=repo.working_dir, check=True)
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
    elif repo.is_dirty(index=True, working_tree=True, untracked_files=True, submodules=False):
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
        if not force:
            if f.name in seen:
                continue
        t = h / f.name
        d = f.read_text()
        t.write_text(d)
        t.chmod(0o755)


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
    mti = rpath.parts.index("moat")
    mtp = rpath.parts[mti:]

    rname = "-".join(mtp)
    rdot = ".".join(mtp)
    rpath = "/".join(mtp)
    runder = "_".join(mtp)
    repl = Replace(
        SUBNAME=rname,
        SUBDOT=rdot,
        SUBPATH=rpath,
        SUBUNDER=runder,
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
        del proj["tool"]["moat"]["fixup"]
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
                    txi,
                    type_=tomlkit.items.StringType.MLB,
                ),
            )

        projp = Path(repo.working_dir) / "pyproject.toml"
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
@click.option("-s", "--show", is_flag=True, help="Show all tags")
@click.option("-r", "--run", is_flag=True, help="Update all stale tags")
def tags(show,run):
    repo = Repo(None)

    if show:
        if run:
            raise click.UsageError("Can't display and change the tag at the same time!")

        for r in repo.parts:
            try:
                tag = r.last_tag()
            except ValueError:
                print(f"{r.dash} -")
                continue
            if r.has_changes(tag):
                print(f"{r.dash} {tag} STALE")
            else:
                print(tag)
        return

    if repo.is_dirty(index=True, working_tree=True, untracked_files=True, submodules=False):
        print("Repo is dirty. Not tagging globally.", file=sys.stderr)
        return

    for r in repo.parts:
        tag = sb.last_tag()
        if not sb.has_changes(tag):
            print(repo.dash,tag,"UNCHANGED")
            continue

        tag = sb.next_tag()
        print(repo.dash,tag)

        if not run:
            continue
        git.TagReference.create(repo, f"{r.dash}/{tag}")


@cli.command()
@click.option("-r", "--run", is_flag=True, help="actually do the tagging")
@click.option("-m", "--minor", is_flag=True, help="create a new minor version")
@click.option("-M", "--major", is_flag=True, help="create a new major version")
@click.option("-s", "--subtree", type=str, help="Tag this partial module")
@click.option("-t", "--tag", "force", type=str, help="Use this explicit tag value")
@click.option("-q", "--query","--show","show", is_flag=True, help="Show the latest tag")
@click.option("-f", "--force","FORCE", is_flag=True, help="replace an existing tag")
def tag(run,minor,major,subtree,force,FORCE,show):
    """
    Tag the repository (or a subtree).
    """
    if minor and major:
        raise click.UsageError("Can't change both minor and major!")
    if force and (minor or major):
        raise click.UsageError("Can't use an explicit tag with changing minor or major!")
    if FORCE and not force:
        raise click.UsageError("Can't replace autogenerated tags, they don't exist by definition")
    if show and (run or force or minor or major):
        raise click.UsageError("Can't display and change the tag at the same time!")

    repo = Repo(None)

    if subtree:
        sb = repo.repo(subtree)
    else:
        sb = repo

    if show:
        tag = sb.last_tag()
        if sb.has_changes(tag):
            print(f"{tag} STALE")
        else:
            print(tag)
        return

    if force:
        tag = force
    else:
        tag = sb.next_tag(major,minor)

    if subtree:
        tag=f"{sb.dash}/{tag}"

    if run:
        git.TagReference.create(repo,tag, force=FORCE)
    else:
        print(f"{tag} DRY_RUN")


@cli.command()
@click.option("-P", "--no-pypi", is_flag=True, help="don't push to PyPi")
@click.option("-D", "--no-deb", is_flag=True, help="don't debianize")
@click.option("-d", "--deb", type=str, help="Debian archive to push to (from dput.cfg)")
@click.option("-o", "--only", type=str, multiple=True, help="affect only this repo")
@click.option("-s", "--skip", type=str, multiple=True, help="skip this repo")
async def publish(no_pypi, no_deb, skip, only, deb):
    """
    Publish modules to PyPi and/or Debian.
    """
    repo = Repo(None)
    skip = set(skip)
    if only:
        repos = (Repo(repo, x) for x in only)
    else:
        repos = (x for x in repo.subrepos() if x.moat_name[5:] not in skip)

    if not no_deb:
        for r in repos:
            p = Path(r.working_dir) / "pyproject.toml"
            if not p.is_file():
                continue
            print(r.working_dir)
            args = ["-d", deb] if deb else []
            subprocess.run(["merge-to-deb"] + args, cwd=r.working_dir, check=True)

    if not no_pypi:
        for r in repos:
            p = Path(r.working_dir) / "pyproject.toml"
            if not p.is_file():
                continue
            print(r.working_dir)
            subprocess.run(["make", "pypi"], cwd=r.working_dir, check=True)


async def fix_main(repo):
    """
    Set "main" references to the current HEAD.

    Repos with a non-detached head are skipped.
    Reports an error if HEAD is not a direct descendant.
    """

    async def _fix(r):
        if not r.head.is_detached:
            if r.head.ref.name not in {"main", "moat"}:
                print(f"{r.working_dir}: Head is {r.head.ref.name!r}", file=sys.stderr)
            return
        if "moat" in r.refs:
            m = r.refs["moat"]
        else:
            m = r.refs["main"]
        if m.commit != r.head.commit:
            ch = await run_process(
                [
                    "git",
                    "-C",
                    r.working_dir,
                    "merge-base",
                    m.commit.hexsha,
                    r.head.commit.hexsha,
                ],
                input=None,
                stderr=sys.stderr,
            )
            ref = ch.stdout.decode().strip()
            if ref != m.commit.hexsha:
                print(f"{r.working_dir}: need merge", file=sys.stderr)
                return
            m.set_reference(ref=r.head.commit, logmsg="fix_main")
        r.head.set_reference(ref=m, logmsg="fix_main 2")

    for r in repo.subrepos():
        await _fix(r)


@cli.command()
async def fixref():
    """
    Reset 'main' ref to HEAD

    Submodules frequently have detached HEADs. This command resets "main"
    to them, but only if that is a fast-forward operation.

    An error message is printed if the head doesn't point to "main", or if
    the merge wouldn't be a fast-forward operation.
    """
    repo = Repo(None)
    await fix_main(repo)


@cli.command()
@click.option("-r", "--remote", type=str, help="Remote. Default: all.", default="--all")
@click.pass_obj
async def push(obj, remote):
    """Push the current state"""

    repo = Repo(None)
    for r in repo.subrepos():
        try:
            cmd = ["git", "-C", r.working_dir, "push", "--tags"]
            if not obj.debug:
                cmd.append("-q")
            elif obj.debug > 1:
                cmd.append("-v")
            cmd.append(remote)
            await run_process(cmd, input=None, stdout=sys.stdout, stderr=sys.stderr)

        except subprocess.CalledProcessError as exc:
            print("  Error in", r.working_dir, file=sys.stderr)
            sys.exit(exc.returncode)


@cli.command()
@click.option("-r", "--remote", type=str, help="Remote to fetch. Default: probably 'origin'.")
@click.option("-b", "--branch", type=str, default=None, help="Branch to merge.")
@click.pass_obj
async def pull(obj, remote, branch):
    """Fetch updates"""

    repo = Repo(None)
    for r in repo.subrepos():
        try:
            cmd = [
                "git",
                "-C",
                r.working_dir,
                "fetch",
                "--recurse-submodules=no",
                "--tags",
            ]
            if not obj.debug:
                cmd.append("-q")
            elif obj.debug > 1:
                cmd.append("-v")
            if remote is not None:
                cmd.append(remote)
            await run_process(cmd, input=None, stdout=sys.stdout, stderr=sys.stderr)

            cmd = ["git", "-C", r.working_dir, "merge", "--ff"]
            if not obj.debug:
                cmd.append("-q")
            elif obj.debug > 1:
                cmd.append("-v")
            if remote is not None:
                if branch is None:
                    branch = "moat" if "moat" in r.refs else "main"
                cmd.append(f"{remote}/{branch}")
            await run_process(cmd, input=None, stdout=sys.stdout, stderr=sys.stderr)

        except subprocess.CalledProcessError as exc:
            print("  Error in", r.working_dir, file=sys.stderr)
            sys.exit(exc.returncode)


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
@click.option("-c", "--cache", is_flag=True, help="don't re-test if unchanged")
async def build(version, no_test, no_commit, no_dirty, cache):
    """
    Rebuild all modified packages.
    """
    bad = False
    repo = Repo(None)
    tags = dict(version)
    skip = set()
    heads = attrdict()

    if repo.is_dirty(index=True, working_tree=True, untracked_files=False, submodules=False):
        print("Please commit top-level changes and try again.")
        return

    if cache:
        cache = Path(".tested.yaml")
        try:
            heads = yload(cache, attr=True)
        except FileNotFoundError:
            pass

    for r in repo.subrepos():
        if not is_clean(r, not no_dirty):
            bad = True
            if not no_dirty:
                skip.add(r)
                continue

        if not no_test and heads.get(r.moat_name, "") != r.commit().hexsha and not run_tests(r):
            print("FAIL", r.moat_name)
            bad = True
            break

        if r.is_dirty(index=True, working_tree=True, untracked_files=True, submodules=False):
            print("DIRTY", r.moat_name)
            if r.moat_name != "src":
                bad = True
            continue

        heads[r.moat_name] = r.commit().hexsha
        t = r.tagged(r.head.commit)
        if t is not None:
            if r.is_dirty(index=False, working_tree=False, untracked_files=False, submodules=True):
                t = None

        if t is None:
            for c in r.commits():
                t = r.tagged(c)
                if t is not None:
                    break
            else:
                print("NOTAG", t, r.moat_name)
                bad = True
                continue
            print("UNTAGGED", t, r.moat_name)
            xt, t = t.name.rsplit(".", 1)
            t = f"{xt}.{int(t) + 1}"
            # t = r.create_tag(t)
            # do not create the tag yet
        else:
            print("TAG", t, r.moat_name)
        tags[r.moat_name] = t

    if cache:
        with cache.open("w") as f:
            # always write cache file
            yprint(heads, stream=f)
    if bad:
        print("No work done. Fix and try again.")
        return

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
            if work or r.is_dirty(index=False, working_tree=False, submodules=True):
                dirty.add(r)
                t = tags[r.moat_name]
                if not isinstance(t, str):
                    xt, t = t.name.rsplit(".", 1)
                    t = f"{xt}.{int(t) + 1}"
                    tags[r.moat_name] = t
                check = True

    if bad:
        print("Partial work done. Fix and try again.")
        return

    if not no_commit:
        for r in repo.subrepos(depth=True):
            if not r.is_dirty(
                index=True,
                working_tree=True,
                untracked_files=False,
                submodules=True,
            ):
                continue

            if r in dirty:
                r.index.commit("Update MoaT requirements")

            for rr in r.subrepos(recurse=False):
                r.git.add(rr.working_dir)
            r.index.commit("Submodule Update")

            t = tags[r.moat_name]
            if isinstance(t, str):
                r.create_tag(t)


add_repr(tomlkit.items.String)
add_repr(tomlkit.items.Integer)
add_repr(tomlkit.items.Bool, bool)
add_repr(tomlkit.items.AbstractTable)
add_repr(tomlkit.items.Array)
