---
description: Compile raw documents into atomic wiki notes
---

# /kb-compile -- LLM Compile Raw -> Wiki

You are the knowledge compiler. Your job is to read raw documents from the inbox, extract atomic ideas, check for duplicates, and create permanent wiki notes. This is the core of the Karpathy workflow -- raw input becomes structured, interlinked knowledge.

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

### 3a. Read the raw document

Read the full content of the raw file (the `file` field from the manifest entry).

### 3b. Extract atomic ideas

Analyze the raw document and extract atomic ideas. Each idea should be:
- **One concept per note** -- if an idea has sub-parts, split them
- **Self-contained** -- understandable without reading the source document
- **Titled descriptively** -- the title should capture the core claim or pattern

A single raw document might produce 1-5 atomic notes depending on its density.

For each atomic idea, determine:
- **title**: A clear, descriptive title (will become the filename slug)
- **knowledge_type**: One of: fact, pattern, decision, correction, idea, design, exploration
- **tags**: Up to 6 from the approved taxonomy (architecture, testing, security, performance, api-design, authentication, observability, databases, distributed-systems, devops, frontend, llm, agent-patterns, code-quality, documentation, error-handling, data-modeling)
- **confidence**: high, medium, or low
- **body**: The note content in markdown, using [[wikilinks]] to reference existing notes where relevant

### 3c. Check for duplicates

For each atomic idea, run the dedup check:

```bash
kb compile --check-dedup "TITLE OR KEY PHRASE" --json
```

Interpret the result:
- **`status: "unique"` (score < 0.80)**: Proceed to write the note
- **`status: "similar"` (score 0.80-0.91)**: Flag it. Show the user the similar note(s) and ask whether to proceed, merge, or skip. If using `--dry-run`, just note it as "flagged for review".
- **`status: "duplicate"` (score >= 0.92)**: Skip it. Report that it's a duplicate of the matching note.

### 3d. Write the note (if not duplicate)

For unique ideas, write the note:

```bash
kb compile --write-note \
  --title "Note Title Here" \
  --knowledge-type pattern \
  --tags "tag1,tag2,tag3" \
  --confidence high \
  --source "compiled from: MANIFEST_ENTRY_ID" \
  --body "The note body content here with [[wikilinks]] to related notes."
```

If `--dry-run` is active, add the `--dry-run` flag:

```bash
kb compile --dry-run --write-note \
  --title "Note Title Here" \
  --knowledge-type pattern \
  --tags "tag1,tag2" \
  --confidence medium \
  --source "test" \
  --body "Preview content."
```

**Shell escaping**: For multi-line body content, write the body to a temp file and pass it via stdin or `--body-file`:

```bash
kb compile --write-note \
  --title "Note Title Here" \
  --knowledge-type pattern \
  --tags "tag1,tag2" \
  --confidence high \
  --source "compiled from: MANIFEST_ENTRY_ID" \
  --body "$(cat /tmp/note-body.md)"
```

### 3e. Mark as processed

After all ideas from a raw document are written (or skipped), mark it as processed:

```bash
kb compile --mark-processed "MANIFEST_ENTRY_ID"
```

Skip this step in `--dry-run` mode.

## Step 4: Update the index and refresh artifacts

After processing all items, update the vector index and regenerate charts:

```bash
kb index --incremental
```

Then refresh the derived artifacts so they reflect the new notes:

```bash
kb charts
```

Skip both steps in `--dry-run` mode.

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
2. [[another-note]] -- "Another Title" (fact, tags: llm, agent-patterns)

### Duplicates Skipped
- "Duplicate Title" -- too similar to [[existing-note]] (score: 0.94)

### Flagged for Review
- "Similar Title" -- similar to [[existing-note]] (score: 0.85)

### Next Steps
- Run `/kb-lint` to check the health of new notes
- Run `/kb-query` to search across the updated wiki
```

## Wikilink Guidelines

When writing note bodies, add [[wikilinks]] to connect to existing notes. To find relevant notes for linking:

```bash
kb search "TOPIC" --limit 3 --json
```

Use the filenames (without `.md`) from the search results as wikilinks: `[[filename-here]]`.

## Important Notes

- The body content passed to `--body` must be properly shell-escaped. For multi-line content, write to a temp file and use `--body "$(cat /tmp/note-body.md)"`.
- If the vector index doesn't exist yet, dedup checks will return "unique" for everything -- that's fine, just create the notes.
- Tag taxonomy is available via `kb lint --tags` or in the wiki's `_meta/tag-taxonomy.md`. Only use approved tags.
- Knowledge types: fact, pattern, decision, correction, idea, design, exploration.
- Scope is always "universal" unless the content is clearly project-specific or time-bound.
