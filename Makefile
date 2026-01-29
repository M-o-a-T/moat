#!/usr/bin/make -f

# SPDX-License-Identifier: GPL-3.0-or-later

PACKAGE = moat
MAKEINCL = $(shell ./mt src path)/make/py
PWD := $(shell pwd)

#ifneq ($(wildcard $(MAKEINCL)),)
#include $(MAKEINCL)
# availabe via http://github.com/smurfix/sourcemgr

#else
#%:
#	@echo "Please fix 'python3 -mmoat src path'."
#	@exit 1
#endif

venv:
	python3 -m venv .venv --upgrade-deps
	.venv/bin/pip install -e .[dev]
	.venv/bin/pip install ty pre-commit

prep:
	git submodule update --init --recursive
	make -C ext/micropython/mpy-cross
	env PYTHONPATH=${PWD} \
	  make -C ext/micropython/ports/unix \
	    VARIANT_DIR=${PWD}/moat/micro/_embed/boards/unix/test \
	    BUILD=${PWD}/build/mpy-unix \
	    STRIP= DEBUG=1

doc:
	set -o pipefail -o errexit ; \
	cd docs/; \
	../.venv/bin/sphinx-build -b html . ../dist/docs
docall:
	set -o pipefail -o errexit ; \
	cd docs/; \
	../.venv/bin/sphinx-build -E -b html . ../dist/docs
docwarn:
	set -o pipefail -o errexit ; \
	cd docs/; \
	../.venv/bin/sphinx-build -E -b html . ../dist/docs 2>&1 | \
	    ( if grep -E 'ERR|WARN' ; then exit 1 ; else exit 0; fi )
