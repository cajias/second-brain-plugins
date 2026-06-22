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

    matches = [s for s in sources if s.get("source") and _normalize_source(str(s["source"])) == target]
    if not matches:
        return None
    # Relies on ISO-8601 date strings being lexicographically sortable; a non-ISO date format would break the latest-wins tie-break.
    best = max(matches, key=lambda s: str(s.get("date") or ""))
    ingest_id = best.get("ingest_id")
    return str(ingest_id) if ingest_id is not None else None


def _build_note_entry(
    md_file: Path, links_to: list[str], existing: set[str]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
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
