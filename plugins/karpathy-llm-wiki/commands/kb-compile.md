---
description: Compile raw documents into atomic wiki notes
---

# /kb-compile -- LLM Compile Raw -> Wiki

You are the knowledge compiler. Your job is to read raw documents from the inbox, extract atomic ideas, check for duplicates, and create permanent wiki notes. This is the core of the Karpathy workflow -- raw input becomes structured, interlinked knowledge.

> **Skills used**: Invoke `compile-note` for extraction/dedup/writing. Invoke `search-and-link` for finding wikilink targets.

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

If `--batch N` was specified, take only the first N pending items.

## Step 3: Process each pending item

For each pending item in the inbox:

1. **Read the raw file** (the `file` field from the manifest entry)
2. **Extract atomic ideas** -- follow the `compile-note` skill's extraction guidelines
3. **For each idea**:
   a. **Dedup check** -- follow the `compile-note` skill's dedup step
   b. **Find related notes** -- invoke the `search-and-link` skill to find wikilink targets
   c. **Write the note** -- follow the `compile-note` skill's writing step (skip in `--dry-run`)
4. **Mark as processed** -- follow the `compile-note` skill's mark-processed step (skip in `--dry-run`)

## Step 4: Update the index and refresh artifacts

After processing all items (skip in `--dry-run`):

```bash
kb index --incremental
kb charts
```

## Step 5: Report

Present a summary:

```
## Compile Summary

- Items processed: N
- Notes created: N
- Duplicates skipped: N
- Flagged for review: N
- Errors: N

### Notes Created
1. [[note-filename]] -- "Note Title" (pattern, tags: security, api-design)

### Duplicates Skipped
- "Duplicate Title" -- too similar to [[existing-note]] (score: 0.94)

### Flagged for Review
- "Similar Title" -- similar to [[existing-note]] (score: 0.85)

### Next Steps
- Run `/kb-lint` to check the health of new notes
- Run `/kb-query` to search across the updated wiki
```

## Important Notes

- Shell escaping for `--body`: see the `compile-note` skill for temp file approach.
- Tag taxonomy: available via `kb lint --tags` or `_meta/tag-taxonomy.md`. Only use approved tags.
- If the vector index doesn't exist, dedup checks return "unique" for everything -- that's fine.
