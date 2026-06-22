# Design: Mirror the LLM Wiki to Notion (`/kb-push-notion`)

**Date:** 2026-06-22
**Status:** Draft for review
**Plugin:** `karpathy-llm-wiki`

## Goal

Mirror the markdown LLM wiki into a Notion database so notes can be browsed,
filtered, and cross-referenced in Notion. Wikilinks (`[[name]]`) become native
Notion **relations**, giving bidirectional back-links for free.

A second Notion database, **"LLM Wiki Sources"**, mirrors the ingest manifest
(the raw source material each note was distilled from). Each note carries a
best-effort **`Source` relation** to the source row it was derived from, so a
source page lists every note that came out of it.

**Sync model:** one-way mirror. Markdown stays the single source of truth.
`/kb-push-notion` (re)builds the Notion view from the wiki. Edits made directly
in Notion are not read back and will be overwritten on the next push.

## Non-goals (v1)

- No two-way sync / conflict resolution.
- No pruning of Notion pages whose source note was deleted from the wiki
  (orphans are left in place and logged; a `--prune` flag is a future addition).
  The same applies to the Sources DB: removed/rewritten manifest entries leave
  their Notion source row in place.
- No new Python dependency and no Notion API token management — Notion I/O goes
  through the Notion MCP, matching the existing `ingest-notion-cited-sources`
  workflow.
- **No wiki-pipeline change for the note→source link.** A compiled note's
  `source` frontmatter is free text ("Origin description") and is not guaranteed
  to equal a manifest entry's `source`, so the note→source link is **best-effort
  string match** only. Adding a stable `source_id` to note frontmatter at compile
  time (which would make the join exact) was considered and **deferred** — it
  would change the compile pipeline and the note schema, which is out of scope
  for this one-way mirror.

## Architecture

Reuses the plugin's established split: mechanical work → `kb` CLI (Python);
Notion I/O → Claude agents via Notion MCP, orchestrated by a Workflow script.
This is the same shape as the existing `workflows/ingest-notion-cited-sources.js`
(the reverse direction: Notion → wiki).

```
wiki/*.md ─────────┐
                   ├─(kb export-notion)──▶ manifest.json ──(push-to-notion.js)──▶ Notion "LLM Wiki" DB
raw_inbox/         │   deterministic Python                  Claude agents      └─▶ Notion "LLM Wiki Sources" DB
  .manifest.json ──┘                                         + Notion MCP            (note ──Source──▶ source row)
```

