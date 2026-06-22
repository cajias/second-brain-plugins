# Design: GitHub-repo-as-tool ingestion + frontmatter-filtered query

- **Date:** 2026-06-22
- **Status:** Draft v2 (awaiting review)
- **Plugin:** `karpathy-llm-wiki`
- **Target version:** 0.5.0 (minor — new feature)

## Problem

Two coupled needs:

1. **Ingest GitHub repos as *tools*.** A repo's README is the source of truth, fetched via the
   GitHub README API (`GET api.github.com/repos/<owner>/<repo>/readme`,
   `Accept: application/vnd.github.raw`) — the repo *root* URL extracts as nav junk through
   `kb ingest --mode url`. A repo is **one tool = one note**, classified by what it is
   (framework, MCP server, CLI…) and where it fits in the agentic SDLC (testing, review…).
2. **Find tools (and any notes) by attribute.** `kb search` is purely semantic
   (`table.search(embedding).metric("cosine")`) with **no metadata filter**, so "every tool tagged
   `phase-testing`" (an exhaustive handout) is impossible today. We fold **frontmatter filtering
   into `kb query`** rather than build a separate tool search.

Grounding facts that shape this:
- `knowledge_type` is already a scalar column in the LanceDB index → exact `.where()` works **with
  no re-index**.
- `tags` is stored as a **comma-joined utf8 string**, and `type`/`scope` are **not stored at all**.
  Token-exact tag filtering needs `tags` as a `list(utf8)` column → **one `kb index --full`**.
- LanceDB 0.30.2 supports `.where(pred, prefilter=True)` on vector *and* filter-only queries;
  making the `search` query arg optional is non-breaking.
- `kb ingest` writes raw markdown + a **`.meta.json` sidecar** (no YAML frontmatter); `source` and
  a `source_class` live in that sidecar.
- **Existing duplication** (must be consolidated because the tags-list change touches all of it):
  frontmatter serialization in two places (`core/frontmatter.dump` vs hand-built block in
  `compile_cmd._write_note`); `MAX_TAGS` defined twice; tags CSV split/join in three places
  (`index._normalize_tags`, `index._do_stats`, `compile_cmd._handle_write_note`); `_slugify` twice;
  ad-hoc tag validation in `_write_note` instead of `taxonomy.validate_tags`.

## Goals

- Ingest a repo (or batch) → README via the GitHub README API + repo metadata, `source:` = repo URL.
- Compile each repo into **one** `knowledge_type: tool` note, classified by controlled tags.
- Fold **frontmatter filtering into `kb query`/`kb search`**: `--knowledge-type`, repeatable `--tag`
  (token-exact, AND semantics), `--type`, `--scope`, and a generic `--where`; **query text becomes
  optional** so a pure filter enumerates *all* matches (the handout). Benefits every note, not just
  tools.
- **Reuse** existing core helpers; **consolidate** the duplication the schema change exposes.
- Ship **upstream** to `cajias/second-brain-plugins` (`karpathy-llm-wiki`).

## Non-goals

- No cloning/building/static-analysis of repos — README + metadata only.
- No separate tool-search surface; no new query *engine* beyond LanceDB `.where()`.
- No new `type: tool` archetype — tools are permanent notes with `knowledge_type: tool` + tags.

## Data model (decided)

Every tool = a permanent note: `type: permanent`, **`knowledge_type: tool`** (new knowledge_type;
the marker — validated, greppable, indexed, no tag slot used), `source:` = repo URL, body =
*What it is · What it's for · Install · Key capabilities · Repo link*. Tags (≤6, three groups):
- **Tool-type** (exactly 1): `tool-framework`, `tool-library`, `tool-cli`, `tool-mcp-server`,
  `tool-agent`, `tool-skill`, `tool-plugin`, `tool-sdk`, `tool-service`, `tool-dataset`
- **SDLC phase** (1–2): `phase-planning`, `phase-design`, `phase-implementation`,
  `phase-code-review`, `phase-testing`, `phase-debugging`, `phase-deployment`,
  `phase-observability`, `phase-security`, `phase-docs`
- **Topic** (0–2, from the existing 21 approved tags)

## Components

