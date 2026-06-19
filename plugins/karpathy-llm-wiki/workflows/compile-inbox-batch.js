export const meta = {
  name: 'compile-inbox-batch',
  description: 'Compile the next N pending llm-wiki inbox items into atomic notes, then index, lint, and de-orphan them (single final index pass; parallel-safe de-orphan).',
  whenToUse: 'Run to process a batch of pending raw/artifacts inbox items end-to-end: scope-judge + dedup + normalize + write-note (fanned out ~6 agents), one batched mark-processed call, then lint, plan inbound backlinks that bridge each orphan to an existing, well-connected hub note (no orphan-to-orphan, no MOCs), de-orphan in parallel partitioned by source file, and a single index+charts pass. Re-invoke for each subsequent batch. Args: { count, chunkSize, compileAgents, workingDir }.',
  phases: [
    { title: 'Discover', detail: 'list the next N pending inbox items' },
    { title: 'Compile', detail: 'fan out ~6 agents: scope-judge, dedup, normalize, write-note' },
    { title: 'Finalize', detail: 'one agent: batched mark-processed (no index/charts here)' },
    { title: 'Find Orphans', detail: 'lint to list the freshly-orphaned notes' },
    { title: 'Plan Links', detail: 'parallel read-only: bridge each orphan to an existing, well-connected hub note (no orphan-to-orphan, no MOCs)' },
    { title: 'De-orphan', detail: 'parallel, partitioned by source file: append inbound backlinks' },
    { title: 'Verify', detail: 'single pass: lint + index + charts; confirm orphans == 0' },
  ],
}

// ---- args normalization (per claude-workflow-authoring-gotchas) ----
let opts = args
if (typeof opts === 'string') {
  try { opts = JSON.parse(opts) } catch { opts = {} }
}
opts = opts || {}

const COUNT = Number(opts.count) > 0 ? Math.floor(Number(opts.count)) : 100
const CHUNK_OVERRIDE = Number(opts.chunkSize) > 0 ? Math.floor(Number(opts.chunkSize)) : null
const TARGET_COMPILE_AGENTS = Number(opts.compileAgents) > 0 ? Math.floor(Number(opts.compileAgents)) : 6
const TARGET_DEORPHAN_AGENTS = 6
const PLAN_SLICE = 12
const WD = typeof opts.workingDir === 'string' && opts.workingDir ? opts.workingDir : null
if (!WD) {
  throw new Error(
    'compile-inbox-batch requires args.workingDir — the absolute path to the wiki root (the dir containing .kb-config.yml).\n' +
      'Invoke: Workflow({ name: "compile-inbox-batch", args: { workingDir: "/abs/wiki", count: 100 } })',
  )
}

function chunk(arr, n) {
  const out = []
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n))
  return out
}

// ---- JSON schemas for structured agent output ----
const DISCOVER_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { id: { type: 'string' }, file: { type: 'string' } },
        required: ['id', 'file'],
      },
    },
    total_pending: { type: 'number' },
  },
  required: ['items'],
}

const COMPILE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          id: { type: 'string' },
          action: { type: 'string', enum: ['written', 'duplicate', 'similar', 'skipped'] },
          note_file: { type: 'string' },
          title: { type: 'string' },
          detail: { type: 'string' },
        },
        required: ['id', 'action'],
      },
    },
  },
  required: ['results'],
}

const FINALIZE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    marked_processed: { type: 'number' },
    pending_after: { type: 'number' },
    notes: { type: 'string' },
  },
  required: ['pending_after'],
}

const ORPHAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    orphans: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { file: { type: 'string' }, title: { type: 'string' } },
        required: ['file'],
      },
    },
    orphan_count: { type: 'number' },
  },
  required: ['orphans'],
}

const PLAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    pairs: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { orphan: { type: 'string' }, source: { type: 'string' } },
        required: ['orphan', 'source'],
      },
    },
    unresolved: { type: 'array', items: { type: 'string' } },
  },
  required: ['pairs'],
}

