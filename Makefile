.PHONY: demo test lint typecheck eval

demo:
	author-agent quickstart

test:
	pytest --cov=author_agent --cov-fail-under=90

lint:
	ruff check .

typecheck:
	mypy .

eval:
	author-agent eval --json
