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

MoaT's main program loads commands from installed submodules.

To work with code in this repository (and its subrepos), use the `./mt`
script instead of the `moat` command that might be installed somewhere.
This script finds all local submodules and adds them to Python's module
path, thereby allowng for seamless local work.

The `src` submodule contains some useful commands to keep the whole
submodule structure in sync. The most-used command is `moat src build -c`.

## Adding a module

Let's say you want to add code to talk to a FooDevice. Calling `./mt` So you do this:

    mkdir dev/foo; cd dev/foo; git init; git remote add …
    mkdir -p moat/dev/foo
    cp ../moat/__init__.py moat
    cp ../moat/__init__.py moat/dev
    cp ../moat/__init__.py moat/dev/foo
    sed -e s/moat.dev/moat.dev.foo/ -e "s/Device Manager/Foo Devices/" < ../moat/dev/_main.py >moat/dev/foo/_main.py
    git add moat; git commit
    touch pyproject.toml
    cd ..; git submodule add … foo
    git commit -m "add foo"
    cd ..; ./mt src setup -o dev/foo
    ./mt dev foo
    cd dev/foo; make format test

Let's break this down.

* create a repository and tell it where to push the data.

* create the directory for our code.

* Copy the boilerplate `__init__.py` file to each subdirectory. This is not
  required for Python to find your module, but the dynamic loader needs it.

* Add a command loader / dispatcher. Right now this does nothing, we'll fix that
  later.

* Commit the thing.

+ Create an empty `pyproject.toml` file tells `moat src setup` to operate
  on your subrepository.

* Add your initial `moat.dev.foo` repository to `moat.dev` as a subrepository so
  that `moat src …` can find it.

* `moat src setup` uses its built-in templates to create a Makefile,
  somewhat-opinionated `pyproject.toml`, and an empty test.

  The Makefile loads its code from the current MoaT source template
  directory instead of including it verbatim, because it's way easier to
  customize the Makefile that way.

* Now we can test this command. It still does nothing, though.

* `make format` applies basic formatting to your code, using `flake8` and
  `isort`.

* `make test` checks that the formatting hasn't been mangled, runs a couple
  of linters over the code, and finishes with `pytest3 -x tests`.

You now can commit your code as usual.

When you're done, run `./mt src build -c`. This command verifies that
everything is checked in, tagged (creating new tags if necessary), and
linked (i.e. submodule references are updated). This way, your copy of the
`moat` repository contains a reference to your new module.

## Why not a single repository?

Because this way it's possible to work on part of the tree and ignore all
the rest of MoaT.

With a single large repository, `git status` looks at the whole repository
even when you're deep in some subdirectory. You need to remember to add the
relative path to the top of your workspace, and it's far too easy to
habitually type `git status .` and forget to check in that important
`../READ_BEFORE_INSTALLING.txt` file until it#s too late.

More importantly, we want to be able to tag different modules and their
requirements independently. A breaking change in `moat.mqtt` should not
affect the tag of `moat.modbus`.

With `moat src build` there's a reasonably-powerful tool that pulls the
disparate parts of Moat back together, so the disadvantages of keeping
track o a lot of submodules can be minimized.