const APPLY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    applied: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { source: { type: 'string' }, orphan: { type: 'string' }, ok: { type: 'boolean' } },
        required: ['source', 'orphan', 'ok'],
      },
    },
  },
  required: ['applied'],
}

const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    orphan_count: { type: 'number' },
    broken_links: { type: 'number' },
    rogue_tags: { type: 'number' },
    total_notes: { type: 'number' },
    indexed: { type: 'string' },
    charts_ok: { type: 'boolean' },
  },
  required: ['orphan_count'],
}

// ---- prompt builders ----
function discoverPrompt() {
  return `You are the discovery step for an llm-wiki compile batch. Working directory: ${WD}. Run kb from there.

Run: kb compile --list-inbox --json
Parse the JSON (it is a list of manifest entries OR an object with an "items"/"inbox" array). Filter entries with status == "pending". Take the FIRST ${COUNT} pending entries in their existing order.

Return structured output: items = [{id, file}] for exactly those (up to ${COUNT}) pending entries, and total_pending = the full count of pending entries. Use the manifest "id" (e.g. ingest-xxxxxxxx) and "file" (relative path) fields verbatim. Do NOT modify anything.`
}

function compilePrompt(items) {
  const list = items.map(it => `- ${it.id} -> ${it.file}`).join('\n')
  return `You are a knowledge-compiler subagent for the llm-wiki (Karpathy-style) knowledge base. Working directory: ${WD}. Run all kb commands from there. The approved tag taxonomy and knowledge_types are defined in wiki/_meta/tag-taxonomy.md — Read that file FIRST and use ONLY the tags and knowledge_types it lists.

You are assigned these ${items.length} inbox items (each raw file is typically an ALREADY-atomized note imported from a foreign "unified-brain" KB: it has frontmatter with knowledge_type/tags/confidence, a title, a body, and a Related/wikilink section whose [[links]] often point to notes that do NOT exist in our wiki):
${list}

FOR EACH item, serially:
1. Read the raw file with the Read tool.
2. SCOPE JUDGMENT — keep vs skip:
   - KEEP if it is a durable, generalizable TECHNICAL insight fitting our approved taxonomy domains (see wiki/_meta/tag-taxonomy.md).
   - SKIP if personal/philosophical/non-technical and maps to NO approved tag, OR an ephemeral fact unlikely to stay true (specific prices/salaries/dates with no transferable principle). Report skipped with a one-line reason. Never force a bad tag.
3. DEDUP (keepers): kb compile --check-dedup "TITLE OR KEY PHRASE" --json
   - status duplicate (>=0.92): SKIP; name the existing duplicate in detail.
   - status similar (0.80-0.91): do NOT write; action=similar, name match+score in detail.
   - status unique (<0.80): write.
   - Also dedup WITHIN your own assigned set: if two of your items are near-identical, write the stronger and mark the other a duplicate.
4. NORMALIZE (unique keepers):
   - TAGS: only tags from the approved taxonomy in wiki/_meta/tag-taxonomy.md; cap at 6; reuse the artifact's valid tags.
   - KNOWLEDGE_TYPE: one of the knowledge_types listed in wiki/_meta/tag-taxonomy.md.
   - CONFIDENCE: high | medium | low (a scalar WORD, never a number).
   - WIKILINKS: validate by running kb search "<core topic>" --limit 3 --json. KEEP only [[links]] whose target actually exists in our wiki (use returned filename without .md). DROP foreign/unresolvable links (convert to plain prose or remove the bullet). You may ADD 1-3 real discovered links. Keep the title and substantive body prose intact otherwise.
   - SOURCE PRESERVATION (web origins): Inspect the raw file's frontmatter source:/url: field (web-ingested items record their origin URL there). If it is a web URL (starts with http:// or https://), you MUST keep a link to that original external source: (a) pass the URL as --source in the write command below, AND (b) append a final body line exactly like: Source: [<short descriptive title>](<the url>). This must SURVIVE the wikilink-dropping step above — never strip the external provenance URL. If the source is NOT a web URL (a file path or internal/foreign reference), omit the body Source line and use the default --source "compiled from: <id>".
5. WRITE (unique keepers only): write the cleaned body (markdown, NO frontmatter — kb generates it) to /tmp/wf-compile-<id>.md with the Write tool, then run:
   kb compile --write-note --title "EXACT TITLE" --knowledge-type TYPE --tags "t1,t2,t3" --confidence LEVEL --source "ORIGIN" --body "$(cat /tmp/wf-compile-<id>.md)"   (ORIGIN = the original web URL if the raw source is an http(s) URL; otherwise the literal string: compiled from: <id>)
   Capture the created note filename from the command output.

CRITICAL: Do NOT run kb compile --mark-processed, do NOT run kb compile --tag-candidate, do NOT run kb index, do NOT run kb charts. The workflow funnels those serially later — concurrent manifest writes corrupt it.

Return structured output: results = [ {id, action: written|duplicate|similar|skipped, note_file (filename without path, or ""), title (or ""), detail (short)} ] with one entry per assigned item.`
}

