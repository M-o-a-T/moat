# This build is used for mostly-interactive testing.
# We thus don't freeze MoaT here.
# include("$(VARIANT_DIR)/../../../../manifest.py")

# Do need the rest of it, though.

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
include("$(PORT_DIR)/variants/manifest.py")
