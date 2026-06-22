# Design: GitHub-repo-as-tool ingestion for llm-wiki

- **Date:** 2026-06-22
- **Status:** Draft (awaiting review)
- **Plugin:** `karpathy-llm-wiki`
- **Target version:** 0.5.0 (minor — new feature)

## Problem

The wiki ingests prose sources (chat, docs, books, papers) and atomizes them into many
permanent notes. GitHub repositories need a *different* treatment:

1. **The README is the source of truth**, not the rendered repo page. `kb ingest --mode url`
   does a plain `GET` with no custom headers and a near-passthrough HTML→text step, so a repo
   *root* URL extracts as navigation junk. The reliable source is the GitHub README API:
   `GET https://api.github.com/repos/<owner>/<repo>/readme` with header
   `Accept: application/vnd.github.raw`.
2. **A repo is one *tool*, not a pile of atomic ideas.** It should compile to a *single*
   structured note, not be fragmented like a paper.
3. **We want to classify and later retrieve tools** — by what they are (framework, MCP server,
   CLI…) and by where they fit in the agentic SDLC (testing, review, deployment…) — so we can
   answer "give me all `phase-testing` tools" or assemble a handout of "tools for the
   implementation phase."

`kb search` is **purely semantic** (`lancedb .search(embedding)` with no `.where()` filter), so
retrieval-by-attribute must work off **frontmatter that is greppable** — i.e. `knowledge_type`
and `tags`, which `kb lint`/`kb compile` already validate against `wiki/_meta/tag-taxonomy.md`.

## Goals

- Ingest a GitHub repo (or a batch) by fetching its README via the GitHub README API plus repo
  metadata, preserving the repo URL as `source:`.
- Compile each repo into **one** `knowledge_type: tool` note, classified by a controlled tag
  vocabulary (tool-type + SDLC-phase + topic).
