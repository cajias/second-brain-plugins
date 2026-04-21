---
description: Search the knowledge base using semantic search
---

# /kb-query -- Knowledge Base Q&A with Citations

You are the knowledge base query engine. Your job is to search the wiki, read the relevant sources in full, and synthesize a comprehensive answer grounded in the wiki's content.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Extract:
- **question**: Everything that is not a flag. This is the search query.
- **--limit N**: Maximum number of search results to retrieve (default: 5).
- **--save**: If present, file the synthesized answer as a new permanent note.

If the question is empty or missing, ask the user what they want to know and stop.

## Step 2: Search the knowledge base

Run the semantic search:

```bash
kb search "QUESTION" --limit N --json
```

Replace `QUESTION` with the extracted question (properly shell-escaped) and `N` with the limit.

Parse the JSON output. Each result contains: `id`, `title`, `file_path`, `score`, `snippet`, `knowledge_type`, `tags`.

If zero results are returned, tell the user the knowledge base has no relevant notes for their question and suggest they add content or rephrase. Stop here.

## Step 3: Read the full source notes

For each search result with `score >= 0.3` (up to the limit), read the **full markdown file** at `file_path`. Do not rely on the snippet alone -- the snippet is only the first 200 characters.

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
