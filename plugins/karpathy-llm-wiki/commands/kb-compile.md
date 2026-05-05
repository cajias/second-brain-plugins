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

   Flags:
   - `--verdict`: `yes`, `no`, or `maybe`
   - `--score`: confidence 0.0-1.0 that this entry is worth extracting
   - `--reason`: short note explaining the verdict (helps audit later)
   - `--suggested-type`: knowledge_type hint for Pass 2 (fact, pattern, decision, correction, idea, design, exploration)
   - `--suggested-tags`: comma-separated taxonomy tags hinting Pass 2's direction

4. The pass-1 prompt to yourself per entry should be **under 30 seconds of attention** -- quick skim, not deep read. The whole point is cheapness.

### Extract pass (Pass 2)

After pass 1 completes, fetch only the keepers:

```bash
kb compile --list-inbox --candidates-only --json
```

The `--candidates-only` flag filters to entries previously tagged `verdict=yes`. Process those entries in Step 3 using the **`suggested_type`** and **`suggested_tags`** from the candidate metadata as a starting hint (not a constraint -- your full read may reveal a better type/tags).

If pass-1 yield was unusually low (<10% verdict=yes on a corpus you expected to be richer), re-run with `--include-maybe` to spot-check the borderline set:

```bash
kb compile --list-inbox --candidates-only --include-maybe --json
```

## Step 3: Process the batch

Process the batch in two phases: first extract atomic ideas from every pending item and dedup the
whole batch in **one** call (3a-3c), then write the surviving notes (3d). Mark-processed happens
once at finalize (Step 4), not per item.

For each pending item in the inbox (or each candidate from Pass 2):

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

> **If the entry came from a Pass 1 candidate**: the manifest's `suggested_type` and `suggested_tags` are useful starting hints. Treat them as a default, but override freely once you've done the full read -- the deeper read may surface a better fit.

**Don't dedup or write yet.** Instead, collect each candidate idea for the whole batch into a list, recording for each a stable `key` you can map back to it (e.g. `<manifest-entry-id>#<n>`) plus its query text (the title or a key phrase). Also keep, per source item, the list of manifest entry ids you successfully extracted from -- these are marked processed once at finalize (Step 4).

### 3c. Check for duplicates (one batch call)

This replaces the previous per-idea dedup step. Instead of running `kb compile --check-dedup` (or `kb search ... --json`) once per idea, dedup the whole batch in a **single** process, so the embedding model cold-load is paid once rather than once per idea.

Write all collected candidates to a temp JSON file shaped `[{"key": "...", "query": "..."}]`:

```bash
cat > /tmp/dedup-batch.json <<'EOF'
[
  {"key": "ingest-aaa#1", "query": "Title or key phrase for idea 1"},
  {"key": "ingest-aaa#2", "query": "Title or key phrase for idea 2"}
]
EOF
```

Run one batch dedup check, passing the JSON file path:

```bash
kb compile --check-dedup-batch /tmp/dedup-batch.json --json
```

Or pass `-` to read the JSON from stdin instead of a file (skips the temp file):

```bash
cat /tmp/dedup-batch.json | kb compile --check-dedup-batch - --json
```

> **Source-aware thresholds**: each manifest entry carries a `source_class` (default `chat` if absent). Denser sources tolerate more overlap before being flagged a duplicate. When you dedup a single idea with `kb compile --check-dedup`, pass the entry's class through so the threshold matches the source's expected density:
>
> ```bash
> kb compile --check-dedup "Title or key phrase" --source-class book --json
> ```
>
> Thresholds by class: `chat` 0.92 (default), `doc` 0.93, `book` 0.94, `paper` 0.94. The JSON output includes the `threshold` actually applied.

The output is a JSON array `[{"key", "status", "top_score", "matches"}]`. Map each result back to its idea via `key` and branch by `status`:

- **`status: "unique"` (score < 0.80)**: Proceed to write the note
- **`status: "similar"` (score 0.80-0.91)**: Flag it. Show the user the similar note(s) and ask whether to proceed, merge, or skip. If using `--dry-run`, just note it as "flagged for review". If proceeding, create the note and add a similarity note in the body referencing the matching note(s).
- **`status: "duplicate"` (score >= 0.92)**: Skip it. Report that it's a duplicate of the matching note.

Clean up the temp file when done: `rm /tmp/dedup-batch.json`.

### 3d. Write the notes (with batch-context linking)

For each non-duplicate idea, write the note. **Maintain a running list of the titles/slugs you have created so far in THIS batch**, and when writing each new note add `[[wikilinks]]` to any already-created sibling from the same batch whose topic is related -- *in addition* to links into the existing wiki (see Wikilink Guidelines below). This matters because `kb index` only runs at the end of the batch (Step 4), so a mid-batch `kb search` cannot see siblings written moments earlier -- the sibling-link signal must be carried in context.

Write each note:

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

**Shell escaping**: For multi-line body content, write the body to a temp file and pass it via command substitution with `--body`:

```bash
kb compile --write-note \
  --title "Note Title Here" \
  --knowledge-type pattern \
  --tags "tag1,tag2" \
  --confidence high \
  --source "compiled from: MANIFEST_ENTRY_ID" \
  --body "$(cat /tmp/note-body.md)"
```

## Step 4: Finalize -- mark processed, then update artifacts

### 4a. Mark all processed (one batched call)

Do **not** mark items processed inside the per-item loop. After the whole batch is written (or skipped), mark every successfully-compiled source item processed in a **single** batched call -- one invocation, one manifest write:

```bash
kb compile --mark-processed "id1,id2,id3"
```

`--mark-processed` accepts a comma-separated list (or repeated `--mark-processed id1 --mark-processed id2`). It exits non-zero only if **none** of the ids were found; partial matches mark the found ones and report a `not_found` list. Skip this step in `--dry-run` mode.

Optionally, before indexing, do a light intra-batch link sweep: revisit the notes created this run and add any sibling `[[wikilinks]]` surfaced by the accumulated batch title list that were missed on first write.

### 4b. Update the index and refresh artifacts

Update the vector index and regenerate charts:

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

If you ran a two-pass workflow, also report:

- Pass 1 verdicts: N yes / N maybe / N no
- Pass 2 yield: notes-created / yes-candidates (effective extraction rate)

## Wikilink Guidelines

When writing note bodies, add [[wikilinks]] to connect to existing notes. To find relevant notes for linking:

```bash
kb search "TOPIC" --limit 3 --json
```

Use the filenames (without `.md`) from the search results as wikilinks: `[[filename-here]]`.

**Sibling (batch-context) links**: `kb search` only sees notes already in the index, and the index is refreshed once at the end of the batch (Step 4b). So also link to related notes you created *earlier in this same batch* using the running title/slug list you maintained in Step 3d -- those siblings won't show up in `kb search` yet.

## Important Notes

- The body content passed to `--body` must be properly shell-escaped. For multi-line content, write to a temp file and use `--body "$(cat /tmp/note-body.md)"`.
- If the vector index doesn't exist yet, dedup checks will return "unique" for everything -- that's fine, just create the notes.
- Tag taxonomy is available via `kb lint --tags` or in the wiki's `_meta/tag-taxonomy.md`. Only use approved tags.
- Knowledge types: fact, pattern, decision, correction, idea, design, exploration.
- Scope is always "universal" unless the content is clearly project-specific or time-bound.
- For inboxes with **50+ pending items**, always run the two-pass pre-filter (Step 2.5) -- it dramatically improves token efficiency and note quality.
