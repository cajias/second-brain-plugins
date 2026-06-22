# LLM Wiki → Notion Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror the markdown LLM wiki into a Notion "LLM Wiki" database, turning `[[wikilinks]]` into native Notion self-relations, via a deterministic `kb export-notion` manifest builder plus a two-pass Notion-MCP Workflow script invoked by a `/kb-push-notion` slash command.

**Architecture:** `kb export-notion` (new Python Typer subcommand) does one deterministic pass over `wiki/permanent/*.md`, reusing `commands/lint.py`'s link graph and `core/frontmatter.py`'s parser, emitting a JSON manifest (`notes[]` + `dangling[]`). `workflows/push-to-notion.js` (new Workflow script, modeled on `ingest-notion-cited-sources.js`) consumes that manifest and writes Notion in three passes via Notion MCP write tools: ensure-DB → upsert-pages-by-slug → wire-relations. `/kb-push-notion` chains the two. Markdown stays the single source of truth (one-way mirror).

**Tech Stack:** Python 3 + Typer + PyYAML (existing deps only); Node.js Workflow script (`export const meta` literal + injected `agent`/`phase`/`parallel` globals); Notion MCP write tools (`mcp__plugin_Notion_notion__notion-*`); pytest + `typer.testing.CliRunner` for the Python side.

## Global Constraints

- Run all commands from `plugins/karpathy-llm-wiki/llm-wiki-core`.
- `uv run pytest -v` must pass; coverage must stay ≥70%.
- `uv run pre-commit run --all-files` must pass (ruff format + ruff check + mypy strict + vulture).
- Line length 120; Google-style docstrings.
- Tests may ignore `S101` / `ANN` / `D10*` / `PLR2004` (already configured in pyproject for `tests/`).
- Do NOT edit `uv.lock` directly — run `uv sync` if dependencies change (they will not for this plan).
- No new Python dependency (Notion I/O is MCP-only, JS side).
- Commit messages use conventional-commit types: `feat` / `fix` / `docs` / etc.

---

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/commands/export_notion.py` | Create | `export_notion` Typer command + `_build_manifest(cfg)` helper that maps frontmatter + link graph to the manifest dict. |
| `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/cli.py` | Modify (import block ~L16-23; registration block ~L38-45) | Import `export_notion`; register `app.command("export-notion")(export_notion)`. |
| `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py` | Create | Unit tests for `_build_manifest` and the `export-notion` CLI command using the `wiki_root` / `populated_wiki` fixtures. |
| `plugins/karpathy-llm-wiki/workflows/push-to-notion.js` | Create | Workflow script: read manifest, ensure "LLM Wiki" DB, upsert pages by `slug`, wire `Links` relation; `dryRun` reports counts. |
| `plugins/karpathy-llm-wiki/commands/kb-push-notion.md` | Create | Slash command: run `kb export-notion --out <manifest>` then invoke `push-to-notion.js` with the manifest. |

---

## Task 1 — `_build_manifest` core mapping (frontmatter + links)

**Files:**
- Create: `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/commands/export_notion.py`
- Create: `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`

**Interfaces:**
- Consumes: `llm_wiki.core.config.load_config(root: Path | None = None) -> WikiConfig`; `WikiConfig.project_root: Path`; `llm_wiki.commands.lint._build_link_graph(wiki_dir: Path) -> dict[str, Any]` returning `{"nodes": {name: {"links_to": list[str], "linked_from": list[str]}}, "all_links": list[dict]}`; `llm_wiki.core.frontmatter.parse_file(filepath: Path) -> tuple[dict[str, Any], str]`; `llm_wiki.core.frontmatter.get_knowledge_type(metadata: dict[str, Any]) -> str | None`.
- Produces: `_build_manifest(cfg: WikiConfig) -> dict[str, Any]` returning `{"notes": list[dict[str, Any]], "dangling": list[dict[str, str]]}`. Each note dict has keys `slug, title, knowledge_type, status, confidence, scope, tags, source, created, body_md, links`. Each dangling dict has keys `from, target`.

**Steps:**

- [ ] 1.1 Write failing test. Create `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`:

```python
"""Tests for ``kb export-notion`` — wiki → Notion manifest builder."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.commands.export_notion import _build_manifest
from llm_wiki.core.config import load_config


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _write_note(permanent: Path, name: str, body: str) -> None:
    """Write a permanent note file (frontmatter + body) to the wiki."""
    (permanent / f"{name}.md").write_text(body, encoding="utf-8")


def test_build_manifest_maps_all_fields(populated_wiki: Path) -> None:
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)

    by_slug = {n["slug"]: n for n in manifest["notes"]}
    note = by_slug["api-gateway-auth-pattern"]

    assert note["title"] == "API Gateway Authentication Pattern"
    assert note["knowledge_type"] == "pattern"
    assert note["status"] == "approved"
    assert note["confidence"] == "high"
    assert note["scope"] == "universal"
    assert note["tags"] == ["architecture", "api-design"]
    assert note["source"] == "session-2026-04-09"
    assert note["created"] == "2026-04-09T10:00:00"
    assert note["links"] == ["token-refresh-strategy"]
    assert "---" not in note["body_md"]
    assert note["body_md"].lstrip().startswith("# API Gateway Authentication Pattern")
```

- [ ] 1.2 Run, expect FAIL. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest tests/test_export_notion.py::test_build_manifest_maps_all_fields -v`
  → FAIL with `ModuleNotFoundError: No module named 'llm_wiki.commands.export_notion'`.

- [ ] 1.3 Write minimal impl. Create `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/commands/export_notion.py`:

```python
"""Export the wiki to a Notion-import manifest.

