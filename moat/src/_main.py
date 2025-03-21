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
from contextlib import suppress

logger = logging.getLogger(__name__)

PACK=Path("packaging")

def dash(n:str) -> str:
    """
    moat.foo.bar > foo-bar
    foo.bar > ext-foo-bar
    """
    if n in ("main","moat"):
        return "main"
    if "." not in n:  # also applies to single-name packages
        return n

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

class _Common:
    _last_tag:str = None

    def next_tag(self,major:bool=False,minor:bool=False):
        tag = self.last_tag()[0]
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

@define
class Package(_Common):
    _repo:Repo = field(repr=False)
    name:str = field()
    under:str = field(init=False,repr=False)
    path:Path = field(init=False,repr=False)
    files:set(Path) = field(init=False,factory=set,repr=False)
    subs:dict[str,Package] = field(factory=dict,init=False,repr=False)
    hidden:bool = field(init=False)

    def __init__(self, repo, name):
        self.__attrs_init__(repo,name)
        self.under = name.replace(".","_")
        self.path = Path(*name.split("."))
        self.hidden = not (PACK/self.dash).exists()

    @property
    def dash(self):
        return dash(self.name)

    def __eq__(self, other):
        return self.name==other.name

    def __hash__(self):
        return hash(self.name)

    @property
    def mdash(self):
        d=dash(self.name)
        if d.startswith("ext-"):
            return d[4:]
        else:
            return "moat-"+d

    def populate(self, path:Path, real=None):
        """
        Collect this package's file names.
        """
        self.path = path
        for fn in path.iterdir():
            if fn.name == "__pycache__":
                continue
            if (sb := self.subs.get(fn.name,None)) is not None:
                sb.populate(fn, real=self if sb.hidden else None)
            else:
                (real or self).files.add(fn)

    def copy(self) -> None:
        """
        Copies the current version of this subsystem to its packaging area.
        """
        if not self.files:
            raise ValueError(f"No files in {self.name}?")
        p = Path("packaging")/self.dash
        with suppress(FileNotFoundError):
            rmtree(p/"moat")
        dest = p/self.path
        dest.mkdir(parents=True)
        for f in self.files:
            pf=p/f
            pf.parent.mkdir(parents=True,exist_ok=True)
            if f.is_dir():
                copytree(f, pf, symlinks=False)
            else:
                copyfile(f, pf, follow_symlinks=True)
        licd = p/"LICENSE.txt"
        if not licd.exists():
            copyfile("LICENSE.txt", licd)

    def last_tag(self, unchanged:bool=False) -> Tag|None:
        """
        Return the most-recent tag for this subrepo
        """
        tag,commit = self._repo.versions[self.dash]
        if unchanged and self.has_changes(commit):
            raise ChangedError(subsys,t,ref)
        return tag,commit

    def has_changes(self, tag:Commit=None) -> bool:
        """
        Test whether the given subsystem (or any subsystem)
        changed between the head and the @tag commit
        """
        if tag is None:
            tag,commit = self.last_tag()
        else:
            commit = tag
        head = self._repo.head.commit
        for d in head.diff(commit):
            if self._repo.repo_for(d.a_path) != self.name and self._repo.repo_for(d.b_path) != self.name:
                continue
            return True
        return False


class Repo(git.Repo,_Common):
    """Amend git.Repo with tag caching and pseudo-submodule splitting"""

    moat_tag = None
    _last_tag=None

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
        with open("versions.yaml") as f:
            self.versions = yload(f)

    def write_tags(self):
        with open("versions.yaml","w") as f:
            yprint(self.versions,f)
        self.index.add("versions.yaml")


    def last_tag(self, unchanged:bool=False) -> Tag|None:
        """
        Return the most-recent tag for this repo
        """
        if self._last_tag is not None:
            return self._last_tag,self._last_tag
        for c in self._repo.commits(self.head.commit):
            t = self.tagged(c)
            if t is None:
                continue

            self._last_tag = t
            if unchanged and self.has_changes(c):
                raise ChangedError(subsys,t)
            return t,t

        raise ValueError(f"No tags found")

    def part(self, name):
        return self._repos[dash(name)]

    @property
    def _repo(self):
        return self

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
            if not fn.is_dir() or "." in fn.name:
                continue
            self._add_repo(str(fn.name))

        self._repos["main"].populate(Path("moat"))

    def repo_for(self, path:Path|str) -> str:
        """
        Given a file path, returns the subrepo in question
        """
        name = "moat"
        sc = self._repos["main"]
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

    def has_changes(self, tag:Tag=None) -> bool:
        """
        Test whether any subsystem changed since the "tagged" commit

        """
        if tag is None:
            tag,commit = self.last_tag()
        head = self._repo.head.commit
        for d in head.diff(tag):
            if self.repo_for(d.a_path) == "moat" and self.repo_for(d.b_path) == "moat":
                continue
            return True
        return False


    def tagged(self, c:Commit=None) -> Tag|None:
        """Return a commit's tag name.
        Defaults to the head commit.
        Returns None if no tag, raises ValueError if more than one is found.
        """
        if c is None:
            c = self.head.commit
        if c not in self._commit_tags:
            return None
        tt = self._commit_tags[c]

        tt = [t for t in tt if "/" not in t.name]

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


