# LLM Wiki → Notion Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror the markdown LLM wiki into a Notion "LLM Wiki" database, turning `[[wikilinks]]` into native Notion self-relations, plus a second "LLM Wiki Sources" database mirroring the ingest manifest with a best-effort note→source relation, via a deterministic `kb export-notion` manifest builder plus a multi-pass Notion-MCP Workflow script invoked by a `/kb-push-notion` slash command.

**Architecture:** `kb export-notion` (new Python Typer subcommand) does one deterministic pass over `wiki/permanent/*.md`, reusing `commands/lint.py`'s link graph and `core/frontmatter.py`'s parser, AND reads the ingest manifest at `cfg.raw_inbox / ".manifest.json"` (a JSON list), emitting a JSON manifest (`notes[]` + `dangling[]` + `sources[]` + `unmatched_sources[]`, with each note carrying a best-effort `source_ref`). `workflows/push-to-notion.js` (new Workflow script, modeled on `ingest-notion-cited-sources.js`) consumes that manifest and writes Notion via Notion MCP write tools: ensure-DBs → upsert-source-rows-by-ingest_id → upsert-pages-by-slug → wire-relations (`Links` self-relation + `Source` note→source relation). `/kb-push-notion` chains the two. Markdown stays the single source of truth (one-way mirror). The note→source link is best-effort string match — no wiki-pipeline or note-frontmatter change.

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
| `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/commands/export_notion.py` | Create | `export_notion` Typer command + `_build_manifest(cfg)` helper that maps frontmatter + link graph to the manifest dict, plus `_build_sources(cfg)` / `_normalize_source(s)` for source rows and the per-note `source_ref` / `unmatched_sources` wiring. |
| `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/cli.py` | Modify (import block ~L16-23; registration block ~L38-45) | Import `export_notion`; register `app.command("export-notion")(export_notion)`. |
| `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py` | Create | Unit tests for `_build_manifest`, `_build_sources`, `_normalize_source`, source-ref matching, and the `export-notion` CLI command using the `wiki_root` / `populated_wiki` fixtures. |
| `plugins/karpathy-llm-wiki/workflows/push-to-notion.js` | Create | Workflow script: read manifest, ensure "LLM Wiki" + "LLM Wiki Sources" DBs, upsert source rows by `ingest_id`, upsert pages by `slug`, wire `Links` + `Source` relations; `dryRun` reports note and source counts. |
| `plugins/karpathy-llm-wiki/commands/kb-push-notion.md` | Create | Slash command: run `kb export-notion --out <manifest>` then invoke `push-to-notion.js` with the manifest. |

---

## Task 1 — `_build_manifest` core mapping (frontmatter + links)

**Files:**
- Create: `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/commands/export_notion.py`
- Create: `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`

**Interfaces:**
- Consumes: `llm_wiki.core.config.load_config(root: Path | None = None) -> WikiConfig`; `WikiConfig.project_root: Path`; `WikiConfig.raw_inbox: Path` (the ingest manifest lives at `raw_inbox / ".manifest.json"`, a JSON **list**); `llm_wiki.commands.lint._build_link_graph(wiki_dir: Path) -> dict[str, Any]` returning `{"nodes": {name: {"links_to": list[str], "linked_from": list[str]}}, "all_links": list[dict]}`; `llm_wiki.core.frontmatter.parse_file(filepath: Path) -> tuple[dict[str, Any], str]`; `llm_wiki.core.frontmatter.get_knowledge_type(metadata: dict[str, Any]) -> str | None`.
- Produces: `_build_manifest(cfg: WikiConfig) -> dict[str, Any]` returning `{"notes": list[dict[str, Any]], "dangling": list[dict[str, str]], "sources": list[dict[str, Any]], "unmatched_sources": list[str]}`. Each note dict has keys `slug, title, knowledge_type, status, confidence, scope, tags, source, created, body_md, links, source_ref`. Each dangling dict has keys `from, target`. Helpers: `_build_sources(cfg: WikiConfig) -> list[dict[str, Any]]` (reads `raw_inbox/.manifest.json`, a JSON list; missing file → `[]`; each entry read defensively with `.get`, keys `ingest_id, source, type, source_class, date, status, file`); `_normalize_source(value: str) -> str` (`value.strip().rstrip("/")`).

**Steps:**

- [ ] 1.1 Write failing test. Create `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`:

