# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Remote
- `origin` — code.aws.dev (proserve/product-and-solutions/tools/knowledge-management/second-brain-plugins)
- SSH host is `ssh.code.aws.dev` (not `code.aws.dev`) — never reference GitHub in docs
- code.aws.dev blocks standard GitLab project creation API — must use manage.code.aws.dev browser UI

## Repository Structure

This is a **Claude Code plugin monorepo**. Each plugin lives in `plugins/<name>/` and is a self-contained Claude Code plugin with its own `.claude-plugin/plugin.json` manifest. The root `.claude-plugin/` makes the repo itself installable.

Currently one plugin: `karpathy-llm-wiki`.

### Plugin Anatomy (karpathy-llm-wiki)

```
plugins/karpathy-llm-wiki/
├── .claude-plugin/plugin.json    # Plugin manifest (name, version, description)
├── commands/kb-*.md              # Claude Code slash commands (user-facing)
├── agents/*.md                   # Autonomous agents (dispatched, work independently)
├── skills/*.md                   # Shared knowledge modules (invoked by commands AND agents)
└── llm-wiki-core/                # Python CLI package
    ├── src/llm_wiki/
    │   ├── cli.py                # Typer app — entry point for `kb` command
    │   ├── commands/             # One module per CLI subcommand
    │   └── core/                 # Shared logic: config, embeddings, dedup, frontmatter, taxonomy
    ├── tests/
    └── pyproject.toml
```

**Key design**: Commands and agents are markdown files that instruct Claude. They delegate mechanical work to the `kb` CLI and shared `skills/`. Skills eliminate duplication — "how to compile a note" lives in `skills/compile-note.md` and is referenced by both `/kb-compile` command and the `compile-agent`.

## Development

All commands run from `plugins/karpathy-llm-wiki/llm-wiki-core`:

```bash
uv sync --all-extras          # Install deps (first time / after pyproject.toml change)
uv run kb --help              # CLI entry point
uv run pytest -v              # Full test suite with coverage (must stay ≥70%)
uv run pytest tests/test_lint.py -v              # Single test file
uv run pytest tests/test_lint.py::test_name -v   # Single test
uv run pre-commit run --all-files                # Lint (ruff format + check + mypy + vulture)
make test                     # Shortcut: uv run pytest -v
make lint                     # Shortcut: pre-commit
```

## Architecture

### Config-Driven Paths
All paths resolve from `.kb-config.yml` found by walking up from cwd. `core/config.py:WikiConfig` is the single source of truth — every command receives resolved absolute paths, never hardcoded strings. Tests use the `wiki_root` fixture (conftest.py) which creates a temp directory with config, taxonomy, and directory tree.

### Embedding Pipeline
`core/embeddings.py` lazy-loads `all-MiniLM-L6-v2` (384-dim) into a module-level cache. LanceDB stores vectors locally (`.lancedb/` dir, gitignored). Search uses cosine distance. Tests mock the model via `mock_embedding_model` fixture (deterministic random vectors seeded by text hash).

### Deduplication Thresholds
`core/dedup.py` — three tiers: ≥0.92 = duplicate (skip), 0.80–0.91 = similar (flag), <0.80 = unique (write). These thresholds are hardcoded, not configurable.

### Frontmatter Contract
`core/frontmatter.py` enforces a tiered schema. **Required** (lint errors if absent): `tags`, `source`, `created`, plus a knowledge type satisfied by either `knowledge_type` or `type`. **Recommended** (canonical schema, auto-repairable, not lint errors): `id`, `type`, `status`, `confidence`, `scope`. Enum values and the 6-tag cap are still strictly validated when present. `core/taxonomy.py` validates tags against `wiki/_meta/tag-taxonomy.md`. Legacy simplified-schema notes upgrade to canonical via `kb migrate-frontmatter` (dry-run default, `--apply` to write).

### CLI Subcommands
`cli.py` registers: `init`, `ingest`, `compile`, `search`, `lint`, `index`, `charts`, plus `maintenance` subgroup (enable/disable/status for cron). Each command module lives in `commands/` and is a standalone Typer function.

## Code Style
- Ruff with aggressive rule set (120 char line length, Google-style docstrings)
- mypy strict mode
- vulture for dead code detection (min confidence 80%)
- Tests ignore: `S101` (assert), `ANN` (annotations), `D10*` (docstrings), `PLR2004` (magic numbers)

## Gotchas
- post-commit hook references `git-stats` which isn't installed — harmless noise, ignore it
- When working in a worktree after a rebase on main, use `cherry-pick` not `merge` (histories diverge)
- `uv.lock` is protected by a PreToolUse hook — don't edit directly, run `uv sync` instead
- PostToolUse hook auto-runs `ruff format` + `ruff check --fix` on every `.py` file edit
