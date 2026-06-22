# Design: tool ingestion (URL-agnostic) + frontmatter-filtered query

- **Date:** 2026-06-22
- **Status:** Draft v3 (awaiting review)
- **Plugin:** `karpathy-llm-wiki`
- **Target version:** 0.5.0 (minor — new feature)

## Problem

Two coupled needs:

1. **Ingest tools from any URL.** A "tool" is any library / framework / service / repo we'd reach
   for in the agentic SDLC — most live on product or docs pages (e.g. `deepeval.com`,
   `buildkite.com`, `linearb.io`), not GitHub. Ingestion is **URL-agnostic** with two fetch paths
   feeding one contract (`source_class: tool`, `source:` = URL, → one tool note):
   - **GitHub repo URL → README API** (`GET api.github.com/repos/<owner>/<repo>/readme`,
     `Accept: application/vnd.github.raw`) — richest signal; the repo *root* page extracts as junk.
   - **Any other URL → fetch + main-content extraction** via **trafilatura** (boilerplate-stripped
     markdown + title/meta-description). The goal is *enough signal to classify and summarize*, not
     full text — the compile LLM already knows many tools and needs the pitch + canonical URL.
   A tool is **one URL = one note**, classified by what it is (framework, MCP server, CLI…) and
   where it fits in the SDLC (testing, review…).
2. **Find tools (and any notes) by attribute.** `kb search` is purely semantic with **no metadata
   filter**, so "every tool tagged `phase-testing`" (an exhaustive handout) is impossible. We fold
   **frontmatter filtering into `kb query`** rather than build a separate tool search.

Grounding facts that shape this:
- `knowledge_type` is already a scalar index column → exact `.where()` with **no re-index**.
- `tags` is a **comma-joined utf8 string**; `type`/`scope` are **not stored**. Token-exact tag
  filtering needs `tags` as `list(utf8)` → **one `kb index --full`**.
- LanceDB 0.30.2 supports `.where(pred, prefilter=True)` on vector *and* filter-only queries;
  making `search`'s query arg optional is non-breaking.
- `kb ingest` writes raw markdown + a **`.meta.json` sidecar** (no YAML frontmatter); `source` and
  `source_class` live there.
- **`ingest.py` url-mode uses a minimal `HTMLParser`** (text-node concatenation) — crude on
  marketing/landing pages. It will be **replaced by trafilatura** so there is exactly ONE HTML
  extractor (tools and existing url-mode share it — no second path).
- **Existing duplication** to consolidate (the tags-list change touches all of it): frontmatter
  serialization in two places (`core/frontmatter.dump` vs hand-built block in
  `compile_cmd._write_note`); `MAX_TAGS` twice; tags CSV split/join in three places
  (`index._normalize_tags`, `index._do_stats`, `compile_cmd._handle_write_note`); `_slugify` twice;
  ad-hoc tag validation in `_write_note` instead of `taxonomy.validate_tags`.

## Goals

- Ingest a tool from any URL (or batch): GitHub→README API, else→trafilatura; `source:` = URL.
- Compile each into **one** `knowledge_type: tool` note, classified by controlled tags.
- Fold **frontmatter filtering into `kb query`/`kb search`**: `--knowledge-type`, repeatable `--tag`
  (token-exact, AND), `--type`, `--scope`, generic `--where`; **query text optional** so a pure
  filter enumerates *all* matches (the handout). Benefits every note, not just tools.
- **Reuse** existing core helpers; **consolidate** the duplication the schema change exposes;
  **one** HTML extractor (trafilatura).
- Ship **upstream** to `cajias/second-brain-plugins` (`karpathy-llm-wiki`).

## Non-goals

- No cloning/building/static-analysis of repos — README/metadata or page content only.
- No separate tool-search surface; no query engine beyond LanceDB `.where()`.
- No new `type: tool` archetype — tools are permanent notes with `knowledge_type: tool` + tags.
- No browser/JS rendering for SPA pages (trafilatura fetches static HTML; meta-description + the
  compile LLM cover gaps). Browser-render via claude-in-chrome is deferred unless a real SPA forces it.

## Data model (decided)

Every tool = a permanent note: `type: permanent`, **`knowledge_type: tool`** (new knowledge_type;
marker — validated, greppable, indexed, no tag slot used), `source:` = URL, body =
*What it is · What it's for · Install · Key capabilities · Link*. Tags (≤6, three groups):
- **Tool-type** (exactly 1): `tool-framework`, `tool-library`, `tool-cli`, `tool-mcp-server`,
  `tool-agent`, `tool-skill`, `tool-plugin`, `tool-sdk`, `tool-service`, `tool-dataset`
- **SDLC phase** (1–2): `phase-planning`, `phase-design`, `phase-implementation`,
  `phase-code-review`, `phase-testing`, `phase-debugging`, `phase-deployment`,
  `phase-observability`, `phase-security`, `phase-docs`
