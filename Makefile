#!/usr/bin/make -f

# SPDX-License-Identifier: GPL-3.0-or-later

PACKAGE = moat
MAKEINCL = $(shell ./mt src path)/make/py
PWD := $(shell pwd)

# Detect whether we're in the main checkout or a worktree.
# "git worktree list" always lists the main checkout first.
WT_MAIN := $(firstword $(shell git worktree list 2>/dev/null))

ifeq ($(PWD),$(WT_MAIN))
# Main checkout (standalone clone, or root with worktrees):
# venv from scratch, ext/ next to us
MOAT_EXT ?= ../moat-ext
IS_WORKTREE :=
else
# Worktree: copy venv from main checkout (reflink to save space),
# ext/ next to the main checkout
MOAT_EXT ?= $(dir $(WT_MAIN))moat-ext
IS_WORKTREE := 1
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
ifdef IS_WORKTREE
	test -d .venv || cp -a --reflink=auto "$(WT_MAIN)/.venv" .venv
endif
	python3 -mvenv .venv --upgrade-deps
	. .venv/bin/activate; test -f .venv/bin/uv || pip install uv
	. .venv/bin/activate; uv pip install -U -e .[dev,doc]
endif
ifdef IS_WORKTREE
	test -d "${MOAT_EXT}" || { echo "MOAT_EXT '${MOAT_EXT}' not found; run 'make setup' in the main checkout first." >&2; exit 1; }
else
	mkdir -p "${MOAT_EXT}"
endif
	rm -rf ext; ln -sf "${MOAT_EXT}" ext
	./mt src submod get

release: doc
	./mt src tag
	./mt -V src build -ar

# Run all TS/JS package tests
jstest:
	@for dir in ts/*/ js/*/ ; do \
	  if [ -f "$$dir/package.json" ]; then \
	    echo "Running tests in $$dir"; \
	    (cd "$$dir" && { [ -d node_modules ] || npm ci; } \
	      && npx vitest run \
	      && { [ ! -f vitest.interop.config.ts ] || npx vitest run --config vitest.interop.config.ts; }) || exit 1; \
	  fi; \
	done

.PHONY: doc docall docwarn setup release venv prep jstest