A single deterministic pass over the permanent notes that reuses the existing
frontmatter parser and the lint module's wikilink graph to produce a JSON
manifest. The manifest is consumed by ``workflows/push-to-notion.js``, which
writes a Notion "LLM Wiki" database via the Notion MCP. Markdown remains the
single source of truth; this command never writes back into the wiki.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import typer

from llm_wiki.commands.lint import _build_link_graph
from llm_wiki.core.config import WikiConfig, load_config
from llm_wiki.core.frontmatter import get_knowledge_type, parse_file


if TYPE_CHECKING:
    from pathlib import Path

# Frontmatter fields copied through to the manifest as scalars.
_SCALAR_FIELDS = ("status", "confidence", "scope", "source")

# Leading "# Title" heading at the very start of a note body.
_H1_PATTERN = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


def _title_from_body(slug: str, body: str) -> str:
    """Return the first H1 heading in the body, falling back to a slug-derived title."""
    match = _H1_PATTERN.search(body)
    if match:
        return match.group(1).strip()
    return slug.replace("-", " ").title()


def _scalar(value: Any) -> str:  # noqa: ANN401  # frontmatter values are heterogeneous
    """Render a frontmatter scalar as a plain string (dates may parse as date objects)."""
    return "" if value is None else str(value)


def _build_note_entry(md_file: Path, links_to: list[str], existing: set[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build one manifest note entry plus its dangling-link records.

    Args:
        md_file: Path to the permanent note.
        links_to: Raw wikilink targets emitted by the link graph for this note.
        existing: Set of all note slugs in the wiki (for resolving links).

    Returns:
        Tuple of (note_entry, dangling_records). Resolved targets go to the
        note's ``links``; unresolved targets become dangling records.
    """
    slug = md_file.stem
    fm, body = parse_file(md_file)

    resolved: list[str] = []
    dangling: list[dict[str, str]] = []
    seen: set[str] = set()
    for target in links_to:
        if target in seen:
            continue
        seen.add(target)
        if target in existing:
            resolved.append(target)
        else:
            dangling.append({"from": slug, "target": target})

    tags = fm.get("tags", [])
    tags = [str(t) for t in tags] if isinstance(tags, list) else []

    entry: dict[str, Any] = {
        "slug": slug,
        "title": _title_from_body(slug, body),
        "knowledge_type": get_knowledge_type(fm),
        "status": _scalar(fm.get("status")),
        "confidence": _scalar(fm.get("confidence")),
        "scope": _scalar(fm.get("scope")),
        "tags": tags,
        "source": _scalar(fm.get("source")),
        "created": _scalar(fm.get("created")),
        "body_md": body,
        "links": resolved,
    }
    return entry, dangling


def _build_manifest(cfg: WikiConfig) -> dict[str, Any]:
    """Build the Notion-import manifest for every permanent note.

    Reuses ``lint._build_link_graph`` (keyed by filename stem, same selection
    that lint and charts use) so wikilink resolution is identical across the
    toolkit.

    Args:
        cfg: Resolved wiki configuration.

    Returns:
        ``{"notes": [...], "dangling": [...]}``. Empty wiki yields empty lists.
    """
    wiki_dir = cfg.project_root / "wiki"
    permanent_dir = wiki_dir / "permanent"
    graph = _build_link_graph(wiki_dir)
    existing = set(graph["nodes"].keys())

    notes: list[dict[str, Any]] = []
    dangling: list[dict[str, str]] = []
    if not permanent_dir.exists():
        return {"notes": notes, "dangling": dangling}

    for md_file in sorted(permanent_dir.glob("*.md")):
        links_to = graph["nodes"].get(md_file.stem, {}).get("links_to", [])
        entry, note_dangling = _build_note_entry(md_file, links_to, existing)
        notes.append(entry)
        dangling.extend(note_dangling)

    return {"notes": notes, "dangling": dangling}


def export_notion(
    out: str | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Write the manifest JSON to this path. Defaults to stdout.",
    ),
) -> None:
    """Export the wiki to a Notion-import manifest JSON.

    Emits ``{"notes": [...], "dangling": [...]}`` for ``push-to-notion.js``.
    """
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    manifest = _build_manifest(cfg)
    payload = json.dumps(manifest, indent=2)

    if out:
        out_path = cfg.project_root / out if not out.startswith("/") else out
        from pathlib import Path  # noqa: PLC0415  # local: only needed on the --out branch

        Path(out_path).write_text(payload + "\n", encoding="utf-8")
        typer.echo(
            f"Wrote {len(manifest['notes'])} note(s), "
            f"{len(manifest['dangling'])} dangling link(s) to {out_path}",
        )
    else:
        typer.echo(payload)
```

- [ ] 1.4 Run, expect PASS. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest tests/test_export_notion.py::test_build_manifest_maps_all_fields -v` → PASS.

- [ ] 1.5 Run pre-commit on the new files. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pre-commit run --files src/llm_wiki/commands/export_notion.py tests/test_export_notion.py`
  → all hooks pass (ruff format, ruff check, mypy, vulture). The PostToolUse hook already ran `ruff format` / `ruff check --fix`; this confirms mypy strict and vulture too.

- [ ] 1.6 Commit. From the worktree root:
  `git add plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/commands/export_notion.py plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`
  `git commit -m "feat(karpathy-llm-wiki): add _build_manifest for kb export-notion"`

---

## Task 2 — Link resolution: dangling, alias, and self-link edge cases

**Files:**
- Modify: `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py` (append tests after `test_build_manifest_maps_all_fields`)

**Interfaces:**
- Consumes: `llm_wiki.commands.export_notion._build_manifest(cfg: WikiConfig) -> dict[str, Any]` (defined in Task 1); `llm_wiki.core.config.load_config(root: Path | None = None) -> WikiConfig`.
- Produces: no new production code — verifies `links` (resolved) vs `dangling` (unresolved) split, `[[a|b]]` → `a` resolution, and frontmatter `type`-only schema variant.

**Steps:**

- [ ] 2.1 Write failing tests. Append to `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`:

```python
def test_dangling_links_are_separated(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "links-everywhere",
        """\
---
id: perm-20260410-lll01
type: permanent
knowledge_type: idea
status: pending
confidence: low
scope: universal
tags:
  - llm
source: "manual"
created: "2026-04-10T08:00:00"
---

# Links Everywhere

Real target [[orphan-note]] and a missing one [[nonexistent-note]].
""",
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)

    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["links-everywhere"]["links"] == ["orphan-note"]
    assert {"from": "links-everywhere", "target": "nonexistent-note"} in manifest["dangling"]
    assert all(d["target"] != "orphan-note" for d in manifest["dangling"])


def test_aliased_wikilink_resolves_to_target(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "aliased-link",
        """\
---
id: perm-20260410-aaa02
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: "manual"
created: "2026-04-10T09:00:00"
---

# Aliased Link

See [[orphan-note|the orphan]] for details.
""",
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["aliased-link"]["links"] == ["orphan-note"]


def test_simplified_schema_type_field_supplies_knowledge_type(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "simplified-schema",
        """\
---
type: decision
status: approved
confidence: medium
scope: project
tags:
  - devops
source: "manual"
created: "2026-04-10T10:00:00"
---

# Simplified Schema Note

This note uses the simplified schema where `type` holds the knowledge type.
""",
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["simplified-schema"]["knowledge_type"] == "decision"
```

- [ ] 2.2 Run, expect PASS. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest tests/test_export_notion.py -v` → all four tests PASS. (No production change is needed: `_build_link_graph` already uses `WIKILINK_PATTERN`, which strips `|alias`, and `get_knowledge_type` already reads `type` as a fallback. These tests pin that behavior for the manifest.)

- [ ] 2.3 Commit. From the worktree root:
  `git add plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`
  `git commit -m "test(karpathy-llm-wiki): cover dangling/alias/simplified-schema in export-notion"`

---

## Task 3 — Empty wiki + `export-notion` CLI command (stdout & `--out`)

**Files:**
- Modify: `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/cli.py` (import block lines 16-23; registration block lines 38-45)
- Modify: `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py` (append tests)

**Interfaces:**
- Consumes: `llm_wiki.commands.export_notion.export_notion` (Typer command, defined in Task 1); `typer.testing.CliRunner.invoke(app, args)`.
- Produces: registered CLI subcommand `kb export-notion` printing manifest JSON to stdout, or writing to `--out PATH` (relative paths resolve under `cfg.project_root`).

**Steps:**

- [ ] 3.1 Write failing tests. Append to `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`:

```python
def test_empty_wiki_yields_empty_manifest(wiki_root: Path) -> None:
    cfg = load_config(wiki_root)
    manifest = _build_manifest(cfg)
    assert manifest == {"notes": [], "dangling": []}


def test_export_notion_cli_stdout(populated_wiki: Path, monkeypatch) -> None:
    monkeypatch.chdir(populated_wiki)
    result = runner.invoke(app, ["export-notion"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    slugs = {n["slug"] for n in payload["notes"]}
    assert {"api-gateway-auth-pattern", "token-refresh-strategy", "orphan-note"} <= slugs


def test_export_notion_cli_writes_out_file(populated_wiki: Path, monkeypatch) -> None:
    monkeypatch.chdir(populated_wiki)
    result = runner.invoke(app, ["export-notion", "--out", "output/notion-manifest.json"])
    assert result.exit_code == 0, result.stdout
    written = (populated_wiki / "output" / "notion-manifest.json").read_text(encoding="utf-8")
    payload = json.loads(written)
    assert any(n["slug"] == "api-gateway-auth-pattern" for n in payload["notes"])
    assert "Wrote" in result.stdout
```

- [ ] 3.2 Run, expect FAIL. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest tests/test_export_notion.py::test_export_notion_cli_stdout -v`
  → FAIL: `kb` exits non-zero with `No such command 'export-notion'` (Typer error; `result.exit_code != 0`). `test_empty_wiki_yields_empty_manifest` already PASSES.

- [ ] 3.3 Wire the import. In `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/cli.py`, add the import alphabetically inside the existing import block (after the `compile_cmd` import, before `index`):

```python
from llm_wiki.commands.export_notion import export_notion
```

  Resulting import block (lines ~16-24):

```python
from llm_wiki.commands.charts import charts
from llm_wiki.commands.compile_cmd import compile_notes
from llm_wiki.commands.export_notion import export_notion
from llm_wiki.commands.index import index
from llm_wiki.commands.ingest import ingest
from llm_wiki.commands.init_cmd import init
from llm_wiki.commands.lint import lint
from llm_wiki.commands.migrate_frontmatter import migrate_frontmatter
from llm_wiki.commands.search import search
```

- [ ] 3.4 Register the command. In `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/cli.py`, add to the top-level commands block (after `app.command("charts")(charts)`):

```python
app.command("export-notion")(export_notion)
```

  Resulting registration block (lines ~38-46):

```python
app.command("init")(init)
app.command("ingest")(ingest)
app.command("compile")(compile_notes)
app.command("search")(search)
app.command("lint")(lint)
app.command("index")(index)
app.command("charts")(charts)
app.command("export-notion")(export_notion)
app.command("migrate-frontmatter")(migrate_frontmatter)
```

- [ ] 3.5 Run, expect PASS. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest tests/test_export_notion.py -v` → all tests PASS (7 total in this file).

- [ ] 3.6 Run full suite + coverage gate. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest -v` → all PASS, coverage ≥70% (export_notion.py is fully exercised: `_build_manifest`, both `export_notion` branches, the `FileNotFoundError` branch is covered by Task 3.7 below).

- [ ] 3.7 Add the config-missing branch test. Append to `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`:

```python
def test_export_notion_cli_no_config(wiki_root_bare: Path, monkeypatch) -> None:
    monkeypatch.chdir(wiki_root_bare)
    result = runner.invoke(app, ["export-notion"])
    assert result.exit_code == 1
    assert "Error:" in result.stdout or "Error:" in (result.stderr or "")
```

  Then run `uv run pytest tests/test_export_notion.py::test_export_notion_cli_no_config -v` → PASS.

- [ ] 3.8 Run pre-commit. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pre-commit run --all-files` → all hooks pass.

- [ ] 3.9 Commit. From the worktree root:
  `git add plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/cli.py plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`
  `git commit -m "feat(karpathy-llm-wiki): register kb export-notion CLI command"`

---

## Task 4 — `workflows/push-to-notion.js` Workflow script

**Files:**
- Create: `plugins/karpathy-llm-wiki/workflows/push-to-notion.js`

**Interfaces:**
- Consumes: injected Workflow globals `args` (object or JSON string), `phase(title: string)`, `agent(prompt: string, opts: {label, phase, schema}) -> Promise<object>`, `parallel(thunks: Array<() => Promise<T>>) -> Promise<T[]>`, `log(msg: string)`; manifest JSON file at `args.manifestPath` shaped `{notes: [...], dangling: [...]}` (produced by Task 1/3); Notion MCP write tools `mcp__plugin_Notion_notion__notion-search`, `mcp__plugin_Notion_notion__notion-create-database`, `mcp__plugin_Notion_notion__notion-query-data-sources`, `mcp__plugin_Notion_notion__notion-create-pages`, `mcp__plugin_Notion_notion__notion-update-page`, `mcp__plugin_Notion_notion__notion-fetch`.
- Produces: a Workflow script with `export const meta` (pure literal) and a return value `{ database_id, created, updated, relations_set, dangling, dryRun }`.

**Steps:**

- [ ] 4.1 Create the script. Create `plugins/karpathy-llm-wiki/workflows/push-to-notion.js`:

```javascript
export const meta = {
  name: 'push-to-notion',
  description: 'Mirror the llm-wiki manifest into a Notion "LLM Wiki" database: ensure the DB, upsert one page per note (keyed by slug), then wire [[wikilinks]] into the self-relation. One-way mirror; markdown stays the source of truth.',
  whenToUse: 'After kb export-notion has written a manifest.json. Args: { manifestPath, workingDir, dryRun }. manifestPath is the JSON file ({notes:[...],dangling:[...]}); workingDir is the wiki root. dryRun:true runs Pass 0 (ensure DB) and reports create/update/relation counts without writing pages.',
  phases: [
    { title: 'EnsureDB', detail: 'search Notion for a database titled "LLM Wiki"; create it with the property schema if absent' },
    { title: 'UpsertPages', detail: 'parallel chunks: find page by slug, update properties + body, or create; collect slug -> page_id' },
    { title: 'WireRelations', detail: 'parallel chunks: map each note\'s links slugs to page-ids and set the Links self-relation' },
    { title: 'Report', detail: 'summarize created / updated / relations_set / dangling' },
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
  },
  required: ['database_id', 'created'],
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
  return `You ensure a Notion database named "${DB_TITLE}" exists with the exact schema below. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

1. notion-search for a database titled exactly "${DB_TITLE}". If found, capture its database id and return { database_id, created: false }. Do NOT recreate or alter it.
2. If not found, notion-create-database titled "${DB_TITLE}" with these properties:
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
   Then return { database_id: "<new id>", created: true }.

Return structured output { database_id, created }.`
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
  const list = items.map(it => `- slug=${it.slug} page_id=${it.page_id} links_to_page_ids=${JSON.stringify(it.target_page_ids)}`).join('\n')
  return `You set the "Links" self-relation on pages in Notion database ${databaseId}. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

For EACH item below, notion-update-page on page_id and set the "Links" relation property to exactly the list of target page-ids given (replace any existing relation value). Notion auto-populates the reverse back-links. If the target list is empty, set the relation to empty. If a page fails, record ok=false with a short error and CONTINUE.

Items:
${list}

Return structured output { results: [ {slug, relations_set, ok, error} ] } one per item.`
}

// ===== run =====
phase('EnsureDB')
const fs = await import('node:fs')
const path = await import('node:path')
const resolvedManifest = path.isAbsolute(MANIFEST_PATH) ? MANIFEST_PATH : path.join(WD, MANIFEST_PATH)
const manifest = JSON.parse(fs.readFileSync(resolvedManifest, 'utf8'))
const notes = Array.isArray(manifest.notes) ? manifest.notes : []
const danglingCount = Array.isArray(manifest.dangling) ? manifest.dangling.length : 0
log(`Loaded ${notes.length} notes, ${danglingCount} dangling links from ${resolvedManifest}`)

const ensured = await agent(ensureDbPrompt(), { label: 'ensure-db', phase: 'EnsureDB', schema: ENSURE_DB_SCHEMA })
const databaseId = ensured && ensured.database_id ? ensured.database_id : null
if (!databaseId) { throw new Error('push-to-notion: could not resolve or create the "LLM Wiki" database id.') }
log(`Database ${databaseId} (created=${ensured.created})`)

if (DRY_RUN) {
  return {
    mode: 'dry-run',
    database_id: databaseId,
    db_created: ensured.created === true,
    would_upsert: notes.length,
    would_set_relations: notes.filter(n => Array.isArray(n.links) && n.links.length > 0).length,
    dangling: danglingCount,
  }
}

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
  relationItems.push({ slug: n.slug, page_id: pageId, target_page_ids: targetIds })
}
const relationChunks = chunk(relationItems.filter(it => it.target_page_ids.length > 0), RELATION_CHUNK)
const relationResults = []
await parallel(relationChunks.map((c, i) => async () => {
  const r = await agent(relationPrompt(databaseId, c), { label: `relations:${i + 1}/${relationChunks.length}`, phase: 'WireRelations', schema: RELATION_SCHEMA })
  if (r && r.results) relationResults.push(...r.results)
}))
const relationsSet = relationResults.filter(r => r.ok).reduce((acc, r) => acc + (Number(r.relations_set) || 0), 0)

phase('Report')
return {
  database_id: databaseId,
  created,
  updated,
  relations_set: relationsSet,
  dangling: danglingCount,
  dryRun: false,
  failures: upsertResults.filter(r => !r.ok).map(r => ({ slug: r.slug, error: r.error })),
}
```

- [ ] 4.2 Lint the JS for syntax errors (no pytest covers this file). From the worktree root:
  `node --check plugins/karpathy-llm-wiki/workflows/push-to-notion.js`
  → exits 0, no output. (Verifies the file parses; `export const meta` is valid ESM, and `await import(...)` is legal at the top level of the Workflow body.)

- [ ] 4.3 Documented verification step (manual, not CI). The Workflow tool is only available in a parent Claude session, so the script's runtime "test" is a `dryRun` invocation. After `kb export-notion --out output/notion-manifest.json` has produced a manifest, the runtime check is:
  `Workflow({ scriptPath: "<abs>/plugins/karpathy-llm-wiki/workflows/push-to-notion.js", args: { manifestPath: "output/notion-manifest.json", workingDir: "<abs wiki root>", dryRun: true } })`
  Expect a returned object `{ mode: "dry-run", database_id, db_created, would_upsert, would_set_relations, dangling }` with `would_upsert` equal to the manifest note count, and NO pages created/updated. Record this as the verification evidence in the implementing session's notes.

- [ ] 4.4 Commit. From the worktree root:
  `git add plugins/karpathy-llm-wiki/workflows/push-to-notion.js`
  `git commit -m "feat(karpathy-llm-wiki): add push-to-notion workflow (manifest -> Notion DB)"`

---

## Task 5 — `/kb-push-notion` slash command

**Files:**
- Create: `plugins/karpathy-llm-wiki/commands/kb-push-notion.md`

**Interfaces:**
- Consumes: `kb export-notion --out <path>` CLI (Task 3); `workflows/push-to-notion.js` (Task 4); the `Workflow` tool.
- Produces: a user-facing slash command markdown matching the `commands/kb-*.md` frontmatter/structure (a `description:` frontmatter key plus step-by-step instructions).

**Steps:**

- [ ] 5.1 Create the command file. Create `plugins/karpathy-llm-wiki/commands/kb-push-notion.md`:

```markdown
---
description: Mirror the wiki into a Notion "LLM Wiki" database
---

# /kb-push-notion -- Mirror the LLM Wiki to Notion

You mirror the markdown wiki into a Notion "LLM Wiki" database. This is a
one-way mirror: markdown stays the single source of truth, and edits made
directly in Notion are overwritten on the next push. Wikilinks (`[[name]]`)
become a native Notion **self-relation**, giving bidirectional back-links for
free. Intended to be chained after `/kb-compile`.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Extract:

- **--dry-run**: Build the manifest and ensure the Notion database, then report
  the create/update/relation counts WITHOUT writing pages.
- No flags: full push (ensure DB, upsert pages, wire relations).

## Step 2: Build the manifest

Run the deterministic exporter from the wiki root. This writes a JSON manifest
(`{"notes": [...], "dangling": [...]}`) with one entry per permanent note,
resolved wikilinks in `links`, and unresolved wikilinks in `dangling`:

```bash
kb export-notion --out output/notion-manifest.json
```

The command prints how many notes and dangling links were written. If it
reports 0 notes, tell the user the wiki has no permanent notes yet and stop.

Note the absolute wiki root path (the directory containing `.kb-config.yml`) --
you pass it to the workflow as `workingDir`.

## Step 3: Push to Notion via the workflow

Invoke the `push-to-notion.js` workflow with the manifest. Use the absolute
path to `${CLAUDE_PLUGIN_ROOT}/workflows/push-to-notion.js` as `scriptPath`,
the absolute manifest path (or the path relative to `workingDir`), and the
absolute wiki root as `workingDir`.

For a dry run (when `--dry-run` was passed):

```
Workflow({
  scriptPath: "<plugin-root>/workflows/push-to-notion.js",
  args: { manifestPath: "output/notion-manifest.json", workingDir: "<wiki-root>", dryRun: true }
})
```

For a full push (no flags):

```
Workflow({
  scriptPath: "<plugin-root>/workflows/push-to-notion.js",
  args: { manifestPath: "output/notion-manifest.json", workingDir: "<wiki-root>", dryRun: false }
})
```

The workflow runs three passes: ensure the "LLM Wiki" database exists, upsert
one page per note keyed by the hidden `slug` property, then wire the `Links`
self-relation. It returns counts for created / updated / relations_set /
dangling.

## Step 4: Report

Present a summary using the workflow's return value:

```
## Notion Push Summary

- Database: <database_id> (created: yes/no)
- Pages created: N
- Pages updated: N
- Relations set: N
- Dangling links (dropped): N

### Next Steps
- Open the "LLM Wiki" database in Notion to browse and filter notes.
- Re-run /kb-push-notion after /kb-compile to keep the mirror current.
```

## Important Notes

- The push is **idempotent**: upsert-by-slug converges, so it is always safe to
  re-run. No Notion page-ids are written back into the markdown.
- Dangling wikilinks (targets with no matching note) are dropped from relations
  and reported; they are never fatal.
- Deleted source notes leave their Notion page as an orphan in v1 (logged, not
  pruned).
- All Notion I/O goes through the Notion MCP; there is no Notion API token to
  configure here.
```

- [ ] 5.2 Verify the command file parses (no pytest covers `.md` commands). From the worktree root:
  `python3 -c "import re,sys; t=open('plugins/karpathy-llm-wiki/commands/kb-push-notion.md').read(); m=re.match(r'^---\n(.*?)\n---\n', t, re.DOTALL); assert m and 'description:' in m.group(1), 'frontmatter missing description'; print('frontmatter OK')"`
  → prints `frontmatter OK` (confirms the YAML frontmatter block with `description:` matches the shape of the other `kb-*.md` commands).

- [ ] 5.3 Commit. From the worktree root:
  `git add plugins/karpathy-llm-wiki/commands/kb-push-notion.md`
  `git commit -m "feat(karpathy-llm-wiki): add /kb-push-notion slash command"`

---

## Final verification

- [ ] F.1 Full suite + coverage. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest -v` → all PASS, coverage ≥70%.
- [ ] F.2 Full lint. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pre-commit run --all-files` → all hooks pass.
- [ ] F.3 JS syntax. From the worktree root:
  `node --check plugins/karpathy-llm-wiki/workflows/push-to-notion.js` → exits 0.
- [ ] F.4 Spec coverage check: confirm every spec section maps to a task — `kb export-notion` manifest + field mapping + link/dangling split (Tasks 1-3), property mapping consumed by the DB schema prompt (Task 4 `ensureDbPrompt`), two-pass crux ensure-DB/upsert/wire-relations (Task 4), idempotent upsert-by-slug (Task 4 + command notes Task 5), dangling/orphan error handling (Tasks 1-2 + command notes Task 5), `/kb-push-notion` slash command (Task 5).
