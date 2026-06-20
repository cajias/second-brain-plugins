export const meta = {
  name: 'ingest-notion-cited-sources',
  description: 'Extract the cited external Source URLs from a set of Notion pages and ingest each one separately into the llm-wiki inbox.',
  whenToUse: 'Given Notion page ids (rows of a database), fetch each page body, extract the external URLs in its Sources section, dedup, and serially kb-ingest each (mode url). Pass extractOnly:true to only return the deduped URL list without ingesting. Args: { pages:[{id,title,number}], urls:[...], extractOnly, ingestChunk, workingDir }.',
  phases: [
    { title: 'Extract', detail: 'parallel: read each Notion page, pull Sources-section URLs' },
    { title: 'Ingest', detail: 'sequential slices: kb ingest --mode url per URL (serial; manifest is non-atomic)' },
    { title: 'Report', detail: 'summarize ingested / failed / deduped' },
  ],
}

let opts = args
if (typeof opts === 'string') { try { opts = JSON.parse(opts) } catch { opts = {} } }
opts = opts || {}

const WD = typeof opts.workingDir === 'string' && opts.workingDir ? opts.workingDir : null
const EXTRACT_ONLY = opts.extractOnly === true
const INGEST_CHUNK = Number(opts.ingestChunk) > 0 ? Math.floor(Number(opts.ingestChunk)) : 15
const EXTRACT_CHUNK = 4
const pages = Array.isArray(opts.pages) ? opts.pages : []
const directUrls = Array.isArray(opts.urls) ? opts.urls : []

if (pages.length === 0 && directUrls.length === 0) {
  throw new Error(`ingest-notion-cited-sources needs args.pages (array of {id,title}) or args.urls (array). Got args=${JSON.stringify(args)}. If args is undefined the caller forgot the args: key. Expected: Workflow({ scriptPath: "<this-file>", args: { pages: [{id, title, number}], extractOnly: true } })`)
}
if (!EXTRACT_ONLY && !WD) {
  throw new Error('ingest-notion-cited-sources requires args.workingDir (the wiki root) unless extractOnly:true.')
}

function chunk(arr, n) { const o = []; for (let i = 0; i < arr.length; i += n) o.push(arr.slice(i, i + n)); return o }
function normUrl(u) {
  let s = String(u).trim()
  s = s.replace(/[)>\].,;'"]+$/, '')
  s = s.replace(/#.*$/, '')
  s = s.replace(/\/+$/, '')
  return s
}

const EXTRACT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    found: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { url: { type: 'string' }, page: { type: 'string' } },
        required: ['url'],
      },
    },
  },
  required: ['found'],
}

const INGEST_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          url: { type: 'string' },
          ingest_id: { type: 'string' },
          path: { type: 'string' },
          ok: { type: 'boolean' },
          error: { type: 'string' },
        },
        required: ['url', 'ok'],
      },
    },
  },
  required: ['results'],
}

function extractPrompt(pgs) {
  const list = pgs.map(p => `- ${p.id}  (${p.title || ''})`).join('\n')
  return `You read Notion pages and extract the external URLs cited in each page's "Sources" section. READ-ONLY — do not modify Notion and do not run kb.

Load Notion read tools in ONE ToolSearch call: "select:mcp__plugin_Notion_notion__notion-fetch,mcp__plugin_Notion_notion__notion-search".

For EACH of these Notion page ids:
${list}

1. notion-fetch the page by id to get its full body (markdown/blocks).
2. Find the "Sources" section (a heading like "Sources", "References", or "Citations", usually near the end). Extract every EXTERNAL URL (http:// or https://) from that section — both markdown-link targets [text](url) and bare URLs. If there is no Sources section, collect any clearly-cited external URLs elsewhere in the body; if none, return nothing for that page.
3. Do NOT include internal Notion URLs (app.notion.com / notion.so) — only external sources.

Return structured output: found = [ {url, page: "<the page title or id>"} ] for every external source URL across all assigned pages. Include duplicates if present (dedup happens downstream). Only Sources/citations — not navigation or unrelated links.`
}

function ingestPrompt(urls) {
  const list = urls.map(u => `- ${u}`).join('\n')
  return `You ingest web URLs into the llm-wiki inbox. Working directory: ${WD}. Run kb from there. Do this STRICTLY SERIALLY — the inbox manifest is non-atomic; never run two kb ingest at once.

For EACH url below, in order, run:
  kb ingest --mode url --source "<url>" --source-class doc
(--source-class doc raises the dedup duplicate threshold to 0.93 — appropriate for web-cited
external sources, which are denser and more self-contained than free-form chat.)
Capture the assigned manifest id (e.g. ingest-xxxxxxxx) and destination path from the output. If a url fails (fetch error or non-zero exit), record ok=false with a short error and CONTINUE to the next — do not abort the batch.

URLs:
${list}

Return structured output: results = [ {url, ingest_id, path, ok, error} ] one per url.`
}

// ===== run =====
let urls = directUrls.map(normUrl)

if (pages.length > 0 && directUrls.length === 0) {
  phase('Extract')
  const pageChunks = chunk(pages, EXTRACT_CHUNK)
  log(`Extracting cited sources from ${pages.length} Notion pages across ${pageChunks.length} agents`)
  const extracted = await parallel(pageChunks.map((c, i) => () =>
    agent(extractPrompt(c), { label: `extract:${i + 1}/${pageChunks.length}`, phase: 'Extract', schema: EXTRACT_SCHEMA })))
  const raw = extracted.filter(Boolean).flatMap(r => (r.found || []).map(f => f.url))
  const seen = new Set(); urls = []
  for (const u of raw) { const n = normUrl(u); if (n && /^https?:\/\//i.test(n) && !seen.has(n)) { seen.add(n); urls.push(n) } }
  log(`Extracted ${raw.length} source URLs; ${urls.length} unique after dedup`)
}

if (EXTRACT_ONLY) {
  return { mode: 'extract-only', extracted_unique: urls.length, urls }
}

phase('Ingest')
const ingestChunks = chunk(urls, INGEST_CHUNK)
const ingestResults = []
for (let i = 0; i < ingestChunks.length; i++) {
  const r = await agent(ingestPrompt(ingestChunks[i]), { label: `ingest:${i + 1}/${ingestChunks.length}`, phase: 'Ingest', schema: INGEST_SCHEMA })
  if (r && r.results) ingestResults.push(...r.results)
}

phase('Report')
const ok = ingestResults.filter(r => r.ok)
const failed = ingestResults.filter(r => !r.ok)
return {
  total_unique_urls: urls.length,
  ingested: ok.length,
  failed: failed.length,
  failures: failed.map(f => ({ url: f.url, error: f.error })),
  ingest_ids: ok.map(r => r.ingest_id).filter(Boolean),
}
