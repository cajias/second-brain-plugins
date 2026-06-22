# Tool Ingestion + Frontmatter-Filtered Query — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest any tool URL (GitHub README API or trafilatura page extract) into a single `knowledge_type: tool` permanent note, and fold frontmatter filtering (`--knowledge-type`, repeatable `--tag`, `--type`, `--scope`, `--where`, optional query) into `kb search`/`kb query`.

**Architecture:** A URL router (`kb-ingest-tool`) feeds two fetch paths into one contract (`source_class: tool`, `source:` = URL, one note) reusing the existing `kb ingest --mode text` sidecar pipeline; the LanceDB index gains a token-exact `tags: list(utf8)` column plus `type`/`scope` so `core/embeddings.search_index` can build a DataFusion `.where(pred, prefilter=True)` predicate (vector-ranked or filter-only). Existing serialization/tag/slug/HTML-extraction duplication is consolidated into single core homes first so the schema change touches one path each.

**Tech Stack:** lancedb 0.30.2, sentence-transformers all-MiniLM-L6-v2/384-dim, pyarrow, typer, pyyaml, trafilatura (new dep), pytest/ruff/mypy/vulture.

## Global Constraints

- python>=3.11 (pyproject `requires-python = ">=3.11"`).
- Reuse `core/frontmatter.dump` + `core/taxonomy.validate_tags`/`validate_knowledge_type` + `core/embeddings.search_index` — do NOT re-implement parse/serialize/search.
- ONE HTML extractor (trafilatura). Remove the minimal `HTMLParser` (`_HTMLTextExtractor`/`_html_to_text`) in `commands/ingest.py`.
- `tags` index column becomes `pa.list_(pa.utf8())` (was `pa.utf8()` CSV).
- `knowledge_type: tool` is a marker (validated, greppable, indexed; uses no tag slot).
- ≤6 tags total: exactly 1 `tool-*`, 1–2 `phase-*`, ≤2 topic (from the existing approved tags).
- `source:` = the original URL, preserved on compile (web-source-preservation rule).
- Batch tool ingest is SERIAL only (manifest is non-atomic) — mirror `workflows/ingest-notion-cited-sources.js`.
- Commits use conventional format (`feat:`/`refactor:`/`test:`/`docs:`) with NO `Co-Authored-By`/attribution trailer (repo attribution is disabled globally).
- ruff line-length 120, max-complexity 10, max-args 7 (`[tool.ruff.lint.mccabe]`/`[tool.ruff.lint.pylint]`).
- mypy strict (`[tool.mypy] strict = true`).
- coverage >=70 (`[tool.coverage.report] fail_under = 70`).

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `llm-wiki-core/src/llm_wiki/core/tags.py` | **create** | Single list-based tag normalizer `normalize_tags(value) -> list[str]` (the one core home). |
| `llm-wiki-core/src/llm_wiki/core/text.py` | **create** | Single `slugify(text, max_len)` shared by compile + ingest. |
| `llm-wiki-core/src/llm_wiki/core/frontmatter.py` | modify | Re-export `MAX_TAGS` as the single source of truth (already there); no schema change beyond knowledge_type marker support via taxonomy. |
| `llm-wiki-core/src/llm_wiki/core/html_extract.py` | **create** | Single trafilatura-backed extractor: `extract_main_content(html, url) -> ExtractedDoc`. |
| `llm-wiki-core/src/llm_wiki/core/github.py` | **create** | GitHub repo detection + README API + repo metadata fetch (stdlib urllib). |
| `llm-wiki-core/src/llm_wiki/commands/compile_cmd.py` | modify | `_write_note` uses `frontmatter.dump`, `text.slugify`, `frontmatter.MAX_TAGS`, `taxonomy.validate_tags`; delete `_MAX_TAGS`/local `_slugify`. |
| `llm-wiki-core/src/llm_wiki/commands/index.py` | modify | `_empty_index_schema` tags→list + `type`/`scope`; `_build_record` writes list + type/scope; `_do_stats`/`_write_stats` read list; drop `_normalize_tags` CSV. |
| `llm-wiki-core/src/llm_wiki/core/embeddings.py` | modify | `search_index` gains `knowledge_type`/`tags`/`type`/`scope`/`where` + filter-only path; returns `tags` as list. |
| `llm-wiki-core/src/llm_wiki/commands/search.py` | modify | `query` optional; add `--knowledge-type`/`--tag`(repeatable)/`--type`/`--scope`/`--where`. |
| `llm-wiki-core/src/llm_wiki/commands/ingest.py` | modify | url-mode uses `core/html_extract`; remove HTMLParser; `_slugify` → `core/text.slugify`. |
| `llm-wiki-core/src/llm_wiki/commands/ingest_tool.py` | **create** | `kb ingest-tool` URL router (GitHub vs trafilatura) → tool-meta block → `_ingest_text` with `source_class=tool`, `source`=URL. |
| `llm-wiki-core/src/llm_wiki/cli.py` | modify | Register `app.command("ingest-tool")(ingest_tool)`. |
| `llm-wiki-core/src/llm_wiki/__init__.py` | modify | `__version__ = "0.5.0"`. |
| `llm-wiki-core/pyproject.toml` | modify | Add `trafilatura>=1.12`; `version = "0.5.0"`; mypy override for trafilatura. |
| `llm-wiki-core/src/llm_wiki/templates/tag-taxonomy.md` | modify | Add `tool` knowledge type + Tool tags section. |
| `wiki/_meta/tag-taxonomy.md` (vault, runtime) | modify | Same taxonomy edits (mirrors template). |
| `commands/kb-ingest-tool.md` | **create** | `/kb-ingest-tool` slash command doc. |
| `commands/kb-query.md` | modify | Document new filter flags + filter-only handout usage. |
| `workflows/ingest-tools.js` | **create** | Serial batch tool ingest (mirror notion workflow). |
| `skills/compile-tool.md` | **create** | Tool-mode compile skill (one note/URL, classify, `frontmatter.dump`, dedup by `source`). |
| `skills/compile-note.md` | modify | Pointer to `compile-tool` when `source_class: tool`. |
| `.claude-plugin/plugin.json` | modify | `"version": "0.5.0"`. |
| `llm-wiki-core/tests/test_tags.py` | **create** | `normalize_tags` unit tests. |
| `llm-wiki-core/tests/test_text.py` | **create** | `slugify` unit tests. |
| `llm-wiki-core/tests/test_html_extract.py` | **create** | trafilatura extractor tests (mocked). |
| `llm-wiki-core/tests/test_github.py` | **create** | GitHub URL detection + README API construction tests (mocked). |
| `llm-wiki-core/tests/test_ingest_tool.py` | **create** | URL router + tool-meta block + source_class=tool tests. |
| `llm-wiki-core/tests/test_index.py` | modify | List-tag round-trip, by-tag stats with list column. |
| `llm-wiki-core/tests/test_search.py` | modify | Filter flags, AND-tag, filter-only completeness, empty, backward-compat. |
| `llm-wiki-core/tests/test_compile.py` | modify | `_write_note` produces canonical dump; tag validation via taxonomy. |
| `llm-wiki-core/tests/test_ingest.py` | modify | url-mode trafilatura path; `tool` source-class accepted. |
| `llm-wiki-core/tests/conftest.py` | modify | Extend `SAMPLE_TAXONOMY` with `tool` + tool/phase tags; add `tool_note` fixture. |

---

# Stage 0 — Refactor / Consolidate (no behavior change)

Land the duplication consolidation that the tags-list and single-extractor changes touch (Component 6), EXCEPT the trafilatura swap (needs the dep — Stage 4a). All tests stay green; behavior is identical.

## Task 0.1 — Single core tag normalizer (`core/tags.py`)

**Files:**
- Create `llm-wiki-core/src/llm_wiki/core/tags.py`
- Create test `llm-wiki-core/tests/test_tags.py`

**Interfaces:**
- Produces: `normalize_tags(value: object) -> list[str]` — coerces a frontmatter tags value (list, CSV string, scalar, or None) into a clean `list[str]` (stripped, empties dropped). Replaces the list→CSV `index._normalize_tags` and the three ad-hoc CSV splits.

- [ ] Write failing test `tests/test_tags.py`:
```python
"""Tests for the single core tag normalizer."""

from __future__ import annotations

from llm_wiki.core.tags import normalize_tags


class TestNormalizeTags:
    def test_list_passthrough_strips_and_drops_empties(self):
        assert normalize_tags(["  a ", "b", "", "  "]) == ["a", "b"]

    def test_csv_string_split(self):
        assert normalize_tags("a, b ,c") == ["a", "b", "c"]

    def test_none_returns_empty_list(self):
        assert normalize_tags(None) == []

    def test_scalar_becomes_single_element(self):
        assert normalize_tags("solo") == ["solo"]

    def test_empty_string_returns_empty_list(self):
        assert normalize_tags("") == []

    def test_non_string_scalar_coerced(self):
        assert normalize_tags(42) == ["42"]
```
- [ ] Run it, expect fail: `cd llm-wiki-core && uv run pytest tests/test_tags.py -q` → `ModuleNotFoundError: No module named 'llm_wiki.core.tags'`.
- [ ] Minimal impl — create `llm-wiki-core/src/llm_wiki/core/tags.py`:
```python
"""Tag normalization — the single core home for turning a frontmatter
``tags`` value into a clean ``list[str]``.

Replaces the ad-hoc CSV split/join previously duplicated across
``commands/index`` and ``commands/compile_cmd``.
"""

from __future__ import annotations


def normalize_tags(value: object) -> list[str]:
    """Coerce a frontmatter tags value into a clean list of tag strings.

    Accepts a list, a comma-separated string, a scalar, or None. Strips
    whitespace and drops empty entries.

    Args:
        value: The raw ``tags`` frontmatter value.

    Returns:
        A list of non-empty, stripped tag strings.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [s for s in (str(t).strip() for t in value) if s]
    if isinstance(value, str):
        return [s for s in (part.strip() for part in value.split(",")) if s]
    text = str(value).strip()
    return [text] if text else []
```
- [ ] Run it, expect pass: `uv run pytest tests/test_tags.py -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/core/tags.py llm-wiki-core/tests/test_tags.py && git commit -m "refactor: add single core tag normalizer in core/tags"`

## Task 0.2 — Single `slugify` (`core/text.py`)

