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
from copy import deepcopy
from packaging.version import Version

import asyncclick as click
import git
import tomlkit
from moat.util import P, add_repr, attrdict, make_proc, yload, yprint
from packaging.requirements import Requirement
from attrs import define, field
from shutil import rmtree, copyfile, copytree
from contextlib import suppress

logger = logging.getLogger(__name__)

PACK = Path("packaging")
ARCH = subprocess.check_output(["dpkg", "--print-architecture"]).decode("utf-8").strip()


def dash(n: str) -> str:
    """
    moat.foo.bar > moat-foo-bar
    foo.bar > foo-bar
    """
    return n.replace(".", "-")


def undash(n: str) -> str:
    """
    moat-foo-bar > moat.foo.bar
    foo-bar > foo.bar
    """
    return n.replace("-", ".")


class ChangedError(RuntimeError):
    def __init__(subsys, tag, head):
        self.subsys = subsys
        self.tag = tag
        self.head = head

    def __str__(self):
        s = self.subsys or "Something"
        if head is None:
            head = "HEAD"
        else:
            head = head.hexsha[:9]
        return f"{s} changed between {tag.name} and {head}"


class _Common:
    def next_tag(self, major: bool = False, minor: bool = False):
        tag = self.last_tag
        try:
            n = [int(x) for x in tag.split(".")]
            if len(n) != 3:
                raise ValueError(n)
        except ValueError:
            raise ValueError(f"Tag {tag} not in major#.minor#.patch# form.") from None

        if major:
            n = [n[0] + 1, 0, 0]
        elif minor:
            n = [n[0], n[1] + 1, 0]
        else:
            n = [n[0], n[1], n[2] + 1]
        return ".".join(str(x) for x in n)


@define
class Package(_Common):
    _repo: Repo = field(repr=False)
    name: str = field()
    under: str = field(init=False, repr=False)
    path: Path = field(init=False, repr=False)
    files: set(Path) = field(init=False, factory=set, repr=False)
    subs: dict[str, Package] = field(factory=dict, init=False, repr=False)
    hidden: bool = field(init=False, repr=False)

    def __init__(self, repo, name):
        self.__attrs_init__(repo, name)
        self.under = name.replace(".", "_")
        self.path = Path(*name.split("."))
        self.hidden = not (PACK / self.dash).exists()

    @property
    def dash(self):
        return dash(self.name)

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    @property
    def verstr(self):
        v=self.vers
        return f"{v.tag}-{v.pkg}"

    @property
    def vers(self):
        try:
            v = self._repo.versions[self.dash]
        except KeyError:
            self._repo.versions[self.dash] = v = attrdict()
        else:
            if not isinstance(v, dict):
                tag, commit = v
                v = attrdict(
                    tag=tag,
                    pkg=1,
                    rev=commit,
                )
                self._repo.versions[self.dash] = v
        return v

    @vers.setter
    def vers(self, d):
        v = self.vers
        v.update(d)
        return v

    @property
    def last_tag(self):
        return self.vers.tag

    @property
    def last_commit(self):
        return self.vers.rev

    @property
    def mdash(self):
        return dash(self.name)

    def copy(self) -> None:
        """
        Copies the current version of this subsystem to its packaging area.
        """
        if not self.files:
            raise ValueError(f"No files in {self.name}?")
        p = Path("packaging") / self.dash / "src"
        with suppress(FileNotFoundError):
            rmtree(p)
        dest = p / self.path
        dest.mkdir(parents=True)
        for f in self.files:
            pf = p / f
            pf.parent.mkdir(parents=True, exist_ok=True)
            if f.is_dir():
                copytree(f, pf, symlinks=False)
            else:
                copyfile(f, pf, follow_symlinks=True)

        p = Path("packaging") / self.dash
        licd = p / "LICENSE.txt"
        if not licd.exists():
            copyfile("LICENSE.txt", licd)

    def has_changes(self, main: bool | None = None) -> bool:
        """
        Test whether the given subsystem changed
        between the head and the @tag commit
        """
        head = self._repo.head.commit
        try:
            lc = self.last_commit
        except AttributeError:
            return True
        for d in head.diff(
                self.last_commit if main else self._repo.last_tag,
                paths=self.path if main else Path("packaging")/self.dash,
            ):
            pp=Path(d.b_path)
            if pp.name == "changelog" and pp.parent.name == "debian":
                continue
            if (
                self._repo.repo_for(d.a_path, main) != self.name
                and self._repo.repo_for(d.b_path, main) != self.name
            ):
                continue
            return True
        return False