def run_tests(pkg: str|None, *opts) -> bool:
    """Run subtests for subpackage @pkg."""

    if pkg is None:
        tests = Path("tests")
    else:
        tests = dash(pkg).replace("-","_")
        tests = Path("tests")/tests

    if not Path(tests):
        # No tests. Assume it's OK.
        return True
    try:
        print("\n*** Testing:", pkg)
        # subprocess.run(["python3", "-mtox"], cwd=repo.working_dir, check=True)
        subprocess.run(["python3","-mpytest", *opts, tests], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, check=True)
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
                tag,commit = r.last_tag()
            except ValueError:
                print(f"{r.dash} -")
                continue
            if r.has_changes(commit):
                print(f"{r.dash} {tag} STALE")
            else:
                print(f"{r.dash} {tag}")
        return

    if repo.is_dirty(index=True, working_tree=True, untracked_files=True, submodules=False):
        print("Repo is dirty. Not tagging globally.", file=sys.stderr)
        return

    changed=False
    for r in repo.parts:
        tag,commit = r.last_tag()
        if not r.has_changes(commit):
            print(repo.dash,tag,"UNCHANGED")
            continue

        tag = r.next_tag()
        print(repo.dash,tag)
        if not run:
            continue

        repo.versions[r.dash] = (tag,repo.head.commit.hexsha[:9])
        changed=True

    if changed:
        repo.write_tags()


@cli.command()
@click.option("-r", "--run", is_flag=True, help="actually do the tagging")
@click.option("-m", "--minor", is_flag=True, help="create a new minor version")
@click.option("-M", "--major", is_flag=True, help="create a new major version")
@click.option("-s", "--subtree", type=str, help="Tag this partial module")
@click.option("-v", "--tag", "force", type=str, help="Use this explicit tag value")
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
        r = repo.part(subtree)
    else:
        r = repo

    if show:
        tag,commit = r.last_tag()
        if r.has_changes(commit):
            print(f"{tag} STALE")
        else:
            print(tag)
        return

    if force:
        tag = force
    else:
        tag = r.next_tag(major,minor)

    if run or subtree:
        if subtree:
            repo.versions[r.dash] = (tag,repo.head.commit.hexsha[:9])
            repo.write_tags()
        else:
            git.TagReference.create(repo,tag, force=FORCE)
        print(f"{tag}")
    else:
        print(f"{tag} DRY_RUN")


@cli.command()
@click.option("-P", "--no-pypi", is_flag=True, help="don't push to PyPi")
@click.option("-D", "--no-deb", is_flag=True, help="don't debianize")
@click.option("-d", "--deb", type=str, help="Debian archive to push to (from dput.cfg)")
@click.option("-o", "--only", type=str, multiple=True, help="affect only this package")
@click.option("-s", "--skip", type=str, multiple=True, help="skip this package")
async def publish(no_pypi, no_deb, skip, only, deb):
    """
    Publish modules to PyPi and/or Debian.

    MoaT modules can be given as shorthand, i.e. with dashes and excluding
    the "moat-" prefix.
    """
    repo = Repo(None)
    if only and skip:
        raise click.UsageError("You can't both include and exclude packages.")

    if only:
        repos = (repo.subrepo(x) for x in only)
    else:
        s = set()
        for sk in skip:
            s += set(sk.split(","))
        repos = (x for x in repo.parts if dash(x.name) not in sk)

    deb_args = "-b -us -uc".split()

    for r in repos:
        t,c = r.last_tag
        if r.has_changes(c):
            print(f"Error: changes in {r.name} since tag {t.name}")
            continue

        print(f"Processing {r.name}, tag: {t.name}")
        r.copy()
        rd=PACK/r.dash

        if not no_deb:
            p = rd / "debian"
            if not p.is_dir():
                continue
            subprocess.run(["debuild"] + deb_args, cwd=rd, check=True)

    if not no_pypi:
        for r in repos:
            p = Path(r.working_dir) / "pyproject.toml"
            if not p.is_file():
                continue
            print(r.working_dir)
            subprocess.run(["make", "pypi"], cwd=r.working_dir, check=True)


