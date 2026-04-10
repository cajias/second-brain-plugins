---
name: search-and-link
description: Reusable skill for finding semantically related notes and adding meaningful wikilinks to connect them into a knowledge graph
---

# Search and Link

Shared knowledge for finding related notes and connecting them with [[wikilinks]]. Used by `/kb-query`, `/kb-compile`, `compile-agent`, and `wikilink-agent`.

## Searching for Related Notes

```bash
kb search "TOPIC OR QUESTION" --limit N --json
```

Each result contains: `id`, `title`, `file_path`, `score`, `snippet`, `knowledge_type`, `tags`.

### Relevance Thresholds

| Score | Meaning | Action |
|-------|---------|--------|
| >= 0.7 | Highly relevant | Strong wikilink candidate |
| 0.4 - 0.69 | Moderately relevant | Wikilink if contextually appropriate |
| 0.3 - 0.39 | Weakly relevant | Only link if thematic connection is clear |
| < 0.3 | Not relevant | Do not link |

## Adding Wikilinks

Wikilinks use the filename without `.md` and without path prefix: `[[note-title-here]]`.

### Inline Links (preferred)

Add links where they make contextual sense in the note body:

> Enterprises manage 45+ machine identities per human user [[45-machine-identities-per-human-user-in-enterprises]], which makes [[certificate-rotation-patterns]] critical.

### Related Section (supplementary)

For broader connections that don't fit inline, add a `## Related` section at the end:

```markdown
## Related

- [[related-concept]] -- how it connects
- [[another-note]] -- why it's relevant
```

### Quality Rules

- **Every wikilink target must exist** -- verify before adding
- **Links must add meaning** -- `see also [[unrelated-note]]` is noise
- **Prefer bidirectional connections** -- if A links to B, consider linking B to A
- **Preserve existing content** -- only add, never remove existing wikilinks or content
- **Don't over-link** -- 3-5 wikilinks per note is healthy; 10+ suggests the note isn't atomic enough

## Hub-and-Spoke Strategy (for wikilink-agent)

When connecting many notes at once:

1. **Start with hubs**: Notes with 4+ tags are natural hubs -- connect other notes to these first
2. **Process orphans next**: After hubs are connected, find remaining orphans and link them to the hub network
3. **Aim for 20+ percentage point orphan rate reduction per run**

## Synthesizing Across Notes (for kb-query)

When answering questions from search results:

1. Read the **full file** at each result's `file_path` -- don't rely on snippets alone
2. **Cite sources inline** using wikilinks: `According to [[note-name]], ...`
3. **Synthesize across notes** -- connect ideas, don't just summarize sequentially
4. **Identify gaps** -- if the question is only partially answered, say what's missing
5. **Preserve nuance** -- surface caveats, confidence levels, and contradictions

### Sources Section

Always end synthesized answers with:

```
### Sources
- [[note-filename]] (score: 0.XX) -- what this note contributed
- [[another-note]] (score: 0.XX) -- what this note contributed
```
