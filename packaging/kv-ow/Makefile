#!/usr/bin/make -f

PACKAGE = moat-kv-ow
MAKEINCL ?= $(shell python3 -mmoat src path)/make/py

ifneq ($(wildcard $(MAKEINCL)),)
include $(MAKEINCL)
# availabe via https://github.com/moat-src

else
%:
	@echo "Please fix 'python3 -mmoat src path'."
	@exit 1
endif