**Files:**
- Create `llm-wiki-core/src/llm_wiki/core/text.py`
- Create test `llm-wiki-core/tests/test_text.py`

**Interfaces:**
- Produces: `slugify(text: str, max_len: int = 80) -> str` — kebab-case filesystem-safe slug. Replaces `compile_cmd._slugify` (max 80, word-boundary trim) and `ingest._slugify` (max 60). Default `max_len=80`; ingest callers pass their own length.

- [ ] Write failing test `tests/test_text.py`:
```python
"""Tests for the single core slugify helper."""

from __future__ import annotations

from llm_wiki.core.text import slugify


class TestSlugify:
    def test_basic_kebab_case(self):
        assert slugify("Hello World Pattern") == "hello-world-pattern"

    def test_strips_punctuation(self):
        assert slugify("API: design & versioning!") == "api-design-versioning"

    def test_collapses_repeated_separators(self):
        assert slugify("a   --  b") == "a-b"

    def test_respects_max_len_on_word_boundary(self):
        out = slugify("alpha beta gamma delta", max_len=12)
        assert len(out) <= 12
        assert not out.endswith("-")

    def test_default_max_len_is_80(self):
        long = "word " * 40
        assert len(slugify(long)) <= 80
```
- [ ] Run it, expect fail: `uv run pytest tests/test_text.py -q` → `ModuleNotFoundError: No module named 'llm_wiki.core.text'`.
- [ ] Minimal impl — create `llm-wiki-core/src/llm_wiki/core/text.py` (merges both prior implementations; trims to the last whole word like `compile_cmd._slugify`):
```python
"""Text utilities — the single core ``slugify`` shared by compile and ingest."""

from __future__ import annotations

import re


def slugify(text: str, max_len: int = 80) -> str:
    """Convert text to a kebab-case slug suitable for filenames.

    Args:
        text: Arbitrary input text.
        max_len: Maximum slug length; truncates on a word boundary.

    Returns:
        A filesystem-safe kebab-case slug.
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text
```
- [ ] Run it, expect pass: `uv run pytest tests/test_text.py -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/core/text.py llm-wiki-core/tests/test_text.py && git commit -m "refactor: add single core slugify in core/text"`

## Task 0.3 — `index.py` uses `core/tags.normalize_tags` (still CSV storage, behavior unchanged)

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/index.py` (`_normalize_tags` at lines 52-56; `_build_record` line 83; `_do_stats` lines 217-221; `_write_stats` lines 264-267)
- Existing test `llm-wiki-core/tests/test_index.py` (no new test; green-keeping refactor)

**Interfaces:**
- Consumes: `core.tags.normalize_tags(value) -> list[str]` (Task 0.1).
- Produces: index `_build_record` still stores `tags` as a CSV string at this stage (`",".join(...)`) so the schema is untouched until Stage 1 — only the *split* logic is centralized.

- [ ] Run existing index tests green first: `uv run pytest tests/test_index.py -q`.
- [ ] Edit `index.py`: replace the local `_normalize_tags` body to delegate the split to the core helper but keep CSV output (schema unchanged this stage):
```python
from llm_wiki.core.tags import normalize_tags


def _tags_csv(tags: object) -> str:
    """Serialize a tags value into a CSV string for the (current) utf8 column."""
    return ",".join(normalize_tags(tags))
```
  Update `_build_record` line 83 `"tags": _normalize_tags(metadata.get("tags", []))` → `"tags": _tags_csv(metadata.get("tags", []))`. In `_do_stats` (lines 217-221) and `_write_stats` (lines 264-267), keep reading the CSV column as-is (`tags_str.split(",")`) — that path changes in Stage 1.
- [ ] Run it, expect pass: `uv run pytest tests/test_index.py -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/index.py && git commit -m "refactor: index tag split via core.tags.normalize_tags"`

## Task 0.4 — `compile_cmd._write_note` → `frontmatter.dump` + core `slugify` + single `MAX_TAGS` + `taxonomy.validate_tags`

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/compile_cmd.py` (imports lines 16-31; constant `_MAX_TAGS` line 42; `_slugify` lines 52-59; `_write_note` lines 82-171)
- Modify test `llm-wiki-core/tests/test_compile.py` (`TestWriteNote` adds canonical-dump assertion)

**Interfaces:**
- Consumes: `core.frontmatter.dump(metadata: dict, body: str) -> str` (frontmatter.py lines 155-188); `core.frontmatter.MAX_TAGS` (= 6, frontmatter.py line 58); `core.text.slugify` (Task 0.2); `core.taxonomy.validate_tags(tags, taxonomy_path) -> list[str]` (taxonomy.py lines 110-124); `core.taxonomy.validate_knowledge_type(kt, taxonomy_path) -> bool` (taxonomy.py lines 127-136).
- Produces: `_write_note(...)` writes via `frontmatter.dump` — identical canonical ordering (id, type, knowledge_type, status, confidence, scope, tags, source, created) the hand-built block produced.

- [ ] Write failing test in `tests/test_compile.py` `TestWriteNote` (assert the file went through the canonical dumper — `tags` block + quoted source/created, which the hand block also produced, but now also asserting the dump path is reused by checking no extra blank lines and the exact tag block shape):
```python
    def test_write_note_uses_canonical_dump(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        runner.invoke(app, self._write_note_args(tags="architecture,api-design"))
        permanent = wiki_root / "wiki" / "permanent"
        content = next(permanent.glob("*.md")).read_text()
        assert content.startswith("---\n")
        assert "knowledge_type: pattern\n" in content
        assert "tags:\n  - architecture\n  - api-design\n" in content
        assert 'source: "session-test"\n' in content
```
- [ ] Run it, expect fail (hand-built block has subtly different spacing/order tolerance — and the goal is to route through `dump`): `uv run pytest tests/test_compile.py -k canonical_dump -q`.
- [ ] Minimal impl — edit `compile_cmd.py`:
  - Imports: add `from llm_wiki.core.frontmatter import MAX_TAGS, dump`, `from llm_wiki.core.text import slugify`, `from llm_wiki.core.taxonomy import load_taxonomy_safe, validate_tags`.
  - Delete `_MAX_TAGS = 6` (line 42) and `_MAX_SLUG_LEN`/local `_slugify` (lines 41, 52-59).
  - In `_write_note`, replace validation + hand-built `lines` (lines 93-149) with:
```python
    taxonomy_path = cfg.wiki_meta / "tag-taxonomy.md"
    taxonomy = load_taxonomy_safe(taxonomy_path)

    warnings: list[str] = []
    if taxonomy["knowledge_types"] and knowledge_type not in taxonomy["knowledge_types"]:
        warnings.append(
            f"knowledge_type '{knowledge_type}' not in approved list: {sorted(taxonomy['knowledge_types'])}"
        )
    invalid_tags = validate_tags(tags, taxonomy_path)
    if invalid_tags:
        warnings.append(f"Tags not in approved taxonomy: {invalid_tags}. Approved: {sorted(taxonomy['tags'])}")
    if len(tags) > MAX_TAGS:
        warnings.append(f"Too many tags ({len(tags)}). Maximum is {MAX_TAGS}.")

    note_id = _generate_id()
    slug = slugify(title)
    filename = f"{slug}.md"
    filepath = cfg.wiki_permanent / filename
    if filepath.exists() and not dry_run:
        slug = f"{slug}-{note_id.split('-')[-1]}"
        filename = f"{slug}.md"
        filepath = cfg.wiki_permanent / filename

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    metadata = {
        "id": note_id,
        "type": "permanent",
        "knowledge_type": knowledge_type,
        "status": "pending",
        "confidence": confidence,
        "scope": "universal",
        "tags": tags,
        "source": source,
        "created": now,
    }
    note_content = dump(metadata, f"\n# {title}\n\n{body}\n")
```
  Keep the `result` dict + dry-run/write tail (lines 151-171) unchanged.
- [ ] Run it, expect pass: `uv run pytest tests/test_compile.py -q` (all `TestWriteNote` pass — existing assertions on `architecture`/`pattern`/`---` still hold).
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/compile_cmd.py llm-wiki-core/tests/test_compile.py && git commit -m "refactor: _write_note via frontmatter.dump + core slugify/MAX_TAGS/validate_tags"`

## Task 0.5 — `ingest._slugify` → `core/text.slugify`

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/ingest.py` (`_slugify` lines 52-58; callers at lines 162, 206, 280, 323)
- Existing tests `llm-wiki-core/tests/test_ingest.py` (green-keeping)

**Interfaces:**
- Consumes: `core.text.slugify(text, max_len) -> str` (Task 0.2).

- [ ] Run existing ingest tests green: `uv run pytest tests/test_ingest.py -q`.
- [ ] Edit `ingest.py`: delete local `_slugify` (lines 52-58); add `from llm_wiki.core.text import slugify`; replace the four call sites `_slugify(x, max_len=N)` → `slugify(x, max_len=N)` (note: the old ingest `_slugify` did not word-boundary-trim, but for these short slugs the output is equivalent; verify via tests).
- [ ] Run it, expect pass: `uv run pytest tests/test_ingest.py -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/ingest.py && git commit -m "refactor: ingest slugify via core.text.slugify"`

## Stage 0 Quality Gate

- [ ] Code review — run `ponytail-review` (and/or `code-reviewer` agent) on the Stage 0 diff; address findings.
- [ ] Code simplification — run the `simplify` skill / `code-simplifier` on the diff; apply.
- [ ] Refactor — fold in any consolidation the review/simplification surfaced (e.g. if `_tags_csv` and `normalize_tags` can collapse once Stage 1 lands the list column — note it; do not pre-empt Stage 1).
- [ ] Lint/type — `make lint` (ruff + mypy + vulture) green.
- [ ] Test — `make test` (pytest, coverage >=70) green.
- [ ] Debt — `ponytail-debt` clean: confirm `MAX_TAGS` is single (no `_MAX_TAGS`), `_slugify` is single (no local copies), tag split is single (`core.tags.normalize_tags`).

---

# Stage 1 — Schema + re-index (tags→list, +type/scope)

`tags` becomes `pa.list_(pa.utf8())`; add `type`/`scope` utf8 columns; `_build_record` writes the list + new fields; `_do_stats`/`_write_stats` read the list. Migration is one `kb index --full` (re-embeds ~2,456 notes, all-MiniLM-L6-v2/384-dim).

