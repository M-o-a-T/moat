"Build command"

# command line interface
# pylint: disable=missing-module-docstring
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from anyio import Path

import asyncclick as click
import git
from packaging.requirements import Requirement

from moat.util import attrdict
from moat.util.exec import run as run_

from ._repo import Repo
from ._toml import tomlkit
from ._util import dash

logger = logging.getLogger(__name__)

PACK = Path("packaging")
DIST_PYPI = Path("dist/pypi")
DIST_DEBIAN = Path("dist/debian")
ARCH = subprocess.check_output(["/usr/bin/dpkg", "--print-architecture"]).decode("utf-8").strip()
SRC = re.compile(r"^Source:\s+(\S+)\s*$", re.MULTILINE)


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


async def run_tests(pkg: str | None, opts, debug: bool) -> bool:
    """Run subtests for subpackage @pkg."""

    if pkg is None:
        tests = Path("tests")
    else:
        tests = Path("tests") / pkg

    if not await tests.exists():
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
            echo=debug,
        )
    except subprocess.CalledProcessError:
        return False
    else:
        return True


def do_autotag(repo, repos, major, minor):
    "Create tags for updated subrepos"
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
            logger.debug("Changes: %s %s", r.name, r.verstr)
        elif r.has_changes(False):
            r.vers.pkg += 1
            r.vers.rev = repo.head.commit.hexsha
            logger.debug("Build Changes: %s %s", r.name, r.verstr)
        else:
            logger.debug("No Changes: %s %s", r.name, r.verstr)


async def do_runtest(repos, pytest_opts, debug):
    "Run tests"
    fails = set()
    for r in repos:
        if not await run_tests(r.under, pytest_opts, debug):
            fails.add(r.name)
    return fails


async def do_versions(repo, repos, tags, no):
    "set versions"
    for r in repos:
        rd = PACK / r.dash
        p = rd / "pyproject.toml"
        skip = rd / "SKIP.build"

        if await skip.is_file():
            # bad=True
            print("Skip:", r.name, file=sys.stderr)
            continue

        if await p.is_file():
            content = await p.read_text()
            pr = tomlkit.loads(content)
            pr["project"]["version"] = r.last_tag

            if not no.version:
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
            await p.write_text(pr.as_string())

            repo.index.add(str(p))


def do_copy_repos(repos):
    "copy repos to packaging dir"
    for r in repos:
        r.copy()


async def do_build_deb(repo, repos, deb_opts, no, debug, forcetag):
    "Build Debian packages"
    await DIST_DEBIAN.mkdir(parents=True, exist_ok=True)

    for r in repos:
        ltag = r.last_tag
        if r.vers.get("deb", "-") == f"{ltag}-{r.vers.pkg}":
            continue
        rd = PACK / r.dash
        p = rd / "debian"
        if not await p.is_dir():
            continue
        if not await (rd / "debian" / "changelog").exists():
            await run_(
                "debchange",
                "--create",
                "--newversion",
                f"{r.last_tag}-{r.vers.pkg}",
                "--package",
                r.mdash,
                f"Initial release for {forcetag}",
                cwd=rd,
                echo=debug,
            )

        try:
            res = await run_(
                "dpkg-parsechangelog",
                "-l",
                "debian/changelog",
                "-S",
                "version",
                cwd=rd,
                capture=True,
                echo=debug,
            )
            tag, ptag = res.strip().rsplit("-", 1)
            ptag = int(ptag)
            if tag != ltag or r.vers.pkg > ptag:
                res = await run_(
                    "dpkg-parsechangelog",
                    "-n1",
                    "-s",
                    "Changes",
                    cwd=rd,
                    capture=True,
                    echo=debug,
                )
                if res[-1].strip().endswith(f" for {forcetag}"):
                    # New version for the same tag.
                    # Restore the previous version before continuing
                    # so we don't end up with duplicates.
                    await run_("git", "restore", "-s", repo.last_tag, cwd=rd)
                await run_(
                    "debchange",
                    "--distribution",
                    "unstable",
                    "--newversion",
                    f"{ltag}-{r.vers.pkg}",
                    f"New release for {forcetag}",
                    cwd=rd,
                    echo=debug,
                )
                repo.index.add(p / "changelog")

            elif tag == ltag and r.vers.pkg < ptag:
                r.vers.pkg = ptag

            changes = DIST_DEBIAN / f"{r.srcname}_{ltag}-{r.vers.pkg}_{ARCH}.changes"
            if not await changes.exists() or no.test_chg:
                await run_("debuild", "--build=binary", *deb_opts, cwd=rd, echo=debug)
                # Move built Debian artifacts to dist/debian
                # First, move files matching the glob pattern
                prefix = f"{r.srcname}_{ltag}-{r.vers.pkg}_"
                moved_files = set()
                async for artifact in PACK.glob(f"{prefix}*"):
                    if await artifact.is_file():
                        await artifact.rename(DIST_DEBIAN / artifact.name)
                        moved_files.add(artifact.name)

                # Also move all files listed in the .changes file
                content = await changes.read_text()
                in_files_section = False
                for line in content.split("\n"):
                    if line.startswith("Files:"):
                        in_files_section = True
                        continue
                    if not in_files_section:
                        continue
                    if not line.startswith((" ", "\t")):
                        # End of Files section
                        break
                    # Parse: md5sum size section priority filename
                    parts = line.split()
                    if len(parts) >= 5:
                        filename = parts[4]
                        if filename not in moved_files:
                            src = PACK / filename
                            if await src.exists():
                                dest = DIST_DEBIAN / filename
                                shutil.move(str(src), str(dest))
                                moved_files.add(filename)

        except subprocess.CalledProcessError:
            if no.run:
                print("*** Failure packaging", r.name, file=sys.stderr)
            else:
                print("Failure packaging", r.name, file=sys.stderr)
                no.commit = True
                no.deb = True
                no.pypi = True


