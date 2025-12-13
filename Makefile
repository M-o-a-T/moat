#!/usr/bin/make -f

# SPDX-License-Identifier: GPL-3.0-or-later

PACKAGE = moat
MAKEINCL = $(shell python3 -mmoat src path)/make/py
PWD := $(shell pwd)

ifneq ($(wildcard $(MAKEINCL)),)
include $(MAKEINCL)
# availabe via http://github.com/smurfix/sourcemgr

else
%:
	@echo "Please fix 'python3 -mmoat src path'."
	@exit 1
endif

prep:
	git submodule update --init --recursive
	make -C ext/micropython/mpy-cross
	env PYTHONPATH=${PWD} \
	  make -C ext/micropython/ports/unix \
	    VARIANT_DIR=${PWD}/moat/micro/_embed/boards/unix/test \
	    BUILD=${PWD}/build/mpy-unix \
	    STRIP= DEBUG=1
