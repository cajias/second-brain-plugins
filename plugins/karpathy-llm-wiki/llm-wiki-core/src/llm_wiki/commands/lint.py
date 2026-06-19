"""Health checks and linting for the wiki knowledge base.

Validates frontmatter, tag compliance against the taxonomy, orphan detection,
wikilink integrity, and index staleness. Outputs structured JSON for
machine consumption or human-readable summaries.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import typer

from llm_wiki.commands.charts import _generate_all_charts
from llm_wiki.core.config import WikiConfig, load_config
from llm_wiki.core.frontmatter import (
    REQUIRED_FIELDS,
    VALID_VALUES,
    get_knowledge_type,
    parse_file,
)
from llm_wiki.core.taxonomy import load_approved_tags


if TYPE_CHECKING:
    from pathlib import Path


WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
MAX_TAGS_PER_NOTE = 6


# ---------------------------------------------------------------------------
# Scan functions (ported from kb_lint.py)
# ---------------------------------------------------------------------------


def _collect_invalid_values(fm: dict[str, Any]) -> dict[str, Any]:
    """Return a map of fields whose values fall outside the allowed enum."""
    invalid: dict[str, Any] = {}
    for field, allowed in VALID_VALUES.items():
        if field in fm and fm[field] is not None:
            val = str(fm[field])
            if val not in allowed:
                invalid[field] = {"got": val, "expected": allowed}
    return invalid


def _build_frontmatter_entry(md_file: Path) -> dict[str, Any]:
    """Build a single frontmatter scan entry for one note file."""
    try:
        fm, _ = parse_file(md_file)
    except (OSError, ValueError, KeyError):
        fm = None

    entry: dict[str, Any] = {
        "file": md_file.name,
        "path": str(md_file),
        "has_frontmatter": bool(fm),
        "fields_present": [],
        "fields_missing": [],
        "tags": [],
        "invalid_values": {},
    }

    if not fm:
        entry["fields_missing"] = [*REQUIRED_FIELDS, "knowledge_type"]
        return entry

    for field in REQUIRED_FIELDS:
        if field in fm and fm[field] is not None:
            entry["fields_present"].append(field)
        else:
            entry["fields_missing"].append(field)

    # Either-or rule: knowledge_type may live in the `knowledge_type` key
    # (canonical schema) or as the value of the `type` key (simplified
    # schema). If resolvable under either name, treat as present.
    if get_knowledge_type(fm) is not None:
        entry["fields_present"].append("knowledge_type")
    else:
        entry["fields_missing"].append("knowledge_type")

    if isinstance(fm.get("tags"), list):
        entry["tags"] = [str(t) for t in fm["tags"]]

    entry["invalid_values"] = _collect_invalid_values(fm)

    if len(entry["tags"]) > MAX_TAGS_PER_NOTE:
        entry["invalid_values"]["tags"] = {
            "got": f"{len(entry['tags'])} tags",
            "expected": f"at most {MAX_TAGS_PER_NOTE}",
        }

    return entry


def _scan_frontmatter(wiki_dir: Path) -> list[dict[str, Any]]:
    """Scan all permanent notes for frontmatter completeness and validity."""
    permanent_dir = wiki_dir / "permanent"
    if not permanent_dir.exists():
        return []

    return [_build_frontmatter_entry(md_file) for md_file in sorted(permanent_dir.glob("*.md"))]


def _extract_wikilinks(filepath: Path) -> list[dict[str, Any]]:
    """Return list of {target, line} for every [[wikilink]] in the file."""
    links: list[dict[str, Any]] = []
    try:
        lines_text = filepath.read_text(encoding="utf-8").splitlines()
    except OSError:
        return links

    for i, line in enumerate(lines_text, start=1):
        for match in WIKILINK_PATTERN.finditer(line):
            target = match.group(1).strip()
            links.append({"target": target, "line": i})
    return links


def _build_link_graph(wiki_dir: Path) -> dict[str, Any]:
    """Build a wikilink graph for all permanent notes."""
    permanent_dir = wiki_dir / "permanent"
    nodes: dict[str, dict[str, Any]] = {}
    all_links: list[dict[str, Any]] = []

    if not permanent_dir.exists():
        return {"nodes": nodes, "all_links": all_links}

    for md_file in sorted(permanent_dir.glob("*.md")):
        name = md_file.stem
        nodes[name] = {"links_to": [], "linked_from": []}

    for md_file in sorted(permanent_dir.glob("*.md")):
        source = md_file.stem
        wikilinks = _extract_wikilinks(md_file)
        for wl in wikilinks:
            target = wl["target"]
            nodes[source]["links_to"].append(target)
            all_links.append(
                {
                    "source": md_file.name,
                    "target": target,
                    "line": wl["line"],
                }
            )
            if target in nodes:
                nodes[target]["linked_from"].append(source)

    return {"nodes": nodes, "all_links": all_links}


def _find_orphans(graph: dict[str, Any]) -> list[str]:
    """Find notes with zero inlinks."""
    orphans = [name for name, data in graph["nodes"].items() if len(data["linked_from"]) == 0]
    return sorted(orphans)


def _find_broken_links(graph: dict[str, Any], wiki_dir: Path) -> list[dict[str, Any]]:
    """Find wikilinks that point to non-existent files."""
    permanent_dir = wiki_dir / "permanent"
    existing: set[str] = set()
    if permanent_dir.exists():
        existing = {f.stem for f in permanent_dir.glob("*.md")}

    return [link for link in graph["all_links"] if link["target"] not in existing]


def _check_tag_compliance(wiki_dir: Path, root: Path) -> dict[str, Any]:
    """Check all notes' tags against the approved taxonomy."""
    taxonomy_path = root / "wiki" / "_meta" / "tag-taxonomy.md"
    approved = load_approved_tags(taxonomy_path)
    result: dict[str, Any] = {
        "approved_tags": approved or [],
        "taxonomy_found": approved is not None,
        "rogue": [],
        "compliant": [],
        "over_limit": [],
    }

    if approved is None:
        return result

    approved_set = set(approved)
    permanent_dir = wiki_dir / "permanent"
    if not permanent_dir.exists():
        return result

    for md_file in sorted(permanent_dir.glob("*.md")):
        try:
            fm, _ = parse_file(md_file)
        except (OSError, ValueError, KeyError):
            continue

        tags = fm.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t) for t in tags]

        rogue_tags = [t for t in tags if t not in approved_set]
        if rogue_tags:
            for rt in rogue_tags:
                result["rogue"].append({"file": md_file.name, "tag": rt})
        else:
            result["compliant"].append({"file": md_file.name, "tags": tags})

        if len(tags) > MAX_TAGS_PER_NOTE:
            result["over_limit"].append(
                {
                    "file": md_file.name,
                    "count": len(tags),
                }
            )

    return result


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------