### 1. Taxonomy extension — `wiki/_meta/tag-taxonomy.md` (+ init template)
Add `tool` to `knowledge_types`; add a **Tool tags** section (10 `tool-*` + 10 `phase-*`). Update
the `kb init` taxonomy template too (confirm location). This is the single file
`taxonomy.load_taxonomy_safe` validates against. Mirror the new `knowledge_types`/`MAX_TAGS` facts
into `core/frontmatter.KNOWLEDGE_TYPES` if that constant is used for validation.

### 2. Core — index schema + one re-index
In `commands/index.py`: `_empty_index_schema` → `tags` becomes `pa.list_(pa.utf8())`; add
`type` (`utf8`) and `scope` (`utf8`) columns; `_build_record` writes `tags` as a list and adds
`type`/`scope` from metadata. Promote tag normalization to a single core home (`core/tags.py` or
`core/frontmatter.py`) returning a list; delete the stranded `index._normalize_tags` CSV join.
Fix `index._do_stats` to consume the list column. One-time migration: `kb index --full`
(re-embeds ~2,456 notes with `all-MiniLM-L6-v2`/384-dim; minutes).

### 3. Core — filtered search + CLI flags
`core/embeddings.search_index(...)` gains optional filter params (`knowledge_type`, `tags: list`,
`type`, `scope`, `where: str|None`) that build a DataFusion predicate and call
`.where(pred, prefilter=True)`; tags use `array_has_any(tags, [...])` (AND across repeated `--tag`).
When `query` is None → filter-only path (`table.search().where(pred).limit(n)`), returning **all**
matches (no semantic ranking; `--limit` default = unbounded for filter-only). `commands/search.py`:
make `query` an optional `typer.Argument(None)`; add `--knowledge-type`, repeatable `--tag`,
`--type`, `--scope`, `--where`. Result dicts return `tags` as a list. The `kb-query` skill is
updated to use these (semantic+filter for discovery; filter-only for handouts).

### 4. Ingest — `kb-ingest-github` (command + `workflows/ingest-github-tools.js`)
Resolve `owner/repo`; fetch README (README API, raw accept header) + metadata
(`description`, `topics`, `language`, `homepage`, `stargazers_count`); use `$GITHUB_TOKEN`/`gh auth
token` if present (read at call time, never persisted). Prepend a short
`<!-- repo: <url> | lang | ⭐stars | topics -->` + description block to the README body so the
compile classifier sees it inline, then `kb ingest --mode text --source <repo-url>
--source-class tool` (reuses the existing sidecar `.meta.json` path; `source_class=tool` is the
deterministic signal). Add `tool` to the accepted `--source-class` values (one-line allow-list +
test). Batch workflow calls `kb ingest` **serially** (non-atomic manifest), mirroring
`ingest-notion-cited-sources.js`.

### 5. Compile — tool-mode (`skills/compile-tool.md` + pointer from `compile-note`)
When `source_class: tool`: produce **one** note, `knowledge_type: tool`, classify exactly one
`tool-*` + 1–2 `phase-*` + ≤2 topic tags (≤6) from README+metadata; structured body; `source:` =
repo URL (source-preservation). Dedup by `source:` (same repo → update in place). The write MUST go
through `core/frontmatter.dump` (see refactor below), and tag validation through
`taxonomy.validate_tags`.

### 6. Refactor / consolidation (on the critical path)
Because the tags-list change touches every CSV site, consolidate while we're there:
- `compile_cmd._write_note` → build the note via `core/frontmatter.dump(metadata, body)` instead of
  the hand-rolled `lines` block (single source of canonical field order).
- Single `MAX_TAGS` (in `core/frontmatter`); delete `compile_cmd._MAX_TAGS`.
- Single tag-normalization helper (list-based) in core; callers updated.
- Single `_slugify` (promote to a core util; dedupe `compile_cmd`/`ingest`).
- Replace ad-hoc tag validation in `_write_note` with `taxonomy.validate_tags`.

## Reuse targets (call these — do not re-implement)
- Frontmatter parse/serialize: `core/frontmatter.parse_file` / `core/frontmatter.dump`
- Taxonomy validation: `core/taxonomy.load_taxonomy_safe` / `validate_tags` / `validate_knowledge_type`
- Search/embeddings: `core/embeddings.search_index` / `embed_texts` / `get_model` / `MODEL_NAME` / `EMBEDDING_DIM`
- Ingest: the existing `kb ingest --mode text` sidecar path (no new writer)
- HTTP: stdlib `urllib.request` (matches `ingest.py`; no new dep)

