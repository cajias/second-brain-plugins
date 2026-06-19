---
name: compile-note
description: Reusable skill for extracting atomic ideas from raw documents, deduplicating against existing notes, and writing permanent wiki notes with proper frontmatter and wikilinks
---

# Compile Note

Shared knowledge for turning raw content into atomic wiki notes. Used by `/kb-compile` (interactively) and `compile-agent` (autonomously).

## Extracting Atomic Ideas

Analyze raw content and extract atomic ideas. Each idea must be:

- **One concept per note** -- if an idea has sub-parts, split them into separate notes
- **Self-contained** -- understandable without reading the source document
- **Titled descriptively** -- the title captures the core claim or pattern

A single raw document typically produces 1-5 atomic notes depending on density.

For each idea, determine:

| Field | Values | Guidance |
|-------|--------|----------|
| **title** | Descriptive slug-friendly title | Captures the core claim or pattern |
| **knowledge_type** | fact, pattern, decision, correction, idea, design, exploration | fact = verified truth; pattern = reusable approach; decision = choice with tradeoffs; correction = common mistake; idea = untested hypothesis; design = system design; exploration = open question |
| **tags** | Up to 6 from approved taxonomy | architecture, testing, security, performance, api-design, authentication, observability, databases, distributed-systems, devops, frontend, llm, agent-patterns, code-quality, documentation, error-handling, data-modeling |
| **confidence** | high, medium, low | high = strong evidence or well-established; medium = reasonable support; low = speculative or single source |
| **scope** | universal, project, temporal | universal unless clearly project-specific or time-bound |

## Deduplication

Before writing any note, check for duplicates:

```bash
kb compile --check-dedup "TITLE OR KEY PHRASE" --json
```

Interpret the result:

| Score | Status | Action |
|-------|--------|--------|
| >= 0.92 | `duplicate` | **Skip** -- report the matching note |
| 0.80 - 0.91 | `similar` | **Flag** -- show similar note(s), ask whether to proceed/merge/skip (interactive) or create with similarity note (autonomous) |
| < 0.80 | `unique` | **Proceed** to write |

If the vector index doesn't exist yet, all checks return "unique" -- that's fine.

## Finding Related Notes for Wikilinks

Before writing, search for related notes to create [[wikilinks]]:

```bash
kb search "TOPIC OR TITLE" --limit 3 --json
```

Use filenames (without `.md`) from results as wikilink targets: `[[filename-here]]`.

Only add wikilinks that are genuinely meaningful -- forced connections are noise. Invoke the `search-and-link` skill for detailed linking guidance.

## Writing the Note

**Always use `kb compile --write-note` to create notes.** Do NOT use the Write/Edit tools to create note files directly.

Why: the CLI emits the canonical frontmatter schema with deterministic field order, collision-safe filenames, and taxonomy validation. The schema is tiered — required fields are `tags`, `source`, `created`, and a knowledge type (via `knowledge_type` or `type`); the recommended fields `id`, `type`, `status`, `confidence`, `scope` round out the canonical set. Writing files directly produces a simplified schema that diverges over time and requires post-hoc migration (`kb migrate-frontmatter`).

```bash
kb compile --write-note \
  --title "Note Title Here" \
  --knowledge-type pattern \
  --tags "tag1,tag2,tag3" \
  --confidence high \
  --source "compiled from: SOURCE_ID" \
  --body "The note body with [[wikilinks]] to related notes."
```

### Shell Escaping

For multi-line body content, write to a temp file first:

```bash
kb compile --write-note \
  --title "Note Title Here" \
  --knowledge-type pattern \
  --tags "tag1,tag2" \
  --confidence high \
  --source "compiled from: SOURCE_ID" \
  --body "$(cat /tmp/note-body.md)"
```

### Dry Run

Add `--dry-run` to preview without writing:

```bash
kb compile --dry-run --write-note \
  --title "Preview Title" \
  --knowledge-type pattern \
  --tags "tag1" \
  --confidence medium \
  --source "test" \
  --body "Preview content."
```

## Marking Processed

After all ideas from a raw document are written (or skipped):

```bash
kb compile --mark-processed "MANIFEST_ENTRY_ID"
```

Skip in dry-run mode.

## Post-Compile Refresh

After writing notes, always refresh the index and derived artifacts:

```bash
kb index --incremental
kb charts
```

Skip both in dry-run mode.
