#!/usr/bin/make -f

PACKAGE=moat-lib-victron

ifneq ($(wildcard /usr/share/sourcemgr/make/py),)
include /usr/share/sourcemgr/make/py
# availabe via http://github.com/smurfix/sourcemgr

else
%:
	@echo "Please use 'python -mbuild'."
	@exit 1
endif

