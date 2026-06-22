export const meta = {
  name: 'push-to-notion',
  description: 'Mirror the llm-wiki manifest into a Notion "LLM Wiki" database plus a "LLM Wiki Sources" database: ensure both DBs, upsert one source row per ingestion event (keyed by ingest_id), upsert one page per note (keyed by slug), then wire [[wikilinks]] into the Links self-relation and each note into its best-effort Source relation. One-way mirror; markdown stays the source of truth.',
  whenToUse: 'After kb export-notion has written a manifest.json. Args: { manifestPath, workingDir, dryRun }. manifestPath is the JSON file ({notes:[...],dangling:[...],sources:[...],unmatched_sources:[...]}); workingDir is the wiki root. dryRun:true runs Pass 0 (ensure both DBs) and reports note + source create/update/relation counts without writing pages.',
  phases: [
    { title: 'EnsureDBs', detail: 'search Notion for databases titled "LLM Wiki" and "LLM Wiki Sources"; create either with its property schema if absent (the notes DB Source relation targets the Sources DB)' },
    { title: 'UpsertSources', detail: 'parallel chunks: find source row by ingest_id, update properties, or create; collect ingest_id -> source_page_id' },
    { title: 'UpsertPages', detail: 'parallel chunks: find page by slug, update properties + body, or create; collect slug -> page_id' },
    { title: 'WireRelations', detail: 'parallel chunks: map each note\'s links slugs to page-ids and set the Links self-relation, and map its source_ref ingest_id to a source page-id and set the Source relation' },
    { title: 'Report', detail: 'summarize created / updated / sources_created / sources_updated / relations_set / source_relations_set / dangling' },
  ],
}

let opts = args
if (typeof opts === 'string') { try { opts = JSON.parse(opts) } catch { opts = {} } }
opts = opts || {}

const MANIFEST_PATH = typeof opts.manifestPath === 'string' && opts.manifestPath ? opts.manifestPath : null
const WD = typeof opts.workingDir === 'string' && opts.workingDir ? opts.workingDir : null
const DRY_RUN = opts.dryRun === true
const UPSERT_CHUNK = Number(opts.upsertChunk) > 0 ? Math.floor(Number(opts.upsertChunk)) : 10
const RELATION_CHUNK = Number(opts.relationChunk) > 0 ? Math.floor(Number(opts.relationChunk)) : 15
const DB_TITLE = 'LLM Wiki'
const SOURCES_DB_TITLE = 'LLM Wiki Sources'

if (!MANIFEST_PATH) {
  throw new Error(`push-to-notion needs args.manifestPath (the kb export-notion JSON file). Got args=${JSON.stringify(args)}. If args is undefined the caller forgot the args: key. Expected: Workflow({ scriptPath: "<this-file>", args: { manifestPath: "/abs/path/notion-manifest.json", workingDir: "/abs/path/wiki-root", dryRun: false } })`)
}
if (!WD) {
  throw new Error(`push-to-notion needs args.workingDir (the wiki root, used to resolve a relative manifestPath). Expected: Workflow({ scriptPath: "<this-file>", args: { manifestPath: "${MANIFEST_PATH}", workingDir: "/abs/path/wiki-root" } })`)
}

function chunk(arr, n) { const o = []; for (let i = 0; i < arr.length; i += n) o.push(arr.slice(i, i + n)); return o }

const NOTION_TOOLS = 'select:mcp__plugin_Notion_notion__notion-search,mcp__plugin_Notion_notion__notion-create-database,mcp__plugin_Notion_notion__notion-query-data-sources,mcp__plugin_Notion_notion__notion-create-pages,mcp__plugin_Notion_notion__notion-update-page,mcp__plugin_Notion_notion__notion-fetch'

const ENSURE_DB_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    database_id: { type: 'string' },
    created: { type: 'boolean' },
    sources_database_id: { type: 'string' },
    sources_created: { type: 'boolean' },
  },
  required: ['database_id', 'created', 'sources_database_id', 'sources_created'],
}

