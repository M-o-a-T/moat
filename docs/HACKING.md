# Working on MoaT code

## Setup

Do this once:

* Get the subrepositories:
  `git submodule update --init --recursive`.

* Set up a Python virtual environment:
  `python3 -mvenv .venv`

* … and activate it:
  `. .venv/bin/activate`

* Install some packages:
  `sh setup.sh`

Do this every time you start working with MoaT code:

* Set up the Python path:
  `export PYTHONPATH=$(./mt path)`


## Code structure

MoaT's main program loads commands from installed components.

To work with code in this repository, use the `./mt`
script instead of the `moat` command that might be installed somewhere.
This script overrides Python's module
path, thereby allowing for seamless local work.

MoaT components are built using `moat src build`. This command copies MoaT's components to their subdirectories in `packaging` and then runs PyPI and (currently) Debian packaging.

## Adding a module

Let's say you want to add code to talk to a FooDevice. So you do this:

    ./mt src setup moat.dev.foo

This command …

* creates subdirectories `moat/dev/foo`, `tests/dev-foo`, and `packaging/dev-foo`.

* adds template `_main.py` and `_cfg.yaml` files to `moat/dev/foo`

* adds an empty `test_basic.py` file to `tests/dev-foo`

* adds template `pyproject.toml` file to `packaging/dev-foo`

* adds a version 0.0.1 for `moat.dev.foo` to `version.txt`

You now can commit your code as usual.

When your code is done, run `./mt src build`.


## Why a single repository?

Because this way it's possible to work on interdependent parts of the tree.

Until early 2025, MoaT was composed using submodules. Unfortunately, that approach caused major problems with merging and keeping track of versioning.
