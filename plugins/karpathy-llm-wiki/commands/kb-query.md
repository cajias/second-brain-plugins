---
description: Search the knowledge base using semantic search
---

# /kb-query -- Knowledge Base Q&A with Citations

You are the knowledge base query engine. Your job is to search the wiki, read the relevant sources in full, and synthesize a comprehensive answer grounded in the wiki's content.

> **Skills used**: Invoke `search-and-link` for finding notes and synthesizing answers with citations.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Extract:
- **question**: Everything that is not a flag. This is the search query.
- **--limit N**: Maximum number of search results to retrieve (default: 5).
- **--save**: If present, file the synthesized answer as a new permanent note.

If the question is empty or missing, ask the user what they want to know and stop.

## Step 2: Search the knowledge base

```bash
kb search "QUESTION" --limit N --json
```

If zero results, tell the user and suggest adding content or rephrasing. Stop.

## Step 3: Read and synthesize

Follow the `search-and-link` skill's synthesis guidelines:

1. Read full files for results with `score >= 0.3` (up to limit)
2. Synthesize an answer that cites sources via `[[wikilinks]]`
3. Connect ideas across notes
4. Identify gaps and preserve nuance
5. End with a Sources section

## Step 4: Handle --save flag

If `--save` was passed, create a new permanent note from the answer. Invoke the `compile-note` skill's writing step:

```bash
kb compile --write-note \
  --title "Synthesized Title from Question" \
  --knowledge-type exploration \
  --tags "tag1,tag2" \
  --confidence medium \
  --source "kb-query synthesis" \
  --body "The synthesized answer content with [[wikilinks]]."
```

After saving, suggest running `/kb-index --incremental`. This implements the "explorations add up" loop -- the query has now compounded into the wiki.

## Important Notes

- Wikilinks: `[[filename-without-extension]]` (no path prefix, no `.md`).
- Search uses vector embeddings -- natural language queries work best.
- Do not hallucinate content not in the wiki. If coverage is incomplete, say so.