```python
"""Tests for ``kb export-notion`` — wiki → Notion manifest builder."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.commands.export_notion import (
    _build_manifest,
    _build_sources,
    _normalize_source,
)
from llm_wiki.core.config import load_config


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _write_note(permanent: Path, name: str, body: str) -> None:
    """Write a permanent note file (frontmatter + body) to the wiki."""
    (permanent / f"{name}.md").write_text(body, encoding="utf-8")


def _write_manifest(wiki_root: Path, entries: list[dict[str, Any]]) -> None:
    """Write the ingest manifest (a JSON list) at ``raw/inbox/.manifest.json``."""
    cfg = load_config(wiki_root)
    cfg.raw_inbox.mkdir(parents=True, exist_ok=True)
    (cfg.raw_inbox / ".manifest.json").write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )


def test_build_manifest_maps_all_fields(populated_wiki: Path) -> None:
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-aaa111",
                "file": "raw/web/api-gw.md",
                "type": "url",
                "source": "session-2026-04-09",
                "date": "2026-04-09T08:00:00",
                "status": "processed",
                "source_class": "web",
            }
        ],
    )
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
    # Best-effort note->source match: the note's free-text source equals a manifest source.
    assert note["source_ref"] == "ingest-aaa111"
    assert manifest["sources"][0]["ingest_id"] == "ingest-aaa111"
    assert manifest["sources"][0]["source_class"] == "web"
```

- [ ] 1.2 Run, expect FAIL. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest tests/test_export_notion.py::test_build_manifest_maps_all_fields -v`
  → FAIL with `ModuleNotFoundError: No module named 'llm_wiki.commands.export_notion'`.

- [ ] 1.3 Write minimal impl. Create `plugins/karpathy-llm-wiki/llm-wiki-core/src/llm_wiki/commands/export_notion.py`:

```python
"""Export the wiki to a Notion-import manifest.

A single deterministic pass over the permanent notes that reuses the existing
frontmatter parser and the lint module's wikilink graph to produce a JSON
manifest. It also mirrors the ingest manifest (``raw_inbox/.manifest.json``) as
source rows and best-effort matches each note's free-text ``source`` to a source
``ingest_id`` (``source_ref``). The manifest is consumed by
``workflows/push-to-notion.js``, which writes the "LLM Wiki" and "LLM Wiki
Sources" databases via the Notion MCP. Markdown remains the single source of
truth; this command never writes back into the wiki.
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


def _normalize_source(value: str) -> str:
    """Normalize a source string for best-effort matching.

    Strips surrounding whitespace and a single trailing slash so that
    ``" https://x/ "`` and ``"https://x"`` compare equal. Case-sensitive by
    design — this is a best-effort join, not an exact key.

    Args:
        value: Raw source string (note frontmatter or manifest entry).

    Returns:
        The trimmed, trailing-slash-stripped source string.
    """
    return value.strip().rstrip("/")


def _build_sources(cfg: WikiConfig) -> list[dict[str, Any]]:
    """Read the ingest manifest into source rows.

    The ingest manifest at ``cfg.raw_inbox / ".manifest.json"`` is a JSON list
    of ingestion events (see ``commands/ingest.py``). Each entry is read
    defensively with ``.get`` because older entries may omit some keys. A missing
    manifest file yields an empty list (not an error).

    Args:
        cfg: Resolved wiki configuration.

    Returns:
        One source dict per manifest entry, keyed
        ``ingest_id, source, type, source_class, date, status, file``.
    """
    manifest_path = cfg.raw_inbox / ".manifest.json"
    if not manifest_path.exists():
        return []

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = raw if isinstance(raw, list) else []

    sources: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sources.append(
            {
                "ingest_id": entry.get("id"),
                "source": entry.get("source"),
                "type": entry.get("type"),
                "source_class": entry.get("source_class"),
                "date": entry.get("date"),
                "status": entry.get("status"),
                "file": entry.get("file"),
            }
        )
    return sources


def _match_source_ref(note_source: str, sources: list[dict[str, Any]]) -> str | None:
    """Best-effort match a note's free-text ``source`` to a source ``ingest_id``.

    Both sides are normalized with :func:`_normalize_source`. On multiple matches
    the source with the latest ``date`` wins. Empty/blank note sources never
    match.

    Args:
        note_source: The note's raw ``source`` frontmatter value.
        sources: Source rows from :func:`_build_sources`.

    Returns:
        The matched source's ``ingest_id``, or ``None`` if nothing matched.
    """
    target = _normalize_source(note_source)
    if not target:
        return None

    matches = [
        s
        for s in sources
        if s.get("source") and _normalize_source(str(s["source"])) == target
    ]
    if not matches:
        return None
    best = max(matches, key=lambda s: str(s.get("date") or ""))
    ingest_id = best.get("ingest_id")
    return str(ingest_id) if ingest_id is not None else None


def _build_note_entry(md_file: Path, links_to: list[str], existing: set[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build one manifest note entry plus its dangling-link records.

    Args:
        md_file: Path to the permanent note.
        links_to: Raw wikilink targets emitted by the link graph for this note.
        existing: Set of all note slugs in the wiki (for resolving links).

    Returns:
        Tuple of (note_entry, dangling_records). Resolved targets go to the
        note's ``links``; unresolved targets become dangling records. The
        ``source_ref`` key starts as ``None`` and is filled in by
        :func:`_build_manifest` once the source rows are available.
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
        "source_ref": None,
    }
    return entry, dangling


def _build_manifest(cfg: WikiConfig) -> dict[str, Any]:
    """Build the Notion-import manifest for every permanent note.

    Reuses ``lint._build_link_graph`` (keyed by filename stem, same selection
    that lint and charts use) so wikilink resolution is identical across the
    toolkit. Also mirrors the ingest manifest as ``sources`` and best-effort
    matches each note's free-text ``source`` to a source ``ingest_id``
    (``source_ref``); notes whose non-empty ``source`` matched nothing are
    collected in ``unmatched_sources``.

    Args:
        cfg: Resolved wiki configuration.

    Returns:
        ``{"notes": [...], "dangling": [...], "sources": [...],
        "unmatched_sources": [...]}``. Empty wiki / absent manifest yield empty
        lists.
    """
    wiki_dir = cfg.project_root / "wiki"
    permanent_dir = wiki_dir / "permanent"
    graph = _build_link_graph(wiki_dir)
    existing = set(graph["nodes"].keys())
    sources = _build_sources(cfg)

    notes: list[dict[str, Any]] = []
    dangling: list[dict[str, str]] = []
    unmatched_sources: list[str] = []
    if not permanent_dir.exists():
        return {
            "notes": notes,
            "dangling": dangling,
            "sources": sources,
            "unmatched_sources": unmatched_sources,
        }

    for md_file in sorted(permanent_dir.glob("*.md")):
        links_to = graph["nodes"].get(md_file.stem, {}).get("links_to", [])
        entry, note_dangling = _build_note_entry(md_file, links_to, existing)
        entry["source_ref"] = _match_source_ref(entry["source"], sources)
        if entry["source"].strip() and entry["source_ref"] is None:
            unmatched_sources.append(entry["slug"])
        notes.append(entry)
        dangling.extend(note_dangling)

    return {
        "notes": notes,
        "dangling": dangling,
        "sources": sources,
        "unmatched_sources": unmatched_sources,
    }


def export_notion(
    out: str | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Write the manifest JSON to this path. Defaults to stdout.",
    ),
) -> None:
    """Export the wiki to a Notion-import manifest JSON.

    Emits ``{"notes": [...], "dangling": [...], "sources": [...],
    "unmatched_sources": [...]}`` for ``push-to-notion.js``.
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
            f"{len(manifest['dangling'])} dangling link(s), "
            f"{len(manifest['sources'])} source(s), "
            f"{len(manifest['unmatched_sources'])} unmatched source(s) to {out_path}",
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

