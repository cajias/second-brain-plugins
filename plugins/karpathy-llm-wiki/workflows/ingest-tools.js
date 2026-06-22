export const meta = {
  name: 'ingest-tools',
  description: 'Serially ingest a batch of tool URLs (GitHub repos or product/docs pages) into the llm-wiki inbox as source_class=tool, one note per URL.',
  whenToUse: 'Given a list of tool URLs (or owner/repo refs), serially run kb ingest-tool for each (manifest is non-atomic; never parallel). Args: { urls:[...], workingDir }.',
  phases: [
    { title: 'Ingest', detail: 'sequential: kb ingest-tool per URL (serial; manifest is non-atomic)' },
    { title: 'Report', detail: 'summarize ingested / failed' },
  ],
}

let opts = args
if (typeof opts === 'string') { try { opts = JSON.parse(opts) } catch { opts = {} } }
opts = opts || {}

const WD = typeof opts.workingDir === 'string' && opts.workingDir ? opts.workingDir : null
const urls = Array.isArray(opts.urls) ? opts.urls : []

if (urls.length === 0) {
  throw new Error(`ingest-tools needs args.urls (array of tool URLs or owner/repo refs). Got args=${JSON.stringify(args)}. Expected: Workflow({ scriptPath: "<this-file>", args: { urls: ["https://github.com/owner/repo"], workingDir: "/path/to/wiki" } })`)
}
if (!WD) {
  throw new Error('ingest-tools requires args.workingDir (the wiki root).')
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

function ingestPrompt(list) {
  const bullets = list.map(u => `- ${u}`).join('\n')
  return `You ingest TOOL URLs into the llm-wiki inbox. Working directory: ${WD}. Run kb from there. Do this STRICTLY SERIALLY — the inbox manifest is non-atomic; never run two kb ingest-tool at once.

For EACH url below, in order, run:
  kb ingest-tool "<url>"
Capture the manifest id (ingest-xxxxxxxx) and destination path from the output. If a url fails, record ok=false with a short error and CONTINUE — do not abort the batch.

URLs:
${bullets}

Return structured output: results = [ {url, ingest_id, path, ok, error} ] one per url.`
}

phase('Ingest')
const r = await agent(ingestPrompt(urls), { label: 'ingest-tools', phase: 'Ingest', schema: INGEST_SCHEMA })
const results = (r && r.results) || []

phase('Report')
const ok = results.filter(x => x.ok)
const failed = results.filter(x => !x.ok)
return {
  total_urls: urls.length,
  ingested: ok.length,
  failed: failed.length,
  failures: failed.map(f => ({ url: f.url, error: f.error })),
  ingest_ids: ok.map(x => x.ingest_id).filter(Boolean),
}
