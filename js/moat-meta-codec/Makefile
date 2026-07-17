.PHONY: install test test-nodered lint fmt clean

NODE ?= node
NPM ?= npm

install:
	$(NPM) install

test:
	$(NODE) --test test/codec.test.js

test-nodered:
	$(NODE) --test test/codec.nodered.test.js

lint:
	npx eslint lib/ test/

fmt:
	npx prettier --write lib/ test/

clean:
	rm -rf node_modules dist coverage