- Make tools retrievable: "all tools", "all `tool-mcp-server`s", "all `phase-testing` tools", and
  composable handouts — via a grep-over-frontmatter skill (semantic search can't filter).
- Ship everything **upstream** to `cajias/second-brain-plugins` (`karpathy-llm-wiki`).

## Non-goals

- No cloning, building, or static analysis of repos — README + metadata only.
- No new query *engine* in core (no `.where()` over the vector index). Retrieval is grep-based.
- No structured per-tool frontmatter fields beyond the marker + tags (we chose the tag
  convention over a new `type: tool` archetype to avoid new core machinery).

## Data model (decided)

Every ingested tool is a normal permanent note with:

- `type: permanent`
- **`knowledge_type: tool`** ← the marker (a new knowledge_type). Validated, greppable, shown in
  `kb search` results, and does **not** consume a tag slot. "Find all tools" = filter
  `knowledge_type == tool`.
- `tags:` (≤6 total, three groups):
  - **Tool-type** (exactly 1): `tool-framework`, `tool-library`, `tool-cli`, `tool-mcp-server`,
    `tool-agent`, `tool-skill`, `tool-plugin`, `tool-sdk`, `tool-service`, `tool-dataset`
  - **SDLC phase** (1–2): `phase-planning`, `phase-design`, `phase-implementation`,
    `phase-code-review`, `phase-testing`, `phase-debugging`, `phase-deployment`,
    `phase-observability`, `phase-security`, `phase-docs`
  - **Topic** (0–2, from the existing 21 approved tags): `agent-patterns`, `llm`, …
- `source:` = the canonical repo URL (`https://github.com/<owner>/<repo>`).
- Body (structured): **What it is · What it's for · Install · Key capabilities · Repo link**.

Example: a LangGraph-style repo → `knowledge_type: tool`, tags
`tool-framework, phase-implementation, agent-patterns` (3 of 6).

## Components

### 1. Taxonomy extension — `wiki/_meta/tag-taxonomy.md`
The single file `kb compile`/`kb lint` validate against (`load_taxonomy_safe`).
- Add `tool` to the `knowledge_types` list.
- Add a **Tool tags** section: the 10 `tool-*` and 10 `phase-*` tags above.
- Applied to the live vault (so it works immediately) **and** to the plugin's init template /
  `kb-init` so new wikis inherit it. (Confirm during implementation whether `kb init` seeds a
  default taxonomy; if so, update that template too.)

### 2. Core change (thin) — `llm-wiki-core`
Add `tool` to the accepted `--source-class` values (currently `chat, doc, book, paper`). This is
the **explicit, deterministic signal** that an inbox item is a repo README so compile switches to
tool-mode. One-line allow-list change + a test. (Chosen over URL-sniffing in compile, which is
fragile, and over a full `kb ingest --mode github` core verb, which is a larger surface — noted
as a possible future enhancement.)

### 3. Ingest path — `kb-ingest-github` (command + workflow)
- **Input:** one or more repo references (`owner/repo` or full URL).
- **Fetch README:** `GET api.github.com/repos/<owner>/<repo>/readme`,
  `Accept: application/vnd.github.raw` (follows the repo's default branch + configured README).
- **Fetch metadata:** `GET api.github.com/repos/<owner>/<repo>` → `description`, `topics`,
  `language`, `homepage`, `stargazers_count`. These are strong classification signals for compile.
- **Auth:** use `$GITHUB_TOKEN`/`gh auth token` if present (5000 req/h vs 60 unauth). Token is
  read from env at call time; never written to disk or notes.
- **Write to inbox:** prepend a small frontmatter block (`title: <owner>/<repo>`,
  `source: <repo-url>`, plus `gh_description`, `gh_topics`, `gh_language`, `gh_stars` as hints)
  to the README markdown, then `kb ingest` it with `--source <repo-url> --source-class tool`.
- **Batch form:** a `workflows/ingest-github-tools.js` that fans out over repo refs but calls
  `kb ingest` **serially** (the `.manifest.json` is non-atomic — never two ingests at once),
  mirroring `ingest-notion-cited-sources.js`.

### 4. Compile guidance — tool-mode (the "special callout")
A `skills/compile-tool.md` (or a documented branch in `compile-note`) that triggers when an item
is `source_class: tool`:
- Produce **one** note for the repo (no atomization).
- Set `knowledge_type: tool`.
- Classify **tool-type** (exactly 1) and **phase(s)** (1–2) from the README + metadata hints;
  add ≤2 topic tags; ≤6 total.
- Body = the structured template (What it is / What it's for / Install / Key capabilities / Repo
  link). Preserve `source:` = repo URL (source-preservation rule).
- Dedup against existing tool notes by repo URL (same `source:` → update, don't duplicate).

### 5. Query / handout — `kb-tools` skill
Since `kb search` can't filter frontmatter, this skill greps `wiki/permanent/*.md` for
`knowledge_type: tool` plus an optional `tool-*` / `phase-*` tag and renders a list (tool name,
type, one-line "what it's for", repo link), grouped by phase or type. Supported asks:
- "all tools" · "all `tool-mcp-server`s" · "all `phase-testing` tools"
- "handout for the implementation phase" → tools tagged `phase-implementation`, grouped by type.

## Data flow

```
repo ref ──▶ kb-ingest-github
              ├─ GET /repos/<o>/<r>/readme  (Accept: vnd.github.raw)   ──▶ README.md
              └─ GET /repos/<o>/<r>          (metadata)                 ──▶ description/topics/lang/stars
                     │
                     ▼  prepend hint frontmatter (source = repo URL)
              kb ingest --mode text --source <repo-url> --source-class tool
                     │   (writes raw/ + .manifest.json entry, source_class=tool)
                     ▼
              compile (tool-mode)  ──▶ ONE note: knowledge_type=tool, tool-*/phase-*/topic tags,
                     │                  structured body, source=repo URL  ──▶ wiki/permanent/
                     ▼
              kb index  ──▶ embeddings refreshed
                     ▼
              kb-tools  ──▶ grep knowledge_type:tool + tag  ──▶ handout
```

## Error handling

- **No README / 404:** report and skip the repo (don't write an empty note).
- **Private/inaccessible repo:** if the token can't read it, skip with a clear message.
- **Rate limit (403 + `X-RateLimit-Remaining: 0`):** surface the reset time; suggest setting a
  token. Batch workflow stops cleanly, leaving already-ingested repos intact.
- **Non-GitHub or malformed ref:** validate `owner/repo` shape up front; reject early.
- **Manifest safety:** serial `kb ingest` only (non-atomic read-modify-write).
- **Compile classification uncertainty:** if tool-type is ambiguous, prefer the most specific
  defensible tag and note the uncertainty in the body rather than guessing a phase.

## Testing

- **Core:** unit test that `--source-class tool` is accepted and recorded in the manifest entry.
- **Ingest smoke:** ingest 2 real, contrasting repos (e.g. an agent *framework* and an
  *MCP-server*); assert raw file has `source:` = repo URL and `source_class: tool`.
- **Compile smoke:** compile those 2 → assert each yields exactly one note with
  `knowledge_type: tool`, exactly one `tool-*` tag, ≥1 `phase-*` tag, ≤6 tags, and `source:` set;
  `kb lint` reports 0 rogue tags / invalid knowledge_type.
- **Query smoke:** `kb-tools` lists both, and filtering by a `phase-*` tag returns the right subset.

## Upstream contribution plan

All changes land in `cajias/second-brain-plugins` on `feat/github-tool-ingestion`:
- `plugins/karpathy-llm-wiki/llm-wiki-core/…` — `tool` source-class + test
- `plugins/karpathy-llm-wiki/commands/kb-ingest-github.md`
- `plugins/karpathy-llm-wiki/workflows/ingest-github-tools.js`
- `plugins/karpathy-llm-wiki/skills/compile-tool.md` (+ a pointer from `compile-note`)
- `plugins/karpathy-llm-wiki/skills/kb-tools.md` (+ `commands/kb-tools.md` wrapper)
- taxonomy template update (and the live vault `wiki/_meta/tag-taxonomy.md`)
- `docs/specs/2026-06-22-github-tool-ingestion-design.md` (this file)
- version bump 0.4.0 → 0.5.0
- One PR; smoke-tested on 2 repos before opening.

## Open questions / future

- Should `kb-tools` eventually become a real CLI verb (`kb tools --phase testing`)? Deferred —
  grep skill first; promote to core only if it proves load-bearing.
- A full `kb ingest --mode github <owner/repo>` core verb (vs. the skill-orchestrated fetch) is a
  cleaner UX but larger surface; revisit after the thin version proves out.
- Re-ingest/refresh policy when a repo's README changes (dedup by `source:` enables update-in-place).