- **Topic** (0–2, from the existing 21 approved tags)

## Components

### 1. Taxonomy extension — `wiki/_meta/tag-taxonomy.md` (+ init template)
Add `tool` to `knowledge_types`; add a **Tool tags** section (10 `tool-*` + 10 `phase-*`). Update
the `kb init` taxonomy template. Mirror new `knowledge_types` into `core/frontmatter.KNOWLEDGE_TYPES`
if used for validation.

### 2. Core — index schema + one re-index
`commands/index._empty_index_schema`: `tags` → `pa.list_(pa.utf8())`; add `type`/`scope` (`utf8`).
`_build_record` writes `tags` as a list + adds `type`/`scope`. Promote tag normalization to a single
core home (`core/tags.py` or `core/frontmatter.py`) returning a list; remove `index._normalize_tags`
CSV join; fix `index._do_stats` to read the list. Migration: `kb index --full` (re-embeds ~2,456
notes, `all-MiniLM-L6-v2`/384-dim).

### 3. Core — filtered search + CLI flags
`core/embeddings.search_index(...)` gains optional `knowledge_type`, `tags: list`, `type`, `scope`,
`where: str|None`; builds a DataFusion predicate, calls `.where(pred, prefilter=True)`; tags via
`array_has_any(tags, [...])` (AND across repeated `--tag`). `query is None` → filter-only path
returning **all** matches (`--limit` default unbounded for filter-only). `commands/search.py`:
`query` becomes optional `typer.Argument(None)`; add `--knowledge-type`, repeatable `--tag`,
`--type`, `--scope`, `--where`. Results return `tags` as a list. `kb-query` skill updated to use
these (semantic+filter for discovery; filter-only for handouts).

### 4. Ingest — `kb-ingest-tool` (command + `workflows/ingest-tools.js`)
**4a. One extractor.** Replace the minimal `HTMLParser` in `ingest.py` url-mode with **trafilatura**
(`trafilatura.fetch_url` + `extract(..., output_format="markdown", include_links=True)`, plus
`extract_metadata` for title/description). All url-mode ingestion uses this single path.
**4b. URL router.** `kb-ingest-tool <url|owner/repo>`: if GitHub repo → README API (raw header) +
repo metadata (`description`, `topics`, `language`, `homepage`, `stargazers_count`), `$GITHUB_TOKEN`/
`gh auth token` if present (read at call time, never persisted); else → trafilatura extract +
page metadata. Prepend a short `<!-- tool: <url> | lang/host | ⭐stars | topics/keywords -->` +
description block to the body so the compile classifier sees it inline, then `kb ingest --mode text
--source <url> --source-class tool` (reuses the sidecar path; add `tool` to accepted
`--source-class` values + test). Batch workflow calls `kb ingest` **serially** (non-atomic
manifest), mirroring `ingest-notion-cited-sources.js`.

### 5. Compile — tool-mode (`skills/compile-tool.md` + pointer from `compile-note`)
When `source_class: tool`: produce **one** note, `knowledge_type: tool`, classify exactly one
`tool-*` + 1–2 `phase-*` + ≤2 topic (≤6) from content+metadata; structured body; `source:` = URL
(source-preservation). Dedup by `source:` (same URL → update in place). Write via
`core/frontmatter.dump`; validate tags via `taxonomy.validate_tags`.

### 6. Refactor / consolidation (critical path)
Because the tags-list + single-extractor changes touch these, consolidate:
- `compile_cmd._write_note` → `core/frontmatter.dump(metadata, body)` (single canonical writer).
- Single `MAX_TAGS` (in `core/frontmatter`); delete `compile_cmd._MAX_TAGS`.
- Single list-based tag-normalization helper in core; callers updated.
- Single `_slugify` (core util; dedupe `compile_cmd`/`ingest`).
- `_write_note` tag validation → `taxonomy.validate_tags`.
- Single HTML extractor: trafilatura replaces the minimal `HTMLParser` (no second path).

## Reuse targets (call these — do not re-implement)
- Frontmatter: `core/frontmatter.parse_file` / `core/frontmatter.dump`
- Taxonomy: `core/taxonomy.load_taxonomy_safe` / `validate_tags` / `validate_knowledge_type`
- Search/embeddings: `core/embeddings.search_index` / `embed_texts` / `MODEL_NAME` / `EMBEDDING_DIM`
- Ingest: existing `kb ingest --mode text` sidecar path (no new writer)
- HTML extraction: **trafilatura** (the one extractor; new dep). GitHub API JSON over stdlib `urllib.request`.

## Data flow