## Task 2 — Link resolution + source matching: dangling, alias, schema, and `source_ref` edge cases

**Files:**
- Modify: `plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py` (append tests after `test_build_manifest_maps_all_fields`)

**Interfaces:**
- Consumes: `llm_wiki.commands.export_notion._build_manifest(cfg: WikiConfig) -> dict[str, Any]`, `_build_sources(cfg)`, `_normalize_source(value)` (defined in Task 1); `llm_wiki.core.config.load_config(root: Path | None = None) -> WikiConfig`; the `_write_manifest` test helper (defined in Task 1).
- Produces: no new production code — verifies `links` (resolved) vs `dangling` (unresolved) split, `[[a|b]]` → `a` resolution, the frontmatter `type`-only schema variant, AND the source-matching behaviors: `_normalize_source` trimming, `_build_sources` reading/empty, exact / trailing-slash / whitespace matches, no-match → `unmatched_sources`, latest-`date` tie-break, and manifest-absent → all `source_ref is None`.

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


def test_normalize_source_strips_whitespace_and_trailing_slash() -> None:
    assert _normalize_source(" https://x/ ") == "https://x"
    assert _normalize_source("https://x") == "https://x"
    assert _normalize_source("  ") == ""


def test_build_sources_reads_manifest_list(populated_wiki: Path) -> None:
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-src001",
                "file": "raw/web/a.md",
                "type": "url",
                "source": "https://example.com/a",
                "date": "2026-05-01T00:00:00",
                "status": "processed",
                "source_class": "web",
            },
            # Older entry missing some keys — read defensively with .get.
            {"id": "ingest-src002", "source": "https://example.com/b"},
        ],
    )
    cfg = load_config(populated_wiki)
    sources = _build_sources(cfg)
    assert sources[0]["ingest_id"] == "ingest-src001"
    assert sources[0]["file"] == "raw/web/a.md"
    assert sources[1]["ingest_id"] == "ingest-src002"
    assert sources[1]["type"] is None  # missing key -> None, not KeyError
    assert sources[1]["source_class"] is None


def test_build_sources_missing_manifest_is_empty(wiki_root: Path) -> None:
    cfg = load_config(wiki_root)
    assert _build_sources(cfg) == []


