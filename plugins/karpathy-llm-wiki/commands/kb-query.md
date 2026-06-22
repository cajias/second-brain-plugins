---
description: Search the knowledge base using semantic search
---

# /kb-query -- Knowledge Base Q&A with Citations

You are the knowledge base query engine. Your job is to search the wiki, read the relevant sources in full, and synthesize a comprehensive answer grounded in the wiki's content.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Extract:
- **question**: Everything that is not a flag. This is the search query (optional when a filter is given).
- **--knowledge-type VALUE**: Filter by `knowledge_type` frontmatter field (e.g. `tool`, `concept`, `decision`).
- **--tag VALUE**: Filter by tag (repeatable; multiple `--tag` flags combine as AND -- the note must have all of them).
- **--type VALUE**: Filter by frontmatter `type` field.
- **--scope VALUE**: Filter by frontmatter `scope` field.
- **--where EXPR**: Raw SQL predicate appended with AND to any other filters (advanced).
- **--limit N**: Maximum number of results to retrieve (default: config `query.default_limit` for semantic search; all matches for filter-only mode).
- **--save**: If present, file the synthesized answer as a new permanent note.

**Two modes:**

1. **Semantic mode** (question provided, no filters OR question + filters): ranked by embedding similarity,
   highest-score results first. Use this for open-ended discovery ("how does X work?").
2. **Filter-only mode** (no question, at least one filter): returns ALL matching notes (no score cap).
   Use this for exhaustive handouts ("every tool tagged `phase-testing`"). No `--limit` cap is applied
   unless you pass one explicitly.

Error cases:
- Question missing AND no filter provided → error. Ask the user what they want to know and stop.

## Step 2: Search the knowledge base

Choose the right invocation based on the mode.

**Semantic search** (question only):

```bash
kb search "QUESTION" --limit N --json
```

**Semantic + filter** (ranked discovery within a subset):

```bash
kb search "QUESTION" --tag tool-cli --limit N --json
```

**Filter-only handout** (enumerate every match, no query):

```bash
kb search --knowledge-type tool --tag phase-testing --json
```

**Multiple tags** (AND logic -- note must carry all tags):

```bash
kb search --tag phase-testing --tag tool-cli --json
```

Replace `QUESTION` with the extracted question (properly shell-escaped) and `N` with the limit.

Parse the JSON output. Each result contains: `id`, `title`, `file_path`, `score`, `snippet`, `knowledge_type`, `tags`.

If zero results are returned, tell the user the knowledge base has no matching notes and suggest they add content, rephrase, or broaden the filters. Stop here.

## Step 3: Read the full source notes

For each search result with `score >= 0.3` (or all results in filter-only mode), read the **full markdown file** at `file_path`. Do not rely on the snippet alone -- the snippet is only the first 200 characters.

As you read each note, track:
- The note's title (for citation)
- The filename without `.md` extension (for wikilinks)
- Key claims, patterns, facts, or decisions from the note
- How it relates to the user's question

If all results have `score < 0.3`, read the top 3 anyway but caveat your answer with a note about low relevance.

## Step 4: Synthesize the answer

Write a comprehensive answer to the user's question that:

1. **Directly addresses the question** -- lead with the answer, not background.
2. **Cites sources using wikilinks** -- use `[[filename-without-extension]]` inline wherever you reference a specific note's content. For example: "Enterprises manage 45+ machine identities per human user [[45-machine-identities-per-human-user-in-enterprises]]."
3. **Synthesizes across notes** -- connect ideas from multiple notes when relevant. Don't just summarize each note sequentially.
4. **Identifies gaps** -- if the question is only partially answered by the wiki, say what's missing and suggest follow-up topics.
5. **Preserves nuance** -- if notes contain caveats, confidence levels, or contradictions, surface them.

For filter-only handouts, present the matched notes as a structured list rather than a synthesized narrative.

Format the answer with clear structure (headers, bullets) when the answer is complex. Keep it concise when the answer is simple.

At the end of the answer, include a **Sources** section:

```
### Sources
- [[note-filename]] (score: 0.XX) -- one-line description of what this note contributed
- [[another-note]] (score: 0.XX) -- one-line description
```

## Step 5: Handle --save flag

If `--save` was passed, create a new permanent note from the synthesized answer:

```bash
kb compile --write-note \
  --title "Synthesized Title from Question" \
  --knowledge-type exploration \
  --tags "tag1,tag2" \
  --confidence medium \
  --source "kb-query synthesis" \
  --body "The synthesized answer content with [[wikilinks]]."
```

After saving, tell the user:
- The file path of the new note
- Suggest running `/kb-index --incremental` to add it to the search index
- This implements the "explorations add up" loop -- the query has now compounded into the wiki

## Step 6: Report

Present the synthesized answer to the user. If `--save` was used, confirm the note was created and where.

## Important Notes

- Wikilinks use the filename without `.md` and without any path prefix: `[[note-title-here]]`.
- The search uses vector embeddings. Queries work best as natural language questions or topic phrases.
- Do not hallucinate content that is not in the wiki notes. If the wiki doesn't cover something, say so.
- **Filter-only mode** is the right tool when you need an exhaustive handout -- e.g. "all tools for phase-testing"
  yields a complete list, not a ranked top-N. Add `--limit` only if you want to cap it.
- **Multiple `--tag` flags combine as AND** -- the note must carry every specified tag.
- **`--where EXPR`** accepts a raw DataFusion SQL predicate for advanced filtering not covered by the named flags.