async def do_build_pypi(repos, no, debug):
    "build for pypi"
    err = set()
    up = set()
    await DIST_PYPI.mkdir(parents=True, exist_ok=True)

    for r in repos:
        rd = PACK / r.dash
        p = rd / "pyproject.toml"
        if not await p.is_file():
            continue
        tag = r.last_tag
        if r.vers.get("pypi", "-") == r.last_tag:
            continue

        targz = DIST_PYPI / f"{r.under}-{tag}.tar.gz"
        whl = DIST_PYPI / f"{r.under}-{tag}-py3-none-any.whl"

        if not no.test_chg and await targz.is_file() and await whl.is_file():
            up.add(r)
        else:
            try:
                await run_("python3", "-mbuild", "-snw", cwd=rd, echo=debug)
                # Move built files to dist/pypi
                build_dist = rd / "dist"
                if await build_dist.exists():
                    async for artifact in build_dist.glob(f"{r.under}-{tag}*"):
                        if artifact.suffix in {".gz", ".whl"}:
                            dest = DIST_PYPI / artifact.name
                            shutil.move(str(artifact), str(dest))
            except subprocess.CalledProcessError:
                err.add(r.name)
            else:
                up.add(r)
    return up, err


async def do_upload_pypi(up, debug, no, twine_repo):
    "send packages to pypi"
    err = set()
    official = twine_repo == "pypi"

    for r in up:
        rd = PACK / r.dash
        p = rd / "pyproject.toml"
        if not await p.is_file():
            continue
        tag = r.last_tag
        if official and r.vers.get("pypi", "-") == tag:
            continue
        targz = DIST_PYPI / f"{r.under}-{tag}.tar.gz"
        whl = DIST_PYPI / f"{r.under}-{tag}-py3-none-any.whl"
        done = DIST_PYPI / f"{r.under}-{tag}-{twine_repo}.done"
        if not no.test_chg and await done.exists():
            continue
        try:
            await run_(
                "twine",
                "upload",
                "-r",
                twine_repo,
                targz,
                whl,
                cwd=rd,
                echo=debug,
            )
        except subprocess.CalledProcessError:
            err.add(r.name)
        else:
            await done.touch()
            if official:
                r.vers.pypi = tag
    return err


async def do_upload_deb(repos, debug, dput_opts, g_done):
    "Upload to Debian"
    err = set()
    if not dput_opts:
        dput_opts = ["-u", "ext"]
    for r in repos:
        ltag = r.last_tag
        if r.vers.get("deb", "-") == f"{ltag}-{r.vers.pkg}":
            continue
        if not await (PACK / r.dash / "debian").is_dir():
            continue
        changes = DIST_DEBIAN / f"{r.srcname}_{ltag}-{r.vers.pkg}_{ARCH}.changes"
        done = DIST_DEBIAN / f"{r.srcname}_{ltag}-{r.vers.pkg}_{ARCH}.done"
        if await done.exists():
            r.vers.deb = f"{ltag}-{r.vers.pkg}"
            continue
        if g_done is not None:
            gd = g_done / f"{r.mdash}_{ltag}-{r.vers.pkg}_{ARCH}.done"
            if await gd.exists():
                r.vers.deb = f"{ltag}-{r.vers.pkg}"
                continue
        try:
            await run_("dput", *dput_opts, changes, echo=debug)
        except subprocess.CalledProcessError:
            err.add(r.name)
        else:
            await done.touch()
            r.vers.deb = f"{ltag}-{r.vers.pkg}"
    return err


