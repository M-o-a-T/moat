# flake8: noqa

# update version file
from pathlib import Path

root = Path("../../../..")

import git


def commits(r):
    """Iterate over topo sort of commits following HEAD."""
    ref = r.head.commit
    visited = set()
    res = []

    def _it(c):
        return iter(sorted(c.parents, key=lambda x: x.committed_date))

    work = [(ref, _it(ref))]

    while work:
        c, gen = work.pop()
        if not work:
            while res:
                yield res.pop()
            yield c

        visited.add(c)
        for n in gen:
            if n not in visited:
                work.append((c, gen))
                work.append((n, _it(n)))
                break
        else:
            res.append(c)

    while res:
        yield res.pop()


vers = Path("moat/micro/_version.py")
r = git.Repo(root)
c = r.head.commit
t = c.tree
td = t.diff(None)
for dif in td:
    if dif.a_path.startswith("moat/micro/_embed/"):
        raise RuntimeError("Not checked in", dif.a_path)

tl = {}
for t in r.tags:
    if t.commit == c:
        tag = t.name
        break
    tl[t.commit] = t
else:
    n = 0
    for cc in commits(r):
        n += 1
        if cc in tl:
            tag = f"{tl[cc].name}-n{n}-g{c.hexsha[:9]}"
            break
    else:
        tag = ""

with vers.open("w") as f:
    f.write(
        f"""\
git="{c.hexsha[:9]}"
tag="{tag}"
"""
    )

try:
    require("copy")
    require("collections")
    require("collections-deque")
    require("contextlib")
    require("functools")
    require("pprint")
    require("types")
    require("typing")
    require("__future__")

    module("msgpack.py", opt=0)
    module("serialpacker.py", opt=0)
    module("async_queue.py", opt=0)
    package("moat", opt=0)
    package("app", opt=0)
except NameError:
    pass