def test_source_ref_matches_trailing_slash_and_whitespace(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "matched-note",
        """\
---
id: perm-20260411-mmm01
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: " https://example.com/paper "
created: "2026-04-11T08:00:00"
---

# Matched Note

Distilled from a paper.
""",
    )
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-match01",
                "file": "raw/web/paper.md",
                "type": "url",
                "source": "https://example.com/paper/",
                "date": "2026-04-10T00:00:00",
                "status": "processed",
                "source_class": "web",
            }
        ],
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    # Trailing slash + whitespace differences still match.
    assert by_slug["matched-note"]["source_ref"] == "ingest-match01"
    # Raw source text is kept regardless of matching.
    assert by_slug["matched-note"]["source"] == "https://example.com/paper"
    assert "matched-note" not in manifest["unmatched_sources"]


def test_source_ref_no_match_lists_unmatched(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "unmatched-note",
        """\
---
id: perm-20260411-uuu01
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: "https://nowhere.example/none"
created: "2026-04-11T09:00:00"
---

# Unmatched Note

No manifest entry has this source.
""",
    )
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-other01",
                "file": "raw/web/other.md",
                "type": "url",
                "source": "https://example.com/other",
                "date": "2026-04-10T00:00:00",
                "status": "processed",
                "source_class": "web",
            }
        ],
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["unmatched-note"]["source_ref"] is None
    assert "unmatched-note" in manifest["unmatched_sources"]


def test_source_ref_multiple_matches_latest_date_wins(populated_wiki: Path) -> None:
    permanent = populated_wiki / "wiki" / "permanent"
    _write_note(
        permanent,
        "dup-source-note",
        """\
---
id: perm-20260411-ddd01
type: permanent
knowledge_type: fact
status: approved
confidence: high
scope: universal
tags:
  - llm
source: "https://example.com/dup"
created: "2026-04-11T10:00:00"
---

# Dup Source Note

Ingested twice.
""",
    )
    _write_manifest(
        populated_wiki,
        [
            {
                "id": "ingest-old",
                "file": "raw/web/dup-old.md",
                "type": "url",
                "source": "https://example.com/dup",
                "date": "2026-04-01T00:00:00",
                "status": "processed",
                "source_class": "web",
            },
            {
                "id": "ingest-new",
                "file": "raw/web/dup-new.md",
                "type": "url",
                "source": "https://example.com/dup",
                "date": "2026-05-01T00:00:00",
                "status": "processed",
                "source_class": "web",
            },
        ],
    )
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    by_slug = {n["slug"]: n for n in manifest["notes"]}
    assert by_slug["dup-source-note"]["source_ref"] == "ingest-new"


def test_missing_manifest_yields_null_source_refs(populated_wiki: Path) -> None:
    # No _write_manifest call: the ingest manifest is absent.
    cfg = load_config(populated_wiki)
    manifest = _build_manifest(cfg)
    assert manifest["sources"] == []
    assert all(n["source_ref"] is None for n in manifest["notes"])
    # Notes that HAVE a source string are still listed as unmatched.
    sourced = [n["slug"] for n in manifest["notes"] if n["source"].strip()]
    assert set(sourced) == set(manifest["unmatched_sources"])
