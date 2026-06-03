```
███████╗███████╗ ██████╗ ██████╗ ███╗   ██╗██████╗       ██████╗ ██████╗  █████╗ ██╗███╗   ██╗
██╔════╝██╔════╝██╔════╝██╔═══██╗████╗  ██║██╔══██╗      ██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║
███████╗█████╗  ██║     ██║   ██║██╔██╗ ██║██║  ██║█████╗██████╔╝██████╔╝███████║██║██╔██╗ ██║
╚════██║██╔══╝  ██║     ██║   ██║██║╚██╗██║██║  ██║╚════╝██╔══██╗██╔══██╗██╔══██║██║██║╚██╗██║
███████║███████╗╚██████╗╚██████╔╝██║ ╚████║██████╔╝      ██████╔╝██║  ██║██║  ██║██║██║ ╚████║
╚══════╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚═════╝       ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝

██████╗ ██╗     ██╗   ██╗ ██████╗ ██╗███╗   ██╗███████╗
██╔══██╗██║     ██║   ██║██╔════╝ ██║████╗  ██║██╔════╝
██████╔╝██║     ██║   ██║██║  ███╗██║██╔██╗ ██║███████╗
██╔═══╝ ██║     ██║   ██║██║   ██║██║██║╚██╗██║╚════██║
██║     ███████╗╚██████╔╝╚██████╔╝██║██║ ╚████║███████║
╚═╝     ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝╚═╝  ╚═══╝╚══════╝
```

<p align="center"><em>Claude Code plugins for personal knowledge management</em></p>

<p align="center">
  <img src="https://img.shields.io/github/languages/top/cajias/second-brain-plugins?style=for-the-badge" alt="Language">
  <a href="https://github.com/cajias/second-brain-plugins/blob/main/LICENSE"><img src="https://img.shields.io/github/license/cajias/second-brain-plugins?style=for-the-badge" alt="License"></a>
  <a href="https://github.com/cajias/second-brain-plugins/stargazers"><img src="https://img.shields.io/github/stars/cajias/second-brain-plugins?style=for-the-badge" alt="Stars"></a>
  <img src="https://img.shields.io/badge/Claude%20Code-plugin-E879F9?style=for-the-badge" alt="Claude Code plugin">
</p>

