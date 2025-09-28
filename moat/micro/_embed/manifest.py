# ruff:noqa:D100,F821,SLF001,I002

freeze("$(PORT_DIR)/modules")

require("copy")
require("collections")
require("contextlib")
require("functools")
require("inspect")
require("pprint")
require("types")
require("typing")
require("__future__")

include("$(MPY_DIR)/extmod/asyncio")

import moat.micro._embed.lib  # noqa:E402

# TODO only if building with networking
require("webrepl")

for p in moat.micro._embed.lib.__path__:
    print(p)
    include(p + "/manifest.py")