```

- [ ] 2.2 Run, expect PASS. From `plugins/karpathy-llm-wiki/llm-wiki-core`:
  `uv run pytest tests/test_export_notion.py -v` → all tests PASS. (No new production change beyond Task 1: `_build_link_graph` already strips `|alias` via `WIKILINK_PATTERN`, `get_knowledge_type` already reads `type` as a fallback, and `_build_sources` / `_normalize_source` / the `source_ref` + `unmatched_sources` wiring all land in Task 1. These tests pin that behavior.)

- [ ] 2.3 Commit. From the worktree root:
  `git add plugins/karpathy-llm-wiki/llm-wiki-core/tests/test_export_notion.py`
  `git commit -m "test(karpathy-llm-wiki): cover dangling/alias/schema + source-ref matching in export-notion"`

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
    assert manifest == {
        "notes": [],
        "dangling": [],
        "sources": [],
        "unmatched_sources": [],
    }


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
  `uv run pytest tests/test_export_notion.py -v` → all tests PASS (the export-notion suite: field mapping, link/dangling/alias/schema, source-ref matching, empty-wiki, and the CLI stdout/`--out`/no-config cases).

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
- Consumes: injected Workflow globals `args` (object or JSON string), `phase(title: string)`, `agent(prompt: string, opts: {label, phase, schema}) -> Promise<object>`, `parallel(thunks: Array<() => Promise<T>>) -> Promise<T[]>`, `log(msg: string)`; manifest JSON file at `args.manifestPath` shaped `{notes: [...], dangling: [...], sources: [...], unmatched_sources: [...]}` (produced by Task 1/3), where each note carries `source_ref` (an `ingest_id` or `null`) and each source carries `{ingest_id, source, type, source_class, date, status, file}`; Notion MCP write tools `mcp__plugin_Notion_notion__notion-search`, `mcp__plugin_Notion_notion__notion-create-database`, `mcp__plugin_Notion_notion__notion-query-data-sources`, `mcp__plugin_Notion_notion__notion-create-pages`, `mcp__plugin_Notion_notion__notion-update-page`, `mcp__plugin_Notion_notion__notion-fetch`.
- Produces: a Workflow script with `export const meta` (pure literal) and a return value `{ database_id, sources_database_id, created, updated, sources_created, sources_updated, relations_set, source_relations_set, dangling, dryRun }`.

**Steps:**

- [ ] 4.1 Create the script. Create `plugins/karpathy-llm-wiki/workflows/push-to-notion.js`:

```javascript
export const meta = {
  name: 'push-to-notion',
  description: 'Mirror the llm-wiki manifest into a Notion "LLM Wiki" database plus a "LLM Wiki Sources" database: ensure both DBs, upsert one source row per ingestion event (keyed by ingest_id), upsert one page per note (keyed by slug), then wire [[wikilinks]] into the Links self-relation and each note into its best-effort Source relation. One-way mirror; markdown stays the source of truth.',
  whenToUse: 'After kb export-notion has written a manifest.json. Args: { manifestPath, workingDir, dryRun }. manifestPath is the JSON file ({notes:[...],dangling:[...],sources:[...],unmatched_sources:[...]}); workingDir is the wiki root. dryRun:true runs Pass 0 (ensure both DBs) and reports note + source create/update/relation counts without writing pages.',
  phases: [
    { title: 'EnsureDBs', detail: 'search Notion for databases titled "LLM Wiki" and "LLM Wiki Sources"; create either with its property schema if absent (the notes DB Source relation targets the Sources DB)' },
    { title: 'UpsertSources', detail: 'parallel chunks: find source row by ingest_id, update properties, or create; collect ingest_id -> source_page_id' },
    { title: 'UpsertPages', detail: 'parallel chunks: find page by slug, update properties + body, or create; collect slug -> page_id' },
    { title: 'WireRelations', detail: 'parallel chunks: map each note\'s links slugs to page-ids and set the Links self-relation, and map its source_ref ingest_id to a source page-id and set the Source relation' },
    { title: 'Report', detail: 'summarize created / updated / sources_created / sources_updated / relations_set / source_relations_set / dangling' },
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
const SOURCES_DB_TITLE = 'LLM Wiki Sources'

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
    sources_database_id: { type: 'string' },
    sources_created: { type: 'boolean' },
  },
  required: ['database_id', 'created', 'sources_database_id', 'sources_created'],
}

const SOURCE_UPSERT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          ingest_id: { type: 'string' },
          page_id: { type: 'string' },
          action: { type: 'string' },
          ok: { type: 'boolean' },
          error: { type: 'string' },
        },
        required: ['ingest_id', 'ok'],
      },
    },
  },
  required: ['results'],
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
          source_relation_set: { type: 'boolean' },
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
  return `You ensure TWO Notion databases exist with the exact schemas below. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

Do the SOURCES database FIRST, because the notes database's "Source" relation must target it.

A. Ensure the sources database titled exactly "${SOURCES_DB_TITLE}":
1. notion-search for a database titled exactly "${SOURCES_DB_TITLE}". If found, capture its id and set sources_created=false. Do NOT recreate or alter it.
2. If not found, notion-create-database titled "${SOURCES_DB_TITLE}" with these properties, then set sources_created=true:
   - Name: title (the source string)
   - Source URL: url (the external source link; plain text if not an http(s) URL)
   - ingest_id: rich_text (hidden join key; the upsert key; never shown to the user)
   - Type: select with options: session, file, url, text (other values auto-create on first use)
   - Class: select (leave options empty; they auto-create on first use)
   - Ingested: date
   - Status: select with options: pending, processed
   - Archived: rich_text (the archived-copy path)

B. Ensure the notes database titled exactly "${DB_TITLE}":
1. notion-search for a database titled exactly "${DB_TITLE}". If found, capture its id and set created=false. Do NOT recreate or alter it.
2. If not found, notion-create-database titled "${DB_TITLE}" with these properties, then set created=true:
   - Name: title
   - slug: rich_text (hidden join key; never shown to the user)
   - Type: select with options: fact, pattern, decision, correction, idea, design, exploration
   - Status: select with options: pending, approved, archived
   - Confidence: select with options: high, medium, low
   - Scope: select with options: universal, project, temporal
   - Tags: multi_select (leave options empty; they auto-create on first use)
   - Created: date
   - Links: relation pointing to THIS SAME database (a self-relation); enable the auto-created reverse "Related to" back-link
   - Source: relation pointing to the "${SOURCES_DB_TITLE}" database (the sources database id from step A); enable the auto-created reverse back-link so each source row lists every note derived from it

Return structured output { database_id, created, sources_database_id, sources_created }.`
}

