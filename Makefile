#!/usr/bin/make -f

.PHONY: doc test update all tag pypi upload code

all:
		@echo "Please use 'python setup.py'."
		@echo "Also 'make code'."
		@exit 1

# need to use python3 sphinx-build
PATH := /usr/share/sphinx/scripts/python3:${PATH}
CFLAGS := -DMOAT_USE_REF -g -O0 -W -I.

PACKAGE = moatbus
PYTHON ?= python3

## host+path to run the tests on
TESTER ?= root@pi-e2
TESTRUN ?= ./moat-bus/ci/test

export PYTHONPATH=$(shell pwd)

PYTEST ?= $(shell which pytest)
TEST_OPTIONS ?= -xvvv --full-trace
PYLINT_RC ?= .pylintrc

BUILD_DIR ?= build
INPUT_DIR ?= docs/source

# Sphinx options (are passed to build_docs, which passes them to sphinx-build)
#   -W       : turn warning into errors
#   -a       : write all files
#   -b html  : use html builder
#   -i [pat] : ignore pattern

SPHINXOPTS ?= -a -W -b html
AUTOSPHINXOPTS := -i *~ -i *.sw* -i Makefile*

SPHINXBUILDDIR ?= $(BUILD_DIR)/sphinx/html
ALLSPHINXOPTS ?= -d $(BUILD_DIR)/sphinx/doctrees $(SPHINXOPTS) docs

ci: code pio copy run
#code:	bin/test_handler_crc bin/test_crc bin/test_handler_crc_bus
code:	bin/fake_spam bin/fake_send bin/fake_recv bin/fake_serialbus
pio:
	platformio run

bin/test_handler_crc_bus:	obj/test_handler_crc_bus.o obj/libmessage.a
	gcc -o $@ $^
bin/test_handler_crc:	obj/test_handler_crc.o obj/libmessage.a
	gcc -o $@ $^
bin/test_crc:	obj/test_crc.o obj/libmessage.a
	gcc -o $@ $^
bin/fake_recv:	obj/fake_recv.o obj/fake_client.o obj/libmessage.a
	gcc -o $@ $^
bin/fake_send:	obj/fake_send.o obj/fake_client.o obj/libmessage.a
	gcc -o $@ $^
bin/fake_spam:	obj/fake_spam.o
	gcc -o $@ $^
bin/fake_serialbus:	obj/fake_serialbus.o obj/fake_client.o obj/libmessage.a
	gcc -o $@ $^
bin/test_minifloat:	obj/test_minifloat.o obj/util.o
	gcc -o $@ $^


obj/libmessage.a: obj/message.o obj/crc.o obj/handler.o obj/serial.o obj/util.o
	ar r $@ $^

obj/crc.o:	moatbus/crc.c
	gcc ${CFLAGS} -c -o $@ $^
obj/handler.o:	moatbus/handler.c
	gcc ${CFLAGS} -c -o $@ $^
obj/message.o:	moatbus/message.c
	gcc ${CFLAGS} -c -o $@ $^
obj/serial.o:	moatbus/serial.c
	gcc ${CFLAGS} -c -o $@ $^
obj/util.o:	moatbus/util.c
	gcc ${CFLAGS} -c -o $@ $^
obj/test_minifloat.o:	tests/test_minifloat.c
	gcc ${CFLAGS} -c -o $@ $^
obj/test_handler_crc_bus.o:	fakebus/test_handler_crc_bus.c
	gcc ${CFLAGS} -c -o $@ $^
obj/test_handler_crc.o:	fakebus/test_handler_crc.c
	gcc ${CFLAGS} -c -o $@ $^
obj/test_crc.o:	fakebus/test_crc.c
	gcc ${CFLAGS} -c -o $@ $^
obj/fake_spam.o:	fakebus/spam.c
	gcc ${CFLAGS} -c -o $@ $^
obj/fake_send.o:	fakebus/send.c
	gcc ${CFLAGS} -c -o $@ $^
obj/fake_recv.o:	fakebus/recv.c
	gcc ${CFLAGS} -c -o $@ $^
obj/fake_client.o:	fakebus/client.c
	gcc ${CFLAGS} -c -o $@ $^
obj/fake_serialbus.o:	fakebus/serialbus.c
	gcc ${CFLAGS} -c -o $@ $^

doc:
	sphinx3-build -a $(INPUT_DIR) $(BUILD_DIR)

livehtml: docs
	sphinx-autobuild $(AUTOSPHINXOPTS) $(ALLSPHINXOPTS) $(SPHINXBUILDDIR)

test: bin/test_minifloat
	$(PYTEST) tests $(TEST_OPTIONS)
	bin/test_minifloat

tagged:
	git describe --tags --exact-match
	test $$(git ls-files -m | wc -l) = 0

pypi:   tagged
	python3 setup.py sdist upload

upload: pypi
	git push-all --tags

update:
	pip install -r ci/test-requirements.txt

copy:
	for f in gate node ; do for e in bin elf ; do scp ./.pio/build/moat_$$f//firmware.$$e ${TESTER}:/tmp/$$f.$$e; done; done
run:
	ssh -n ${TESTER} ${TESTRUN}
