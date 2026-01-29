# Working on MoaT code

## Setup

Do this once:

* Clone the MoaT:
  `git clone git@github.com:M-o-a-T/moat.git`
  `cd moat`

* Ensure that the Python modules `venv` and `build` are available.
  On Debian(-derived) systems: run `apt install python3-venv python3-build`.

* Set things up:
  `make setup`

* Activate the Python virtual evnironment:
  `. .venv/bin/activate`


MoaT's main program dynamically loads commands from `PYTHONPATH`.

To work with code in this repository, use the `./mt`
script instead of the `moat` command that might or might not be installed
on your system. This script overrides Python's module
path, thereby allowing for seamless local work.

MoaT components are built using `moat src build`. This command copies
MoaT's components to their subdirectories in `packaging`, builds PyPI
and (currently) Debian files, and uploads them to the place(s) of your
choice.


## Adding a module

Let's say you want to add code to talk to a FooDevice. So you do this:

    ./mt src setup moat.dev.foo

This command …

* creates subdirectories `moat/dev/foo`, `tests/moat_dev_foo`, and
  `packaging/dev-foo`.

* adds template `_main.py` and `_cfg.yaml` files to `moat/dev/foo`

* adds an empty `test_basic.py` file to `tests/moat_dev_foo`

* adds template `pyproject.toml` file to `packaging/moat-dev-foo`

* adds a version 0.0.1 for `moat.dev.foo` to `versions.yaml`

You now can commit your code as usual.

When your code is done, run `./mt src build`.


## Why a single repository ("monorepo")?

Because this way it's possible to work on interdependent parts of the
code.

Until early 2025 MoaT was composed using submodules. That approach caused
major problems with merging and keeping track of versioning, as git's
"merge" and "submodule" parts still do not work at all well together.
