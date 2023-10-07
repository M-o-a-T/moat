from moat.micro.cmd.tree import Dispatch as _Dispatch

from moat.util import yload

from pathlib import Path

class Dispatch(_Dispatch):
	pass
	# APP = "test.app"

def get_cfg(n):
	pn=Path(n)
	tn = pn.name.rsplit(".",1)[-1]
	if tn.startswith("test_"):
		tn = tn[5:]
	if tn.endswith(".py"):
		tn = tn[:-3]
	p=pn.parent / "tests" / "cfg" / (tn+".cfg")

	return yload(p)