@cli.command(epilog="""
The default for building Debian packages is '--no-sign --build=binary'.
'--no-sign' is dropped when you use '--deb'.
The binary-only build is currently unconditional.

The default for uploading to Debian via 'dput' is '--unchecked ext';
it is dropped when you use '--dput'.
""")
@click.option("-f", "--no-dirty", is_flag=True, help="don't check for dirtiness (DANGER)")
@click.option("-F", "--no-tag", is_flag=True, help="don't check for tag uptodate-ness (DANGER)")
@click.option("-D", "--no-deb", is_flag=True, help="don't build Debian packages")
@click.option("-C", "--no-commit", is_flag=True, help="don't commit the result")
@click.option("-V", "--no-version", is_flag=True, help="don't update dependency versions in pyproject files")
@click.option("-P", "--no-pypi", is_flag=True, help="don't push to PyPI")
@click.option("-T", "--no-test", is_flag=True, help="don't run tests")
@click.option("-o", "--pytest", "pytest_opts", type=str,multiple=True, help="Options for pytest")
@click.option("-d", "--deb", "deb_opts", type=str,multiple=True, help="Options for debuild")
@click.option("-p", "--dput", "dput_opts", type=str,multiple=True, help="Options for dput")
@click.option("-r", "--run", is_flag=True, help="actually do the tagging")
@click.option("-s", "--skip", "skip_", type=str,multiple=True, help="skip these repos")
@click.option("-m", "--minor", is_flag=True, help="create a new minor version")
@click.option("-M", "--major", is_flag=True, help="create a new major version")
@click.option("-t", "--tag", "forcetag", type=str, help="Use this explicit tag value")
@click.option(
    "-v",
    "--version",
    type=(str, str),
    multiple=True,
    help="Update external dependency",
)
@click.argument("parts", nargs=-1)
async def build(no_commit, no_dirty, no_test, no_tag, no_pypi, parts, dput_opts, pytest_opts, deb_opts, run, version, no_version, no_deb, skip_, major,minor,forcetag):
    """
    Rebuild all modified packages.
    """
    repo = Repo(None)

    tags = dict(version)
    skip = set()
    for s in skip_:
        for sn in s.split(","):
            skip.add(dash(sn))
    parts = set(dash(s) for s in parts)
    debversion={}

    if no_tag and not no_version:
        print("Warning: not updating moat versions in pyproject files", file=sys.stderr)
    if minor and major:
        raise click.UsageError("Can't change both minor and major!")
    if forcetag and (minor or major):
        raise click.UsageError("Can't use an explicit tag with changing minor or major!")

    if forcetag is None:
        forcetag = repo.next_tag(major,minor)

    full = False
    if parts:
        repos = [ repo.part(x) for x in parts ]
    else:
        if not skip:
            full = True
        repos = [ x for x in repo.parts if not x.hidden and x.dash not in skip and not (PACK/x.dash/"SKIP").exists() ]

    for name in PACK.iterdir():
        if name.suffix != ".changes":
            continue
        name=name.stem
        name,vers,_ = name.split("_")
        if name.startswith("moat-"):
            name = name[5:]
        else:
            name = "ext-"+name
        debversion[name]=vers.rsplit("-",1)[0]

    
    # Step 0: basic check
    if not no_dirty:
        if repo.is_dirty(index=True, working_tree=True, untracked_files=True, submodules=False):
            if not run:
                print("*** Repository is not clean.", file=sys.stderr)
            else:
                print("Please commit top-level changes and try again.", file=sys.stderr)
                return

    # Step 1: check for changed files since last tagging
    if not no_tag:
        err = set()
        for r in repos:
            try:
                tag,commit = r.last_tag()
            except KeyError:
                rd = PACK/r.dash
                p = rd / "pyproject.toml"
                if not p.is_file():
                    continue
                raise
            tags[r.mdash] = tag
            if r.has_changes(commit):
                err.add(r.dash)
        if err:
            if not run:
                print("*** Untagged changes:", file=sys.stderr)
                print("***", *err, file=sys.stderr)
            else:
                print("Untagged changes:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please tag (moat src tag -s PACKAGE) and try again.", file=sys.stderr)
                return

    # Step 2: run tests
    if not no_test:
        fails = set()
        for p in parts:
            if not run_tests(p, *pytest_opts):
                fails.add(p.name)
        if fails:
            if not run:
                print(f"*** Tests failed:", *fails, file=sys.stderr)
            else:
                print(f"Failed tests:", *fails, file=sys.stderr)
                print(f"Fix and try again.", file=sys.stderr)
                return

    # Step 3: set version and fix versioned dependencies
    for r in repos:
        rd = PACK/r.dash
        p = rd / "pyproject.toml"
        if not p.is_file():
            # bad=True
            print("Skip:", r.name, file=sys.stderr)
            continue
        with p.open("r") as f:
            pr = tomlkit.load(f)
            pr["project"]["version"] = r.last_tag()[0]

        if not no_version:
            try:
                deps = pr["project"]["dependencies"]
            except KeyError:
                pass
            else:
                fix_deps(deps, tags)
            try:
                deps = pr["project"]["optional_dependencies"]
            except KeyError:
                pass
            else:
                for v in deps.values():
                    fix_deps(v, tags)

        p.write_text(pr.as_string())
        repo.index.add(p)

    # Step 3: copy to packaging dir
    for r in repos:
        r.copy()
        
    # Step 4: build Debian package
    if not no_deb:
        if not deb_opts:
            deb_opts = ["--no-sign"]

        for r in repos:
            rd=PACK/r.dash
            p = rd / "debian"
            if not p.is_dir():
                continue
            try:
                res = subprocess.run(["dpkg-parsechangelog","-l","debian/changelog","-S","version"], cwd=rd, check=True, stdout=subprocess.PIPE)
                tag = res.stdout.strip().decode("utf-8").rsplit("-",1)[0]
                ltag = r.last_tag()[0]
                if tag != ltag:
                    subprocess.run(["debchange", "--distribution","unstable", "--newversion",ltag+"-1",f"New release for {forcetag}"] , cwd=rd, check=True)
                    repo.index.add(p/"changelog")

                if debversion.get(r.dash,"") != ltag:
                    subprocess.run(["debuild", "--build=binary"] + deb_opts, cwd=rd, check=True)
            except subprocess.CalledProcessError:
                if not run:
                    print("*** Failure packaging",r.name,file=sys.stderr)
                else:
                    print("Failure packaging",r.name,file=sys.stderr)
                    return

    # Step 5: build PyPI package
    if not no_pypi:
        err=set()
        up=set()
        for r in repos:
            rd=PACK/r.dash
            p = rd / "pyproject.toml"
            if not p.is_file():
                continue
            tag = r.last_tag()[0]
            name = r.dash
            if name.startswith("ext-"):
                name=name[4:]
            else:
                name="moat-"+r.dash

            targz = rd/"dist"/f"{r.under}-{tag}.tar.gz"
            done = rd/"dist"/f"{r.under}-{tag}.done"
            if targz.is_file():
                print(f"{name}: Source package exists.")
                if not done.exists():
                    up.add(r)
            else:
                try:
                    subprocess.run(["python3", "-mbuild", "-snw"], cwd=rd, check=True)
                except subprocess.CalledProcessError:
                    err.add(r.name)
        if err:
            if not run:
                print("*** Build errors:", file=sys.stderr)
                print("***", *err, file=sys.stderr)
            else:
                print("Build errors:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please fix and try again.", file=sys.stderr)
                return
        
        # Step 6: upload PyPI package
        if run:
            err=set()
            for p in up:
                rd=PACK/r.dash
                p = rd / "pyproject.toml"
                if not p.is_file():
                    continue
                tag = r.last_tag()[0]
                name = r.dash
                if name.startswith("ext-"):
                    name=name[4:]
                else:
                    name="moat-"+r.dash
                targz = Path("dist")/f"{name}-{tag}.tar.gz"
                whl = Path("dist")/f"{name}-{tag}-py3-none-any.whl"
                try:
                    subprocess.run(["twine", "upload", str(targz), str(whl)], cwd=rd, check=True)
                except subprocess.CalledProcessError:
                    err.add(r.name)
                else:
                    done = rd/"dist"/f"{r.under}-{tag}.done"
                    done.touch()
            if err:
                print("Upload errors:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please fix(?) and try again.", file=sys.stderr)
                return

    # Step 7: upload Debian package
    if run and not no_deb:
        err = set()
        if not dput_opts:
            dput_opts = ["-u","ext"]
        for r in repos:
            try:
                subprocess.run(["dput", *dput_opts, "upload", str(targz), str(whl)], cwd=PACK, check=True)
            except subprocess.CalledProcessError:
                err.add(r.name)
        if err:
            print("Upload errors:", file=sys.stderr)
            print(*err, file=sys.stderr)
            print("Please fix(?) and try again.", file=sys.stderr)
            return

    # Step 8: commit the result
    if run and not no_commit:
        repo.write_tags()
        repo.index.commit(f"Build version {forcetag}")
        git.TagReference.create(repo, forcetag)


add_repr(tomlkit.items.String)
add_repr(tomlkit.items.Integer)
add_repr(tomlkit.items.Bool, bool)
add_repr(tomlkit.items.AbstractTable)
add_repr(tomlkit.items.Array)
