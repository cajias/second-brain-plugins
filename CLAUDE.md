# Project: second-brain-plugins

## Remote
- `origin` — code.aws.dev (proserve/product-and-solutions/tools/knowledge-management/second-brain-plugins)
- SSH host is `ssh.code.aws.dev` (not `code.aws.dev`)
- code.aws.dev blocks standard GitLab project creation API — must use manage.code.aws.dev browser UI

## Structure
- Plugins live in `plugins/<name>/` with commands, agents, skills, and a Python CLI
- Only plugin currently: `karpathy-llm-wiki`

## Development (karpathy-llm-wiki)
- `cd plugins/karpathy-llm-wiki/llm-wiki-core`
- Install: `uv sync --all-extras`
- Test: `uv run pytest -v`
- Lint: `uv run pre-commit run --all-files`
- CLI: `uv run kb --help`

## Gotchas
- post-commit hook references `git-stats` which isn't installed — harmless noise, ignore it
- When working in a worktree after a rebase on main, use `cherry-pick` not `merge` (histories diverge)