const SOURCE_UPSERT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          ingest_id: { type: 'string' },
          page_id: { type: 'string' },
          action: { type: 'string' },
          ok: { type: 'boolean' },
          error: { type: 'string' },
        },
        required: ['ingest_id', 'ok'],
      },
    },
  },
  required: ['results'],
}

const UPSERT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          slug: { type: 'string' },
          page_id: { type: 'string' },
          action: { type: 'string' },
          ok: { type: 'boolean' },
          error: { type: 'string' },
        },
        required: ['slug', 'ok'],
      },
    },
  },
  required: ['results'],
}

const RELATION_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          slug: { type: 'string' },
          relations_set: { type: 'number' },
          source_relation_set: { type: 'boolean' },
          ok: { type: 'boolean' },
          error: { type: 'string' },
        },
        required: ['slug', 'ok'],
      },
    },
  },
  required: ['results'],
}

function ensureDbPrompt() {
  return `You ensure TWO Notion databases exist with the exact schemas below. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

Do the SOURCES database FIRST, because the notes database's "Source" relation must target it.

A. Ensure the sources database titled exactly "${SOURCES_DB_TITLE}":
1. notion-search for a database titled exactly "${SOURCES_DB_TITLE}". If found, capture its id and set sources_created=false. Do NOT recreate or alter it.
2. If not found, notion-create-database titled "${SOURCES_DB_TITLE}" with these properties, then set sources_created=true:
   - Name: title (the source string)
   - Source: url (the source string; plain text if not an http(s) URL)
   - ingest_id: rich_text (hidden join key; the upsert key; never shown to the user)
   - Type: select with options: session, file, url, text (other values auto-create on first use)
   - Class: select (leave options empty; they auto-create on first use)
   - Ingested: date
   - Status: select with options: pending, processed
   - Archived: rich_text (the archived-copy path)

B. Ensure the notes database titled exactly "${DB_TITLE}":
1. notion-search for a database titled exactly "${DB_TITLE}". If found, capture its id and set created=false. Do NOT recreate or alter it.
2. If not found, notion-create-database titled "${DB_TITLE}" with these properties, then set created=true:
   - Name: title
   - slug: rich_text (hidden join key; never shown to the user)
   - Type: select with options: fact, pattern, decision, correction, idea, design, exploration
   - Status: select with options: pending, approved, archived
   - Confidence: select with options: high, medium, low
   - Scope: select with options: universal, project, temporal
   - Tags: multi_select (leave options empty; they auto-create on first use)
   - Source: url
   - Created: date
   - Links: relation pointing to THIS SAME database (a self-relation); enable the auto-created reverse "Related to" back-link
   - Source: relation pointing to the "${SOURCES_DB_TITLE}" database (the sources database id from step A); enable the auto-created reverse back-link so each source row lists every note derived from it

Return structured output { database_id, created, sources_database_id, sources_created }.`
}

function sourceUpsertPrompt(sourcesDatabaseId, sources) {
  const list = sources.map(s => `- ingest_id=${s.ingest_id || ''} | source=${JSON.stringify(s.source || '')} | type=${s.type || ''} | class=${s.source_class || ''} | ingested=${s.date || ''} | status=${s.status || ''} | archived=${JSON.stringify(s.file || '')}`).join('\n')
  return `You upsert SOURCE rows into the Notion database id ${sourcesDatabaseId} (the "${SOURCES_DB_TITLE}" database). Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

For EACH source below (one row per ingestion event; the upsert key is ingest_id):
1. notion-query-data-sources on database ${sourcesDatabaseId} filtering the "ingest_id" rich_text property equals the source's ingest_id.
2. If a row matches, notion-update-page: set Name=source, Source (url; if not an http(s) URL store it as a plain value anyway), Type, Class, Ingested (date), Status, Archived (the file path). Record action="updated".
3. If no row matches, notion-create-pages in database ${sourcesDatabaseId} with the same properties. Always set the hidden "ingest_id" property to the source's ingest_id. Record action="created".
4. If a source fails, record ok=false with a short error and CONTINUE.

Sources:
${list}

Return structured output { results: [ {ingest_id, page_id, action, ok, error} ] } one per source.`
}

