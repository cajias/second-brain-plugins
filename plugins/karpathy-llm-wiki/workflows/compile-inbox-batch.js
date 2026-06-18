export const meta = {
  name: 'compile-inbox-batch',
  description: 'Compile pending inbox items into atomic wiki notes: parallel extract, batched dedup, parallel write, single finalize',
  phases: [
    { title: 'Extract' },
    { title: 'Dedup' },
    { title: 'Write' },
    { title: 'Finalize' },
  ],
}

// ---------------------------------------------------------------------------
// args contract (see claude-workflow-authoring-gotchas):
//   { wikiRoot: "/abs/path/to/wiki", items: [{ id, file }, ...] }
// `wikiRoot` is the dir containing .kb-config.yml; `items` is the pending
// inbox list. Scout it inline BEFORE invoking this workflow:
//   cd <wikiRoot> && kb compile --list-inbox --json
// then pass the parsed list as args.items.
// ---------------------------------------------------------------------------

function normalizeArgs(raw) {
  let a = raw
  if (typeof a === 'string') {
    try {
      a = JSON.parse(a)
    } catch {
      a = undefined
    }
  }
  if (!a || typeof a !== 'object' || !a.wikiRoot || !Array.isArray(a.items)) {
    throw new Error(
      'compile-inbox-batch requires args { wikiRoot: string, items: [{id, file}] }.\n' +
        'Scout the inbox first:  kb compile --list-inbox --json\n' +
        'then invoke: Workflow({ name: "compile-inbox-batch", args: { wikiRoot, items } })',
    )
  }
  return a
}

const { wikiRoot, items } = normalizeArgs(args)

if (items.length === 0) {
  log('No pending inbox items — nothing to compile.')
  return { items: 0, candidates: 0, written: 0, skipped: 0 }
}

log(`Compiling ${items.length} inbox item(s) from ${wikiRoot}`)

const EXTRACT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['item_id', 'candidates'],
  properties: {
    item_id: { type: 'string' },
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['key', 'title', 'idea_text', 'knowledge_type', 'tags', 'confidence'],
        properties: {
          key: { type: 'string' },
          title: { type: 'string' },
          idea_text: { type: 'string' },
          knowledge_type: { type: 'string' },
          tags: { type: 'array', items: { type: 'string' } },
          confidence: { type: 'string' },
        },
      },
    },
  },
}

const DEDUP_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['results'],
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['key', 'status'],
        properties: {
          key: { type: 'string' },
          status: { type: 'string', enum: ['duplicate', 'similar', 'unique'] },
          top_score: { type: 'number' },
        },
      },
    },
  },
}

const WRITE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['key', 'written'],
  properties: {
    key: { type: 'string' },
    written: { type: 'boolean' },
    filename: { type: 'string' },
    note: { type: 'string' },
  },
}

// === Phase 1: Extract (parallel, one agent per inbox item) =================
// Each agent reads ONE raw file and proposes atomic note candidates WITHOUT
// writing or deduping. Items are independent → safe to fan out.
phase('Extract')
const extracted = await parallel(
  items.map((it) => () =>
    agent(
      `You are extracting atomic wiki-note candidates from one raw inbox file.\n` +
        `Working directory: ${wikiRoot} (run any kb commands from here).\n` +
        `Manifest id: ${it.id}\nRaw file: ${it.file}\n\n` +
        `Read the raw file and follow the karpathy-llm-wiki 'compile-note' skill's ` +
        `EXTRACTION guidance to split it into atomic ideas (one concept each). ` +
        `Do NOT dedup, do NOT write notes, do NOT touch the index.\n\n` +
        `For each idea return: key="${it.id}#<n>" (n starts at 1), a concise title, ` +
        `idea_text (a 1-3 sentence self-contained statement, used for dedup), ` +
        `knowledge_type (fact|pattern|decision|correction|idea|design|exploration), ` +
        `up to 6 taxonomy tags, and confidence (high|medium|low).`,
      { label: `extract:${it.id}`, phase: 'Extract', schema: EXTRACT_SCHEMA },
    ),
  ),
)

const allCandidates = extracted.filter(Boolean).flatMap((r) => r.candidates || [])