```
url/repo ─▶ kb-ingest-tool ─┬─ GitHub? ─▶ README API (raw) + repo metadata
                            └─ else    ─▶ trafilatura fetch+extract (markdown) + page metadata
                ─▶ prepend tool-meta block ─▶ kb ingest --mode text --source <url> --source-class tool
                ─▶ compile tool-mode ─▶ ONE note (knowledge_type=tool, tool-*/phase-*/topic),
                       via frontmatter.dump, source=url ─▶ wiki/permanent/
                ─▶ kb index (tags list col) ─▶ kb query --knowledge-type tool --tag phase-testing
                       (filter-only ⇒ full handout) | kb query "debug agent loop" --tag tool-cli (ranked)
```

## Error handling
- README/page 404, private, rate-limited (403 + `X-RateLimit-Remaining: 0`; surface reset, suggest
  token), or trafilatura empty extraction: skip cleanly, leave already-ingested intact.
- Malformed ref/URL: validate up front. Manifest: serial `kb ingest` only.
- Filter with no matches: empty set (not an error). Unknown `--where` column: clear error.
- Ambiguous classification: most-specific defensible `tool-*`; note uncertainty in body.

## Implementation stages & quality gates

Each stage is **TDD-first** (red→green) and ends with this gate **in order**; no stage advances
while red or with unresolved review findings:
1. **Code review** — `ponytail-review` + `code-reviewer` agent on the stage diff; address findings.
2. **Code simplification** — `simplify` skill / `code-simplifier` on the diff (reuse/clarity/
   efficiency); apply.
3. **Refactor** — fold in any consolidation the review/simplification surfaced.
4. **Lint/type** — `make lint` (pre-commit: ruff strict + mypy strict + vulture).
5. **Test** — `make test` (pytest, coverage ≥70).
6. **Debt** — `ponytail-debt` (duplication/complexity; ruff `max-complexity=10`, `max-args=7`).

Stages:
- **Stage 0 — Refactor/consolidate (no behavior change).** Land component 6 dedup first (except the
  trafilatura swap, which needs the dep — Stage 4a). Gate as above; ponytail-debt shows duplication resolved.
- **Stage 1 — Schema + re-index.** tags→list, +type/scope, `_build_record`/`_do_stats`; `kb index
  --full`. Tests: list-tag round-trip, by-tag stats.
- **Stage 2 — Filtered query.** `search_index` filters + filter-only path; `search.py` flags; optional
  query. Tests: knowledge_type, AND-tag, type/scope, filter-only completeness, semantic+filter, empty,
  query-only backward-compat. Update `kb-query` skill.
- **Stage 3 — Taxonomy + `tool` source-class.** Taxonomy file/template + `--source-class tool`.
  Tests: lint accepts `knowledge_type: tool` + new tags; ingest records `source_class=tool`.
- **Stage 4 — Tool ingest.** 4a: replace url-mode HTMLParser with trafilatura (tests: markdown
  extraction, metadata, existing url ingestion still works). 4b: `kb-ingest-tool` URL router +
  `ingest-tools.js` (tests: GitHub README-API construction, generic-URL trafilatura path, tool-meta
  block, serial ingest, source=URL). Smoke: 2 real tools (a GitHub framework + a SaaS page like deepeval.com).
- **Stage 5 — Compile tool-mode.** `compile-tool` skill. Smoke: the 2 tools → one note each, exactly
  one `tool-*`, ≥1 `phase-*`, ≤6 tags, `source` set, `kb lint` clean; `kb query --tag` finds them.
- **Stage 6 — Finalize.** Full `make test`+`make lint`+`ponytail-audit` on branch; bump 0.4.0→0.5.0; PR.

## Testing
Unit (pytest) per stage. Integration smoke on a GitHub framework + a SaaS landing page (e.g.
deepeval.com): ingest→compile→`kb query` filter-only handout returns both; `--tag phase-*` returns
the right subset; `kb lint` 0 rogue/invalid. Coverage ≥70 (repo gate).

## Upstream contribution plan
Branch `feat/tool-ingestion`; consider two PRs (PR-A: refactor+schema+filtered query+trafilatura swap
— useful standalone; PR-B: ingest+compile tool-mode). Files: `llm-wiki-core` (frontmatter/tags/index/
embeddings/search/ingest + trafilatura dep + tests), `commands/kb-ingest-tool.md`,
`workflows/ingest-tools.js`, `skills/compile-tool.md`, updated `kb-query` skill/commands, taxonomy
template, this spec; version → 0.5.0; smoke-tested before opening.

## Open questions / future
- Promote `kb query` filters to a future `kb tools` alias? Deferred — flags suffice.
- Native `kb ingest --mode github`/`--mode tool` core verb (vs. skill fetch)? Revisit later.
- SPA pages needing JS render → browser-render path, only if a real case forces it.
- README/page-refresh policy: dedup-by-`source:` enables update-in-place on re-ingest.
