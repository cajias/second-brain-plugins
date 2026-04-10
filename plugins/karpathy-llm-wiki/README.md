# karpathy-llm-wiki

An implementation of [Andrej Karpathy's LLM knowledge base workflow](https://x.com/karpathy/status/2039805659525644595) as a Claude Code plugin.

> *"Something I'm finding very useful recently: using LLMs to build personal knowledge bases for various topics of research interest. [...] Raw data from a given number of sources is collected, then an LLM incrementally compiles a wiki from it, which you can then query, visualize, and lint."*
> — Andrej Karpathy

## The Idea

Karpathy described a workflow where raw documents (articles, papers, repos) are indexed into a `raw/` directory, then an LLM **incrementally compiles a wiki** from them — extracting concepts, writing articles, adding backlinks, and maintaining the whole thing. You query it, explore it, lint it, and your explorations feed back in, so your knowledge always "adds up."

This plugin implements that full loop as a set of Claude Code commands.

## The Workflow

```
           ┌──────────────────────────────────────────────┐
           │                                              │
           v                                              │
  ┌─────────────┐    ┌──────────────┐    ┌────────────┐  │
  │  /kb-ingest  │───>│  /kb-compile  │───>│  /kb-query  │──┘
  │              │    │              │    │            │
  │  PDFs        │    │  Extract     │    │  Semantic  │
  │  Articles    │    │  atomic      │    │  search    │
  │  Web clips   │    │  ideas       │    │  across    │
  │  Sessions    │    │  Dedup       │    │  261+      │
  │  Text        │    │  Wikilink    │    │  notes     │
  └─────────────┘    └──────────────┘    └────────────┘
                           │
                           v
                    ┌──────────────┐    ┌────────────┐
                    │  /kb-lint     │───>│  /kb-charts │
                    │              │    │            │
                    │  Orphans     │    │  Tag dist  │
                    │  Rogue tags  │    │  Growth    │
                    │  Broken      │    │  Health    │
                    │  links       │    │  dashboard │
                    │  Gap         │    │            │
                    │  analysis    │    │            │
                    └──────────────┘    └────────────┘
```

## Install

```bash
claude plugin add cajias/second-brain-plugins --plugin karpathy-llm-wiki
```

Then initialize a wiki in any directory:

```bash
mkdir my-knowledge-base && cd my-knowledge-base
/kb-init
```

## Commands

| Command | What it does |
|---------|-------------|
| `/kb-init` | Scaffold a new wiki: directories, config, tag taxonomy, .gitignore |
| `/kb-ingest` | Route raw documents into the pipeline (PDF, markdown, web, text, session logs) |
| `/kb-compile` | The core loop: read raw docs, extract atomic ideas, check for duplicates, write permanent notes with frontmatter and wikilinks |
| `/kb-query` | Semantic search across all notes using vector embeddings |
| `/kb-lint` | Health checks: orphaned notes, broken links, rogue tags, knowledge gaps |
| `/kb-index` | Rebuild the LanceDB vector index (full or incremental) |

## How It Works

### Notes are atomic

Each wiki note captures **one idea** with structured YAML frontmatter:

```yaml
---
id: perm-20260409-a1b2c
type: permanent
knowledge_type: pattern    # fact | pattern | decision | correction | idea | design | exploration
status: accepted
confidence: high           # high | medium | low
scope: universal           # universal | project | temporal
tags:                      # up to 6 from approved taxonomy
  - architecture
  - llm
  - agent-patterns
source: "compiled from: ingest-f422cad5"
created: "2026-04-09"
---

The actual insight goes here, with [[wikilinks]] to related notes.
```

### Deduplication is automatic

When compiling, every new idea is checked against the existing wiki using cosine similarity on sentence embeddings:

- **>= 0.92**: Duplicate — automatically skipped
- **0.80 - 0.91**: Similar — flagged for your review
- **< 0.80**: Unique — written to the wiki

### Search is semantic, not keyword

```bash
/kb-query "How should agents authenticate on behalf of users?"
```

Uses [LanceDB](https://lancedb.com/) with `all-MiniLM-L6-v2` embeddings for local-first vector search. No API keys, no cloud services, everything runs on your machine.

### Gap analysis feeds back in

```bash
/kb-lint --explore
```

Analyzes your wiki for knowledge gaps: underrepresented tags, missing knowledge types, disconnected clusters, and generates follow-up questions. Research the answers, ingest them, compile — the loop continues.

## Architecture

```
my-wiki/
├── .kb-config.yml          # Central config (all paths, thresholds)
├── wiki/
│   ├── permanent/          # Your knowledge base (flat, no hierarchy)
│   └── _meta/
│       ├── tag-taxonomy.md # 17 approved tags, 7 knowledge types
│       └── stats.md        # Auto-generated stats
├── raw/
│   ├── inbox/              # Staging area + .manifest.json
│   ├── artifacts/          # Ingested files (PDFs, etc.)
│   ├── sessions/           # Claude Code session logs
│   └── web/                # Web clips
├── output/
│   ├── reports/            # Lint reports, gap analyses
│   └── charts/             # Matplotlib visualizations
└── .lancedb/               # Vector index (auto-generated, gitignored)
```

**Key design choices:**

- **Flat storage** — all notes in `wiki/permanent/`, no directory hierarchy. Discovery is through semantic search, not folders.
- **Local-first** — LanceDB is embedded, sentence-transformers runs locally. No external services.
- **Obsidian-compatible** — notes use `[[wikilinks]]` and YAML frontmatter. Open the wiki directory in Obsidian and everything renders. But Obsidian is not required.
- **CLI-first** — the `kb` CLI handles all mechanical work. Claude Code commands orchestrate the intelligence.

## Tech Stack

- **Python 3.11+** with [Typer](https://typer.tiangolo.com/) CLI
- **LanceDB** for vector storage and search
- **sentence-transformers** (`all-MiniLM-L6-v2`) for local embeddings
- **matplotlib** for visualizations
- **PyYAML** for frontmatter parsing

## Development

```bash
cd plugins/karpathy-llm-wiki/llm-wiki-core
uv sync
uv run kb --help
uv run pytest -v    # 106 tests
```

## Credits

This plugin implements the workflow described by [Andrej Karpathy](https://x.com/karpathy/status/2039805659525644595). The idea is his; the implementation is ours.

## License

MIT