def _run_all_checks(cfg: WikiConfig) -> dict[str, Any]:
    """Run all lint checks and return structured results."""
    wiki_dir = cfg.project_root / "wiki"

    frontmatter = _scan_frontmatter(wiki_dir)
    graph = _build_link_graph(wiki_dir)
    orphans = _find_orphans(graph)
    broken = _find_broken_links(graph, wiki_dir)
    tags = _check_tag_compliance(wiki_dir, cfg.project_root)

    permanent_dir = wiki_dir / "permanent"
    note_count = len(list(permanent_dir.glob("*.md"))) if permanent_dir.exists() else 0

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "note_count": note_count,
        "frontmatter": frontmatter,
        "link_graph": {
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["all_links"]),
            "nodes": {
                name: {
                    "links_to": data["links_to"],
                    "linked_from": data["linked_from"],
                }
                for name, data in graph["nodes"].items()
            },
        },
        "orphans": orphans,
        "broken_links": broken,
        "tag_compliance": tags,
    }


def _empty_lint_result() -> dict[str, Any]:
    """Build the lint result payload for a missing wiki directory."""
    return {
        "error": None,
        "timestamp": datetime.now(UTC).isoformat(),
        "note_count": 0,
        "frontmatter": [],
        "link_graph": {"node_count": 0, "edge_count": 0, "nodes": {}},
        "orphans": [],
        "broken_links": [],
        "tag_compliance": {
            "approved_tags": [],
            "taxonomy_found": False,
            "rogue": [],
            "compliant": [],
            "over_limit": [],
        },
        "message": "Wiki directory not found. Nothing to lint.",
    }


