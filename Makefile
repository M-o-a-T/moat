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

all: setup

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
ifndef IS_WORKTREE
	bash setup.sh
else
	test -d "${MOAT_EXT}" || { echo "MOAT_EXT '${MOAT_EXT}' not found; run 'make' in the main checkout first." >&2; exit 1; }
ifneq ($(VENV),N)
	test -d .venv || cp -a --reflink=auto "$(WT_MAIN)/.venv" .venv
endif
	./mt src submod get
endif
	rm -rf ext; ln -sf "${MOAT_EXT}" ext

release: doc
	./mt src tag
	./mt -V src build -ar

# Run all TS/JS package tests.
# Each package owns its test runner (vitest, node --test, …); delegate to its
# Makefile instead of assuming a common toolchain. Dependencies are bootstrapped
# via the package's own `install` target when node_modules is missing.
jstest:
	@for dir in ts/*/ js/*/ ; do \
	  if [ -f "$$dir/package.json" ]; then \
	    echo "Running tests in $$dir"; \
	    (cd "$$dir" \
	      && { [ -d node_modules ] || $(MAKE) install; } \
	      && $(MAKE) test \
	      && { if grep -q '^test-interop:' Makefile 2>/dev/null; then $(MAKE) test-interop; fi; }) || exit 1; \
	  fi; \
	done

.PHONY: doc docall docwarn setup release venv prep jstest
