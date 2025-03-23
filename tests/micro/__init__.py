# noqa:D104 pylint:disable=missing-module-docstring

# We need to ensure that the test interpreter exists
import os
from pathlib import Path
def make_upy(force:bool=False):
	p=Path("ext/micropython/ports/unix")
	upy = p/"build-standard/micropython"
	if not force and upy.exists():
		return
	if upy.exists():
		run(["make","clean"], cwd=p, check=True)
	run(["make"], cwd=p, check=True)

make_upy()
