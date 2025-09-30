#!/usr/bin/make -f

PACKAGE = moat-micro
MAKEINCL ?= $(shell python3 -mmoat src path)/make/py

install:
	mkdir -p $(PREFIX)/lib/systemd/system
	cp systemd/*.udev $(PREFIX)/lib/udev/rules.d


ifneq ($(wildcard $(MAKEINCL)),)
include $(MAKEINCL)
# availabe via http://github.com/smurfix/sourcemgr

else
%:
	@echo "Please fix 'python3 -mmoat src path'."
	@exit 1
endif