if (allCandidates.length === 0) {
  log('Extraction produced no candidates.')
  return { items: items.length, candidates: 0, written: 0, skipped: 0 }
}

// Full title list — handed to every writer so siblings can wikilink each other.
// The index isn't refreshed until Finalize, so this in-context list is the only
// cross-note link signal available during parallel writing.
const batchTitles = allCandidates.map((c) => c.title)
log(`Extracted ${allCandidates.length} candidate(s) across ${items.length} item(s).`)

// === Phase 2: Dedup (single agent, batched) ================================
// BARRIER is justified: dedup is a cross-item check over the WHOLE candidate
// set and must finish before any write. One agent → one `kb` process → one
// embedding-model load (via the --check-dedup-batch CLI).
phase('Dedup')
const dedup = await agent(
  `You are batch-deduplicating wiki-note candidates against the existing index.\n` +
    `Working directory: ${wikiRoot}.\n\n` +
    `Candidates as JSON:\n` +
    JSON.stringify(allCandidates.map((c) => ({ key: c.key, query: c.idea_text }))) +
    `\n\nWrite them to a temp JSON file and run exactly:\n` +
    `  kb compile --check-dedup-batch <tempfile> --json\n` +
    `Then return the results array (one entry per key, same keys, with status).`,
  { label: 'dedup:batch', phase: 'Dedup', schema: DEDUP_SCHEMA },
)

const statusByKey = new Map((dedup?.results || []).map((r) => [r.key, r]))
// duplicate → skip; similar/unique → write (similar gets a similarity note).
const toWrite = allCandidates.filter(
  (c) => (statusByKey.get(c.key)?.status ?? 'unique') !== 'duplicate',
)
const skipped = allCandidates.length - toWrite.length
log(`Dedup: ${toWrite.length} to write, ${skipped} duplicate(s) skipped.`)

// === Phase 3: Write (parallel, one agent per unique candidate) =============
// Each writer creates its OWN new note file (distinct slug) → no shared-file
// race. Every writer gets the full batch title list for sibling wikilinks.
phase('Write')
const written = await parallel(
  toWrite.map((c) => () => {
    const st = statusByKey.get(c.key)
    const similarNote =
      st?.status === 'similar'
        ? `\nThis candidate is SIMILAR (score ${st.top_score ?? '?'}) to an existing note — ` +
          `still write it, but add a short "Related / overlaps with" line in the body.`
        : ''
    return agent(
      `You are writing ONE atomic wiki note, following the karpathy-llm-wiki ` +
        `'compile-note' (writing step) and 'search-and-link' skills.\n` +
        `Working directory: ${wikiRoot} (run kb from here).\n\n` +
        `Candidate:\n${JSON.stringify(c, null, 2)}\n${similarNote}\n\n` +
        `Sibling notes being created in THIS same batch — add [[wikilinks]] to any ` +
        `that are genuinely related, in addition to links into the existing wiki:\n` +
        `${batchTitles.map((t) => `- ${t}`).join('\n')}\n\n` +
        `Use search-and-link to find existing wiki targets, then write the note with ` +
        `full 9-field frontmatter via the kb CLI (kb compile --write-note ...). ` +
        `Do NOT mark anything processed and do NOT run the index — Finalize does that.`,
      { label: `write:${c.key}`, phase: 'Write', schema: WRITE_SCHEMA },
    )
  }),
)

const writtenOk = written.filter(Boolean).filter((w) => w.written)
log(`Wrote ${writtenOk.length} note(s).`)

// === Phase 4: Finalize (single agent) ======================================
// One process: batch mark-processed (one manifest write) + incremental index +
// charts. All items were attempted, so mark them all processed.
phase('Finalize')
const processedIds = items.map((it) => it.id)
const finalize = await agent(
  `You are finalizing a compile batch. Working directory: ${wikiRoot}.\n\n` +
    `Run these three commands in order and report each result:\n` +
    `1. kb compile --mark-processed "${processedIds.join(',')}"\n` +
    `2. kb index --incremental\n` +
    `3. kb charts\n\n` +
    `Return a one-line summary of each command's outcome.`,
  { label: 'finalize', phase: 'Finalize' },
)

return {
  items: items.length,
  candidates: allCandidates.length,
  written: writtenOk.length,
  skipped,
  finalize,
}
