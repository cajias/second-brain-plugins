---
description: Initialize a new knowledge wiki in the current directory
---

# /kb-init -- Initialize Knowledge Wiki

You are the knowledge base initializer. Your job is to scaffold a new knowledge wiki in the current directory.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

There are no required arguments. An optional positional path can be provided to initialize a different directory.

If no arguments are provided, proceed with default initialization in the current directory.

## Step 2: Initialize

Run the initialization:

```bash
kb init
```

Or with a specific path:

```bash
kb init /path/to/wiki
```

If `.kb-config.yml` already exists, the CLI will error. In that case, tell the user:
> "This directory already has a knowledge wiki. Start using `/kb-ingest` to add documents."

Stop here.

## Step 3: Report what was created

After successful initialization, report the structure that was created:

```
## Wiki Initialized

Created knowledge wiki structure:

  .kb-config.yml          -- Configuration file
  wiki/
    permanent/            -- Atomic wiki notes live here
    _meta/
      tag-taxonomy.md     -- Approved tag vocabulary
  raw/
    inbox/                -- Raw documents waiting to be compiled
    inbox/.manifest.json  -- Tracks ingestion state
    sessions/             -- Claude Code session logs
    artifacts/            -- Ingested files (PDFs, etc.)
    web/                  -- Web clips
  output/
    reports/              -- Lint reports and explorations
    charts/               -- Auto-generated visualizations
  .gitignore              -- Ignores .lancedb/, __pycache__, etc.

### Next Steps
1. Ingest some documents: `/kb-ingest file path/to/document.md`
2. Compile into wiki notes: `/kb-compile`
3. Search your wiki: `/kb-query "your question here"`
```

## Important Notes

- The `kb` CLI must be installed and on PATH.
- Initialization creates the directory structure and default config but does NOT create any wiki notes.
- The `.kb-config.yml` file controls all paths and settings -- edit it to customize.