@click.command(
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
@click.option("-G", "--no-test-chg", is_flag=True, help="rebuild even if artefact exists")
@click.option("-o", "--pytest", "pytest_opts", type=str, multiple=True, help="Options for pytest")
@click.option("-d", "--deb", "deb_opts", type=str, multiple=True, help="Options for debuild")
@click.option("-p", "--dput", "dput_opts", type=str, multiple=True, help="Options for dput")
@click.option("-r", "--run", is_flag=True, help="apply tags")
@click.option("-s", "--skip", "skip_", type=str, multiple=True, help="skip these repos")
@click.option("-m", "--minor", is_flag=True, help="create a new minor version")
@click.option("-M", "--major", is_flag=True, help="create a new major version")
@click.option(
    "-R",
    "--twine",
    "twine_repo",
    type=str,
    default="pypi",
    help="Repository to upload Twine packages to",
)
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
async def cli(
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
    no_test_chg,
    version,
    no_version,
    no_deb,
    skip_,
    major,
    minor,
    forcetag,
    autotag,
    twine_repo,
):
    """
    Rebuild all modified packages.
    """
    cfg = obj.cfg
    g_done = cfg.get("src", {}).get("done")
    if g_done is not None:
        g_done = Path(g_done)
    repo = Repo(cfg.src.toplevel, None)

    tags = dict(version)
    skip = set()
    for s in skip_:
        for sn in s.split(","):
            skip.add(dash(sn))
    parts = set(dash(s) for s in parts)
    debversion = {}

    no = attrdict()
    no.commit = bool(no_commit)
    no.deb = bool(no_deb)
    no.dirty = bool(no_dirty)
    no.pypi = bool(no_pypi)
    no.run = not bool(run)
    no.tag = bool(no_tag)
    no.test = bool(no_test)
    no.test_chg = bool(no_test_chg)
    no.version = bool(no_version)

    if no.tag and not no.version:
        print("Warning: not updating moat versions in pyproject files", file=sys.stderr)
    if minor and major:
        raise click.UsageError("Can't change both minor and major!")
    if autotag and no.tag:
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
        repos = []
        for x in repo.parts:
            if not x.hidden and x.dash not in skip and not await (PACK / x.dash / "SKIP").exists():
                repos.append(x)

    if await DIST_DEBIAN.exists():
        async for name in DIST_DEBIAN.iterdir():
            if name.suffix != ".changes":
                continue
            name = name.stem  # noqa:PLW2901
            name, vers, _ = name.split("_")  # noqa:PLW2901
            debversion[name] = vers.rsplit("-", 1)[0]

    # Step 0: basic check
    if not no.dirty:
        if repo.is_dirty(index=False, working_tree=True, untracked_files=True, submodules=False):
            if no.run:
                print("*** Repository is not clean.", file=sys.stderr)
            else:
                print("Please commit changes and try again.", file=sys.stderr)
                return

    # Step 1: check for changed files since last tagging
    if autotag:
        do_autotag(repo, repos, major, minor)

    elif not no.tag:
        err = set()
        for r in repos:
            try:
                tag = r.last_tag
            except KeyError:
                rd = PACK / r.dash
                p = rd / "pyproject.toml"
                if not await p.is_file():
                    continue
                raise
            tags[r.mdash] = tag
            if r.has_changes(True):
                err.add(r.dash)
        if err:
            if no.run:
                print("*** Untagged changes:", file=sys.stderr)
                print("***", *err, file=sys.stderr)
            else:
                print("Untagged changes:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please tag (moat src tag -s PACKAGE) and try again.", file=sys.stderr)
                return

    # Step 2: run tests
    if not no.test:
        fails = await do_runtest(repos, pytest_opts, debug=obj.debug > 1)
        if fails:
            if no.run:
                print("*** Tests failed:", *fails, file=sys.stderr)
            else:
                print("Failed tests:", *fails, file=sys.stderr)
                print("Fix and try again.", file=sys.stderr)
                raise SystemExit(1)

    # Step 3: set version and fix versioned dependencies
    await do_versions(repo, repos, tags, no)

    # Step 3: copy to packaging dir
    do_copy_repos(repos)

    # Step 4: build Debian package
    if not no.deb:
        if not deb_opts:
            deb_opts = ["--no-sign"]
        await do_build_deb(repo, repos, deb_opts, no, obj.debug > 1, forcetag)

    # Step 5: build PyPI package
    if not no.pypi:
        up, err = await do_build_pypi(repos, no, obj.debug > 1)

        if err:
            if no.run:
                print("*** Build errors:", file=sys.stderr)
                print("***", *err, file=sys.stderr)
            else:
                print("Build errors:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please fix and try again.", file=sys.stderr)
                no.commit = True
                no.deb = True

        # Step 6: upload PyPI package
        elif not no.run:
            err = await do_upload_pypi(up, obj.debug > 1, no, twine_repo)
            if err:
                print("Upload errors:", file=sys.stderr)
                print(*err, file=sys.stderr)
                print("Please fix(?) and try again.", file=sys.stderr)
                no.commit = True
                no.deb = True

    # Step 7: upload Debian package
    if not no.run and not no.deb:
        err = await do_upload_deb(repos, obj.debug > 1, dput_opts, g_done)

        if err:
            print("Upload errors:", file=sys.stderr)
            print(*err, file=sys.stderr)
            print("Please fix(?) and try again.", file=sys.stderr)
            no.commit = True

    # Step 8: commit the result
    if not no.run:
        if repo.write_tags() and not no.commit:
            repo.index.commit(f"Build version {forcetag}")
            git.TagReference.create(repo, forcetag)
