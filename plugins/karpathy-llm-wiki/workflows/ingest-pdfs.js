export const meta = {
  name: 'ingest-pdfs',
  description: 'Download a book PDF and/or arxiv papers (from a gist or URL list), extract to markdown with pymupdf4llm, split the book by chapter, stamp provenance frontmatter, and serial-ingest each unit into the llm-wiki inbox.',
  whenToUse: 'Use to bulk-ingest PDFs as per-chapter / per-paper wiki inbox items. Give a bookUrl and/or a gistId (a gist whose file has a URL column of arxiv/paper links) and/or an explicit pdfUrls list. It downloads them, extracts markdown via pymupdf4llm (uv, pinned python), splits the book on chapter headings, writes a source: URL into each markdown for provenance, and ingests each serially. Optionally runs compile-inbox-batch after. Args: { workingDir (required), bookUrl, gistId, pdfUrls, splitBook, compileAfter, chunkSize, scratchDir }.',
  phases: [
    { title: 'Download', detail: 'fetch book + papers (gist/urls) into the scratch dir' },
    { title: 'Extract', detail: 'pymupdf4llm -> markdown; split book by chapter; stamp source frontmatter' },
    { title: 'Ingest', detail: 'serial kb ingest --mode file per markdown unit' },
    { title: 'Compile', detail: 'optional: run compile-inbox-batch on the new items' },
  ],
}

// ---- args normalization (per claude-workflow-authoring-gotchas) ----
let opts = args
if (typeof opts === 'string') {
  try { opts = JSON.parse(opts) } catch { opts = {} }
}
opts = opts || {}

const WD = typeof opts.workingDir === 'string' && opts.workingDir ? opts.workingDir : null
if (!WD) {
  throw new Error(
    `ingest-pdfs requires args.workingDir (absolute path to the wiki root containing .kb-config.yml).
Got args=${JSON.stringify(args)}. If args is undefined the caller likely forgot the \`args:\` key.
Expected: Workflow({ name: "ingest-pdfs", args: { workingDir: "/abs/wiki", bookUrl: "https://.../book.pdf", gistId: "<id>", compileAfter: true } })`,
  )
}
const SCRATCH = typeof opts.scratchDir === 'string' && opts.scratchDir ? opts.scratchDir : '/tmp/pdf-ingest'
const BOOK_URL = typeof opts.bookUrl === 'string' && opts.bookUrl ? opts.bookUrl : null
const GIST_ID = typeof opts.gistId === 'string' && opts.gistId ? opts.gistId : null
const PDF_URLS = Array.isArray(opts.pdfUrls) ? opts.pdfUrls : []
const SPLIT_BOOK = opts.splitBook !== false // default true
const COMPILE_AFTER = opts.compileAfter === true
const CHUNK = Number(opts.chunkSize) > 0 ? Math.floor(Number(opts.chunkSize)) : 5
const EXTRACT_BATCH = 12
const INGEST_SLICE = 30

function chunk(arr, n) {
  const out = []
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n))
  return out
}

// ---- schemas ----
const DOWNLOAD_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    book: { type: 'string' },
    papers: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { path: { type: 'string' }, source: { type: 'string' }, title: { type: 'string' } },
        required: ['path', 'source'],
      },
    },
    skipped: { type: 'array', items: { type: 'string' } },
  },
  required: ['papers'],
}

const EXTRACT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    mds: { type: 'array', items: { type: 'string' } },
    failed: { type: 'array', items: { type: 'string' } },
  },
  required: ['mds'],
}

const INGEST_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    ingested: { type: 'number' },
    failed: { type: 'number' },
    pending_after: { type: 'number' },
    notes: { type: 'string' },
  },
  required: ['ingested'],
}

// ---- prompts ----
function downloadPrompt() {
  return `You download PDFs (a book and/or arxiv papers) into a scratch dir. Be polite to arxiv (sleep 3 between fetches). Do not extract.

SCRATCH: mkdir -p ${SCRATCH}/papers
${BOOK_URL ? `BOOK: curl -sL "${BOOK_URL}" -o ${SCRATCH}/book.pdf ; verify it is a real PDF (file ${SCRATCH}/book.pdf shows 'PDF document') and non-trivial size.` : 'BOOK: none provided (skip).'}

PAPERS — gather URLs from BOTH sources below, dedupe:
${GIST_ID ? `- GIST: curl -sL "https://api.github.com/gists/${GIST_ID}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(next(iter(d['files'].values()))['content'])" — parse the URL column (last column if CSV).` : '- GIST: none.'}
${PDF_URLS.length ? `- EXPLICIT URLS: ${PDF_URLS.join(' , ')}` : '- EXPLICIT URLS: none.'}

For EACH paper URL, normalize to a direct PDF: arxiv.org/abs/<id> and www.arxiv.org/abs/<id> and arxiv.org/html/<id> and huggingface.co/papers/<id> -> https://arxiv.org/pdf/<id> ; arxiv.org/pdf/<id> keep. Anything else (blog/DOI/paywall) -> SKIP and record in skipped.
Download each with a real User-Agent following redirects to ${SCRATCH}/papers/<arxiv-id-or-slug>.pdf ; sleep 3 between arxiv fetches; verify each is a 'PDF document' and >20KB (delete + mark failed otherwise). Capture the canonical source URL (https://arxiv.org/abs/<id>) and, if available from the gist title column, the paper title.

Return structured output: book = "${SCRATCH}/book.pdf" (or "" if none), papers = [{path, source, title}] for each downloaded PDF, skipped = [urls skipped].`
}