function sourceUpsertPrompt(sourcesDatabaseId, sources) {
  const list = sources.map(s => `- ingest_id=${s.ingest_id || ''} | source=${JSON.stringify(s.source || '')} | type=${s.type || ''} | class=${s.source_class || ''} | ingested=${s.date || ''} | status=${s.status || ''} | archived=${JSON.stringify(s.file || '')}`).join('\n')
  return `You upsert SOURCE rows into the Notion database id ${sourcesDatabaseId} (the "${SOURCES_DB_TITLE}" database). Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

For EACH source below (one row per ingestion event; the upsert key is ingest_id):
1. notion-query-data-sources on database ${sourcesDatabaseId} filtering the "ingest_id" rich_text property equals the source's ingest_id.
2. If a row matches, notion-update-page: set Name=source, Source URL (url; if not an http(s) URL store it as a plain value anyway), Type, Class, Ingested (date), Status, Archived (the file path). Record action="updated".
3. If no row matches, notion-create-pages in database ${sourcesDatabaseId} with the same properties. Always set the hidden "ingest_id" property to the source's ingest_id. Record action="created".
4. If a source fails, record ok=false with a short error and CONTINUE.

Sources:
${list}

Return structured output { results: [ {ingest_id, page_id, action, ok, error} ] } one per source.`
}

function upsertPrompt(databaseId, notes) {
  const list = notes.map(n => `- slug=${n.slug} | title=${JSON.stringify(n.title)} | type=${n.knowledge_type || ''} | status=${n.status || ''} | confidence=${n.confidence || ''} | scope=${n.scope || ''} | tags=${JSON.stringify(n.tags || [])} | created=${n.created || ''}`).join('\n')
  const bodies = notes.map(n => `### slug=${n.slug}\n${n.body_md || ''}`).join('\n\n---\n\n')
  return `You upsert pages into the Notion database id ${databaseId}. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}". Do NOT set the Links relation in this pass — relations are wired in a later pass.

For EACH note below:
1. notion-query-data-sources on database ${databaseId} filtering the "slug" rich_text property equals the note's slug.
2. If a page matches, notion-update-page: set Name=title, Type, Status, Confidence, Scope, Tags (multi-select), Created (date), and replace the page body with the markdown for that slug. Record action="updated". Do NOT set any raw "Source" URL/text property — the note's external origin is reached via the Source relation (wired in the relations pass).
3. If no page matches, notion-create-pages in database ${databaseId} with the same properties and the markdown body. Always set the hidden "slug" property to the note's slug. Record action="created". Do NOT set any raw "Source" URL/text property.
4. If a note fails, record ok=false with a short error and CONTINUE.

Note properties:
${list}

Note bodies (markdown; the heading "### slug=..." is a separator, not page content):
${bodies}

Return structured output { results: [ {slug, page_id, action, ok, error} ] } one per note.`
}

function relationPrompt(databaseId, items) {
  const list = items.map(it => `- slug=${it.slug} page_id=${it.page_id} links_to_page_ids=${JSON.stringify(it.target_page_ids)} source_page_id=${JSON.stringify(it.source_page_id || null)}`).join('\n')
  return `You set the "Links" self-relation AND the "Source" relation on pages in Notion database ${databaseId}. Load Notion tools in ONE ToolSearch call: "${NOTION_TOOLS}".

For EACH item below, notion-update-page on page_id and:
1. Set the "Links" relation property to exactly the list of links_to_page_ids given (replace any existing relation value). If that list is empty, set the relation to empty.
2. If source_page_id is a non-null string, set the "Source" relation property to exactly that single page-id (replace any existing value). If source_page_id is null, leave the "Source" relation empty.
Notion auto-populates the reverse back-links for both relations. If a page fails, record ok=false with a short error and CONTINUE.

In each result, record relations_set = number of Links targets set, and source_relation_set = true if you set a Source relation for that item (else false).

Items:
${list}

Return structured output { results: [ {slug, relations_set, source_relation_set, ok, error} ] } one per item.`
}

// ===== run =====
phase('EnsureDBs')
const fs = await import('node:fs')
const path = await import('node:path')
const resolvedManifest = path.isAbsolute(MANIFEST_PATH) ? MANIFEST_PATH : path.join(WD, MANIFEST_PATH)
const manifest = JSON.parse(fs.readFileSync(resolvedManifest, 'utf8'))
const notes = Array.isArray(manifest.notes) ? manifest.notes : []
const sources = Array.isArray(manifest.sources) ? manifest.sources : []
const danglingCount = Array.isArray(manifest.dangling) ? manifest.dangling.length : 0
const unmatchedCount = Array.isArray(manifest.unmatched_sources) ? manifest.unmatched_sources.length : 0
log(`Loaded ${notes.length} notes, ${sources.length} sources, ${danglingCount} dangling links, ${unmatchedCount} unmatched sources from ${resolvedManifest}`)

