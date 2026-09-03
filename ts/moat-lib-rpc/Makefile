.PHONY: install build min minified-build test test-interop lint fmt typecheck example pack publish clean

install:
	npm ci

build:
	npm run build

min: minified-build

minified-build:
	node scripts/build-min.mjs

test:
	npm run test

test-interop:
	npx vitest run --config vitest.interop.config.ts

lint:
	npm run lint

fmt:
	npm run format

typecheck:
	npm run typecheck

example:
	tsx examples/server.ts & sleep 1 && tsx examples/client.ts && kill $$! 2>/dev/null || true

pack:
	npm pack --dry-run

publish:
	npm publish --provenance

clean:
	rm -rf dist coverage node_modules/.cache
