---
description: Mirror the wiki into a Notion "LLM Wiki" database
---

# /kb-push-notion -- Mirror the LLM Wiki to Notion

You mirror the markdown wiki into a Notion "LLM Wiki" database, plus a "LLM Wiki
Sources" database mirroring the ingested source material. This is a one-way
mirror: markdown stays the single source of truth, and edits made directly in
Notion are overwritten on the next push. Wikilinks (`[[name]]`) become a native
Notion **self-relation**, and each note gets a best-effort **Source relation**
to the source row it was derived from, giving bidirectional back-links for free.
Intended to be chained after `/kb-compile`.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Extract:

- **--dry-run**: Build the manifest and ensure the Notion database, then report
  the create/update/relation counts WITHOUT writing pages.
- No flags: full push (ensure DB, upsert pages, wire relations).

## Step 2: Build the manifest

Run the deterministic exporter from the wiki root. This writes a JSON manifest
(`{"notes": [...], "dangling": [...], "sources": [...], "unmatched_sources": [...]}`)
with one entry per permanent note (resolved wikilinks in `links`, unresolved in
`dangling`, and a best-effort `source_ref`), plus one `sources` row per ingestion
event read from `raw/inbox/.manifest.json`:

```bash
kb export-notion --out output/notion-manifest.json
```

The command prints how many notes and dangling links were written. If it
reports 0 notes, tell the user the wiki has no permanent notes yet and stop.

Note the absolute wiki root path (the directory containing `.kb-config.yml`) --
you pass it to the workflow as `workingDir`.

## Step 3: Push to Notion via the workflow

Invoke the `push-to-notion.js` workflow with the manifest. Use the absolute
path to `${CLAUDE_PLUGIN_ROOT}/workflows/push-to-notion.js` as `scriptPath`,
the absolute manifest path (or the path relative to `workingDir`), and the
absolute wiki root as `workingDir`.

For a dry run (when `--dry-run` was passed):

```
Workflow({
  scriptPath: "<plugin-root>/workflows/push-to-notion.js",
  args: { manifestPath: "output/notion-manifest.json", workingDir: "<wiki-root>", dryRun: true }
})
```

For a full push (no flags):

```
Workflow({
  scriptPath: "<plugin-root>/workflows/push-to-notion.js",
  args: { manifestPath: "output/notion-manifest.json", workingDir: "<wiki-root>", dryRun: false }
})
```

The workflow runs several passes: ensure the "LLM Wiki" and "LLM Wiki Sources"
databases exist, upsert one source row per ingestion event keyed by the hidden
`ingest_id` property, upsert one page per note keyed by the hidden `slug`
property, then wire the `Links` self-relation and the `Source` note→source
relation. It returns counts for created / updated / sources_created /
sources_updated / relations_set / source_relations_set / dangling /
unmatched_sources.

## Step 4: Report

Present a summary using the workflow's return value:

```
## Notion Push Summary

- Notes database: <database_id> (created: yes/no)
- Sources database: <sources_database_id> (created: yes/no)
- Pages created: N
- Pages updated: N
- Source rows created: N
- Source rows updated: N
- Links relations set: N
- Source relations set: N
- Dangling links (dropped): N
- Notes with an unmatched source: N

### Next Steps
- Open the "LLM Wiki" database in Notion to browse and filter notes.
- Open a source page to see every note derived from it (the Source back-link).
- Re-run /kb-push-notion after /kb-compile to keep the mirror current.
```

## Important Notes

- The push is **idempotent**: upsert-by-slug (notes) and upsert-by-`ingest_id`
  (sources) converge, so it is always safe to re-run. No Notion page-ids are
  written back into the markdown.
- Dangling wikilinks (targets with no matching note) are dropped from relations
  and reported; they are never fatal.
- The note→source link is **best-effort**: a note's free-text `source` is matched
  against the ingest manifest by normalized string. A note whose `source` matches
  nothing gets no `Source` relation and is counted under "unmatched source". The
  notes DB does **not** store a raw "Source" URL property — the note's external
  origin is reached via the **`Source` relation** → the "LLM Wiki Sources" row,
  which holds the external link as the "Source URL" property.
- If `raw/inbox/.manifest.json` is absent, there are simply no source rows and no
  `Source` relations — not an error.
- Deleted source notes (and removed manifest entries) leave their Notion page or
  source row as an orphan in v1 (logged, not pruned).
- All Notion I/O goes through the Notion MCP; there is no Notion API token to
  configure here.
