---
name: compile-tool
description: Compile a tool-ingested inbox item (source_class=tool) into exactly one knowledge_type=tool permanent note, classified by one tool-* tag, 1-2 phase-* tags, and up to 2 topic tags, with source preserved as the original URL.
---

# Compile Tool

Turns a tool-ingested raw item (one URL = one tool) into ONE permanent
`knowledge_type: tool` note. Used by `/kb-compile` when an inbox entry has
`source_class: tool` (or `type: tool`).

## When this applies

Only for inbox entries whose manifest `source_class` is `tool`. For every other
entry, use `compile-note` (atomic-idea extraction). One tool URL → exactly ONE note.

## Step 1: Read the raw item

The raw file starts with a `<!-- tool: <url> | lang/host | ⭐stars | topics -->`
comment and a one-line description, followed by the README (GitHub) or extracted
page markdown. The `<url>` in that comment is the canonical `source:`.

## Step 2: Dedup by source URL

```bash
kb search --where "source = '<url>'" --json
```

If a note already has this `source`, UPDATE it in place (re-classify/refresh body)
rather than creating a duplicate. Otherwise proceed.

## Step 3: Classify (controlled tags, ≤6 total)

- **Exactly one** tool-type: `tool-framework`, `tool-library`, `tool-cli`, `tool-mcp-server`, `tool-agent`, `tool-skill`, `tool-plugin`, `tool-sdk`, `tool-service`, `tool-dataset`.
- **1-2** SDLC phase: `phase-planning`, `phase-design`, `phase-implementation`, `phase-code-review`, `phase-testing`, `phase-debugging`, `phase-deployment`, `phase-observability`, `phase-security`, `phase-docs`.
- **0-2** topic tags from the existing approved taxonomy (e.g. `llm`, `agent-patterns`, `testing`).

If classification is ambiguous, pick the most-specific defensible `tool-*` and note the uncertainty in the body.

## Step 4: Write the note (structured body)

Body sections: **What it is · What it's for · Install · Key capabilities · Link**.
Always preserve the canonical URL as `source`.

```bash
kb compile --write-note \
  --title "Deepeval -- LLM Evaluation Framework" \
  --knowledge-type tool \
  --tags "tool-framework,phase-testing,llm" \
  --confidence medium \
  --source "https://deepeval.com" \
  --body "$(cat /tmp/tool-body.md)"
```

`--source` MUST be the original URL (web-source preservation). `kb compile`
validates tags against the taxonomy and writes via the canonical frontmatter dumper.

## Step 5: Mark processed + refresh

```bash
kb compile --mark-processed "MANIFEST_ENTRY_ID"
kb index --incremental
```

After indexing, `kb search --knowledge-type tool --tag phase-testing --json` will
return this tool in the handout.