function finalizePrompt(ids) {
  const idCsv = ids.join(',')
  return `You are the finalizer for an llm-wiki compile batch. Working directory: ${WD}. Run all kb commands from there.

STEP 1 — Mark all ${ids.length} items processed in ONE batched call (the manifest write is atomic and batched, so a single call is safe):
kb compile --mark-processed "${idCsv}" --json
Parse the JSON: "processed" lists the ids marked; "not_found" lists any misses. For each not_found id, grep raw/inbox/.manifest.json to find its correct id and run kb compile --mark-processed "<correct-id>" for those. All ${ids.length} must end up status=processed.

STEP 2 — confirm the new pending count:
kb compile --list-inbox --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); items=d if isinstance(d,list) else d.get("items",d.get("inbox",[])); print(sum(1 for i in items if i.get("status")=="pending"))'

Do NOT run kb index or kb charts — the Verify step runs those ONCE at the end.

Return structured output: marked_processed (count that succeeded), pending_after (the number from STEP 2), notes (any id corrections or errors).`
}

function findOrphansPrompt() {
  return `You are the linter for the llm-wiki knowledge base. Working directory: ${WD}. Run kb from there.

Run: kb lint --json
Parse it. An orphan = a note whose inbound backlink list (linked_from) is EMPTY (outbound links_to do NOT count). Return structured output: orphans = [ {file: "<filename-without-.md>", title: "<title if the lint JSON exposes it, else omit>"} ] for EVERY current orphan, and orphan_count = number of orphans. Do NOT open every note just to fetch titles — include title only if cheaply available. Do not modify anything. Do not run index or charts.`
}

function planPrompt(orphanSlice, newNotes, allOrphans) {
  const olist = orphanSlice.map(o => `- ${o.file}  (${o.title || ''})`).join('\n')
  const forbidden = new Set()
  for (const o of (allOrphans || [])) forbidden.add(typeof o === 'string' ? o : o.file)
  for (const n of (newNotes || [])) if (n && n.file) forbidden.add(n.file)
  const xlist = [...forbidden].filter(Boolean).join(', ')
  return `You PLAN inbound backlinks that BRIDGE orphan notes into the existing main graph. READ-ONLY — do NOT edit files, do NOT run kb index/charts. Working directory: ${WD}. Run kb from there.

An orphan = a note with zero inbound backlinks. For each orphan, choose the single best SOURCE note that should link TO it. The SOURCE receives a new outbound [[orphan]] wikilink, so the source is what attaches the orphan to the rest of the graph.

HARD RULES (these prevent islands — follow exactly):
- The SOURCE must be an EXISTING note that is NOT itself an orphan and was NOT created in this batch. NEVER use a source that appears in the FORBIDDEN list below (those are the current orphans + this batch's new notes). Linking an orphan to another orphan only builds a disconnected island — do not do it.
- The link must reflect a REAL topical relationship. Find the source by SEMANTIC similarity: run kb search "<orphan's core topic or title>" --limit 8 --json, then pick the highest-ranked result whose filename is NOT in the forbidden set (that result is an established, well-connected note). NEVER pair notes by alphabetical or filename proximity.
- If NO genuinely related established note exists for an orphan, mark it UNRESOLVED. Do NOT fabricate a link and do NOT fall back to an orphan-to-orphan link.

Orphans to bridge (filename without .md, and title):
${olist}

FORBIDDEN as sources (current orphans + this batch's new notes — never use any of these as a source):
${xlist}

Return structured output: pairs = [ {orphan, source} ] where source is an EXISTING well-connected note NOT in the forbidden set (one per orphan you can genuinely bridge), and unresolved = [orphan filenames] for orphans with no genuinely related established source.`
}