class Repo(git.Repo, _Common):
    """Amend git.Repo with tag caching and pseudo-submodule splitting"""

    moat_tag = None
    _last_tag = None

    toplevel:str

    def __init__(self, toplevel:str, *a, **k):
        self.toplevel = toplevel

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
            self.versions = yload(f, attr=True)
        self.orig_versions = deepcopy(self.versions)


    def write_tags(self):
        if self.versions == self.orig_versions:
            logger.warning("No changed versions. Not tagging.")
            return False
        with open("versions.yaml", "w") as f:
            yprint(self.versions, f)
        self.index.add("versions.yaml")
        return True

    @property
    def last_tag(self) -> Tag | None:
        """
        Return the most-recent tag for this repo
        """
        if self._last_tag is not None:
            return self._last_tag

        tag = None
        vers = None
        for tt in self._commit_tags.values():
            for t in tt:
                if "/" in t.name:
                    continue
                tv = Version(t.name)
                if tag is None or vers < tv:
                    tag = t
                    vers = tv

        if tag is None:
            raise ValueError("No tags found")
        self._last_tag = tag.name
        return tag.name

    @property
    def last_commit(self) -> str:
        t = self.last_tag
        c = self.tags[t].commit
        return c.hexsha

    def part(self, name):
        return self._repos[dash(name)]

    @property
    def _repo(self):
        return self

    @property
    def parts(self):
        return self._repos.values()

    def tags_of(self, c: Commit) -> Sequence[Tag]:
        return self._commit_tags[c]

    def _add_repo(self, name):
        dn = dash(name)
        pn = undash(name)
        if dn in self._repos:
            return self._repos[dn]

        p = Package(self, pn)
        self._repos[dn] = p
        if "." in pn:
            par, nam = pn.rsplit(".", 1)
            pp = self._add_repo(par)
            pp.subs[nam] = p
        return p

    def _make_repos(self) -> dict:
        """Collect subrepos"""
        for fn in Path("packaging").iterdir():
            if not fn.is_dir() or "." in fn.name:
                continue
            self._add_repo(str(fn.name))

        res = subprocess.run(
            [ "git","ls-files","-z","--exclude-standard" ],
            check=True,
            stdout=subprocess.PIPE,
        )
        for fn in res.stdout.split(b"\0"):
            if not fn:
                continue
            fn = Path(fn.decode("utf-8"))
            if fn.name == ".gitignore":  # heh
                continue
            sb = self.repo_for(fn, True)
            if sb is None:
                continue
            sb = dash(sb)
            if sb not in self._repos:
                breakpoint()
            self._repos[sb].files.add(fn)

    def repo_for(self, path: Path | str, main: bool | None) -> str:
        """
        Given a file path, returns the subrepo in question
        """
        sc = self._repos["moat"]
        path = Path(path)

        if main is not True and path.parts[0] == "packaging":
            try:
                return undash(path.parts[1])
            except IndexError:
                return None

        name = path.parts[0]
        if main is not False and name == self.toplevel:
            res = name
            for p in path.parts[1:]:
                if p not in sc.subs:
                    break
                sc = sc.subs[p]
                name += "." + p
                if not sc.hidden:
                    res = name
            return res

        return None

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

    def has_changes(self, main: bool | None = None) -> bool:
        """
        Test whether any subsystem changed since the "tagged" commit

        """
        if tag is None:
            tag = self.last_tag
        head = self._repo.head.commit
        print("StartDiff B",self,tag,head,file=sys.stderr)
        for d in head.diff(tag):
            if self.repo_for(d.a_path, main) == self.toplevel and self.repo_for(d.b_path, main) == self.toplevel:
                continue
            return True
        return False

    def tagged(self, c: Commit = None) -> Tag | None:
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


