"MoaT satellite boot script"
# from moat import setup
# setup.run()
from __future__ import annotations

import sys
try:
	sys.path.remove("/lib")
except ValueError:
	pass
sys.path.insert(0,"/lib")

print("\n*** MoaT ***\n", file=sys.stderr)
