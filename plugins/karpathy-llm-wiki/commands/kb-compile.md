---
description: Compile raw documents into atomic wiki notes
---

# /kb-compile -- LLM Compile Raw -> Wiki

You are the command dispatcher for knowledge compilation. Your job is to check the inbox, then dispatch the `compile-agent` to do the actual work.

> **Agent used**: Dispatch the `compile-agent` for extraction, dedup, wikilink discovery, and note creation.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Extract:
- **--batch N**: Process only N items from the inbox (default: all pending)
- **--dry-run**: Preview what notes would be created without writing anything
- No flags: process all pending inbox items

## Step 2: Check the inbox

List pending items:

```bash
kb compile --list-inbox --json
```

Parse the JSON output. Filter for entries with `status: "pending"`.

If the inbox is empty, tell the user: "Inbox is empty. Use `/kb-ingest` to add raw documents first." Stop here.

If `--batch N` was specified, note the batch size for the agent.

## Step 3: Dispatch the compile-agent

Dispatch the `compile-agent` with context:
- Which pending items to process (all, or first N if `--batch` was specified)
- Whether `--dry-run` is active (agent should preview only, not write)

The agent handles the full workflow: extraction, dedup, wikilink discovery, writing, marking processed, index update, and charts refresh.

## Step 4: Display results

After the agent completes, display its summary to the user:
- Notes created, duplicates skipped, flagged items, errors
- Suggest next steps: `/kb-lint` to check health, `/kb-query` to search

## Important Notes

- Tag taxonomy: available via `kb lint --tags` or `_meta/tag-taxonomy.md`. Only use approved tags.
- If the vector index doesn't exist, dedup checks return "unique" for everything -- that's fine.
