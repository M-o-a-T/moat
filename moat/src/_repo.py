from __future__ import annotations

import logging
import re
import subprocess
import sys
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from shutil import copyfile, copytree, rmtree

import git
from attrs import define, field
from packaging.version import Version

from moat.util import attrdict, yload, yprint

from ._util import dash, undash

from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

PACK = Path("packaging")
ARCH = subprocess.check_output(["/usr/bin/dpkg", "--print-architecture"]).decode("utf-8").strip()
SRC = re.compile(r"^Source:\s+(\S+)\s*$", re.MULTILINE)


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
        v = self.vers
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

    @property
    def srcname(self):
        ctl = PACK / self.dash / "debian" / "control"
        src = ctl.read_text()
        sm = SRC.match(src)
        return sm.group(1)

    def copy(self) -> None:
        """
        Copies the current version of this subsystem to its packaging area.
        """
        if not self.files:
            raise ValueError(f"No files in {self.name}?")
        p = Path("packaging") / self.dash / "src"
        pe = Path("packaging") / self.dash / "examples"
        with suppress(FileNotFoundError):
            rmtree(p)
        with suppress(FileNotFoundError):
            rmtree(pe)
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

        exa = Path("examples") / self.dash
        if exa.is_dir():
            copytree(exa, pe)

    def has_changes(self, main: bool | None = None) -> bool:
        """
        Test whether the given subsystem changed
        between the head and the @tag commit
        """
        head = self._repo.head.commit
        if not hasattr(self, "last_commit"):
            return True
        for d in head.diff(
            self.last_commit if main else self._repo.last_tag,
            paths=self.path if main else Path("packaging") / self.dash,
        ):
            pp = Path(d.b_path)
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

    toplevel: str

    def __init__(self, toplevel: str, *a, **k):
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
    def last_tag(self) -> git.Tag | None:
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

    def tags_of(self, c: git.Commit) -> Sequence[git.Tag]:
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
            ["/usr/bin/git", "ls-files", "-z", "--exclude-standard"],
            check=False,
            stdout=subprocess.PIPE,
        )
        for fn in res.stdout.split(b"\0"):
            if not fn:
                continue
            fn = Path(fn.decode("utf-8"))  # noqa:PLW2901
            if fn.name == ".gitignore":  # heh
                continue
            sb = self.repo_for(fn, True)
            if sb is None:
                continue
            sb = dash(sb)
            if sb not in self._repos:
                raise RuntimeError(f"Inconsistent repo data: {sb} not found")
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
        tag = self.last_tag
        head = self._repo.head.commit
        print("StartDiff B", self, tag, head, file=sys.stderr)
        for d in head.diff(tag):
            if (
                self.repo_for(d.a_path, main) == self.toplevel
                and self.repo_for(d.b_path, main) == self.toplevel
            ):
                continue
            return True
        return False

    def tagged(self, c: git.Commit = None) -> git.Tag | None:
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
            raise ValueError(f"Multiple tags: {tt}")
        return tt[0].name