const ensured = await agent(ensureDbPrompt(), { label: 'ensure-dbs', phase: 'EnsureDBs', schema: ENSURE_DB_SCHEMA })
const databaseId = ensured && ensured.database_id ? ensured.database_id : null
const sourcesDatabaseId = ensured && ensured.sources_database_id ? ensured.sources_database_id : null
if (!databaseId) { throw new Error('push-to-notion: could not resolve or create the "LLM Wiki" database id.') }
if (!sourcesDatabaseId) { throw new Error('push-to-notion: could not resolve or create the "LLM Wiki Sources" database id.') }
log(`Notes DB ${databaseId} (created=${ensured.created}); Sources DB ${sourcesDatabaseId} (created=${ensured.sources_created})`)

if (DRY_RUN) {
  return {
    mode: 'dry-run',
    database_id: databaseId,
    sources_database_id: sourcesDatabaseId,
    db_created: ensured.created === true,
    sources_db_created: ensured.sources_created === true,
    would_upsert: notes.length,
    would_upsert_sources: sources.length,
    would_set_relations: notes.filter(n => Array.isArray(n.links) && n.links.length > 0).length,
    would_set_source_relations: notes.filter(n => typeof n.source_ref === 'string' && n.source_ref).length,
    dangling: danglingCount,
    unmatched_sources: unmatchedCount,
  }
}

phase('UpsertSources')
const sourceChunks = chunk(sources, UPSERT_CHUNK)
const sourceResults = []
await parallel(sourceChunks.map((c, i) => async () => {
  const r = await agent(sourceUpsertPrompt(sourcesDatabaseId, c), { label: `upsert-sources:${i + 1}/${sourceChunks.length}`, phase: 'UpsertSources', schema: SOURCE_UPSERT_SCHEMA })
  if (r && r.results) sourceResults.push(...r.results)
}))
const ingestToPage = {}
for (const r of sourceResults) { if (r.ok && r.ingest_id && r.page_id) ingestToPage[r.ingest_id] = r.page_id }
const sourcesCreated = sourceResults.filter(r => r.ok && r.action === 'created').length
const sourcesUpdated = sourceResults.filter(r => r.ok && r.action === 'updated').length

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
  const sourcePageId = (typeof n.source_ref === 'string' && n.source_ref) ? (ingestToPage[n.source_ref] || null) : null
  relationItems.push({ slug: n.slug, page_id: pageId, target_page_ids: targetIds, source_page_id: sourcePageId })
}
// Only wire items that have at least one Links target OR a resolved Source page.
const relationChunks = chunk(relationItems.filter(it => it.target_page_ids.length > 0 || it.source_page_id), RELATION_CHUNK)
const relationResults = []
await parallel(relationChunks.map((c, i) => async () => {
  const r = await agent(relationPrompt(databaseId, c), { label: `relations:${i + 1}/${relationChunks.length}`, phase: 'WireRelations', schema: RELATION_SCHEMA })
  if (r && r.results) relationResults.push(...r.results)
}))
const relationsSet = relationResults.filter(r => r.ok).reduce((acc, r) => acc + (Number(r.relations_set) || 0), 0)
const sourceRelationsSet = relationResults.filter(r => r.ok && r.source_relation_set === true).length