## Data flow

```
repo ref ─▶ kb-ingest-github ─▶ README API (raw) + metadata ─▶ prepend repo-meta block
          └▶ kb ingest --mode text --source <url> --source-class tool  (raw/ + .meta.json)
                 ─▶ compile tool-mode ─▶ ONE note (knowledge_type=tool, tool-*/phase-*/topic),
                        via frontmatter.dump, source=url ─▶ wiki/permanent/
                 ─▶ kb index (tags list column) ─▶ kb query --knowledge-type tool --tag phase-testing
                        (filter-only ⇒ full handout)  |  kb query "debug agent loop" --tag tool-cli
                        (semantic + filter ⇒ ranked)
```

## Error handling
- README 404 / private / rate-limited (403 + `X-RateLimit-Remaining: 0`, surface reset; suggest
  token): skip cleanly, leave already-ingested repos intact.
- Malformed ref: validate `owner/repo` up front.
- Manifest: serial `kb ingest` only.
- Filter with no matches: return empty set (not an error). Unknown `--where` column: clear error.
- Ambiguous classification: most-specific defensible `tool-*`; note uncertainty in body.

## Implementation stages & quality gates

Each stage is **TDD-first** (red→green→refactor) and ends with the same gate:
`make test` (pytest, cov ≥70) · `make lint` (pre-commit: ruff strict + mypy strict + vulture) ·
**ponytail review** (`ponytail-review`) on the stage diff · address findings · **ponytail-debt** to
catch new duplication/complexity (ruff `max-complexity=10`, `max-args=7`). No stage merges red.

- **Stage 0 — Refactor/consolidate (no behavior change).** Land the dedup (component 6) first so
  later stages build on one frontmatter writer + one tag helper. Gate: existing tests still green;
  ponytail-debt shows the 5 duplication risks resolved.
- **Stage 1 — Schema + re-index.** tags→list, +type/scope, `_build_record`/`_do_stats` updated;
  migration `kb index --full`. Tests: index round-trips a list-tagged note; stats by-tag correct.
- **Stage 2 — Filtered query.** `search_index` filter params + filter-only path; `search.py` flags;
  optional query. Tests: knowledge_type filter, AND-tag filter, type/scope, filter-only completeness,
  semantic+filter, empty result, backward-compat (query-only unchanged). Update `kb-query` skill.
- **Stage 3 — Taxonomy + `tool` source-class.** Taxonomy file/template + `--source-class tool`
  allow-list. Tests: lint accepts `knowledge_type: tool` + new tags; ingest records `source_class=tool`.
- **Stage 4 — Ingest path.** `kb-ingest-github` command + `ingest-github-tools.js`. Tests: README-API
  URL construction, metadata block, serial ingest, source=repo URL. Smoke: 2 real repos.
- **Stage 5 — Compile tool-mode.** `compile-tool` skill. Smoke: the 2 repos → one tool note each,
  exactly one `tool-*`, ≥1 `phase-*`, ≤6 tags, `source` set, `kb lint` clean; `kb query --tag` finds them.
- **Stage 6 — Finalize.** Full `make test`+`make lint`+`ponytail-audit` on the branch; version
  bump 0.4.0→0.5.0; PR.

## Testing
Unit (pytest) per stage as above. Integration smoke on 2 contrasting real repos (an agent
*framework* + an *MCP server*): ingest→compile→`kb query` filter-only handout returns both;
`--tag phase-*` returns the right subset; `kb lint` 0 rogue/invalid. Coverage ≥70 (repo gate).

## Upstream contribution plan
One branch `feat/github-tool-ingestion`; consider two PRs if review prefers (PR-A: refactor+schema+
filtered query — useful standalone; PR-B: ingest+compile tool-mode). Files: `llm-wiki-core`
(frontmatter/tags/index/embeddings/search/ingest + tests), `commands/kb-ingest-github.md`,
`workflows/ingest-github-tools.js`, `skills/compile-tool.md`, updated `skills/kb-query`/`commands`,
taxonomy template, this spec; version → 0.5.0; smoke-tested before opening.

## Open questions / future
- Promote `kb query` filters to a future `kb tools` convenience alias? Deferred — flags suffice.
- A native `kb ingest --mode github <owner/repo>` core verb (vs. skill fetch) — revisit later.
- README-refresh policy: dedup-by-`source:` enables update-in-place on re-ingest.