function applyPrompt(assignments) {
  const blocks = assignments.map(a => `SOURCE: ${a.source}\n  add inbound link bullets pointing to: ${a.orphans.join(', ')}`).join('\n')
  return `You APPLY inbound backlinks for the llm-wiki. Working directory: ${WD}. Each SOURCE file listed below is assigned EXCLUSIVELY to you — no other agent edits these files — so editing them is race-free. Do NOT run kb index or kb charts.

For EACH source file: open wiki/permanent/<source>.md (Read), then Edit it to append, to its "## Related" section (create that section at the END of the body if it has none), one bullet per target orphan:
  - [[<orphan-filename>]] — <short phrase on the relationship>
Use the EXACT orphan filename (no .md) inside [[ ]]. Append only; do not disturb existing bullets, and do NOT modify frontmatter (preserve field names, scalar values, and the newline before the closing ---). If an Edit fails because the file content changed, re-Read and retry. If wiki/permanent/<source>.md is not found, run: ls wiki/permanent/ | grep "<source-prefix>" to locate the exact name.

Assignments:
${blocks}

Return structured output: applied = [ {source, orphan, ok} ] one row per (source -> orphan) backlink you added (ok=false if you could not add it).`
}

function verifyPrompt() {
  return `You are the verifier for an llm-wiki compile batch. Working directory: ${WD}. Run kb from there. This is the SINGLE index+charts pass for the whole run. Serially:
1. kb lint --json  -> parse orphan_count, broken_links count, rogue tag count, total note_count.
2. kb index --incremental 2>&1 | tail -6
3. kb charts --all 2>&1 | tail -6
Return structured output: orphan_count, broken_links, rogue_tags, total_notes, indexed (short string), charts_ok (true/false). Do not modify notes.`
}

// ============================ run ============================
phase('Discover')
const disc = await agent(discoverPrompt(), { label: 'discover', phase: 'Discover', schema: DISCOVER_SCHEMA })
const items = (disc && disc.items) || []
log(`Discovered ${items.length} pending items (total pending: ${disc ? disc.total_pending : '?'})`)
if (items.length === 0) {
  return { discovered: 0, message: 'No pending inbox items found — nothing to compile.' }
}

phase('Compile')
const CHUNK = CHUNK_OVERRIDE || Math.max(1, Math.ceil(items.length / TARGET_COMPILE_AGENTS))
const chunks = chunk(items, CHUNK)
log(`Compiling ${items.length} items across ${chunks.length} agents (${CHUNK}/agent)`)
const compileResults = await parallel(
  chunks.map((c, idx) => () =>
    agent(compilePrompt(c), { label: `compile:${idx + 1}/${chunks.length}`, phase: 'Compile', schema: COMPILE_SCHEMA })),
)
const allResults = compileResults.filter(Boolean).flatMap(r => (r.results || []))
const written = allResults.filter(r => r.action === 'written')
const skipped = allResults.filter(r => r.action === 'skipped')
const duplicate = allResults.filter(r => r.action === 'duplicate')
const similar = allResults.filter(r => r.action === 'similar')
log(`Compile done: ${written.length} written, ${skipped.length} skipped, ${duplicate.length} duplicate, ${similar.length} similar`)

