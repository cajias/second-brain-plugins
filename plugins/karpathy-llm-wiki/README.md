# karpathy-llm-wiki

An implementation of [Andrej Karpathy's LLM knowledge base workflow](https://x.com/karpathy/status/2039805659525644595) as a Claude Code plugin.

> _"Something I'm finding very useful recently: using LLMs to build personal knowledge bases for various topics of research interest. [...] Raw data from a given number of sources is collected, then an LLM incrementally compiles a wiki from it, which you can then query, visualize, and lint."_
> — Andrej Karpathy

![karpathy-llm-wiki shell CLI demo: init → ingest → compile → index → search](../../docs/demos/karpathy-llm-wiki.gif)

## The Idea

Karpathy described a workflow where raw documents (articles, papers, repos) are indexed into a `raw/` directory, then an LLM **incrementally compiles a wiki** from them — extracting concepts, writing articles, adding backlinks, and maintaining the whole thing. You query it, explore it, lint it, and your explorations feed back in, so your knowledge always "adds up."

This plugin implements that full loop as a set of Claude Code commands.

## The Workflow

```mermaid
flowchart LR
    subgraph Ingest
        A["/kb-ingest\nPDFs, articles,\nweb clips, sessions"]
    end
    subgraph Compile
        B["/kb-compile\nExtract atomic ideas\nDedup · Wikilink"]
    end
    subgraph Query
        C["/kb-query\nSemantic search\nacross all notes"]
    end
    subgraph Maintain
        D["/kb-lint\nOrphans · Rogue tags\nBroken links · Gaps"]
        E["/kb-health\nStaleness · Coverage\nLink suggestions"]
        F["kb charts\nTag dist · Growth\nHealth dashboard"]
    end

    A --> B --> C
    C -->|explorations\nfeed back in| A
    B --> D --> F
    B --> E
```

## Install

```bash
claude plugin marketplace add https://code.aws.dev/proserve/product-and-solutions/tools/knowledge-management/second-brain-plugins
claude plugin install karpathy-llm-wiki@second-brain-plugins
```

Then initialize a wiki in any directory:

```bash
mkdir my-knowledge-base && cd my-knowledge-base
/kb-init
```

## Commands

| Command       | What it does                                                                                                                   |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `/kb-init`    | Scaffold a new wiki: directories, config, tag taxonomy, .gitignore                                                             |
| `/kb-ingest`  | Route raw documents into the pipeline (PDF, markdown, web, text, session logs)                                                 |
| `/kb-compile` | The core loop: read raw docs, extract atomic ideas, check for duplicates, write permanent notes with frontmatter and wikilinks |
| `/kb-query`   | Semantic search across all notes using vector embeddings                                                                       |
| `/kb-lint`    | Health checks: orphaned notes, broken links, rogue tags, knowledge gaps                                                        |
| `/kb-health`  | Comprehensive wiki audit — staleness, gaps, orphans, link suggestions; produces an actionable report                           |
| `/kb-index`   | Rebuild the LanceDB vector index (full or incremental)                                                                         |

## Agents

The plugin includes 5 autonomous agents that can work on your wiki independently:

| Agent                | What it does                                                                                                                                      |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **compile-agent**    | Processes all pending inbox items end-to-end: reads raw docs, extracts atomic ideas, deduplicates, writes notes with wikilinks, updates the index |
| **gap-researcher**   | Analyzes your wiki for knowledge gaps (underrepresented tags, missing topic bridges), then researches and creates notes to fill them              |
| **wikilink-agent**   | Scans for orphaned notes and adds meaningful `[[wikilinks]]` to connect them into a knowledge graph                                               |
| **quality-reviewer** | Audits recently compiled notes for accuracy, proper tagging, confidence calibration, and connection quality                                       |
| **wiki-health**      | Runs a full health audit (staleness, gaps, orphans, link suggestions) and produces an actionable report                                           |

These agents can be dispatched to work in the background while you continue other work. They're the "maintenance crew" that keeps your wiki healthy and interconnected.

## Skills

Skills are reusable knowledge modules that both commands and agents invoke. They eliminate duplication — the "how to do X" lives in one place.

| Skill               | What it knows                                                                |
| ------------------- | ---------------------------------------------------------------------------- |
| **compile-note**    | Extracting atomic ideas, dedup checking, writing notes with frontmatter      |
| **search-and-link** | Finding related notes via semantic search, adding meaningful `[[wikilinks]]` |
| **lint-and-repair** | Running health checks, interpreting results, conservative auto-repair        |
| **gap-analysis**    | Identifying underrepresented tags/types, missing bridges, research questions |

```mermaid
flowchart TD
    subgraph Skills
        S1["compile-note"]
        S2["search-and-link"]
        S3["lint-and-repair"]
        S4["gap-analysis"]
    end
    subgraph Commands
        C1["/kb-compile"]
        C2["/kb-query"]
        C3["/kb-lint"]
        C4["/kb-health"]
    end
    subgraph Agents
        A1["compile-agent"]
        A2["wikilink-agent"]
        A3["quality-reviewer"]
        A4["gap-researcher"]
        A5["wiki-health"]
    end

    C1 -.-> S1
    C1 -.-> S2
    C2 -.-> S2
    C3 -.-> S3
    C3 -.-> S4
    C4 -.-> S3
    C4 -.-> S4
    A1 -.-> S1
    A1 -.-> S2
    A2 -.-> S2
    A2 -.-> S3
    A3 -.-> S3
    A3 -.-> S2
    A4 -.-> S4
    A4 -.-> S1
    A4 -.-> S2
    A5 -.-> S3
    A5 -.-> S4
```

**Commands** are interactive (you invoke them, you stay in the loop). **Agents** are autonomous (dispatch them, they work independently). **Skills** are the shared knowledge both use.

## Hooks

The plugin ships a `PostToolUse` hook that wires the wiki engine into Claude Code itself:

```jsonc
// hooks/hooks.json
{
  "PostToolUse": [
    {
      "matcher": "Edit|Write",
      "hooks": [
        {
          "command": "bash $CLAUDE_PLUGIN_ROOT/hooks/scripts/lint-and-index.sh",
        },
      ],
    },
  ],
}
```

Whenever Claude edits or writes a file, `lint-and-index.sh` runs `kb lint` on the touched file and triggers an incremental `kb index` if it's a permanent note. The vector index stays current without you ever invoking `kb index` manually.

## How It Works

### Notes are atomic

Each wiki note captures **one idea** with structured YAML frontmatter:

```yaml
---
id: perm-20260409-a1b2c
type: permanent
knowledge_type: pattern # fact | pattern | decision | correction | idea | design | exploration
status: accepted
confidence: high # high | medium | low
scope: universal # universal | project | temporal
tags: # up to 6 from approved taxonomy
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

### PDF ingest via Marker (opt-in)

PDF extraction uses [Marker](https://github.com/datalab-to/marker), which preserves equations, tables, code blocks, and document structure far better than naive text extraction. It is shipped as an **optional extra** because the model weights are sizable:

```bash
cd plugins/karpathy-llm-wiki/llm-wiki-core
uv sync --all-extras   # installs marker-pdf
```

Without the `[pdf]` extra, `kb ingest --mode pdf` will print an instructive error pointing you back here. Markdown, plain text, and web ingest all work without the extra.

### Location-independent CLI

Set `KARPATHY_WIKI_ROOT` so `kb` works from anywhere:

```bash
export KARPATHY_WIKI_ROOT=~/my-wiki
kb search "authentication patterns"   # no need to cd into the wiki
```

Resolution order: `--root` flag → `KARPATHY_WIKI_ROOT` → walk up from cwd looking for `.kb-config.yml`.

### Gap analysis feeds back in

```bash
/kb-lint --explore
# or for a richer audit:
/kb-health
```

Analyzes your wiki for knowledge gaps: underrepresented tags, missing knowledge types, disconnected clusters, and generates follow-up questions. Research the answers, ingest them, compile — the loop continues.

## Architecture

```
my-wiki/
├── .kb-config.yml          # Central config (all paths, thresholds)
├── wiki/
│   ├── permanent/          # Your knowledge base (flat, no hierarchy)
│   ├── _index/             # Created on first `kb index` run
│   └── _meta/
│       ├── tag-taxonomy.md # 17 approved tags, 7 knowledge types
│       └── stats.md        # Auto-generated by `kb charts`
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

## What It Produces

These are real outputs from a vault of 66 notes spanning trading patterns, LLM agents, and risk management:

| ![Tag distribution](../../docs/demos/screenshots/tag-distribution.png) | ![Knowledge types](../../docs/demos/screenshots/knowledge-type-distribution.png) |
| :--------------------------------------------------------------------: | :------------------------------------------------------------------------------: |
|               **Tag distribution** — note counts per tag               |                **Knowledge types** — types observed in this vault                |
| ![Growth over time](../../docs/demos/screenshots/growth-over-time.png) |        ![Health summary](../../docs/demos/screenshots/health-summary.png)        |
|              **Growth over time** — note-creation cadence              |           **Health summary** — snapshot of vault size and composition            |

All charts are auto-generated by the analytics pipeline. Browse [`docs/demos/screenshots/`](../../docs/demos/screenshots/) for the full set, including an [example stats dashboard](../../docs/demos/screenshots/example-stats-dashboard.md) that the plugin writes to `wiki/_meta/stats.md`.

## Tech Stack

- **Python 3.11+** with [Typer](https://typer.tiangolo.com/) CLI
- **LanceDB** for vector storage and search
- **sentence-transformers** (`all-MiniLM-L6-v2`) for local embeddings
- **[Marker](https://github.com/datalab-to/marker)** for high-fidelity PDF extraction (opt-in `[pdf]` extra)
- **matplotlib** for visualizations
- **PyYAML** for frontmatter parsing

## Development

```bash
cd plugins/karpathy-llm-wiki/llm-wiki-core
uv sync --all-extras
uv run kb --help
uv run pytest -v
```

## Credits

This plugin implements the workflow described by [Andrej Karpathy](https://x.com/karpathy/status/2039805659525644595). The idea is his; the implementation is ours.

## License

MIT