**A collection of [Claude Code](https://claude.ai/code) plugins that turn scattered notes, papers, and conversations into a structured, searchable, interconnected knowledge graph.** Each plugin is a self-contained personal-knowledge-management system with its own commands, agents, skills, and Python CLI — with Claude doing the heavy lifting of ingesting, compiling, and linking your second brain.

<table>
<tr><td><b>Karpathy-style wiki</b></td><td>The <a href="plugins/karpathy-llm-wiki/"><code>karpathy-llm-wiki</code></a> plugin ingests files, compiles them into atomic permanent notes, and maintains a semantic knowledge base.</td></tr>
<tr><td><b>Semantic search</b></td><td>A local <a href="https://lancedb.github.io/lancedb/">LanceDB</a> vector index over <code>sentence-transformers</code> embeddings — query your notes by meaning, not keywords.</td></tr>
<tr><td><b>Ingest anything</b></td><td>Pull in Markdown, raw text, or PDFs (via <code>pypdf</code>) into a staging inbox, then compile the best material into the permanent wiki.</td></tr>
<tr><td><b>Health &amp; analytics</b></td><td><code>kb lint</code> reports schema and link health; <code>kb charts</code> auto-generates tag-distribution, growth, and knowledge-type plots from the live vault.</td></tr>
<tr><td><b>Scheduled maintenance</b></td><td><code>kb maintenance enable</code> installs cron jobs to incrementally re-index, lint, and regenerate charts on a nightly/weekly cadence.</td></tr>
<tr><td><b>Slash commands + CLI</b></td><td>Drive everything from Claude Code (<code>/kb-init</code>, <code>/kb-ingest</code>, <code>/kb-compile</code>, <code>/kb-query</code>, …) or from the standalone <code>kb</code> Python CLI.</td></tr>
</table>

## Available plugins

| Plugin | Description |
|--------|-------------|
| [karpathy-llm-wiki](plugins/karpathy-llm-wiki/) | Karpathy-style knowledge wiki — ingest, compile, search, and maintain a semantic knowledge base |

## Installation

### As a Claude Code plugin (recommended)

Add this repo as a marketplace, then install the plugin:

```bash
claude plugin marketplace add cajias/second-brain-plugins
claude plugin install karpathy-llm-wiki@second-brain-plugins
```

The plugin registers slash commands (`/kb-init`, `/kb-ingest`, `/kb-compile`, `/kb-query`, `/kb-index`, `/kb-lint`, `/kb-test`) for use directly inside Claude Code.

### As a standalone CLI

The wiki engine ships as a Python package (`kb`) you can run without Claude Code. Dependencies are heavier here (vector index + embedding model), so [`uv`](https://docs.astral.sh/uv/) is recommended:

```bash
cd plugins/karpathy-llm-wiki/llm-wiki-core
uv sync --all-extras
uv run kb --help
```

## Usage

### Inside Claude Code

```bash
# Initialize a wiki in any directory
cd ~/my-wiki
/kb-init

# Build knowledge
/kb-ingest file paper.pdf
/kb-compile
/kb-query "What patterns exist for X?"
```

### From the CLI

The `kb` command exposes the full pipeline — `init`, `ingest`, `compile`, `search`, `index`, `lint`, `charts`, and a `maintenance` subcommand group:

```bash
# Initialize, ingest, compile, index, and search
kb init /tmp/my-wiki
cd /tmp/my-wiki
kb ingest --mode text --source "Functional options use variadic closures to configure structs."
kb compile --write-note --title "Functional Options" --knowledge-type pattern --confidence high --source demo --body "..."
kb index --full
kb search "configure a struct without breaking the API" --limit 3
```

### Demo

The end-to-end shell flow — `init → ingest → compile → index → search`:

![karpathy-llm-wiki demo: init → ingest → compile → index → search](docs/demos/karpathy-llm-wiki.gif)

_The demo is fully reproducible: from the repo root, run `vhs docs/demos/karpathy-llm-wiki.tape`._

### What it produces

Captured from a real wiki of 66 notes — all four charts are auto-generated by `kb charts`, no mockups:

| ![Tag distribution](docs/demos/screenshots/tag-distribution.png) | ![Knowledge types](docs/demos/screenshots/knowledge-type-distribution.png) |
|:--:|:--:|
| **Tag distribution** — note counts per tag | **Knowledge types** — types observed in this vault |
| ![Growth over time](docs/demos/screenshots/growth-over-time.png) | ![Health summary](docs/demos/screenshots/health-summary.png) |
| **Growth over time** — note-creation cadence | **Health summary** — vault size and composition |

See [`docs/demos/screenshots/`](docs/demos/screenshots/) for the full set and a sample [auto-generated stats dashboard](docs/demos/screenshots/example-stats-dashboard.md).

## Configuration

- **Scheduled maintenance** — `kb maintenance enable` installs cron jobs (nightly incremental index, weekly lint report, weekly chart regeneration); `kb maintenance status` and `kb maintenance disable` manage them. Pass `--json` for machine-readable output.
- **Embeddings cache** — set the standard Hugging Face environment variables (`HF_HUB_DISABLE_PROGRESS_BARS`, `TRANSFORMERS_VERBOSITY`, `TOKENIZERS_PARALLELISM`) to quiet model downloads, as the demo tape does.

## How it works

Each plugin is self-contained under `plugins/<name>/`:

```
plugins/karpathy-llm-wiki/
├── .claude-plugin/plugin.json   # Claude Code manifest
├── commands/                    # slash commands (/kb-*)
├── agents/                      # compile, wikilink, gap-research, quality-review
├── skills/                      # search-and-link, lint-and-repair, gap-analysis, compile-note
└── llm-wiki-core/               # Python engine (the `kb` CLI)
    ├── src/llm_wiki/            # commands: init/ingest/compile/search/index/lint/charts
    └── tests/                   # pytest suite
```

The flow: **ingest** stages raw material in an inbox → **compile** distills it into atomic permanent notes with frontmatter → **index** embeds notes into a LanceDB vector store → **search** retrieves by semantic similarity. Slash commands and agents orchestrate the same engine from inside Claude Code.

## Development

The Python engine lives in `plugins/karpathy-llm-wiki/llm-wiki-core` and uses `uv` plus a small Makefile:

```bash
cd plugins/karpathy-llm-wiki/llm-wiki-core
make setup   # uv sync --all-extras + pre-commit install
make test    # uv run pytest -v (with coverage)
make lint    # ruff, mypy, vulture via pre-commit
```

New plugins should live in `plugins/<name>/`, ship a `.claude-plugin/plugin.json` manifest and a `README.md`, and stay self-contained (no cross-plugin dependencies).

## License

Released under the [MIT License](LICENSE).