function upsertPrompt(databaseId, notes) {
  const list = notes.map(n => `- slug=${n.slug} | title=${JSON.stringify(n.title)} | type=${n.knowledge_type || ''} | status=${n.status || ''} | confidence=${n.confidence || ''} | scope=${n.scope || ''} | tags=${JSON.stringify(n.tags || [])} | source=${JSON.stringify(n.source || '')} | created=${n.created || ''}`).join('\n')
  const bodies = notes.map(n => `### slug=${n.slug}\n${n.body_md || ''}`).join('\n\n---\n\n')
  return `You upsert pages into the Notion database id ${databaseId}. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}". Do NOT set the Links relation in this pass — relations are wired in a later pass.

For EACH note below:
1. notion-query-data-sources on database ${databaseId} filtering the "slug" rich_text property equals the note's slug.
2. If a page matches, notion-update-page: set Name=title, Type, Status, Confidence, Scope, Tags (multi-select), Source (url; if not an http(s) URL store it as a plain rich_text-style value in the Source field anyway), Created (date), and replace the page body with the markdown for that slug. Record action="updated".
3. If no page matches, notion-create-pages in database ${databaseId} with the same properties and the markdown body. Always set the hidden "slug" property to the note's slug. Record action="created".
4. If a note fails, record ok=false with a short error and CONTINUE.

Note properties:
${list}

Note bodies (markdown; the heading "### slug=..." is a separator, not page content):
${bodies}

Return structured output { results: [ {slug, page_id, action, ok, error} ] } one per note.`
}

function relationPrompt(databaseId, items) {
  const list = items.map(it => `- slug=${it.slug} page_id=${it.page_id} links_to_page_ids=${JSON.stringify(it.target_page_ids)} source_page_id=${JSON.stringify(it.source_page_id || null)}`).join('\n')
  return `You set the "Links" self-relation AND the "Source" relation on pages in Notion database ${databaseId}. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

For EACH item below, notion-update-page on page_id and:
1. Set the "Links" relation property to exactly the list of links_to_page_ids given (replace any existing relation value). If that list is empty, set the relation to empty.
2. If source_page_id is a non-null string, set the "Source" relation property to exactly that single page-id (replace any existing value). If source_page_id is null, leave the "Source" relation empty.
Notion auto-populates the reverse back-links for both relations. If a page fails, record ok=false with a short error and CONTINUE.

In each result, record relations_set = number of Links targets set, and source_relation_set = true if you set a Source relation for that item (else false).

Items:
${list}

Return structured output { results: [ {slug, relations_set, source_relation_set, ok, error} ] } one per item.`
}

// ===== run =====
phase('EnsureDBs')
const fs = await import('node:fs')
const path = await import('node:path')
const resolvedManifest = path.isAbsolute(MANIFEST_PATH) ? MANIFEST_PATH : path.join(WD, MANIFEST_PATH)
const manifest = JSON.parse(fs.readFileSync(resolvedManifest, 'utf8'))
const notes = Array.isArray(manifest.notes) ? manifest.notes : []
const sources = Array.isArray(manifest.sources) ? manifest.sources : []
const danglingCount = Array.isArray(manifest.dangling) ? manifest.dangling.length : 0
const unmatchedCount = Array.isArray(manifest.unmatched_sources) ? manifest.unmatched_sources.length : 0
log(`Loaded ${notes.length} notes, ${sources.length} sources, ${danglingCount} dangling links, ${unmatchedCount} unmatched sources from ${resolvedManifest}`)

const ensured = await agent(ensureDbPrompt(), { label: 'ensure-dbs', phase: 'EnsureDBs', schema: ENSURE_DB_SCHEMA })
const databaseId = ensured && ensured.database_id ? ensured.database_id : null
const sourcesDatabaseId = ensured && ensured.sources_database_id ? ensured.sources_database_id : null
if (!databaseId) { throw new Error('push-to-notion: could not resolve or create the "LLM Wiki" database id.') }
if (!sourcesDatabaseId) { throw new Error('push-to-notion: could not resolve or create the "LLM Wiki Sources" database id.') }
log(`Notes DB ${databaseId} (created=${ensured.created}); Sources DB ${sourcesDatabaseId} (created=${ensured.sources_created})`)

