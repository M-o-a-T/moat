#!/usr/bin/make -f

PACKAGE = moat-link-server
MAKEINCL ?= $(shell python3 -mmoat src path)/make/py

install: installscript installsystemd

installsystemd:
	mkdir -p $(PREFIX)/lib/systemd/system
	mkdir -p $(PREFIX)/usr/lib/sysusers.d
	cp systemd/*.service $(PREFIX)/lib/systemd/system/
	# cp systemd/*.timer $(PREFIX)/lib/systemd/system/
	cp systemd/sysusers $(PREFIX)/usr/lib/sysusers.d/moat-link-server.conf

installscript:
	mkdir -p $(PREFIX)/usr/lib/moat/link
	cp scripts/* $(PREFIX)/usr/lib/moat/link/
	
	# sigh
	mkdir -p $(PREFIX)/lib/systemd/system
	cp systemd/*@.service $(PREFIX)/lib/systemd/system/


ifneq ($(wildcard $(MAKEINCL)),)
include $(MAKEINCL)
# availabe via http://github.com/smurfix/sourcemgr

else
%:
	@echo "Please fix 'python3 -mmoat src path'."
	@exit 1
endif