function extractPapersPrompt(paperBatch) {
  const list = paperBatch.map(p => `- ${p.path}  source=${p.source}  title=${(p.title || '').slice(0, 120)}`).join('\n')
  return `You extract PDF papers to markdown with pymupdf4llm and stamp provenance frontmatter. Use uv with a pinned python for reliable wheels: prefix python with \`uv run --python 3.12 --with pymupdf4llm python3\`. mkdir -p ${SCRATCH}/md/papers

For EACH paper below, in ONE python script (loop; not one call per file):
  - md = pymupdf4llm.to_markdown("<path>")
  - If md < 500 chars, record as failed and skip.
  - Write ${SCRATCH}/md/papers/<basename-without-.pdf>.md as:
    ---
    title: "<title>"
    source: "<source>"
    ---

    <md>

Papers:
${list}

Return structured output: mds = [list of written .md absolute paths], failed = [paths that failed].`
}

function extractBookPrompt(bookPath) {
  return `You extract a book PDF to markdown with pymupdf4llm and split it into per-chapter files with provenance frontmatter. Use \`uv run --python 3.12 --with pymupdf4llm python3\`. mkdir -p ${SCRATCH}/md/book

1. md = pymupdf4llm.to_markdown("${bookPath}") (may take a minute for a large book).
${SPLIT_BOOK ? `2. Find the chapter delimiter by inspecting headings (print lines matching '^#+ .*[Cc]hapter', '^Chapter \\\\d+', '^#+ \\\\d+\\\\b'); the cleanest pattern (often '^## Chapter N: <title>') wins.
3. Split into one file PER CHAPTER (front-matter as its own file or attached to ch1; appendices/refs can be one back-matter file). Write ${SCRATCH}/md/book/chapter-NN-<slug>.md for each, with frontmatter:
   ---
   title: "<book title> — Ch NN: <chapter title>"
   source: "${BOOK_URL || 'book'}"
   ---

   <chapter markdown>
   If chapters can't be detected cleanly, fall back to splitting on top-level (#) headings, but PREFER true chapter boundaries.` : `2. Write the whole book as ONE file ${SCRATCH}/md/book/book.md with frontmatter title + source: "${BOOK_URL || 'book'}".`}

Return structured output: mds = [list of written .md absolute paths], failed = [] (or note extraction failure).`
}

function ingestSlicePrompt(mdPaths) {
  const list = mdPaths.map(p => `"${p}"`).join(' ')
  return `You ingest markdown files into the llm-wiki inbox STRICTLY SERIALLY (the manifest is non-atomic; never two kb ingest at once). Working directory: ${WD}. Run kb from there.

For each file path below, run (one at a time, serial loop):
  for f in ${list}; do kb ingest --mode file --source "$f" 2>&1 | tail -1; done
Each file already has YAML frontmatter with a source: URL — kb ingest --mode file copies markdown as-is (preserves frontmatter). Count how many succeeded vs failed.

Then report the new pending count:
  kb compile --list-inbox --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); items=d if isinstance(d,list) else d.get("items",d.get("inbox",[])); print(sum(1 for i in items if i.get("status")=="pending"))'

Return structured output: ingested (count ok), failed (count), pending_after (the number), notes (any errors).`
}

// ============================ run ============================
phase('Download')
const dl = await agent(downloadPrompt(), { label: 'download', phase: 'Download', schema: DOWNLOAD_SCHEMA })
const papers = (dl && dl.papers) || []
const bookPath = dl && typeof dl.book === 'string' && dl.book ? dl.book : null
log(`Downloaded ${papers.length} papers${bookPath ? ' + book' : ''}; skipped ${dl && dl.skipped ? dl.skipped.length : 0}`)

phase('Extract')
const extractThunks = []
if (bookPath) {
  extractThunks.push(() => agent(extractBookPrompt(bookPath), { label: 'extract:book', phase: 'Extract', schema: EXTRACT_SCHEMA }))
}
for (const [i, batch] of chunk(papers, EXTRACT_BATCH).entries()) {
  extractThunks.push(() => agent(extractPapersPrompt(batch), { label: `extract:papers:${i + 1}`, phase: 'Extract', schema: EXTRACT_SCHEMA }))
}
const extractResults = await parallel(extractThunks)
const allMds = extractResults.filter(Boolean).flatMap(r => (r.mds || []))
log(`Extracted ${allMds.length} markdown units`)

phase('Ingest')
const ingestSlices = chunk(allMds, INGEST_SLICE)
let totalIngested = 0
let pendingAfter = null
for (let i = 0; i < ingestSlices.length; i++) {
  const r = await agent(ingestSlicePrompt(ingestSlices[i]), { label: `ingest:${i + 1}/${ingestSlices.length}`, phase: 'Ingest', schema: INGEST_SCHEMA })
  if (r) { totalIngested += (r.ingested || 0); if (typeof r.pending_after === 'number') pendingAfter = r.pending_after }
}
log(`Ingested ${totalIngested} markdown units; pending now ${pendingAfter}`)

let compileResult = null
if (COMPILE_AFTER) {
  phase('Compile')
  try {
    compileResult = await workflow('compile-inbox-batch', { count: 100, chunkSize: CHUNK, workingDir: WD })
  } catch (e) {
    log(`compile-inbox-batch failed: ${e && e.message ? e.message : e}`)
  }
}

return {
  downloaded_papers: papers.length,
  book: !!bookPath,
  extracted_mds: allMds.length,
  ingested: totalIngested,
  pending_after: pendingAfter,
  compiled: compileResult ? (compileResult.written ?? true) : false,
}