## Task 1.1 — `_empty_index_schema` tags→list + type/scope

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/index.py` (`_empty_index_schema` lines 109-124)
- Modify test `llm-wiki-core/tests/test_index.py`

**Interfaces:**
- Produces: `_empty_index_schema() -> pa.Schema` with `pa.field("tags", pa.list_(pa.utf8()))`, `pa.field("type", pa.utf8())`, `pa.field("scope", pa.utf8())`.

- [ ] Write failing test in `tests/test_index.py` (new class, asserts the empty-table schema):
```python
class TestIndexSchema:
    """The seeded empty index uses a list tags column plus type/scope."""

    def test_empty_schema_tags_is_list(self):
        import pyarrow as pa

        from llm_wiki.commands.index import _empty_index_schema

        schema = _empty_index_schema()
        assert schema.field("tags").type == pa.list_(pa.utf8())
        assert schema.field("type").type == pa.utf8()
        assert schema.field("scope").type == pa.utf8()
```
- [ ] Run it, expect fail: `uv run pytest tests/test_index.py -k empty_schema_tags_is_list -q` → `AssertionError` (tags is `pa.utf8()`; no `type` field → `KeyError`).
- [ ] Minimal impl — edit `_empty_index_schema` (lines 111-124): change `pa.field("tags", pa.utf8())` → `pa.field("tags", pa.list_(pa.utf8()))`; insert after the `tags` field: `pa.field("type", pa.utf8()),` and `pa.field("scope", pa.utf8()),`.
- [ ] Run it, expect pass: `uv run pytest tests/test_index.py -k empty_schema -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/index.py llm-wiki-core/tests/test_index.py && git commit -m "feat: index schema tags as list + type/scope columns"`

## Task 1.2 — `_build_record` writes list tags + type/scope

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/index.py` (`_build_record` lines 70-90; remove `_tags_csv` from Task 0.3)
- Modify test `llm-wiki-core/tests/test_index.py`

**Interfaces:**
- Consumes: `core.tags.normalize_tags` (Task 0.1).
- Produces: `_build_record(...)` returns `"tags": list[str]`, `"type": str`, `"scope": str`.

- [ ] Write failing test in `tests/test_index.py` (`TestIndexSchema`), verifying a round-trip via stats after a full index that a list-tag note keeps its tags discrete:
```python
    def test_full_index_round_trips_list_tags(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["index", "--full"])
        assert result.exit_code == 0
        import json

        stats = runner.invoke(app, ["index", "--stats", "--json"])
        data = json.loads(stats.stdout)
        # populated_wiki note 1 has tags architecture + api-design — both counted discretely
        assert data["by_tag"].get("architecture") == 1
        assert data["by_tag"].get("api-design") == 1
```
- [ ] Run it, expect fail: `uv run pytest tests/test_index.py -k round_trips_list_tags -q` (writing a Python list into the still-CSV-reading stats path mismatches, or the build still emits CSV) — confirm the message.
- [ ] Minimal impl — edit `_build_record` (lines 79-90): replace `"tags": _tags_csv(metadata.get("tags", []))` → `"tags": normalize_tags(metadata.get("tags", []))`; after the `tags` line add `"type": metadata.get("type", "permanent"),` and `"scope": metadata.get("scope", ""),`. Delete the now-unused `_tags_csv` helper added in Task 0.3.
- [ ] Run it, expect pass: `uv run pytest tests/test_index.py -k round_trips_list_tags -q` (after Task 1.3 lands the reader; run both together if needed).
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/index.py llm-wiki-core/tests/test_index.py && git commit -m "feat: _build_record writes list tags + type/scope"`

## Task 1.3 — `_do_stats` + `_write_stats` read list tags

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/index.py` (`_do_stats` by-tag loop lines 216-221; `_write_stats` by-tag loop lines 263-270)
- Existing test `llm-wiki-core/tests/test_index.py` (Task 1.2 test now passes)

**Interfaces:**
- Consumes: index column `tags: list[str]`.
- Produces: `_do_stats` `by_tag` counts iterate list elements (not CSV split).

- [ ] Edit `_do_stats` (lines 216-221): replace the CSV-split loop with list iteration:
```python
    all_tags: list[str] = []
    for tags_val in df["tags"]:
        if tags_val is not None:
            all_tags.extend(str(t).strip() for t in tags_val if str(t).strip())
    stats["by_tag"] = dict(Counter(all_tags).most_common())
```
- [ ] Edit `_write_stats` (lines 263-270): mirror the same list iteration in the by-tag block.
- [ ] Run it, expect pass: `uv run pytest tests/test_index.py -q` (Task 1.2 round-trip + existing stats tests green).
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/index.py && git commit -m "feat: index stats read list tags column"`

## Stage 1 Quality Gate

- [ ] Code review — `ponytail-review` + `code-reviewer` agent on the Stage 1 diff; address findings.
- [ ] Code simplification — `simplify` skill / `code-simplifier` on the diff; apply (e.g. extract the shared list-tag-counting loop used by `_do_stats`/`_write_stats` into one helper).
- [ ] Refactor — fold in the consolidation surfaced (single `_count_tags(df)` helper if review flags duplication).
- [ ] Lint/type — `make lint` green.
- [ ] Test — `make test` (coverage >=70) green.
- [ ] Debt — `ponytail-debt` clean: no duplicated tag-counting loop, no leftover `_normalize_tags`/`_tags_csv`.
- [ ] Migration note (manual, post-merge on a real vault): run `kb index --full` once to re-embed all notes into the new schema.

---

# Stage 2 — Filtered query (`search_index` filters + `search.py` flags)

`search_index` gains optional `knowledge_type`/`tags`/`type`/`scope`/`where`, builds a DataFusion predicate, and `.where(pred, prefilter=True)`. `query is None` → filter-only path returning ALL matches (verified: `t.search().where(pred, prefilter=True).limit(N)`); repeated `--tag` → `array_has_any(tags, [...])` AND-chained (verified). `search.py` makes `query` optional and adds the flags. Results return `tags` as a list.

## Task 2.1 — Predicate builder in `core/embeddings.py`

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/core/embeddings.py` (add `_build_filter_predicate` above `search_index` line 58)
- Modify test `llm-wiki-core/tests/test_search.py` (unit-test the builder directly)

**Interfaces:**
- Produces: `_build_filter_predicate(knowledge_type: str | None, tags: list[str] | None, type_: str | None, scope: str | None, where: str | None) -> str | None` — returns a DataFusion SQL predicate string AND-joining each clause, or `None` if no filters. Tags become one `array_has_any(tags, ['t'])` clause per tag (AND across tags). String literals single-quoted; embedded single quotes doubled.

- [ ] Write failing test in `tests/test_search.py` (new class):
```python
class TestFilterPredicate:
    def test_no_filters_returns_none(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate(None, None, None, None, None) is None

    def test_knowledge_type_clause(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate("tool", None, None, None, None) == "knowledge_type = 'tool'"

    def test_repeated_tags_anded_via_array_has_any(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        pred = _build_filter_predicate(None, ["tool-cli", "phase-testing"], None, None, None)
        assert pred == "array_has_any(tags, ['tool-cli']) AND array_has_any(tags, ['phase-testing'])"

    def test_combined_clauses_anded(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        pred = _build_filter_predicate("tool", ["tool-cli"], "permanent", "universal", None)
        assert pred == (
            "knowledge_type = 'tool' AND array_has_any(tags, ['tool-cli']) "
            "AND type = 'permanent' AND scope = 'universal'"
        )

    def test_where_passthrough_appended(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate("tool", None, None, None, "confidence > 0.5") == (
            "knowledge_type = 'tool' AND (confidence > 0.5)"
        )

    def test_single_quote_escaped(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate("o'brien", None, None, None, None) == "knowledge_type = 'o''brien'"
```
- [ ] Run it, expect fail: `uv run pytest tests/test_search.py -k FilterPredicate -q` → `ImportError: cannot import name '_build_filter_predicate'`.
- [ ] Minimal impl — add to `embeddings.py` (before `search_index`):
```python
def _sql_literal(value: str) -> str:
    """Single-quote a string for a DataFusion predicate, escaping quotes."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _build_filter_predicate(
    knowledge_type: str | None,
    tags: list[str] | None,
    type_: str | None,
    scope: str | None,
    where: str | None,
) -> str | None:
    """Build a DataFusion predicate AND-joining the requested filters.

    Repeated tags are AND-chained via ``array_has_any`` (token-exact list
    membership). ``where`` is appended verbatim, parenthesized. Returns None
    when no filter is requested.
    """
    clauses: list[str] = []
    if knowledge_type:
        clauses.append(f"knowledge_type = {_sql_literal(knowledge_type)}")
    for tag in tags or []:
        clauses.append(f"array_has_any(tags, [{_sql_literal(tag)}])")
    if type_:
        clauses.append(f"type = {_sql_literal(type_)}")
    if scope:
        clauses.append(f"scope = {_sql_literal(scope)}")
    if where:
        clauses.append(f"({where})")
    return " AND ".join(clauses) if clauses else None
```
- [ ] Run it, expect pass: `uv run pytest tests/test_search.py -k FilterPredicate -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/core/embeddings.py llm-wiki-core/tests/test_search.py && git commit -m "feat: DataFusion filter predicate builder for search_index"`

