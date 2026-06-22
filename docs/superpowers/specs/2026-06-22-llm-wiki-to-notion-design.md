# Design: Mirror the LLM Wiki to Notion (`/kb-push-notion`)

**Date:** 2026-06-22
**Status:** Draft for review
**Plugin:** `karpathy-llm-wiki`

## Goal

Mirror the markdown LLM wiki into a Notion database so notes can be browsed,
filtered, and cross-referenced in Notion. Wikilinks (`[[name]]`) become native
Notion **relations**, giving bidirectional back-links for free.

**Sync model:** one-way mirror. Markdown stays the single source of truth.
`/kb-push-notion` (re)builds the Notion view from the wiki. Edits made directly
in Notion are not read back and will be overwritten on the next push.

## Non-goals (v1)

- No two-way sync / conflict resolution.
- No pruning of Notion pages whose source note was deleted from the wiki
  (orphans are left in place and logged; a `--prune` flag is a future addition).
- No new Python dependency and no Notion API token management — Notion I/O goes
  through the Notion MCP, matching the existing `ingest-notion-cited-sources`
  workflow.

## Architecture

Reuses the plugin's established split: mechanical work → `kb` CLI (Python);
Notion I/O → Claude agents via Notion MCP, orchestrated by a Workflow script.
This is the same shape as the existing `workflows/ingest-notion-cited-sources.js`
(the reverse direction: Notion → wiki).

```
wiki/*.md ──(kb export-notion)──▶ manifest.json ──(push-to-notion.js)──▶ Notion "LLM Wiki" DB
            deterministic Python                   Claude agents + Notion MCP
```

### The two-pass crux

A Notion relation can only target a page that already exists (you need its
page-id). The wiki link graph contains cycles (`A ↔ B`). Therefore pages and
their relations **cannot** be written in a single pass. The workflow must:

1. Create/upsert **every** page first, recording `slug → page_id`.
2. **Then** resolve each note's links to page-ids and set the relation property.

### Identity & idempotency

The join key is the note **slug** — the filename stem, which is exactly what
`[[name]]` wikilinks resolve against (see `lint.py:_build_link_graph`, keyed by
`name`). The slug is stored as a hidden `slug` text property on each Notion page.

Upsert = query the DB for a page with matching `slug`; update if found, else
create. **No Notion page-ids are written back into the markdown** — the wiki
stays a clean source of truth. Re-running the push is safe and idempotent.

## Components

### 1. `kb export-notion` (new Python subcommand)

A single deterministic pass over the wiki producing a JSON manifest. Registered
in `cli.py` with `app.command("export-notion")(export_notion)`, living in
`commands/export_notion.py`.

Reuses existing parsing — **no new wikilink parser**:
- `core/frontmatter.py` for per-note metadata + body.
- `commands/lint.py:_build_link_graph()` (and `WIKILINK_PATTERN` /
  `_extract_wikilinks`) for the resolved `links_to` per note.

Output (`--out manifest.json`, or stdout):

```json
{
  "notes": [
    {
      "slug": "transformer-attention",
      "title": "Transformer Attention",
      "knowledge_type": "fact",
      "status": "approved",
      "confidence": "high",
      "scope": "universal",
      "tags": ["transformers", "attention"],
      "source": "https://...",
      "created": "2026-05-01",
      "body_md": "...note body without frontmatter...",
      "links": ["softmax", "self-attention"]
    }
  ],
  "dangling": [
    {"from": "transformer-attention", "target": "nonexistent-note"}
  ]
}
```

- `links` contains only targets that resolve to an existing note slug.
- Unresolved wikilinks go to `dangling` (reported, never fatal).
- Only `permanent`/compiled notes are exported (same selection `lint`/`charts`
  use for the graph).

### 2. Property mapping (Notion "LLM Wiki" database)

| Manifest field   | Notion property | Notion type   | Notes |
|------------------|-----------------|---------------|-------|
| `title`          | Name            | Title         | Page title |
| `slug`           | `slug`          | Text          | Hidden join key |
| `knowledge_type` | Type            | Select        | fact / pattern / decision / correction / idea / design / exploration |
| `status`         | Status          | Select        | pending / approved / archived |
| `confidence`     | Confidence      | Select        | high / medium / low |
| `scope`          | Scope           | Select        | universal / project / temporal |
| `tags`           | Tags            | Multi-select  | seeded from `wiki/_meta/tag-taxonomy.md`; ≤6 |
| `source`         | Source          | URL           | plain text if not a URL |
| `created`        | Created         | Date          | |
| `links`          | **Links**       | **Relation**  | **self-relation** → same DB; back-links auto-created |
| `body_md`        | (page content)  | blocks        | markdown converted by the Notion MCP page create |

Select option values come from the enums in `core/frontmatter.py:VALID_VALUES`.

### 3. `workflows/push-to-notion.js` (new Workflow script)

Mirrors the structure of `ingest-notion-cited-sources.js`. Args:
`{ manifestPath, workingDir, dryRun? }`.

- **Pass 0 — ensure database (once):** search Notion for a database titled
  "LLM Wiki". If absent, create it with the properties above (Selects seeded
  from the enums, Tags multi-select seeded from the taxonomy, `Links` as a
  self-relation). Record the database id for this run.
- **Pass 1 — upsert pages (parallel, chunked):** for each note, find the page by
  `slug` and update its properties + body, or create it. Relations are **not**
  set here. Collect `slug → page_id`.
- **Pass 2 — wire relations (parallel, chunked):** for each note, map its `links`
  slugs to page-ids via the Pass-1 map and set the `Links` relation. Notion
  populates the reverse back-links automatically.
- `dryRun: true` runs export + Pass 0 and reports the create/update/relation
  counts without writing pages.

### 4. `/kb-push-notion` (new slash command)

A thin command markdown that: runs `kb export-notion` → invokes
`push-to-notion.js` with the manifest. Intended to be chained after
`/kb-compile`. For unattended runs it goes through `claude -p` (same as the
existing Notion workflow); there is no pure-Python headless path by design.

## Error handling

- **Dangling wikilinks:** dropped from `links`, surfaced in `dangling`, logged.
  Never fatal.
- **Tags off-taxonomy / >6:** `kb lint` already guards this upstream; the mirror
  passes tags through and Notion multi-select auto-creates any missing option.
- **Notes missing `id` frontmatter:** irrelevant — identity is the slug, not
  `id`.
- **Deleted source notes:** v1 leaves the Notion page as an orphan and logs it.
- **Partial failure mid-push:** safe to re-run; upsert-by-slug converges.

## Testing

- `kb export-notion` is fully unit-tested with the `wiki_root` fixture:
  - frontmatter → manifest field mapping (each property, both schema variants).
  - link resolution: resolved links land in `links`; unresolved in `dangling`.
  - body extraction strips frontmatter; aliased links `[[a|b]]` resolve to `a`.
  - empty wiki → `{"notes": [], "dangling": []}`.
- Coverage must stay ≥70% (repo gate).
- The Notion/MCP side is exercised manually via `dryRun` (matches the existing
  untested-workflow precedent; no Notion API in unit tests).

## Open questions

None blocking. Pruning, two-way sync, and a pure-Python headless path are
explicitly deferred.