if (DRY_RUN) {
  return {
    mode: 'dry-run',
    database_id: databaseId,
    sources_database_id: sourcesDatabaseId,
    db_created: ensured.created === true,
    sources_db_created: ensured.sources_created === true,
    would_upsert: notes.length,
    would_upsert_sources: sources.length,
    would_set_relations: notes.filter(n => Array.isArray(n.links) && n.links.length > 0).length,
    would_set_source_relations: notes.filter(n => typeof n.source_ref === 'string' && n.source_ref).length,
    dangling: danglingCount,
    unmatched_sources: unmatchedCount,
  }
}

phase('UpsertSources')
const sourceChunks = chunk(sources, UPSERT_CHUNK)
const sourceResults = []
await parallel(sourceChunks.map((c, i) => async () => {
  const r = await agent(sourceUpsertPrompt(sourcesDatabaseId, c), { label: `upsert-sources:${i + 1}/${sourceChunks.length}`, phase: 'UpsertSources', schema: SOURCE_UPSERT_SCHEMA })
  if (r && r.results) sourceResults.push(...r.results)
}))
const ingestToPage = {}
for (const r of sourceResults) { if (r.ok && r.ingest_id && r.page_id) ingestToPage[r.ingest_id] = r.page_id }
const sourcesCreated = sourceResults.filter(r => r.ok && r.action === 'created').length
const sourcesUpdated = sourceResults.filter(r => r.ok && r.action === 'updated').length

phase('UpsertPages')
const upsertChunks = chunk(notes, UPSERT_CHUNK)
const upsertResults = []
await parallel(upsertChunks.map((c, i) => async () => {
  const r = await agent(upsertPrompt(databaseId, c), { label: `upsert:${i + 1}/${upsertChunks.length}`, phase: 'UpsertPages', schema: UPSERT_SCHEMA })
  if (r && r.results) upsertResults.push(...r.results)
}))

const slugToPage = {}
for (const r of upsertResults) { if (r.ok && r.slug && r.page_id) slugToPage[r.slug] = r.page_id }
const created = upsertResults.filter(r => r.ok && r.action === 'created').length
const updated = upsertResults.filter(r => r.ok && r.action === 'updated').length

phase('WireRelations')
const relationItems = []
for (const n of notes) {
  const pageId = slugToPage[n.slug]
  if (!pageId) continue
  const targetIds = (Array.isArray(n.links) ? n.links : []).map(s => slugToPage[s]).filter(Boolean)
  const sourcePageId = (typeof n.source_ref === 'string' && n.source_ref) ? (ingestToPage[n.source_ref] || null) : null
  relationItems.push({ slug: n.slug, page_id: pageId, target_page_ids: targetIds, source_page_id: sourcePageId })
}
// Only wire items that have at least one Links target OR a resolved Source page.
const relationChunks = chunk(relationItems.filter(it => it.target_page_ids.length > 0 || it.source_page_id), RELATION_CHUNK)
const relationResults = []
await parallel(relationChunks.map((c, i) => async () => {
  const r = await agent(relationPrompt(databaseId, c), { label: `relations:${i + 1}/${relationChunks.length}`, phase: 'WireRelations', schema: RELATION_SCHEMA })
  if (r && r.results) relationResults.push(...r.results)
}))
const relationsSet = relationResults.filter(r => r.ok).reduce((acc, r) => acc + (Number(r.relations_set) || 0), 0)
const sourceRelationsSet = relationResults.filter(r => r.ok && r.source_relation_set === true).length

phase('Report')
return {
  database_id: databaseId,
  sources_database_id: sourcesDatabaseId,
  created,
  updated,
  sources_created: sourcesCreated,
  sources_updated: sourcesUpdated,
  relations_set: relationsSet,
  source_relations_set: sourceRelationsSet,
  dangling: danglingCount,
  unmatched_sources: unmatchedCount,
  dryRun: false,
  failures: upsertResults.filter(r => !r.ok).map(r => ({ slug: r.slug, error: r.error })),
  source_failures: sourceResults.filter(r => !r.ok).map(r => ({ ingest_id: r.ingest_id, error: r.error })),
}
