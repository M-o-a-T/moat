# flake8: noqa

#freeze("$(PORT_DIR)/modules")

require("copy")
require("collections")
require("collections-deque")
require("contextlib")
require("functools")
require("pprint")
require("types")
require("typing")
require("__future__")

include("$(MPY_DIR)/extmod/asyncio")

# TODO only if building with networking
require("webrepl")


import moat.micro._embed.lib
for p in moat.micro._embed.lib.__path__:
    print(p)
    include(p+"/manifest.py")