phase('Finalize')
const allIds = items.map(i => i.id)
const fin = await agent(finalizePrompt(allIds), { label: 'finalize', phase: 'Finalize', schema: FINALIZE_SCHEMA })
log(`Finalized: pending now ${fin ? fin.pending_after : '?'}`)

phase('Find Orphans')
const lintRes = await agent(findOrphansPrompt(), { label: 'find-orphans', phase: 'Find Orphans', schema: ORPHAN_SCHEMA })
const orphans = (lintRes && lintRes.orphans) || []
log(`Orphans to fix: ${orphans.length}`)

let deorphanApplied = 0
let planUnresolved = []
if (orphans.length > 0) {
  phase('Plan Links')
  const newNotes = written.map(w => ({ file: w.note_file, title: w.title })).filter(n => n.file)
  const planChunks = chunk(orphans, PLAN_SLICE)
  const plans = await parallel(planChunks.map((c, i) => () =>
    agent(planPrompt(c, newNotes, orphans), { label: `plan:${i + 1}/${planChunks.length}`, phase: 'Plan Links', schema: PLAN_SCHEMA })))
  const pairs = plans.filter(Boolean).flatMap(p => (p.pairs || []))
  planUnresolved = plans.filter(Boolean).flatMap(p => (p.unresolved || []))
  // Group edits by the SOURCE file being edited; each distinct source file -> exactly one editor agent (no write race).
  const bySource = new Map()
  for (const pr of pairs) {
    if (!pr || !pr.orphan || !pr.source || pr.source === pr.orphan) continue
    if (!bySource.has(pr.source)) bySource.set(pr.source, new Set())
    bySource.get(pr.source).add(pr.orphan)
  }
  const sources = [...bySource.keys()].map(source => ({ source, orphans: [...bySource.get(source)] }))
  log(`Planned ${pairs.length} links across ${sources.length} source files; ${planUnresolved.length} unresolved`)

  if (sources.length > 0) {
    phase('De-orphan')
    const groupSize = Math.max(1, Math.ceil(sources.length / TARGET_DEORPHAN_AGENTS))
    const groups = chunk(sources, groupSize)
    const applies = await parallel(groups.map((g, i) => () =>
      agent(applyPrompt(g), { label: `deorphan:${i + 1}/${groups.length}`, phase: 'De-orphan', schema: APPLY_SCHEMA })))
    deorphanApplied = applies.filter(Boolean).flatMap(a => (a.applied || [])).filter(x => x.ok).length
    log(`Applied ${deorphanApplied} inbound links across ${groups.length} editors`)
  }
} else {
  log('No orphans — skipping plan + de-orphan phases.')
}

phase('Verify')
const verify = await agent(verifyPrompt(), { label: 'verify', phase: 'Verify', schema: VERIFY_SCHEMA })

return {
  discovered: items.length,
  compile_agents: chunks.length,
  written: written.length,
  skipped: skipped.length,
  duplicate: duplicate.length,
  similar: similar.length,
  written_files: written.map(w => w.note_file).filter(Boolean),
  skipped_detail: skipped.map(s => ({ id: s.id, reason: s.detail })),
  pending_after: fin ? fin.pending_after : null,
  orphans_found: orphans.length,
  deorphan_links_applied: deorphanApplied,
  deorphan_unresolved: planUnresolved,
  final_orphan_count: verify ? verify.orphan_count : null,
  final_broken_links: verify ? verify.broken_links : null,
  final_rogue_tags: verify ? verify.rogue_tags : null,
  total_notes: verify ? verify.total_notes : null,
  charts_ok: verify ? verify.charts_ok : null,
}