def _print_frontmatter_issues(fm_issues: list[dict[str, Any]]) -> None:
    """Print the frontmatter-issues section of the lint report."""
    if not fm_issues:
        return
    typer.echo(f"\nFrontmatter issues ({len(fm_issues)}):")
    for f in fm_issues:
        typer.echo(f"  {f['file']}:")
        if f["fields_missing"]:
            typer.echo(f"    missing: {', '.join(f['fields_missing'])}")
        if f["invalid_values"]:
            for field, detail in f["invalid_values"].items():
                typer.echo(f"    invalid {field}: {detail['got']}")


def _print_orphans_and_links(results: dict[str, Any]) -> None:
    """Print orphan and broken-link sections."""
    if results["orphans"]:
        typer.echo(f"\nOrphans ({len(results['orphans'])}):")
        for o in results["orphans"]:
            typer.echo(f"  - {o}")
    if results["broken_links"]:
        typer.echo(f"\nBroken links ({len(results['broken_links'])}):")
        for bl in results["broken_links"]:
            typer.echo(f"  {bl['source']}:{bl['line']} -> [[{bl['target']}]]")


def _print_tag_compliance(tc: dict[str, Any]) -> None:
    """Print rogue-tag and over-limit sections of the lint report."""
    if tc["rogue"]:
        typer.echo(f"\nRogue tags ({len(tc['rogue'])}):")
        for r in tc["rogue"]:
            typer.echo(f"  {r['file']}: {r['tag']}")
    if tc["over_limit"]:
        typer.echo("\nOver tag limit:")
        for ol in tc["over_limit"]:
            typer.echo(f"  {ol['file']}: {ol['count']} tags")


def _print_lint_summary(results: dict[str, Any]) -> None:
    """Render the human-readable lint report to stdout."""
    typer.echo(f"\nKB Lint Report ({results['timestamp'][:19]})")
    typer.echo(f"{'=' * 50}\n")
    typer.echo(f"Total notes: {results['note_count']}")
    typer.echo(f"Link graph: {results['link_graph']['node_count']} nodes, {results['link_graph']['edge_count']} edges")

    fm_issues = [f for f in results["frontmatter"] if f["fields_missing"] or f["invalid_values"]]
    tc = results["tag_compliance"]

    _print_frontmatter_issues(fm_issues)
    _print_orphans_and_links(results)
    _print_tag_compliance(tc)

    issue_count = len(fm_issues) + len(results["broken_links"]) + len(tc["rogue"])
    if issue_count == 0:
        typer.echo("\nAll checks passed.")
    else:
        typer.echo(f"\n{issue_count} issue(s) found.")


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


def lint(
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output all checks as JSON.",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Auto-fix issues where possible.",
    ),
) -> None:
    """Run health checks on the wiki.

    By default runs all checks. Use --json for machine-readable output.
    """
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    wiki_dir = cfg.project_root / "wiki"
    if not wiki_dir.exists():
        empty_result = _empty_lint_result()
        if json_output:
            typer.echo(json.dumps(empty_result, indent=2))
        else:
            typer.echo("Wiki directory not found. Nothing to lint.")
        return

    results = _run_all_checks(cfg)

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        _print_lint_summary(results)

    # Auto-refresh charts after lint --fix
    if fix:
        _auto_refresh_charts(cfg)


def _auto_refresh_charts(cfg: WikiConfig) -> None:
    """Run chart generation after lint fixes (best-effort)."""
    try:
        _generate_all_charts(cfg)
    except Exception as e:  # noqa: BLE001  # best-effort cosmetic refresh; convention permits logged catch-all
        typer.echo(f"Warning: chart refresh failed: {e}", err=True)