phase('Report')
return {
  database_id: databaseId,
  sources_database_id: sourcesDatabaseId,
  created,
  updated,
  sources_created: sourcesCreated,
  sources_updated: sourcesUpdated,
  relations_set: relationsSet,
  source_relations_set: sourceRelationsSet,
  dangling: danglingCount,
  unmatched_sources: unmatchedCount,
  dryRun: false,
  failures: upsertResults.filter(r => !r.ok).map(r => ({ slug: r.slug, error: r.error })),
  source_failures: sourceResults.filter(r => !r.ok).map(r => ({ ingest_id: r.ingest_id, error: r.error })),
}
```

- [ ] 4.2 Lint the JS for syntax errors (no pytest covers this file). From the worktree root:
  `node --check plugins/karpathy-llm-wiki/workflows/push-to-notion.js`
  → exits 0, no output. (Verifies the file parses; `export const meta` is valid ESM, and `await import(...)` is legal at the top level of the Workflow body.)

- [ ] 4.3 Documented verification step (manual, not CI). The Workflow tool is only available in a parent Claude session, so the script's runtime "test" is a `dryRun` invocation. After `kb export-notion --out output/notion-manifest.json` has produced a manifest, the runtime check is:
  `Workflow({ scriptPath: "<abs>/plugins/karpathy-llm-wiki/workflows/push-to-notion.js", args: { manifestPath: "output/notion-manifest.json", workingDir: "<abs wiki root>", dryRun: true } })`
  Expect a returned object `{ mode: "dry-run", database_id, sources_database_id, db_created, sources_db_created, would_upsert, would_upsert_sources, would_set_relations, would_set_source_relations, dangling, unmatched_sources }` with `would_upsert` equal to the manifest note count and `would_upsert_sources` equal to the manifest source count, and NO pages or source rows created/updated. Record this as the verification evidence in the implementing session's notes.

- [ ] 4.4 Commit. From the worktree root:
  `git add plugins/karpathy-llm-wiki/workflows/push-to-notion.js`
  `git commit -m "feat(karpathy-llm-wiki): add push-to-notion workflow (manifest -> Notion notes + sources DBs)"`

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

You mirror the markdown wiki into a Notion "LLM Wiki" database, plus a "LLM Wiki
Sources" database mirroring the ingested source material. This is a one-way
mirror: markdown stays the single source of truth, and edits made directly in
Notion are overwritten on the next push. Wikilinks (`[[name]]`) become a native
Notion **self-relation**, and each note gets a best-effort **Source relation**
to the source row it was derived from, giving bidirectional back-links for free.
Intended to be chained after `/kb-compile`.

## Step 1: Parse arguments

The user's input is: `$ARGUMENTS`

Extract:

- **--dry-run**: Build the manifest and ensure the Notion database, then report
  the create/update/relation counts WITHOUT writing pages.
- No flags: full push (ensure DB, upsert pages, wire relations).

## Step 2: Build the manifest

Run the deterministic exporter from the wiki root. This writes a JSON manifest
(`{"notes": [...], "dangling": [...], "sources": [...], "unmatched_sources": [...]}`)
with one entry per permanent note (resolved wikilinks in `links`, unresolved in
`dangling`, and a best-effort `source_ref`), plus one `sources` row per ingestion
event read from `raw/inbox/.manifest.json`:

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

The workflow runs several passes: ensure the "LLM Wiki" and "LLM Wiki Sources"
databases exist, upsert one source row per ingestion event keyed by the hidden
`ingest_id` property, upsert one page per note keyed by the hidden `slug`
property, then wire the `Links` self-relation and the `Source` note→source
relation. It returns counts for created / updated / sources_created /
sources_updated / relations_set / source_relations_set / dangling /
unmatched_sources.

## Step 4: Report

Present a summary using the workflow's return value:

```
## Notion Push Summary

- Notes database: <database_id> (created: yes/no)
- Sources database: <sources_database_id> (created: yes/no)
- Pages created: N
- Pages updated: N
- Source rows created: N
- Source rows updated: N
- Links relations set: N
- Source relations set: N
- Dangling links (dropped): N
- Notes with an unmatched source: N

### Next Steps
- Open the "LLM Wiki" database in Notion to browse and filter notes.
- Open a source page to see every note derived from it (the Source back-link).
- Re-run /kb-push-notion after /kb-compile to keep the mirror current.
```

## Important Notes

- The push is **idempotent**: upsert-by-slug (notes) and upsert-by-`ingest_id`
  (sources) converge, so it is always safe to re-run. No Notion page-ids are
  written back into the markdown.
- Dangling wikilinks (targets with no matching note) are dropped from relations
  and reported; they are never fatal.
- The note→source link is **best-effort**: a note's free-text `source` is matched
  against the ingest manifest by normalized string. A note whose `source` matches
  nothing gets no `Source` relation (its raw source text is still stored) and is
  counted under "unmatched source".
- If `raw/inbox/.manifest.json` is absent, there are simply no source rows and no
  `Source` relations — not an error.
- Deleted source notes (and removed manifest entries) leave their Notion page or
  source row as an orphan in v1 (logged, not pruned).
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
- [ ] F.4 Spec coverage check: confirm every spec section maps to a task — `kb export-notion` manifest + field mapping + link/dangling split (Tasks 1-3); source rows + `source_ref` + `unmatched_sources` (`_build_sources` / `_normalize_source` / `_match_source_ref` wiring in Task 1, edge cases in Task 2); notes-DB property mapping incl. the `Source` relation + Sources-DB property mapping (§2a) consumed by the DB schema prompt (Task 4 `ensureDbPrompt`); multi-pass crux ensure-DBs / upsert-sources / upsert-pages / wire-relations incl. note→source (Task 4); idempotent upsert-by-slug + upsert-by-`ingest_id` (Task 4 + command notes Task 5); dangling/orphan/unmatched-source/manifest-absent error handling (Tasks 1-2 + command notes Task 5); `/kb-push-notion` slash command (Task 5).
