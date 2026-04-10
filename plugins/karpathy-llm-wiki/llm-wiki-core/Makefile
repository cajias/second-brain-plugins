.PHONY: help test lint setup

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies and set up hooks
	uv sync --all-extras
	uv run pre-commit install

test: ## Run unit tests with coverage
	uv run pytest -v

lint: ## Run all linters (ruff, mypy, vulture)
	uv run pre-commit run --all-files
