.PHONY: test lint format fixtures

# Unit tests run with sockets disabled, which also proves the tools make no network calls.
test:
	uv run pytest --disable-socket --allow-unix-socket tests/unit_tests

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy strands_comment_scraper tests

format:
	uv run ruff format .
	uv run ruff check --fix .

# Rebuilds tests/fixtures with the extension's own serialisers. Needs a checkout of
# supertj/comment-scraper-mcp next to this repository, with its dependencies installed.
fixtures:
	../comment-scraper-mcp/node_modules/.bin/esbuild tests/fixtures/generate.ts --bundle \
		--platform=node --format=esm --outfile=.generate.mjs --log-level=warning
	node .generate.mjs && rm .generate.mjs
