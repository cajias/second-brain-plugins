---
description: Run the llm-wiki test suite with optional flags
---

# /kb-test -- Run Test Suite

Run the plugin's test suite to verify correctness.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Determine the mode:

- **No args**: Run the full test suite
- **`--quick`**: Run tests without coverage
- **`--lint`**: Run linters only (ruff, mypy, vulture)
- **`--all`**: Run both linters and tests
- **A test path or pattern**: Pass through to pytest (e.g., `test_compile`, `tests/test_lint.py`)

## Step 2: Execute

Run from the `llm-wiki-core` directory inside the plugin:

```bash
cd plugins/karpathy-llm-wiki/llm-wiki-core
```

Then based on the mode:

```bash
# Full test suite (default)
uv run pytest -v

# Quick (no coverage)
uv run pytest -v --no-cov

# Lint only
uv run pre-commit run --all-files

# All (lint + test)
uv run pre-commit run --all-files && uv run pytest -v

# Specific test file or pattern
uv run pytest -v -k "PATTERN"
```

## Step 3: Report results

Summarize:
- Tests passed / failed / skipped
- Coverage percentage (if coverage was enabled)
- Any lint errors found (if lint was run)

If tests fail, read the failure output and suggest fixes.
