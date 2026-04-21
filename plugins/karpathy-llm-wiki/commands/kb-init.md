---
description: Initialize a new knowledge wiki in the current directory
---

# /kb-init -- Initialize Knowledge Wiki

You are the knowledge base initializer. Your job is to scaffold a new knowledge wiki in the current directory.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

There are no required arguments. Optional flags:
- **--force**: Re-initialize even if a `.kb-config.yml` already exists

If no arguments are provided, proceed with default initialization.

## Step 2: Check for existing wiki

Before initializing, check if a `.kb-config.yml` already exists in the current directory:

```bash
kb init --check 2>/dev/null || true
```

If the wiki is already initialized and `--force` was not passed, tell the user:
> "This directory already has a knowledge wiki. Use `--force` to re-initialize, or start using `/kb-ingest` to add documents."

Stop here unless `--force` was specified.

## Step 3: Initialize

Run the initialization:

```bash
kb init
```

If `--force` was passed:

```bash
kb init --force
```

## Step 4: Report what was created

After successful initialization, report the structure that was created:

```
## Wiki Initialized

Created knowledge wiki structure:

  .kb-config.yml          -- Configuration file
  wiki/
    permanent/            -- Atomic wiki notes live here
    _meta/
      tag-taxonomy.md     -- Approved tag vocabulary
      stats.md            -- Auto-generated statistics
  raw/
    inbox/                -- Raw documents waiting to be compiled
    inbox/.manifest.json  -- Tracks ingestion state
  output/
    reports/              -- Lint reports and explorations
    charts/               -- Auto-generated visualizations

### Next Steps
1. Ingest some documents: `/kb-ingest file path/to/document.md`
2. Compile into wiki notes: `/kb-compile`
3. Search your wiki: `/kb-query "your question here"`
```

## Important Notes

- The `kb` CLI must be installed and on PATH.
- Initialization creates the directory structure and default config but does NOT create any wiki notes.
- The `.kb-config.yml` file controls all paths and settings -- edit it to customize.
