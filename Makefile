#!/usr/bin/make -f

# SPDX-License-Identifier: GPL-3.0-or-later

PACKAGE = moat
MAKEINCL ?= $(shell python3 -mmoat src path)/make/py

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
	make -C ext/micropython/ports/unix
	@echo "You might want to do 'make upy-install'"

upy-install: prep
	sudo cp ext/micropython/mpy-cross/build/mpy-cross /usr/local/bin/
	sudo cp ext/micropython/ports/unix/build-standard/micropython /usr/local/bin/