## Task 2.2 — `search_index` filter params + filter-only path; list tags in results

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/core/embeddings.py` (`search_index` lines 58-108)
- Modify test `llm-wiki-core/tests/test_search.py`

**Interfaces:**
- Consumes: `_build_filter_predicate` (Task 2.1).
- Produces: `search_index(db_path, table_name, query: str | None = None, limit: int = 10, *, knowledge_type: str | None = None, tags: list[str] | None = None, type_: str | None = None, scope: str | None = None, where: str | None = None) -> list[dict[str, Any]]`. When `query` is None → filter-only (`table.search()` with no vector, `.where(pred, prefilter=True)`, no score). When `query` set → vector search with optional `.where(pred, prefilter=True)`. Result `tags` field is the list from the row.

- [ ] Write failing test in `tests/test_search.py` (new class — uses the CLI-built index so the real list column is present):
```python
class TestSearchIndexFilters:
    def test_filter_only_returns_all_matching(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        db = populated_wiki / ".lancedb"
        # populated_wiki has two knowledge_type=pattern notes
        res = search_index(db, "notes", query=None, knowledge_type="pattern")
        kinds = {r["knowledge_type"] for r in res}
        assert kinds == {"pattern"}
        assert len(res) == 2

    def test_tags_returned_as_list(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(populated_wiki / ".lancedb", "notes", query=None, knowledge_type="idea")
        assert res and isinstance(res[0]["tags"], list)
        assert res[0]["tags"] == ["llm"]

    def test_and_tag_filter(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(
            populated_wiki / ".lancedb", "notes", query=None, tags=["security", "authentication"]
        )
        assert len(res) == 1  # only token-refresh-strategy has both
```
- [ ] Run it, expect fail: `uv run pytest tests/test_search.py -k SearchIndexFilters -q` → `TypeError: search_index() got an unexpected keyword argument 'knowledge_type'`.
- [ ] Minimal impl — rewrite `search_index` (lines 58-108):
```python
def _row_to_result(row: Any, *, scored: bool) -> dict[str, Any]:  # noqa: ANN401  # pandas row is heterogeneous
    """Map a result row into the public result dict."""
    score = round(1.0 - row.get("_distance", 0.0), 4) if scored else None
    snippet = row.get("content", "")[:200].replace("\n", " ").strip()
    tags = row.get("tags", [])
    return {
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "file_path": row.get("file_path", ""),
        "score": score,
        "snippet": snippet,
        "knowledge_type": row.get("knowledge_type", ""),
        "tags": list(tags) if tags is not None else [],
    }


def search_index(  # noqa: PLR0913  # each filter is a discrete query dimension
    db_path: Path,
    table_name: str,
    query: str | None = None,
    limit: int = 10,
    *,
    knowledge_type: str | None = None,
    tags: list[str] | None = None,
    type_: str | None = None,
    scope: str | None = None,
    where: str | None = None,
) -> list[dict[str, Any]]:
    """Search the LanceDB index by vector and/or frontmatter filters.

    When ``query`` is None the search is filter-only (returns every matching
    row, unscored). When ``query`` is set it is a vector search optionally
    narrowed by the same filters via a prefiltered ``.where`` predicate.

    Returns a list of result dicts: id, title, file_path, score (None when
    filter-only), snippet, knowledge_type, tags (list).
    """
    db = lancedb.connect(str(db_path))
    if table_name not in db.table_names():
        return []
    table = db.open_table(table_name)
    if table.count_rows() == 0:
        return []

    predicate = _build_filter_predicate(knowledge_type, tags, type_, scope, where)

    if query is None:
        builder = table.search().limit(limit)
        if predicate:
            builder = builder.where(predicate, prefilter=True)
        df = builder.to_pandas()
        return [_row_to_result(row, scored=False) for _, row in df.iterrows()]

    query_embedding = get_model().encode([query])[0].tolist()
    builder = table.search(query_embedding).metric("cosine").limit(limit)
    if predicate:
        builder = builder.where(predicate, prefilter=True)
    df = builder.to_pandas()
    if df.empty:
        return []
    return [_row_to_result(row, scored=True) for _, row in df.iterrows()]
```
  Note: the old `search_index` returned `tags` as a string; callers that read it (search.py text render, dedup) tolerate the list (dedup uses only `title`/`score`/`file_path`/`snippet`). For filter-only, default `limit` is set by the CLI (Task 2.3) to a large unbounded value.
- [ ] Run it, expect pass: `uv run pytest tests/test_search.py -k SearchIndexFilters -q`.
- [ ] Run dedup tests to confirm no regression (they read `r["score"]`, now possibly None only on filter-only — dedup always passes a query so `scored=True`): `uv run pytest tests/test_compile.py -k Dedup -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/core/embeddings.py llm-wiki-core/tests/test_search.py && git commit -m "feat: search_index frontmatter filters + filter-only path"`

## Task 2.3 — `search.py` optional query + filter flags

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/search.py` (whole `search` command lines 17-63)
- Modify test `llm-wiki-core/tests/test_search.py`

**Interfaces:**
- Consumes: `search_index(...)` (Task 2.2).
- Produces: CLI `kb search [QUERY] [--knowledge-type T] [--tag X ...] [--type T] [--scope S] [--where SQL] [--limit N] [--json]`. `query` is `typer.Argument(None)`. Filter-only (`query` None) default limit is large (10000) so a pure filter enumerates all matches.

- [ ] Write failing test in `tests/test_search.py` (`TestSearchErrors` no longer requires a query when a filter is given; add a filter-CLI class):
```python
class TestSearchFilterCLI:
    def test_filter_only_enumerates_all(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--knowledge-type", "pattern", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert all(r["knowledge_type"] == "pattern" for r in data)

    def test_repeated_tag_flag_anded(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(
            app, ["search", "--tag", "security", "--tag", "authentication", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 1

    def test_no_query_no_filter_errors(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search"])
        assert result.exit_code != 0
```
  Also UPDATE the existing `TestSearchErrors.test_no_query_fails` (lines 130-133): it previously expected a missing positional to fail; now `query` is optional, so a bare `kb search` must fail because no filter was given either — keep the `assert result.exit_code != 0` but it now flows through our explicit "specify a query or a filter" guard. (Same assertion holds; no edit needed if it still exits non-zero — verify.)
- [ ] Run it, expect fail: `uv run pytest tests/test_search.py -k SearchFilterCLI -q` → unknown option `--knowledge-type`.
- [ ] Minimal impl — rewrite `search.py`:
```python
"""Semantic and/or frontmatter-filtered search across the wiki knowledge base."""

from __future__ import annotations

import json

import typer

from llm_wiki.core.config import load_config
from llm_wiki.core.embeddings import search_index


_FILTER_ONLY_LIMIT = 10000


def search(  # noqa: PLR0913  # each filter is a discrete CLI dimension
    query: str | None = typer.Argument(None, help="Search query string (optional if a filter is given)."),
    knowledge_type: str | None = typer.Option(None, "--knowledge-type", help="Filter by knowledge_type."),
    tag: list[str] | None = typer.Option(  # noqa: B008  # Typer requires the call in the default
        None, "--tag", help="Filter by tag (repeatable; AND across tags, token-exact)."
    ),
    type_: str | None = typer.Option(None, "--type", help="Filter by frontmatter type."),
    scope: str | None = typer.Option(None, "--scope", help="Filter by scope."),
    where: str | None = typer.Option(None, "--where", help="Raw DataFusion predicate appended with AND."),
    limit: int | None = typer.Option(None, "--limit", "-l", help="Max results (default from config)."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output results as JSON."),
) -> None:
    """Search wiki notes by semantic similarity, frontmatter filters, or both."""
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    has_filter = bool(knowledge_type or tag or type_ or scope or where)
    if query is None and not has_filter:
        typer.echo("Error: provide a query and/or a filter (--knowledge-type/--tag/--type/--scope/--where).", err=True)
        raise typer.Exit(code=1)

    if limit is None:
        limit = _FILTER_ONLY_LIMIT if query is None else cfg.query_default_limit

    try:
        results = search_index(
            cfg.db_path,
            cfg.table_name,
            query,
            limit=limit,
            knowledge_type=knowledge_type,
            tags=tag,
            type_=type_,
            scope=scope,
            where=where,
        )
    except Exception as e:  # surface any backend error to the user, then exit
        typer.echo(f"Search failed: {e}", err=True)
        raise typer.Exit(code=1) from e

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return
    if not results:
        typer.echo("No results found.")
        return
    label = query if query is not None else "(filter-only)"
    typer.echo(f"\nSearch results for: '{label}'\n")
    for i, r in enumerate(results, 1):
        score = f" (score: {r['score']:.4f})" if r["score"] is not None else ""
        typer.echo(f"  [{i}] {r['title']}{score}")
        typer.echo(f"      type: {r['knowledge_type']} | tags: {', '.join(r['tags'])} | file: {r['file_path']}")
        typer.echo(f"      {r['snippet'][:120]}...")
        typer.echo("")
```
- [ ] Run it, expect pass: `uv run pytest tests/test_search.py -q` (existing query-only tests still pass — backward compat; new filter tests pass).
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/search.py llm-wiki-core/tests/test_search.py && git commit -m "feat: kb search optional query + frontmatter filter flags"`

## Task 2.4 — Update `kb-query` skill/command for filters

**Files:**
- Modify `commands/kb-query.md` (Step 2 + a new filter section)

**Interfaces:**
- Documentation only; no code/tests.

- [ ] Edit `commands/kb-query.md` Step 1 to parse `--knowledge-type`, repeatable `--tag`, `--type`, `--scope`, `--where`. Edit Step 2 to show both forms:
```bash
# Semantic + filter (ranked discovery):
kb search "debug agent loop" --tag tool-cli --json

# Filter-only handout (every match, no query):
kb search --knowledge-type tool --tag phase-testing --json
```
  Add a note: filter-only returns ALL matches (no `--limit` cap) — use it for exhaustive handouts (e.g. "every tool tagged phase-testing"); semantic+filter for ranked discovery.
- [ ] Commit: `git add commands/kb-query.md && git commit -m "docs: kb-query skill documents frontmatter filter flags"`

## Stage 2 Quality Gate

- [ ] Code review — `ponytail-review` + `code-reviewer` agent on the Stage 2 diff; check the predicate builder for injection surface (only `--where` is raw; document it).
- [ ] Code simplification — `simplify` skill / `code-simplifier`; apply.
- [ ] Refactor — fold in consolidation (e.g. a shared `_run_search_builder` if vector/filter-only branches duplicate `.where` wiring).
- [ ] Lint/type — `make lint` green (watch `search` for `max-args 7`: it has 8 params — split filters into a small dataclass/`@dataclass` `Filters` or apply a scoped `# noqa: PLR0913` consistent with the codebase's existing `# noqa: PLR0913` usage in `compile_cmd`).
- [ ] Test — `make test` (coverage >=70) green; includes knowledge_type, AND-tag, type/scope, filter-only completeness, semantic+filter, empty, query-only backward-compat.
- [ ] Debt — `ponytail-debt` clean.

---

# Stage 3 — Taxonomy + `tool` source-class

Add `tool` to knowledge types and a Tool tags section (10 `tool-*` + 10 `phase-*`) in both the template and the runtime taxonomy; add `tool` to the accepted `--source-class` values for `kb ingest`.

## Task 3.1 — Taxonomy file + template: `tool` type + Tool tags

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/templates/tag-taxonomy.md` (Knowledge Types table after line 21; new Tool tags section after Approved Tags)
- Modify `wiki/_meta/tag-taxonomy.md` (the live vault taxonomy — same edits)
- Modify `llm-wiki-core/tests/conftest.py` (`SAMPLE_TAXONOMY` lines 53-89)

**Interfaces:**
- Consumes: `core.taxonomy.load_taxonomy_safe` parses `## Knowledge Types` and `## Approved Tags` table rows (`| \`tag\` |`). The new Tool tags must live under a section heading parsed as approved tags. Since `_parse_taxonomy_content` only treats `## Approved Tags` rows as tags, add the tool/phase rows INTO the `## Approved Tags` table (so they validate) OR add a section whose name starts with "Approved Tags". Decision: append tool-* and phase-* rows to the existing `## Approved Tags` table; document them visually under a sub-heading comment. (taxonomy.py line 57 matches `section.startswith("Approved Tags")` — only one such section.)

- [ ] Write failing test in `tests/test_compile.py` (`TestWriteNote`) — a tool note with the new tags must NOT warn:
```python
    def test_tool_tags_accepted_by_taxonomy(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            self._write_note_args(
                **{"knowledge-type": "tool", "tags": "tool-cli,phase-testing", "title": "Some Tool"}
            ),
        )
        assert result.exit_code == 0
        assert "not in approved" not in result.stdout.lower()
        assert "not in approved list" not in result.stdout.lower()
```
- [ ] Run it, expect fail: `uv run pytest tests/test_compile.py -k tool_tags_accepted -q` → warns (tool-cli/phase-testing/`tool` not in `SAMPLE_TAXONOMY`).
- [ ] Minimal impl — edit `conftest.py` `SAMPLE_TAXONOMY`: add `| \`tool\` | Library/framework/service/CLI reference |` to the Knowledge Types table, and append to the Approved Tags table:
```
| `tool-framework` | Tool type: framework |
| `tool-library` | Tool type: library |
| `tool-cli` | Tool type: CLI |
| `tool-mcp-server` | Tool type: MCP server |
| `tool-agent` | Tool type: agent |
| `tool-skill` | Tool type: skill |
| `tool-plugin` | Tool type: plugin |
| `tool-sdk` | Tool type: SDK |
| `tool-service` | Tool type: service |
| `tool-dataset` | Tool type: dataset |
| `phase-planning` | SDLC phase: planning |
| `phase-design` | SDLC phase: design |
| `phase-implementation` | SDLC phase: implementation |
| `phase-code-review` | SDLC phase: code review |
| `phase-testing` | SDLC phase: testing |
| `phase-debugging` | SDLC phase: debugging |
| `phase-deployment` | SDLC phase: deployment |
| `phase-observability` | SDLC phase: observability |
| `phase-security` | SDLC phase: security |
| `phase-docs` | SDLC phase: docs |
```
  Then apply the SAME knowledge-type row + Tool tags rows to `templates/tag-taxonomy.md` (under a `### Tool Tags` sub-heading inside the existing `## Approved Tags` section so `load_taxonomy_safe` still counts them — a `###` does not start a new `##` section) and to the live `wiki/_meta/tag-taxonomy.md`. In `frontmatter.KNOWLEDGE_TYPES` (lines 19-27) add `"tool"` so validation/`get_knowledge_type` accept it.
- [ ] Run it, expect pass: `uv run pytest tests/test_compile.py -k tool_tags_accepted -q`.
- [ ] Run frontmatter tests to confirm `tool` knowledge type validates: `uv run pytest tests/test_frontmatter.py -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/templates/tag-taxonomy.md wiki/_meta/tag-taxonomy.md llm-wiki-core/tests/conftest.py llm-wiki-core/src/llm_wiki/core/frontmatter.py && git commit -m "feat: taxonomy adds tool knowledge type + tool/phase tags"`

## Task 3.2 — `tool` accepted as `--source-class`

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/core/dedup.py` (`SOURCE_CLASS_THRESHOLDS` lines 26-31)
- Modify test `llm-wiki-core/tests/test_ingest.py` (`TestIngestSourceClass`)

**Interfaces:**
- Consumes: `ingest.py` validates `source_class.lower() in SOURCE_CLASS_THRESHOLDS` (lines 490-495).
- Produces: `SOURCE_CLASS_THRESHOLDS["tool"] = 0.93` (tool pages/READMEs are dense, doc-like → reuse the doc threshold).

- [ ] Write failing test in `tests/test_ingest.py` (`TestIngestSourceClass`):
```python
    def test_tool_source_class_persisted_on_manifest(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "readme.md", "# Tool\n\nbody")
        result = runner.invoke(
            app, ["ingest", "--mode", "file", "--source", str(src), "--source-class", "tool"]
        )
        assert result.exit_code == 0, result.output
        manifest = _read_manifest(wiki_root)
        assert manifest[-1]["source_class"] == "tool"
```
- [ ] Run it, expect fail: `uv run pytest tests/test_ingest.py -k tool_source_class -q` → exit != 0 (`tool` not in `{book,chat,doc,paper}`).
- [ ] Minimal impl — edit `dedup.py` `SOURCE_CLASS_THRESHOLDS`: add `"tool": 0.93,`.
- [ ] Run it, expect pass: `uv run pytest tests/test_ingest.py -k tool_source_class -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/core/dedup.py llm-wiki-core/tests/test_ingest.py && git commit -m "feat: accept tool as a source-class (0.93 dedup threshold)"`

## Stage 3 Quality Gate

- [ ] Code review — `ponytail-review` + `code-reviewer` agent on the Stage 3 diff; confirm template and live taxonomy match.
- [ ] Code simplification — `simplify` skill / `code-simplifier`; apply.
- [ ] Refactor — fold in consolidation surfaced.
- [ ] Lint/type — `make lint` green.
- [ ] Test — `make test` (coverage >=70) green: lint accepts `knowledge_type: tool` + new tags; ingest records `source_class=tool`.
- [ ] Debt — `ponytail-debt` clean.

---

# Stage 4 — Tool ingest (4a one extractor, 4b URL router + workflow)

## Task 4.1 (4a) — Add trafilatura dep + single HTML extractor (`core/html_extract.py`)

**Files:**
- Modify `llm-wiki-core/pyproject.toml` (dependencies lines 6-14; mypy overrides line 81)
- Create `llm-wiki-core/src/llm_wiki/core/html_extract.py`
- Create test `llm-wiki-core/tests/test_html_extract.py`

**Interfaces:**
- Produces: `extract_main_content(html: str, url: str | None = None) -> ExtractedDoc` where `ExtractedDoc` is a frozen dataclass `(text: str, title: str | None, description: str | None)`. Uses `trafilatura.extract(html, output_format="markdown", include_links=True, url=url)` and `trafilatura.extract_metadata(html)` for title/description. Empty extraction → `text == ""`.

- [ ] Write failing test `tests/test_html_extract.py` (mock trafilatura so no network and deterministic):
```python
"""Tests for the single trafilatura-backed HTML extractor."""

from __future__ import annotations

from llm_wiki.core import html_extract


class TestExtractMainContent:
    def test_returns_markdown_and_metadata(self, monkeypatch):
        monkeypatch.setattr(html_extract.trafilatura, "extract", lambda *a, **k: "# Deepeval\n\nLLM eval framework.")

        class _Meta:
            title = "Deepeval"
            description = "The LLM evaluation framework"

        monkeypatch.setattr(html_extract.trafilatura, "extract_metadata", lambda _html: _Meta())
        doc = html_extract.extract_main_content("<html>...</html>", url="https://deepeval.com")
        assert doc.text.startswith("# Deepeval")
        assert doc.title == "Deepeval"
        assert doc.description == "The LLM evaluation framework"

    def test_empty_extraction_yields_empty_text(self, monkeypatch):
        monkeypatch.setattr(html_extract.trafilatura, "extract", lambda *a, **k: None)
        monkeypatch.setattr(html_extract.trafilatura, "extract_metadata", lambda _html: None)
        doc = html_extract.extract_main_content("<html></html>", url="https://x.test")
        assert doc.text == ""
        assert doc.title is None
```
- [ ] Run it, expect fail: `uv run pytest tests/test_html_extract.py -q` → `ModuleNotFoundError: No module named 'llm_wiki.core.html_extract'` (and trafilatura not yet installed).
- [ ] Minimal impl — edit `pyproject.toml`: add `"trafilatura>=1.12",` to `dependencies`; add `trafilatura.*` to the mypy `ignore_missing_imports` override module list (line 81). Run `uv sync` to install. Create `core/html_extract.py`:
```python
"""Single HTML main-content extractor (trafilatura).

The one HTML→text path for the toolkit: both ``kb ingest --mode url`` and the
tool ingester (generic-URL branch) call this. Replaces the minimal stdlib
``HTMLParser`` that produced junk on marketing/landing pages.
"""

from __future__ import annotations

from dataclasses import dataclass

import trafilatura


@dataclass(frozen=True)
class ExtractedDoc:
    """The result of extracting a web page's main content."""

    text: str
    title: str | None
    description: str | None


def extract_main_content(html: str, url: str | None = None) -> ExtractedDoc:
    """Extract boilerplate-stripped markdown plus title/description.

    Args:
        html: Raw HTML document text.
        url: Source URL (improves trafilatura's extraction heuristics).

    Returns:
        An ExtractedDoc; ``text`` is "" when nothing could be extracted.
    """
    text = trafilatura.extract(html, output_format="markdown", include_links=True, url=url) or ""
    meta = trafilatura.extract_metadata(html)
    title = getattr(meta, "title", None) if meta is not None else None
    description = getattr(meta, "description", None) if meta is not None else None
    return ExtractedDoc(text=text, title=title, description=description)
```
- [ ] Run it, expect pass: `uv run pytest tests/test_html_extract.py -q`.
- [ ] Commit: `git add llm-wiki-core/pyproject.toml llm-wiki-core/src/llm_wiki/core/html_extract.py llm-wiki-core/tests/test_html_extract.py llm-wiki-core/uv.lock && git commit -m "feat: trafilatura HTML extractor (core/html_extract) + dep"`

## Task 4.2 (4a) — `ingest.py` url-mode uses the single extractor; remove HTMLParser

**Files:**
- Modify `llm-wiki-core/src/llm_wiki/commands/ingest.py` (imports line 16; `_HTMLTextExtractor`/`_html_to_text` lines 61-78; `_ingest_url` text extraction line 278; empty-extraction guard)
- Modify test `llm-wiki-core/tests/test_ingest.py`

**Interfaces:**
- Consumes: `core.html_extract.extract_main_content(html, url) -> ExtractedDoc` (Task 4.1).
- Produces: `_ingest_url` writes the extracted markdown; raises `RuntimeError` on empty extraction (per spec error handling).

- [ ] Write failing test in `tests/test_ingest.py` (new class — mock `urlopen` + the extractor so no network):
```python
class TestIngestUrlTrafilatura:
    def test_url_mode_uses_extractor(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        import io

        from llm_wiki.commands import ingest as ingest_mod
        from llm_wiki.core.html_extract import ExtractedDoc

        monkeypatch.setattr(
            ingest_mod, "urlopen", lambda *a, **k: io.BytesIO(b"<html><body>raw</body></html>")
        )
        monkeypatch.setattr(
            ingest_mod,
            "extract_main_content",
            lambda _html, url=None: ExtractedDoc(text="# Extracted\n\nClean body.", title="T", description="D"),
        )
        result = runner.invoke(app, ["ingest", "--mode", "url", "--source", "https://example.test/page"])
        assert result.exit_code == 0, result.output
        web = wiki_root / "raw" / "web"
        md = next(web.glob("*.md")).read_text()
        assert "Clean body." in md

    def test_url_empty_extraction_errors(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        import io

        from llm_wiki.commands import ingest as ingest_mod
        from llm_wiki.core.html_extract import ExtractedDoc

        monkeypatch.setattr(ingest_mod, "urlopen", lambda *a, **k: io.BytesIO(b"<html></html>"))
        monkeypatch.setattr(
            ingest_mod, "extract_main_content", lambda _html, url=None: ExtractedDoc(text="", title=None, description=None)
        )
        result = runner.invoke(app, ["ingest", "--mode", "url", "--source", "https://example.test/empty"])
        assert result.exit_code != 0
        assert "no content" in result.output.lower() or "empty" in result.output.lower()
```
  Note: `urlopen` is used as a context manager (`with urlopen(...) as resp: resp.read()`). `io.BytesIO` supports the context-manager protocol and `.read()`, so the mock works.
- [ ] Run it, expect fail: `uv run pytest tests/test_ingest.py -k Trafilatura -q` → `AttributeError: module ... has no attribute 'extract_main_content'`.
- [ ] Minimal impl — edit `ingest.py`: remove `from html.parser import HTMLParser` (line 16), delete `_HTMLTextExtractor` (lines 61-73) and `_html_to_text` (lines 75-78); add `from llm_wiki.core.html_extract import extract_main_content`. In `_ingest_url` replace `text = _html_to_text(raw_html)` (line 278) with:
```python
    doc = extract_main_content(raw_html, url=source)
    if not doc.text.strip():
        msg = f"No content could be extracted from {source} (empty/boilerplate-only page)."
        raise RuntimeError(msg)
    text = doc.text
```
- [ ] Run it, expect pass: `uv run pytest tests/test_ingest.py -q` (existing url tests, if any, still pass; new ones pass).
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/ingest.py llm-wiki-core/tests/test_ingest.py && git commit -m "refactor: url-mode ingest uses single trafilatura extractor"`

## Task 4.3 (4b) — GitHub detection + README API (`core/github.py`)

**Files:**
- Create `llm-wiki-core/src/llm_wiki/core/github.py`
- Create test `llm-wiki-core/tests/test_github.py`

**Interfaces:**
- Produces:
  - `parse_github_repo(url_or_ref: str) -> tuple[str, str] | None` — returns `(owner, repo)` for `github.com/<owner>/<repo>[/...]` URLs or bare `owner/repo` refs; None otherwise.
  - `readme_api_url(owner: str, repo: str) -> str` → `https://api.github.com/repos/<owner>/<repo>/readme`.
  - `repo_api_url(owner: str, repo: str) -> str` → `https://api.github.com/repos/<owner>/<repo>`.
  - `github_token() -> str | None` — `$GITHUB_TOKEN` else `gh auth token` (read at call time; never persisted).
  - `fetch_github(owner, repo, token, *, fetch=...) -> GitHubTool` (dataclass: `readme_markdown: str`, `description: str | None`, `topics: list[str]`, `language: str | None`, `homepage: str | None`, `stargazers_count: int`). README fetched with `Accept: application/vnd.github.raw`; metadata from the repo JSON. `fetch` is injectable for tests.

- [ ] Write failing test `tests/test_github.py`:
```python
"""Tests for GitHub repo detection + README/metadata API construction."""

from __future__ import annotations

from llm_wiki.core import github


class TestParseGithubRepo:
    def test_full_url(self):
        assert github.parse_github_repo("https://github.com/openai/whisper") == ("openai", "whisper")

    def test_url_with_trailing_path(self):
        assert github.parse_github_repo("https://github.com/openai/whisper/tree/main") == ("openai", "whisper")

    def test_bare_ref(self):
        assert github.parse_github_repo("openai/whisper") == ("openai", "whisper")

    def test_non_github_url_returns_none(self):
        assert github.parse_github_repo("https://deepeval.com") is None

    def test_strips_dot_git(self):
        assert github.parse_github_repo("https://github.com/a/b.git") == ("a", "b")


class TestApiUrls:
    def test_readme_url(self):
        assert github.readme_api_url("a", "b") == "https://api.github.com/repos/a/b/readme"

    def test_repo_url(self):
        assert github.repo_api_url("a", "b") == "https://api.github.com/repos/a/b"


class TestFetchGithub:
    def test_assembles_tool_from_injected_fetch(self):
        def _fake_fetch(url, headers):
            if url.endswith("/readme"):
                assert headers["Accept"] == "application/vnd.github.raw"
                return b"# Whisper\n\nASR model."
            import json

            return json.dumps(
                {
                    "description": "Robust ASR",
                    "topics": ["asr", "speech"],
                    "language": "Python",
                    "homepage": "https://openai.com",
                    "stargazers_count": 1234,
                }
            ).encode()

        tool = github.fetch_github("openai", "whisper", token=None, fetch=_fake_fetch)
        assert tool.readme_markdown.startswith("# Whisper")
        assert tool.description == "Robust ASR"
        assert tool.topics == ["asr", "speech"]
        assert tool.language == "Python"
        assert tool.stargazers_count == 1234
```
- [ ] Run it, expect fail: `uv run pytest tests/test_github.py -q` → `ModuleNotFoundError: No module named 'llm_wiki.core.github'`.
- [ ] Minimal impl — create `core/github.py`:
```python
"""GitHub repo detection + README/metadata fetch (stdlib urllib)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen


_GITHUB_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/?#]+)", re.IGNORECASE)
_BARE_REF_RE = re.compile(r"^([\w.-]+)/([\w.-]+)$")
_GH_TOKEN_TIMEOUT_SEC = 5

Fetch = Callable[[str, dict[str, str]], bytes]


@dataclass(frozen=True)
class GitHubTool:
    """README + metadata for a GitHub repo."""

    readme_markdown: str
    description: str | None
    topics: list[str]
    language: str | None
    homepage: str | None
    stargazers_count: int


def parse_github_repo(url_or_ref: str) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` for a GitHub URL or bare ``owner/repo`` ref, else None."""
    ref = url_or_ref.strip()
    m = _GITHUB_URL_RE.match(ref) or _BARE_REF_RE.match(ref)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    return owner, repo[:-4] if repo.endswith(".git") else repo


def readme_api_url(owner: str, repo: str) -> str:
    """Return the README API URL for a repo."""
    return f"https://api.github.com/repos/{owner}/{repo}/readme"


def repo_api_url(owner: str, repo: str) -> str:
    """Return the repo-metadata API URL."""
    return f"https://api.github.com/repos/{owner}/{repo}"


def github_token() -> str | None:
    """Read a GitHub token from $GITHUB_TOKEN, falling back to ``gh auth token``.

    Read at call time and never persisted.
    """
    import os  # noqa: PLC0415  # local import keeps the module import side-effect-free

    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env
    if shutil.which("gh") is None:
        return None
    try:
        out = subprocess.run(
            ["gh", "auth", "token"],  # noqa: S607  # resolved via PATH
            capture_output=True,
            text=True,
            timeout=_GH_TOKEN_TIMEOUT_SEC,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    token = out.stdout.strip()
    return token or None


def _default_fetch(url: str, headers: dict[str, str]) -> bytes:
    req = Request(url, headers=headers)  # noqa: S310  # api.github.com https only
    with urlopen(req, timeout=30) as resp:  # noqa: S310
        return bytes(resp.read())


def fetch_github(owner: str, repo: str, token: str | None, *, fetch: Fetch = _default_fetch) -> GitHubTool:
    """Fetch README (raw) + repo metadata. ``fetch`` is injectable for tests."""
    base = {"User-Agent": "kb-ingest-tool/1.0"}
    if token:
        base["Authorization"] = f"Bearer {token}"
    readme = fetch(readme_api_url(owner, repo), {**base, "Accept": "application/vnd.github.raw"}).decode(
        "utf-8", errors="replace"
    )
    meta = json.loads(fetch(repo_api_url(owner, repo), {**base, "Accept": "application/vnd.github+json"}).decode())
    return GitHubTool(
        readme_markdown=readme,
        description=meta.get("description"),
        topics=list(meta.get("topics", [])),
        language=meta.get("language"),
        homepage=meta.get("homepage"),
        stargazers_count=int(meta.get("stargazers_count", 0)),
    )
```
- [ ] Run it, expect pass: `uv run pytest tests/test_github.py -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/core/github.py llm-wiki-core/tests/test_github.py && git commit -m "feat: GitHub repo detection + README/metadata fetch (core/github)"`

## Task 4.4 (4b) — `kb ingest-tool` URL router (`commands/ingest_tool.py` + cli registration)

**Files:**
- Create `llm-wiki-core/src/llm_wiki/commands/ingest_tool.py`
- Modify `llm-wiki-core/src/llm_wiki/cli.py` (imports line 19; registration after line 39)
- Create test `llm-wiki-core/tests/test_ingest_tool.py`

**Interfaces:**
- Consumes: `core.github.parse_github_repo`/`fetch_github`/`github_token` (Task 4.3); `core.html_extract.extract_main_content` (Task 4.1); reuses `commands.ingest._ingest_text(source, cfg, source_class)` (ingest.py lines 318-357) as the sidecar writer; `core.config.load_config`.
- Produces:
  - `build_tool_meta_block(url: str, *, lang_or_host: str, stars: int | None, topics_or_keywords: list[str], description: str | None) -> str` — the `<!-- tool: <url> | lang/host | ⭐stars | topics -->` comment + description prepended to the body.
  - `_ingest_tool(url: str, cfg, *, github_fetch=..., html_fetch=...) -> dict[str, Any]` — routes (GitHub vs generic), prepends the meta block, calls `_ingest_text` with the assembled body and `source_class="tool"`, then overwrites the sidecar `source` to the URL (so compile preserves it; `_ingest_text` defaults `source` to `"inline-text"`).
  - CLI `ingest_tool(url: str = typer.Argument(...), json_output=...)`.

- [ ] Write failing test `tests/test_ingest_tool.py`:
```python
"""Tests for ``kb ingest-tool`` — URL router into the tool ingest contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from llm_wiki.commands import ingest_tool as it
from llm_wiki.core.github import GitHubTool
from llm_wiki.core.html_extract import ExtractedDoc


if TYPE_CHECKING:
    from pathlib import Path


def _cfg(wiki_root: Path):
    import os

    os.chdir(wiki_root)
    from llm_wiki.core.config import load_config

    return load_config()


class TestToolMetaBlock:
    def test_block_has_url_and_meta(self):
        block = it.build_tool_meta_block(
            "https://github.com/openai/whisper",
            lang_or_host="Python",
            stars=1234,
            topics_or_keywords=["asr", "speech"],
            description="Robust ASR",
        )
        assert "tool: https://github.com/openai/whisper" in block
        assert "Python" in block
        assert "1234" in block
        assert "asr" in block
        assert "Robust ASR" in block


class TestIngestToolRouting:
    def test_github_url_uses_readme(self, wiki_root: Path, monkeypatch):
        cfg = _cfg(wiki_root)
        tool = GitHubTool(
            readme_markdown="# Whisper\n\nASR.",
            description="Robust ASR",
            topics=["asr"],
            language="Python",
            homepage="https://openai.com",
            stargazers_count=1234,
        )
        result = it._ingest_tool(
            "https://github.com/openai/whisper",
            cfg,
            github_fetch=lambda owner, repo, token: tool,
            html_fetch=lambda url: ExtractedDoc("should-not-be-used", None, None),
        )
        body = (wiki_root / result["dest"]).read_text() if result["dest"].startswith("/") else (
            cfg.project_root / result["dest"]
        ).read_text()
        assert "Whisper" in body
        assert "tool: https://github.com/openai/whisper" in body
        manifest = json.loads((wiki_root / "raw" / "inbox" / ".manifest.json").read_text())
        assert manifest[-1]["source_class"] == "tool"
        assert manifest[-1]["source"] == "https://github.com/openai/whisper"

    def test_generic_url_uses_trafilatura(self, wiki_root: Path, monkeypatch):
        cfg = _cfg(wiki_root)
        result = it._ingest_tool(
            "https://deepeval.com",
            cfg,
            github_fetch=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch github")),
            html_fetch=lambda url: ExtractedDoc("# Deepeval\n\nLLM eval.", "Deepeval", "The eval framework"),
        )
        body = (cfg.project_root / result["dest"]).read_text()
        assert "Deepeval" in body
        manifest = json.loads((wiki_root / "raw" / "inbox" / ".manifest.json").read_text())
        assert manifest[-1]["source"] == "https://deepeval.com"
```
  Note: `_ingest_text` writes into `cfg.raw_inbox` and the manifest `file`/`source` are relative to `cfg.project_root`; the test resolves `result["dest"]` against the project root.
- [ ] Run it, expect fail: `uv run pytest tests/test_ingest_tool.py -q` → `ModuleNotFoundError: No module named 'llm_wiki.commands.ingest_tool'`.
- [ ] Minimal impl — create `commands/ingest_tool.py`:
```python
"""Ingest a tool from any URL into the tool contract (source_class=tool).

GitHub repo URLs → README API + repo metadata; any other URL → trafilatura
main-content extraction + page metadata. Both prepend a tool-meta comment so
the compile classifier sees the signal inline, then reuse the existing
``kb ingest --mode text`` sidecar path.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.request import Request, urlopen

import typer

from llm_wiki.commands.ingest import _ingest_text
from llm_wiki.core.config import load_config
from llm_wiki.core.github import GitHubTool, fetch_github, github_token, parse_github_repo
from llm_wiki.core.html_extract import ExtractedDoc, extract_main_content


if TYPE_CHECKING:
    from collections.abc import Callable

    from llm_wiki.core.config import WikiConfig

    GithubFetch = Callable[[str, str, str | None], GitHubTool]
    HtmlFetch = Callable[[str], ExtractedDoc]


def build_tool_meta_block(
    url: str,
    *,
    lang_or_host: str,
    stars: int | None,
    topics_or_keywords: list[str],
    description: str | None,
) -> str:
    """Build the inline tool-meta comment + description prepended to the body."""
    star_part = f" | ⭐{stars}" if stars else ""
    topic_part = f" | {', '.join(topics_or_keywords)}" if topics_or_keywords else ""
    comment = f"<!-- tool: {url} | {lang_or_host}{star_part}{topic_part} -->"
    desc = f"\n\n> {description}" if description else ""
    return f"{comment}{desc}\n\n"


def _default_html_fetch(url: str) -> ExtractedDoc:
    req = Request(url, headers={"User-Agent": "kb-ingest-tool/1.0"})  # noqa: S310  # http(s) only
    with urlopen(req, timeout=30) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")
    return extract_main_content(raw, url=url)


def _default_github_fetch(owner: str, repo: str, token: str | None) -> GitHubTool:
    return fetch_github(owner, repo, token)


def _set_source(cfg: WikiConfig, result: dict[str, Any], url: str) -> None:
    """Rewrite the just-written sidecar + manifest entry so ``source`` is the URL."""
    dest = cfg.project_root / result["dest"]
    meta_path = dest.parent / (dest.name + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["source"] = url
    meta["type"] = "tool"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    mp = cfg.raw_inbox / ".manifest.json"
    entries = json.loads(mp.read_text(encoding="utf-8"))
    entries[-1]["source"] = url
    entries[-1]["type"] = "tool"
    mp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def _ingest_tool(
    url: str,
    cfg: WikiConfig,
    *,
    github_fetch: GithubFetch = _default_github_fetch,
    html_fetch: HtmlFetch = _default_html_fetch,
) -> dict[str, Any]:
    """Route a URL to GitHub or generic extraction and ingest it as a tool."""
    repo = parse_github_repo(url)
    if repo is not None:
        owner, name = repo
        tool = github_fetch(owner, name, github_token())
        block = build_tool_meta_block(
            url,
            lang_or_host=tool.language or "github",
            stars=tool.stargazers_count,
            topics_or_keywords=tool.topics,
            description=tool.description,
        )
        body = block + tool.readme_markdown
    else:
        doc = html_fetch(url)
        if not doc.text.strip():
            msg = f"No content could be extracted from {url}."
            raise RuntimeError(msg)
        from urllib.parse import urlparse  # noqa: PLC0415

        block = build_tool_meta_block(
            url,
            lang_or_host=urlparse(url).netloc,
            stars=None,
            topics_or_keywords=[],
            description=doc.description or doc.title,
        )
        body = block + doc.text

    result = _ingest_text(body, cfg, source_class="tool")
    _set_source(cfg, result, url)
    return result


def ingest_tool(
    url: str = typer.Argument(..., help="Tool URL or owner/repo ref."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON."),
) -> None:
    """Ingest a tool from any URL into the inbox (source_class=tool)."""
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e
    try:
        result = _ingest_tool(url, cfg)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e
    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        typer.echo(f"Ingested tool: {result['dest']} (source_class=tool)")
        typer.echo(f"  Manifest ID: {result['manifest_id']}")
        typer.echo("\nRun /compile-tool (or kb compile) to turn it into a tool note.")
```
  Then register in `cli.py`: add `from llm_wiki.commands.ingest_tool import ingest_tool` (line 19 area) and `app.command("ingest-tool")(ingest_tool)` (after line 39).
- [ ] Run it, expect pass: `uv run pytest tests/test_ingest_tool.py -q`.
- [ ] Commit: `git add llm-wiki-core/src/llm_wiki/commands/ingest_tool.py llm-wiki-core/src/llm_wiki/cli.py llm-wiki-core/tests/test_ingest_tool.py && git commit -m "feat: kb ingest-tool URL router (GitHub README API + trafilatura)"`

## Task 4.5 (4b) — `commands/kb-ingest-tool.md` slash command + `workflows/ingest-tools.js`

**Files:**
- Create `commands/kb-ingest-tool.md`
- Create `workflows/ingest-tools.js`

**Interfaces:**
- Documentation/workflow only. The workflow mirrors `ingest-notion-cited-sources.js`: pure-literal `meta`, args-normalization, serial `kb ingest-tool` per URL.

- [ ] Create `commands/kb-ingest-tool.md` (mirror `kb-ingest.md` frontmatter style):
```markdown
---
description: Ingest a tool (library/framework/service/repo) from any URL into the knowledge base
---

# /kb-ingest-tool -- Tool Ingestion (URL-agnostic)

You ingest a *tool* from any URL into the inbox so it can be compiled into one
`knowledge_type: tool` note.

## Step 1: Parse arguments

Input: `$ARGUMENTS`. Each item is a tool URL or a bare `owner/repo` GitHub ref.

## Step 2: Ingest each tool (SERIALLY)

The inbox manifest is non-atomic — never run two `kb ingest-tool` at once.

```bash
kb ingest-tool "https://github.com/owner/repo"
kb ingest-tool "https://deepeval.com"
```

GitHub URLs use the README API (richest signal); any other URL uses trafilatura
main-content extraction. `source:` is set to the URL and `source_class` to `tool`.

## Step 3: Report

For each: manifest id + destination. Suggest `/compile-tool` next.

## Notes

- For private/rate-limited GitHub repos, set `$GITHUB_TOKEN` (or `gh auth login`) — read at call time, never stored.
- For batch (many URLs), use the `ingest-tools` workflow (serial).
```
- [ ] Create `workflows/ingest-tools.js` (pure-literal meta; serial ingest; mirror the notion workflow):
```javascript
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
```
- [ ] Commit: `git add commands/kb-ingest-tool.md workflows/ingest-tools.js && git commit -m "feat: /kb-ingest-tool command + ingest-tools serial workflow"`

## Task 4.6 (4b) — Integration smoke (2 real tools)

**Files:** none committed (manual smoke).

**Interfaces:** end-to-end exercise of Tasks 4.1-4.5 on a real network.

- [ ] Smoke a GitHub framework: `kb ingest-tool "https://github.com/explodinggradients/ragas"` → confirm a `raw/inbox/*.md` with the tool-meta comment + README, sidecar `source` = the URL, manifest `source_class=tool`.
- [ ] Smoke a SaaS landing page: `kb ingest-tool "https://deepeval.com"` → confirm trafilatura body (not junk), sidecar `source` = the URL.
- [ ] If either page is SPA/empty: confirm a clean skip/error (per spec error handling), not a crash.

## Stage 4 Quality Gate

- [ ] Code review — `ponytail-review` + `code-reviewer` agent on the Stage 4 diff; check the GitHub token handling (never persisted) and SSRF surface (schemes restricted to http/https as in existing `_ingest_url`).
- [ ] Code simplification — `simplify` skill / `code-simplifier`; apply.
- [ ] Refactor — fold in consolidation (e.g. the http(s) fetch helper shared by `ingest._ingest_url` and `ingest_tool._default_html_fetch`).
- [ ] Lint/type — `make lint` green (mypy strict: trafilatura/`gh`/urllib overrides; `Callable` typed fetch injections).
- [ ] Test — `make test` (coverage >=70) green: trafilatura extraction, metadata, existing url ingestion still works, GitHub README-API construction, generic-URL trafilatura path, tool-meta block, source=URL.
- [ ] Debt — `ponytail-debt` clean: one HTML extractor only (no `HTMLParser`), one fetch helper.

---

# Stage 5 — Compile tool-mode (`skills/compile-tool.md`)

When `source_class: tool`, produce ONE note: `knowledge_type: tool`, exactly one `tool-*` + 1-2 `phase-*` + ≤2 topic (≤6 total); structured body (What it is · What it's for · Install · Key capabilities · Link); `source:` = URL; dedup by `source:` (same URL → update in place). Writes via `kb compile --write-note` (which now routes through `frontmatter.dump` + `taxonomy.validate_tags`, from Stage 0).

## Task 5.1 — `skills/compile-tool.md` + pointer from `compile-note`

**Files:**
- Create `skills/compile-tool.md`
- Modify `skills/compile-note.md` (add the pointer)

**Interfaces:**
- Consumes: `kb compile --list-inbox --json` (entries with `source_class`/`type: tool`); `kb compile --write-note --knowledge-type tool ...`; `kb search --where "source = '<url>'" --json` for dedup-by-source.
- Documentation only.

- [ ] Create `skills/compile-tool.md`:
```markdown
---
name: compile-tool
description: Compile a tool-ingested inbox item (source_class=tool) into exactly one knowledge_type=tool permanent note, classified by one tool-* tag, 1-2 phase-* tags, and up to 2 topic tags, with source preserved as the original URL.
---

# Compile Tool

Turns a tool-ingested raw item (one URL = one tool) into ONE permanent
`knowledge_type: tool` note. Used by `/kb-compile` when an inbox entry has
`source_class: tool` (or `type: tool`).

## When this applies

Only for inbox entries whose manifest `source_class` is `tool`. For every other
entry, use `compile-note` (atomic-idea extraction). One tool URL → exactly ONE note.

## Step 1: Read the raw item

The raw file starts with a `<!-- tool: <url> | lang/host | ⭐stars | topics -->`
comment and a one-line description, followed by the README (GitHub) or extracted
page markdown. The `<url>` in that comment is the canonical `source:`.

## Step 2: Dedup by source URL

```bash
kb search --where "source = '<url>'" --json
```

If a note already has this `source`, UPDATE it in place (re-classify/refresh body)
rather than creating a duplicate. Otherwise proceed.

## Step 3: Classify (controlled tags, ≤6 total)

- **Exactly one** tool-type: `tool-framework`, `tool-library`, `tool-cli`, `tool-mcp-server`, `tool-agent`, `tool-skill`, `tool-plugin`, `tool-sdk`, `tool-service`, `tool-dataset`.
- **1-2** SDLC phase: `phase-planning`, `phase-design`, `phase-implementation`, `phase-code-review`, `phase-testing`, `phase-debugging`, `phase-deployment`, `phase-observability`, `phase-security`, `phase-docs`.
- **0-2** topic tags from the existing approved taxonomy (e.g. `llm`, `agent-patterns`, `testing`).

If classification is ambiguous, pick the most-specific defensible `tool-*` and note the uncertainty in the body.

## Step 4: Write the note (structured body)

Body sections: **What it is · What it's for · Install · Key capabilities · Link**.
Always preserve the canonical URL as `source`.

```bash
kb compile --write-note \
  --title "Deepeval -- LLM Evaluation Framework" \
  --knowledge-type tool \
  --tags "tool-framework,phase-testing,llm" \
  --confidence medium \
  --source "https://deepeval.com" \
  --body "$(cat /tmp/tool-body.md)"
```

`--source` MUST be the original URL (web-source preservation). `kb compile`
validates tags against the taxonomy and writes via the canonical frontmatter dumper.

## Step 5: Mark processed + refresh

```bash
kb compile --mark-processed "MANIFEST_ENTRY_ID"
kb index --incremental
```

After indexing, `kb search --knowledge-type tool --tag phase-testing --json` will
return this tool in the handout.
```
- [ ] Edit `skills/compile-note.md`: add a short pointer near the top (after the intro, before "Extracting Atomic Ideas"):
```markdown
> **Tool items:** If the inbox entry's `source_class` is `tool` (one URL = one tool),
> do NOT extract atomic ideas — use the `compile-tool` skill instead (one
> `knowledge_type: tool` note, classified by one `tool-*` + `phase-*` tags).
```
- [ ] Commit: `git add skills/compile-tool.md skills/compile-note.md && git commit -m "docs: compile-tool skill + pointer from compile-note"`

## Task 5.2 — Compile smoke (the 2 tools from Stage 4.6)

**Files:** none committed (manual smoke).

- [ ] Compile each smoked tool into one note via `kb compile --write-note --knowledge-type tool ...`. Confirm: exactly one `tool-*` tag, ≥1 `phase-*`, ≤6 tags, `source` = URL, `kb lint` clean (no rogue/invalid tags or knowledge type).
- [ ] `kb index --incremental`, then `kb search --knowledge-type tool --tag <phase> --json` returns the right subset; filter-only `kb search --knowledge-type tool --json` returns both (the handout).

## Stage 5 Quality Gate

- [ ] Code review — `ponytail-review` + `code-reviewer` agent on the Stage 5 diff (skills); confirm the dedup-by-source instruction and source-preservation are explicit.
- [ ] Code simplification — `simplify` skill / `code-simplifier`; apply.
- [ ] Refactor — fold in consolidation surfaced.
- [ ] Lint/type — `make lint` green (no code change, but run to confirm nothing drifted).
- [ ] Test — `make test` (coverage >=70) green.
- [ ] Debt — `ponytail-debt` clean.

---

# Stage 6 — Finalize (full gate + version bump + PR)

## Task 6.1 — Version bump 0.4.0 → 0.5.0 (all 3 places)

**Files:**
- Modify `.claude-plugin/plugin.json` (line 4 `"version": "0.4.0"`)
- Modify `llm-wiki-core/pyproject.toml` (line 3 `version = "0.4.0"`)
- Modify `llm-wiki-core/src/llm_wiki/__init__.py` (line 6 `__version__ = "0.4.0"`)

**Interfaces:** none (metadata).

- [ ] Edit `.claude-plugin/plugin.json`: `"version": "0.4.0"` → `"version": "0.5.0"`.
- [ ] Edit `llm-wiki-core/pyproject.toml`: `version = "0.4.0"` → `version = "0.5.0"` (this is the line 3 `[project]` version, distinct from the Stage 4.1 dependency edit).
- [ ] Edit `llm-wiki-core/src/llm_wiki/__init__.py`: `__version__ = "0.4.0"` → `__version__ = "0.5.0"`.
- [ ] Commit: `git add .claude-plugin/plugin.json llm-wiki-core/pyproject.toml llm-wiki-core/src/llm_wiki/__init__.py && git commit -m "chore: bump version to 0.5.0"`

## Task 6.2 — Full branch gate

**Files:** none committed (verification).

- [ ] `cd llm-wiki-core && make lint` — ruff + mypy strict + vulture all green across the branch.
- [ ] `make test` — full pytest run, coverage >=70 (repo gate).
- [ ] `ponytail-audit` on the whole branch — no new duplication/over-complexity; confirm: single `frontmatter.dump` writer, single `MAX_TAGS`, single `normalize_tags`, single `slugify`, single HTML extractor (trafilatura), `taxonomy.validate_tags` used in `_write_note`.
- [ ] Grep sanity: `grep -rn "_html_to_text\|_HTMLTextExtractor\|_MAX_TAGS\|_normalize_tags" llm-wiki-core/src` returns nothing (all consolidated away).

## Task 6.3 — Open the PR(s)

**Files:** none committed.

**Interfaces:** GitHub PR on `feat/tool-ingestion` against `main` of `cajias/second-brain-plugins`.

- [ ] Push the branch: `git push -u origin feat/tool-ingestion`.
- [ ] Open the PR with `gh pr create` (consider two PRs per spec: PR-A = Stages 0-2 + 4a [refactor+schema+filtered query+trafilatura swap — useful standalone], PR-B = Stages 3,4b,5 [ingest+compile tool-mode]). PR body summarizes the 6 stages, the schema migration (`kb index --full`), the new `trafilatura` dep, and the smoke results from 4.6/5.2.
- [ ] PR body ends with:
```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01SYXri1d9k3X2KcjgYac4Zy
```

## Stage 6 Quality Gate

- [ ] Code review — final `ponytail-review` + `code-reviewer` agent on the full branch diff; address findings.
- [ ] Code simplification — final `simplify` pass; apply.
- [ ] Refactor — fold in any final consolidation.
- [ ] Lint/type — `make lint` green (re-run after any gate fixes).
- [ ] Test — `make test` (coverage >=70) green.
- [ ] Debt — `ponytail-debt` clean on the whole branch.
