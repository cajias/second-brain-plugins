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

## Step 2.5: Decide single-pass vs two-pass

Count the pending items. If **fewer than 50**, use single-pass: skip directly to Step 3.

If **50 or more pending items**, run a **pre-filter pass first**. The yield rate on saturated chat corpora is ~1% if you extract from every entry; pre-filtering lifts effective yield to ~15-20% on the entries you actually extract from. This saves tokens and produces better notes.

### Pre-filter pass (Pass 1)

For each pending item:

1. **Read the raw file** (the `file` field).
2. **Skim only** -- do not extract. Decide one of three verdicts:
   - **`yes`**: contains a concrete, durable, generalizable insight worth a permanent note (specific pattern, decision rationale, surprising fact, reusable design).
   - **`no`**: personal/household, ephemeral Q&A, recipe lookup, role-play, image-gen prompt, "look at this file" opener, conversation winding-down.
   - **`maybe`**: borderline -- might be useful but uncertain. The second pass can spot-check these if budget allows.
3. **Tag the verdict on the manifest** with `kb compile --tag-candidate`:

   ```bash
   kb compile --tag-candidate <ingest-id> \
       --verdict yes \
       --score 0.85 \
       --reason "specific pattern with measurable result" \
       --suggested-type pattern \
       --suggested-tags "agent-patterns,llm"
   ```

4. The pass-1 prompt to yourself per entry should be **under 30 seconds of attention** -- quick skim, not deep read. The whole point is cheapness.

### Extract pass (Pass 2)

After pass 1 completes, fetch only the keepers:

```bash
kb compile --list-inbox --candidates-only --json
```

Process those entries in Step 3 using the **`suggested_type`** and **`suggested_tags`** from the candidate metadata as a starting hint (not a constraint -- your full read may reveal a better type/tags).

If pass-1 yield was unusually low (<10% verdict=yes on a corpus you expected to be richer), re-run with `--include-maybe` to spot-check the borderline set:

```bash
kb compile --list-inbox --candidates-only --include-maybe --json
```

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
