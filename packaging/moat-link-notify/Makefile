#!/usr/bin/make -f

PACKAGE = moat-link-notify
MAKEINCL ?= $(shell python3 -mmoat src path)/make/py

install: installsystemd

installsystemd:
	mkdir -p $(PREFIX)/usr/lib/systemd/system
	cp systemd/*.service $(PREFIX)/usr/lib/systemd/system/

ifneq ($(wildcard $(MAKEINCL)),)
include $(MAKEINCL)
# availabe via http://github.com/smurfix/sourcemgr

else
%:
	@echo "Please fix 'python3 -mmoat src path'."
	@exit 1
endif
