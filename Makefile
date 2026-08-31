#!/usr/bin/make -f

# SPDX-License-Identifier: GPL-3.0-or-later

PACKAGE = moat
MAKEINCL = $(shell ./mt src path)/make/py
PWD := $(shell pwd)

ifeq ($(notdir $(PWD)),moat)
MOAT_EXT ?= ../moat-ext
else
MOAT_EXT ?= ../../moat-ext
endif

VENV ?= N

ifneq ($(VENV),N)
	export PATH=.venv/bin:$(PATH)
endif

#ifneq ($(wildcard $(MAKEINCL)),)
#include $(MAKEINCL)
# availabe via http://github.com/smurfix/sourcemgr

#else
#%:
#	@echo "Please fix 'python3 -mmoat src path'."
#	@exit 1
#endif

venv:
ifneq ($(VENV),N)
	python3 -m venv .venv --upgrade-deps
	uv pip install -U -e .
	uv pip install -U -e .[dev]
	uv pip install -U -e .[doc]
	uv pip install -U ty pre-commit
endif

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
	sphinx-build -b html . ../dist/docs
spec:
	set -o pipefail -o errexit ; \
	cd docs/; \
	sphinx-build -b markdown . ../build/specs

docall:
	set -o pipefail -o errexit ; \
	cd docs/; \
	sphinx-build -E -b html . ../dist/docs
docwarn:
	set -o pipefail -o errexit ; \
	cd docs/; \
	sphinx-build -E -b html . ../dist/docs 2>&1 | \
	    ( if grep -E 'ERR|WARN' ; then exit 1 ; else exit 0; fi )

setup:
ifneq ($(VENV),N)
 	python3 -mvenv .venv --upgrade-deps
 	. .venv/bin/activate; test -f .venv/bin/uv || pip install uv
 	. .venv/bin/activate; uv pip install -U -e .[dev,doc]
endif
ifeq ($(notdir $(PWD)),moat)
	mkdir -p "${MOAT_EXT}"
else
	test -d "${MOAT_EXT}" || { echo "MOAT_EXT '${MOAT_EXT}' not found; run 'make setup' in the main 'moat' checkout first." >&2; exit 1; }
endif
	rm -rf ext; ln -sf "${MOAT_EXT}" ext
	./mt src submod get
	bd bootstrap -y || bd list -n1 >/dev/null 2>&1

release: doc
	./mt src tag
	./mt -V src build -ar

.PHONY: doc docall docwarn setup release venv prep
