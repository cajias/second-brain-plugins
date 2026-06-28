---
name: compile-note
description: Reusable skill for extracting atomic ideas from raw documents, deduplicating against existing notes, and writing permanent wiki notes with proper frontmatter and wikilinks
---

# Compile Note

Shared knowledge for turning raw content into atomic wiki notes. Used by `/kb-compile` (interactively) and `compile-agent` (autonomously).

> **Tool items:** If the inbox entry's `source_class` is `tool` (one URL = one tool),
> do NOT extract atomic ideas — use the `compile-tool` skill instead (one
> `knowledge_type: tool` note, classified by one `tool-*` + `phase-*` tags).

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

### Output language

Extract note **titles and bodies** in the same language as the source document, unless the
user asks for a different language. Keep frontmatter **field names** (`knowledge_type`,
`tags`, `confidence`, ...) and **taxonomy values** (tag names and knowledge types) in
English -- those are a fixed controlled vocabulary the CLI validates against.

> **Caveat:** the filename slug is derived from the title, and the slugifier currently keeps
> only Latin `a-z0-9`. A title in a non-Latin script (CJK, Cyrillic, Arabic, Hebrew) slugs to
> empty and falls back to an opaque `perm-YYYYMMDD-xxxxx` filename -- which also becomes the
> `[[wikilink]]` target, defeating human-readable links. Latin-accented titles degrade but
> survive. Prefer a Latin-script (e.g. transliterated or English) title when readable
> filenames matter.

## Deduplication

Before writing any note, check for duplicates:

```bash
kb compile --check-dedup "TITLE OR KEY PHRASE" --json
```

Interpret the result:

| Score | Status | Action |
|-------|--------|--------|
| >= 0.92 | `duplicate` | **Skip** -- report the matching note |
| 0.80 - 0.91 | `similar` | **Merge** -- append this idea into the existing note via `kb compile --merge-into` (see below); interactive callers may confirm with the user first |
| < 0.80 | `unique` | **Proceed** to write |

If the vector index doesn't exist yet, all checks return "unique" -- that's fine.

### Merging into a similar note

When the check returns `similar`, don't create a new note -- the idea belongs with the one
it overlaps. Take the `file_path` of the top match from the dedup result (the highest-scoring
entry in the `--check-dedup --json` `matches` list) and append the new idea body into it:

```bash
kb compile --merge-into "/abs/path/to/existing-note.md" \
  --body "The new idea body with [[wikilinks]]."
```

The dedup `file_path` is **project-root-relative** (e.g. `wiki/permanent/foo.md`), but
`--merge-into` resolves the path against the current working directory. Pass an **absolute**
path: either prefix the project root onto the relative `file_path`, or run `kb` from the
project root so the relative path resolves. A bare relative path will fail with
`Merge target not found` whenever `kb` runs from a subdirectory.

This appends the body to the existing note and preserves its frontmatter (same wiring as
`--write-note`). For multi-line bodies, use the temp-file pattern shown below. Skip in
dry-run mode.

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