`kb export-notion` now reads both the wiki **and** the ingest manifest
(`raw_inbox/.manifest.json`), emitting one combined JSON manifest that carries
notes, their resolved links, **and** the source rows plus each note's
best-effort `source_ref`.

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
- The ingest manifest at `cfg.raw_inbox / ".manifest.json"` (a JSON **list**)
  for the source rows. `cfg.raw_inbox` is a `Path`; the file may be absent.

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
      "source": "https://arxiv.org/abs/1706.03762",
      "created": "2026-05-01",
      "body_md": "...note body without frontmatter...",
      "links": ["softmax", "self-attention"],
      "source_ref": "ingest-ab12cd"
    }
  ],
  "dangling": [
    {"from": "transformer-attention", "target": "nonexistent-note"}
  ],
  "sources": [
    {
      "ingest_id": "ingest-ab12cd",
      "source": "https://arxiv.org/abs/1706.03762",
      "type": "url",
      "source_class": "web",
      "date": "2026-05-01T09:00:00",
      "status": "processed",
      "file": "raw/web/2026-05-01-attention-is-all-you-need.md"
    }
  ],
  "unmatched_sources": ["some-note-whose-source-matched-nothing"]
}
```

- `links` contains only targets that resolve to an existing note slug.
- Unresolved wikilinks go to `dangling` (reported, never fatal).
- Only `permanent`/compiled notes are exported (same selection `lint`/`charts`
  use for the graph).
- `sources` mirrors the ingest manifest 1:1 — **one row per ingestion event**.
  If the same URL was ingested twice, that is two rows (an accepted
  simplification; the de-dup of identical URLs is out of scope).
- Each note's `source_ref` is the `ingest_id` of the matched source row, or
  `null`. Matching is **best-effort**: both sides are normalized with
  `_normalize_source(s) = s.strip().rstrip("/")` (case-sensitive) and the note's
  `source` is compared to each manifest entry's `source`. On multiple matches the
  entry with the latest `date` wins. The note's raw `source` text is always kept
  regardless of whether it matched.
- `unmatched_sources` lists the slugs of notes whose (non-empty) `source` matched
  no manifest entry — for logging only.
- If `raw_inbox/.manifest.json` is absent, `sources` is `[]` and every
  `source_ref` is `null` (not an error); notes that have a `source` string still
  appear in `unmatched_sources`.

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
| `created`        | Created         | Date          | |
| `links`          | **Links**       | **Relation**  | **self-relation** → same DB; back-links auto-created |
| `source_ref`     | **Source**      | **Relation**  | → "LLM Wiki Sources" DB; many notes → one source; reverse back-link auto-created. Unset when `source_ref` is `null`. |
| `body_md`        | (page content)  | blocks        | markdown converted by the Notion MCP page create |

Select option values come from the enums in `core/frontmatter.py:VALID_VALUES`.

The notes DB does **not** store a raw "Source" URL/text property. A note's external
origin is reached via the **`Source` relation** → the ingested-docs (Sources DB) row,
which holds the external link as "Source URL". The note's raw `source` frontmatter
string remains in the markdown as the single source of truth; it is used only for
best-effort matching at export time and is not written as a notes-DB property.

The **`Source` relation** is the feature's whole point: Notion auto-creates the
reverse back-link on the target source row, so each source page lists every wiki
note derived from it. The relation is set only when `source_ref` is non-null; a
note that matched nothing has no `Source` relation.

### 2a. Property mapping (Notion "LLM Wiki Sources" database)

The Sources DB is a 1:1 mirror of the ingest manifest entries — **one row per
ingestion event**. Each manifest field maps as follows:

| Manifest field | Notion property | Notion type | Notes |
|----------------|-----------------|-------------|-------|
| `source`       | Name            | Title       | Page title |
| `source`       | Source URL      | URL         | the external source link; plain text if not a URL |
| `id`           | `ingest_id`     | Text        | hidden join key; upsert key |
| `type`         | Type            | Select      | session / file / url / text / … (pass through; `artifact`/`web` also seen) |
| `source_class` | Class           | Select      | chat / web / … |
| `date`         | Ingested        | Date        | |
| `status`       | Status          | Select      | pending / processed |
| `file`         | Archived        | Text        | archived copy path, relative to project root |

The hidden `ingest_id` text property is the **upsert key** for source rows
(querying it by equality finds an existing row to update, else a new one is
created). Each manifest entry is read defensively (keys may be absent in older
entries); the manifest field `id` becomes the Notion `ingest_id` and the
manifest field `source` feeds **both** Name (Title) and Source (URL).

### 3. `workflows/push-to-notion.js` (new Workflow script)

Mirrors the structure of `ingest-notion-cited-sources.js`. Args:
`{ manifestPath, workingDir, dryRun? }`.

- **Pass 0 — ensure databases (once):** search Notion for a database titled
  "LLM Wiki"; if absent, create it with the notes properties above (Selects
  seeded from the enums, Tags multi-select seeded from the taxonomy, `Links` as
  a self-relation, **`Source` as a relation → "LLM Wiki Sources"**). Then ensure
  a database titled "LLM Wiki Sources" with the source properties from §2a
  (`ingest_id` text, Type/Class/Status selects, Ingested date, Archived text,
  Source URL). Record both database ids for this run. The notes-DB `Source`
  relation targets the Sources DB, so the Sources DB must exist (or be created)
  before the notes-DB `Source` relation property is configured.
- **Pass 1 — upsert source rows (parallel, chunked):** for each entry in
  `sources`, find the row by `ingest_id` and update its properties, or create
  it. Collect `ingest_id → source_page_id`.
- **Pass 2 — upsert note pages (parallel, chunked):** for each note, find the
  page by `slug` and update its properties + body, or create it. Relations
  (`Links`, `Source`) are **not** set here. Collect `slug → page_id`.
- **Pass 3 — wire relations (parallel, chunked):** for each note, map its `links`
  slugs to page-ids via the Pass-2 map and set the `Links` relation, AND map its
  `source_ref` to a source page-id via the Pass-1 `ingest_id → source_page_id`
  map and set the `Source` relation (skip when `source_ref` is `null` or unknown).
  Notion populates the reverse back-links automatically.
- `dryRun: true` runs export + Pass 0 and reports the create/update/relation
  counts (notes **and** sources) without writing pages.

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
- **Partial failure mid-push:** safe to re-run; upsert-by-slug (notes) and
  upsert-by-`ingest_id` (sources) both converge.
- **Note `source` matches no manifest entry:** `source_ref` is `null`, no
  `Source` relation is wired, the raw `source` text is kept on the page, and the
  note's slug is listed in `unmatched_sources` and logged. Never fatal.
- **Ingest manifest absent:** `sources` is `[]` and every `source_ref` is
  `null`. The Sources DB is still ensured (Pass 0) but has no rows to upsert.
  Not an error.

## Testing

- `kb export-notion` is fully unit-tested with the `wiki_root` fixture:
  - frontmatter → manifest field mapping (each property, both schema variants).
  - link resolution: resolved links land in `links`; unresolved in `dangling`.
  - body extraction strips frontmatter; aliased links `[[a|b]]` resolve to `a`.
  - empty wiki → `{"notes": [], "dangling": [], "sources": [], "unmatched_sources": []}`.
  - source rows: `_build_sources(cfg)` reads `raw_inbox/.manifest.json` (a JSON
    list) into source dicts; missing file → `[]`; each field read with `.get`.
  - `_normalize_source`: `" https://x/ "` → `"https://x"` (strip + `rstrip("/")`).
  - `source_ref` matching: exact match → that `ingest_id`; trailing-slash /
    whitespace differences still match; no match → `source_ref is None` and the
    slug appears in `unmatched_sources`; multiple entries with the same `source`
    → the one with the latest `date` wins.
  - manifest absent → `sources == []`, every `source_ref is None`, and notes that
    HAVE a `source` string appear in `unmatched_sources`.
- Coverage must stay ≥70% (repo gate).
- The Notion/MCP side is exercised manually via `dryRun` (matches the existing
  untested-workflow precedent; no Notion API in unit tests).

## Open questions

None blocking. Pruning, two-way sync, and a pure-Python headless path are
explicitly deferred.
