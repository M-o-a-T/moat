#!/usr/bin/make -f

PACKAGE = moat-link
MAKEINCL ?= $(shell python3 -mmoat src path)/make/py

installscript:
	mkdir -p $(PREFIX)/lib/systemd/system
	cp systemd/*.service $(PREFIX)/lib/systemd/system/

ifneq ($(wildcard $(MAKEINCL)),)
include $(MAKEINCL)
# availabe via http://github.com/smurfix/sourcemgr

else
%:
	@echo "Please fix 'python3 -mmoat src path'."
	@exit 1
endif