def run_tests(pkg: str | None, *opts) -> bool:
    """Run subtests for subpackage @pkg."""

    if pkg is None:
        tests = Path("tests")
    else:
        tests = dash(pkg).replace("-", "_")
        tests = Path("tests") / tests

    if not Path(tests):
        # No tests. Assume it's OK.
        return True
    try:
        print("\n*** Testing:", pkg)
        subprocess.run(
            ["python3", "-mpytest", *opts, tests],
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=True,
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


@cli.command(
    epilog="""
The default for building Debian packages is '--no-sign --build=binary'.
'--no-sign' is dropped when you use '--deb'.
The binary-only build is currently unconditional.

The default for uploading to Debian via 'dput' is '--unchecked ext';
it is dropped when you use '--dput'.
""",
)
@click.option("-f", "--no-dirty", is_flag=True, help="don't check for dirtiness (DANGER)")
@click.option("-F", "--no-tag", is_flag=True, help="don't check for tag uptodate-ness (DANGER)")
@click.option("-D", "--no-deb", is_flag=True, help="don't build Debian packages")
@click.option("-C", "--no-commit", is_flag=True, help="don't commit the result")
@click.option(
    "-V",
    "--no-version",
    is_flag=True,
    help="don't update dependency versions in pyproject files",
)
@click.option("-P", "--no-pypi", is_flag=True, help="don't push to PyPI")
@click.option("-T", "--no-test", is_flag=True, help="don't run tests")
@click.option("-G", "--test-chg", is_flag=True, help="rebuild if changes file doesn't exist")
@click.option("-o", "--pytest", "pytest_opts", type=str, multiple=True, help="Options for pytest")
@click.option("-d", "--deb", "deb_opts", type=str, multiple=True, help="Options for debuild")
@click.option("-p", "--dput", "dput_opts", type=str, multiple=True, help="Options for dput")
@click.option("-r", "--run", is_flag=True, help="actually do the tagging")
@click.option("-s", "--skip", "skip_", type=str, multiple=True, help="skip these repos")
@click.option("-m", "--minor", is_flag=True, help="create a new minor version")
@click.option("-M", "--major", is_flag=True, help="create a new major version")
@click.option("-t", "--tag", "forcetag", type=str, help="Use this explicit tag value")
@click.option("-a", "--auto-tag", "autotag", is_flag=True, help="Auto-retag updated packages")
@click.option(
    "-v",
    "--version",
    type=(str, str),
    multiple=True,
    help="Update external dependency",
)
@click.argument("parts", nargs=-1)
@click.pass_obj
async def build(
    obj,
    no_commit,
    no_dirty,
    no_test,
    no_tag,
    no_pypi,
    parts,
    dput_opts,
    pytest_opts,
    deb_opts,
    run,
    test_chg,
    version,
    no_version,
    no_deb,
    skip_,
    major,
    minor,
    forcetag,
    autotag,
):
    """
    Rebuild all modified packages.
    """
    cfg = obj.cfg
    g_done = cfg.get("src", {}).get("done")
    if g_done is not None:
        g_done = Path(g_done)
    else:
        g_done = Path("/tmp/nonexistent")
    repo = Repo(cfg.src.toplevel, None)

    tags = dict(version)
    skip = set()
    for s in skip_:
        for sn in s.split(","):
            skip.add(dash(sn))
    parts = set(dash(s) for s in parts)
    debversion = {}

    if no_tag and not no_version:
        print("Warning: not updating moat versions in pyproject files", file=sys.stderr)
    if minor and major:
        raise click.UsageError("Can't change both minor and major!")
    if autotag and no_tag:
        raise click.UsageError("Can't change tags without verifying them!")
    if forcetag and (minor or major):
        raise click.UsageError("Can't use an explicit tag with changing minor or major!")

    if forcetag is None:
        forcetag = repo.next_tag(major, minor)

    if parts:
        repos = [repo.part(x) for x in parts]
    else:
        if not skip:
            pass
        repos = [
            x
            for x in repo.parts
            if not x.hidden and x.dash not in skip and not (PACK / x.dash / "SKIP").exists()
        ]

    for name in PACK.iterdir():
        if name.suffix != ".changes":
            continue
        name = name.stem
        name, vers, _ = name.split("_")
        debversion[name] = vers.rsplit("-", 1)[0]

    # Step 0: basic check
    if not no_dirty:
        if repo.is_dirty(index=False, working_tree=True, untracked_files=True, submodules=False):
            if not run:
                print("*** Repository is not clean.", file=sys.stderr)
            else:
                print("Please commit changes and try again.", file=sys.stderr)
                return

    # Step 1: check for changed files since last tagging
    if autotag:
        for r in repos:
            if r.has_changes(True):
                try:
                    nt = r.next_tag()
                except AttributeError:
                    nt = "1.0.0" if major else "0.1.0" if minor else "0.0.1"
                r.vers = attrdict(
                    tag=nt,
                    pkg=1,
                    rev=repo.head.commit.hexsha,
                )
                logger.debug("Changes: %s %s",r.name,r.verstr)
            elif r.has_changes(False):
                r.vers.pkg += 1
                r.vers.rev = repo.head.commit.hexsha
                logger.debug("Build Changes: %s %s",r.name,r.verstr)
            else:
                logger.debug("No Changes: %s %s",r.name,r.verstr)

    elif not no_tag:
        err = set()
        for r in repos:
            try:
                tag = r.last_tag
            except KeyError:
                rd = PACK / r.dash
                p = rd / "pyproject.toml"
                if not p.is_file():
                    continue
                raise
            tags[r.mdash] = tag
            if r.has_changes(True):
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
                fails.add(p)
        if fails:
            if not run:
                print("*** Tests failed:", *fails, file=sys.stderr)
            else:
                print("Failed tests:", *fails, file=sys.stderr)
                print("Fix and try again.", file=sys.stderr)
                return

    # Step 3: set version and fix versioned dependencies
    for r in repos:
        rd = PACK / r.dash
        p = rd / "pyproject.toml"
        skip = rd / "SKIP.build"

        if skip.is_file():
            # bad=True
            print("Skip:", r.name, file=sys.stderr)
            continue

        if p.is_file():
            with p.open("r") as f:
                pr = tomlkit.load(f)
                pr["project"]["version"] = r.last_tag

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
            ltag = r.last_tag
            if r.vers.get("deb","-") == f"{ltag}-{r.vers.pkg}":
                continue
            rd = PACK / r.dash
            p = rd / "debian"
            if not p.is_dir():
                continue
            if not (rd/"debian"/"changelog").exists():
                subprocess.run(
                    [
                        "debchange",
                        "--create",
                        "--newversion", f"{r.last_tag}-{r.vers.pkg}",
                        "--package", r.mdash,
                        f"Initial release for {forcetag}",
                     ],
                    cwd=rd,
                    check=True,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )

            try:
                res = subprocess.run(
                    ["dpkg-parsechangelog", "-l", "debian/changelog", "-S", "version"],
                    cwd=rd,
                    check=True,
                    stdout=subprocess.PIPE,
                )
                tag,ptag = res.stdout.strip().decode("utf-8").rsplit("-", 1)
                ptag = int(ptag)
                if tag != ltag or r.vers.pkg > ptag:
                    subprocess.run(
                        [
                            "debchange",
                            "--distribution",
                            "unstable",
                            "--newversion",
                            f"{ltag}-{r.vers.pkg}",
                            f"New release for {forcetag}",
                        ],
                        cwd=rd,
                        check=True,
                    )
                    repo.index.add(p / "changelog")

                elif tag == ltag and r.vers.pkg < ptag:
                    r.vers.pkg = ptag

                changes = PACK / f"{r.mdash}_{ltag}-{r.vers.pkg}_{ARCH}.changes"
                if debversion.get(r.dash, "") != ltag or r.vers.pkg != ptag or test_chg and not changes.exists():

                    subprocess.run(["debuild", "--build=binary"] + deb_opts, cwd=rd, check=True)
            except subprocess.CalledProcessError:
                if not run:
                    print("*** Failure packaging", r.name, file=sys.stderr)
                else:
                    print("Failure packaging", r.name, file=sys.stderr)
                    no_commit=True
                    no_deb=True
                    no_pypi=True

    # Step 5: build PyPI package
    if not no_pypi:
        err = set()
        up = set()
        for r in repos:
            rd = PACK / r.dash
            p = rd / "pyproject.toml"
            if not p.is_file():
                continue
            tag = r.last_tag
            name = r.dash
            if r.vers.get("pypi","-") == r.last_tag:
                continue

            targz = rd / "dist" / f"{r.under}-{tag}.tar.gz"
            done = rd / "dist" / f"{r.under}-{tag}.done"

            if done.exists():
                pass
            elif targz.is_file():
                up.add(r)
            else:
                try:
                    subprocess.run(["python3", "-mbuild", "-snw"], cwd=rd, check=True)
                except subprocess.CalledProcessError:
                    err.add(r.name)
                else:
                    up.add(r)
        if err:
            if not run:
                print("*** Build errors:", file=sys.stderr)
                print("***", *err, file=sys.stderr)
            else:
                print("Build errors:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please fix and try again.", file=sys.stderr)
                no_commit=True
                no_deb=True

        # Step 6: upload PyPI package
        elif run:
            err = set()
            for r in up:
                rd = PACK / r.dash
                p = rd / "pyproject.toml"
                if not p.is_file():
                    continue
                tag = r.last_tag
                name = r.dash
                targz = Path("dist") / f"{r.under}-{tag}.tar.gz"
                whl = Path("dist") / f"{r.under}-{tag}-py3-none-any.whl"
                try:
                    res = subprocess.run(
                        ["twine", "upload", str(targz), str(whl)],
                        cwd=rd,
                        check=True,
                    )
                except subprocess.CalledProcessError:
                    err.add(r.name)
                else:
                    done = rd / "dist" / f"{r.under}-{tag}.done"
                    done.touch()
            if err:
                print("Upload errors:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please fix(?) and try again.", file=sys.stderr)
                no_commit=True
                no_deb=True
            else:
                r.vers.pypi = r.last_tag

    # Step 7: upload Debian package
    if run and not no_deb:
        err = set()
        if not dput_opts:
            dput_opts = ["-u", "ext"]
        for r in repos:
            ltag = r.last_tag
            if r.vers.get("deb","-") == f"{ltag}-{r.vers.pkg}":
                continue
            if not (PACK / r.dash / "debian").is_dir():
                continue
            changes = PACK / f"{r.mdash}_{ltag}-{r.vers.pkg}_{ARCH}.changes"
            done = PACK / f"{r.mdash}_{ltag}-{r.vers.pkg}_{ARCH}.done"
            if done.exists():
                continue
            if g_done is not None:
                gdone = g_done / f"{r.mdash}_{ltag}-{r.vers.pkg}_{ARCH}.done"
                if gdone.exists():
                    continue
            try:
                subprocess.run(["dput", *dput_opts, str(changes)], check=True)
            except subprocess.CalledProcessError:
                err.add(r.name)
            else:
                done.touch()
        if err:
            print("Upload errors:", file=sys.stderr)
            print(*err, file=sys.stderr)
            print("Please fix(?) and try again.", file=sys.stderr)
            no_commit=True
        else:
            r.vers.deb = f"{ltag}-{r.vers.pkg}"

    # Step 8: commit the result
    if run:
        if repo.write_tags() and not no_commit:
            repo.index.commit(f"Build version {forcetag}")
            git.TagReference.create(repo, forcetag)


add_repr(tomlkit.items.String)
add_repr(tomlkit.items.Integer)
add_repr(tomlkit.items.Bool, bool)
add_repr(tomlkit.items.AbstractTable)
add_repr(tomlkit.items.Array)
