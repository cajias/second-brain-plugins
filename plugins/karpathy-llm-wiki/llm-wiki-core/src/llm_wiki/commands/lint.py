"""Health checks and linting for the wiki knowledge base.

Validates frontmatter, tag compliance against the taxonomy, orphan detection,
wikilink integrity, and index staleness. Outputs structured JSON for
machine consumption or human-readable summaries.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import typer

from llm_wiki.commands.charts import _generate_all_charts
from llm_wiki.commands.migrate_frontmatter import _MIGRATION_DEFAULTS, _migrate_one
from llm_wiki.core.config import WikiConfig, load_config
from llm_wiki.core.dedup import check_duplicates_batch
from llm_wiki.core.embeddings import search_index
from llm_wiki.core.frontmatter import (
    REQUIRED_FIELDS,
    VALID_VALUES,
    dump,
    get_knowledge_type,
    parse_file,
)
from llm_wiki.core.taxonomy import load_approved_tags


WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
MAX_TAGS_PER_NOTE = 6

# Contradiction detection: a pair of notes whose cosine similarity falls in
# [CONTRADICTION_THRESHOLD, DUPLICATE_THRESHOLD) is close enough to plausibly
# disagree without being a near-duplicate -- the band most worth a human review.
CONTRADICTION_THRESHOLD = 0.85
DUPLICATE_THRESHOLD = 0.92

# difflib cutoff for mapping a rogue tag to the closest approved tag.
_ROGUE_TAG_CUTOFF = 0.6

# Timeout (seconds) for the `git status` dirty-tree probe before --apply.
_GIT_STATUS_TIMEOUT_SEC = 5


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
# Contradiction detection (read-only)
# ---------------------------------------------------------------------------


def _read_body(md_file: Path) -> str:
    """Return a note's body text, or empty string if it cannot be parsed."""
    try:
        _, body = parse_file(md_file)
    except (OSError, ValueError, KeyError):
        return ""
    return body


def _contradiction_entry(
    md_file: Path,
    match: dict[str, Any],
    threshold: float,
    seen: set[tuple[str, str]],
) -> dict[str, Any] | None:
    """Build a contradiction entry for one similarity match, or None to skip.

    Skips self-matches, near-duplicates (>= DUPLICATE_THRESHOLD), matches below
    ``threshold``, and pairs already recorded from the other direction.
    """
    score = match.get("score", 0.0)
    if score < threshold or score >= DUPLICATE_THRESHOLD:
        return None
    file_path = match.get("file_path", "")
    other = Path(file_path).stem if file_path else ""
    if not other or other == md_file.stem:
        return None
    pair = (min(md_file.stem, other), max(md_file.stem, other))
    if pair in seen:
        return None
    seen.add(pair)
    # Shape mirrors the optional `contradiction` frontmatter mapping; detection
    # only reports candidates -- it never writes the field onto notes.
    return {
        "file": md_file.name,
        "score": round(score, 4),
        "contradiction": {"status": "detected", "with": f"[[{other}]]"},
    }


def _find_contradictions(cfg: WikiConfig, threshold: float = CONTRADICTION_THRESHOLD) -> list[dict[str, Any]]:
    """Detect candidate contradictions among permanent notes.

    Embeds every note body and looks for another note whose cosine similarity
    lands in the "close but not duplicate" band. Such pairs are surfaced as
    ``detected`` candidates for a reviewer to adjudicate. Degrades to an empty
    list when no vector index is available.
    """
    permanent_dir = cfg.project_root / "wiki" / "permanent"
    if not permanent_dir.exists():
        return []
    files = sorted(permanent_dir.glob("*.md"))
    if not files:
        return []

    queries = [_read_body(f) for f in files]
    results = check_duplicates_batch(queries, cfg.db_path, cfg.table_name, threshold=threshold)

    contradictions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for md_file, res in zip(files, results, strict=True):
        for match in res.get("matches", []):
            entry = _contradiction_entry(md_file, match, threshold, seen)
            if entry is not None:
                contradictions.append(entry)
    return contradictions


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------


def _run_all_checks(cfg: WikiConfig, *, detect_contradictions: bool = False) -> dict[str, Any]:
    """Run all lint checks and return structured results.

    The ``contradictions`` key is always present for a stable JSON shape; it is
    only populated when ``detect_contradictions`` is set (the check needs the
    vector index and is comparatively expensive).
    """
    wiki_dir = cfg.project_root / "wiki"

    frontmatter = _scan_frontmatter(wiki_dir)
    graph = _build_link_graph(wiki_dir)
    orphans = _find_orphans(graph)
    broken = _find_broken_links(graph, wiki_dir)
    tags = _check_tag_compliance(wiki_dir, cfg.project_root)
    contradictions = _find_contradictions(cfg) if detect_contradictions else []

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
        "contradictions": contradictions,
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
        "contradictions": [],
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


def _print_contradictions(contradictions: list[dict[str, Any]]) -> None:
    """Print the candidate-contradictions section of the lint report."""
    if not contradictions:
        return
    typer.echo(f"\nCandidate contradictions ({len(contradictions)}):")
    for c in contradictions:
        typer.echo(f"  {c['file']} <-> {c['contradiction']['with']} (score {c['score']})")


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
    _print_contradictions(results.get("contradictions", []))

    issue_count = len(fm_issues) + len(results["broken_links"]) + len(tc["rogue"])
    if issue_count == 0:
        typer.echo("\nAll checks passed.")
    else:
        typer.echo(f"\n{issue_count} issue(s) found.")


# ---------------------------------------------------------------------------
# Smart fix-all (dry-run by default; --apply writes)
# ---------------------------------------------------------------------------


def _fix_frontmatter(permanent_dir: Path, *, apply: bool) -> list[dict[str, Any]]:
    """Fill missing canonical frontmatter defaults via the migration helper.

    Reuses ``migrate_frontmatter._migrate_one`` so the defaults match the
    one-shot migration exactly. Notes already complete are left untouched.
    """
    fixes: list[dict[str, Any]] = []
    for md_file in sorted(permanent_dir.glob("*.md")):
        try:
            meta, body = parse_file(md_file)
        except (OSError, ValueError, KeyError):
            continue
        if not meta:
            continue
        new_meta, changes = _migrate_one(meta, md_file.name, _MIGRATION_DEFAULTS)
        if not changes:
            continue
        fixes.append({"file": md_file.name, "changes": changes})
        if apply:
            md_file.write_text(dump(new_meta, body), encoding="utf-8")
    return fixes


def _remap_tags(tags: list[str], approved: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    """Map rogue tags to their closest approved tag; leave ambiguous ones as-is."""
    approved_set = set(approved)
    new_tags: list[str] = []
    changes: list[dict[str, str]] = []
    for tag in tags:
        if tag in approved_set:
            new_tags.append(tag)
            continue
        match = get_close_matches(tag, approved, n=1, cutoff=_ROGUE_TAG_CUTOFF)
        if match:
            new_tags.append(match[0])
            changes.append({"from": tag, "to": match[0]})
        else:
            new_tags.append(tag)  # ambiguous -- flagged by lint, not auto-changed
    # Preserve order while dropping any duplicate introduced by a remap.
    return list(dict.fromkeys(new_tags)), changes


def _fix_rogue_tags(permanent_dir: Path, approved: list[str], *, apply: bool) -> list[dict[str, Any]]:
    """Replace rogue tags with the closest approved tag (string similarity)."""
    if not approved:
        return []
    fixes: list[dict[str, Any]] = []
    for md_file in sorted(permanent_dir.glob("*.md")):
        try:
            meta, body = parse_file(md_file)
        except (OSError, ValueError, KeyError):
            continue
        tags = meta.get("tags")
        if not isinstance(tags, list):
            continue
        new_tags, changes = _remap_tags([str(t) for t in tags], approved)
        if not changes:
            continue
        fixes.append({"file": md_file.name, "changes": changes})
        if apply:
            meta["tags"] = new_tags
            md_file.write_text(dump(meta, body), encoding="utf-8")
    return fixes


def _top_suggestion(cfg: WikiConfig, md_file: Path, stem: str) -> str | None:
    """Return a wikilink to the most similar other note, or None (read-only)."""
    if not md_file.exists():
        return None
    body = _read_body(md_file)
    if not body:
        return None
    results = search_index(cfg.db_path, cfg.table_name, query=body, limit=3)
    for r in results:
        other = Path(r["file_path"]).stem if r.get("file_path") else ""
        if other and other != stem:
            return f"[[{other}]]"
    return None


def _report_orphans(cfg: WikiConfig, graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag orphans for manual linking, with a top-similarity suggestion when available.

    De-orphaning means adding an *inbound* link from another note, which is a
    subjective editorial choice -- so this reports rather than auto-writes.
    """
    permanent_dir = cfg.project_root / "wiki" / "permanent"
    reports: list[dict[str, Any]] = []
    for name in _find_orphans(graph):
        suggestion = _top_suggestion(cfg, permanent_dir / f"{name}.md", name)
        reports.append({"file": f"{name}.md", "suggested_link_from": suggestion})
    return reports


def _apply_all_fixes(cfg: WikiConfig, *, apply: bool) -> dict[str, Any]:
    """Run all fixers in causal order and return a structured plan.

    Writes only the two safe, deterministic phases (frontmatter defaults and
    rogue-tag replacement) and only when ``apply`` is set. Orphans and broken
    links are reported for manual review (per the lint-and-repair skill).
    """
    wiki_dir = cfg.project_root / "wiki"
    permanent_dir = wiki_dir / "permanent"
    taxonomy_path = cfg.project_root / "wiki" / "_meta" / "tag-taxonomy.md"
    approved = load_approved_tags(taxonomy_path) or []

    frontmatter_fixed = _fix_frontmatter(permanent_dir, apply=apply)
    rogue_tags_fixed = _fix_rogue_tags(permanent_dir, approved, apply=apply)

    # Build the graph after the write phases so flags reflect post-fix state.
    graph = _build_link_graph(wiki_dir)
    return {
        "mode": "apply" if apply else "dry-run",
        "frontmatter_fixed": frontmatter_fixed,
        "rogue_tags_fixed": rogue_tags_fixed,
        "orphans_flagged": _report_orphans(cfg, graph),
        "broken_links_flagged": _find_broken_links(graph, wiki_dir),
    }


def _print_fix_plan(plan: dict[str, Any]) -> None:
    """Render the smart fix-all plan with per-phase counts to stdout."""
    mode_label = "APPLIED" if plan["mode"] == "apply" else "DRY RUN (no changes written)"
    typer.echo(f"\nSmart fix-all -- {mode_label}")
    typer.echo("=" * 50)
    typer.echo(f"Frontmatter defaults filled: {len(plan['frontmatter_fixed'])}")
    typer.echo(f"Rogue tags replaced:         {len(plan['rogue_tags_fixed'])}")
    typer.echo(f"Orphans flagged (manual):    {len(plan['orphans_flagged'])}")
    typer.echo(f"Broken links flagged:        {len(plan['broken_links_flagged'])}")

    for entry in plan["frontmatter_fixed"]:
        typer.echo(f"\n  {entry['file']} (frontmatter):")
        for change in entry["changes"]:
            typer.echo(f"    - {change}")
    for entry in plan["rogue_tags_fixed"]:
        typer.echo(f"\n  {entry['file']} (tags):")
        for change in entry["changes"]:
            typer.echo(f"    - {change['from']} -> {change['to']}")

    if plan["mode"] != "apply" and (plan["frontmatter_fixed"] or plan["rogue_tags_fixed"]):
        typer.echo("\nRe-run with --apply to write these changes.")


def _warn_if_dirty(project_root: Path) -> None:
    """Warn (without aborting) when the git working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607  # `git` resolved via system PATH
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=_GIT_STATUS_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return  # not a repo / git unavailable -- can't determine, stay quiet
    if result.returncode == 0 and result.stdout.strip():
        typer.echo("Warning: git working tree is dirty; --apply will modify files in place.", err=True)


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
        help="Run smart fix-all. Previews changes unless --apply is also given.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="With --fix, write fixes to disk (default is a dry-run preview).",
    ),
    contradictions: bool = typer.Option(
        False,
        "--contradictions",
        help="Also detect candidate contradictions (requires a vector index).",
    ),
) -> None:
    """Run health checks on the wiki.

    By default runs all checks. Use --json for machine-readable output, --fix to
    preview safe auto-repairs (add --apply to write them), and --contradictions
    to surface close-but-distinct notes that may disagree.
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

    if fix:
        if apply:
            _warn_if_dirty(cfg.project_root)
        plan = _apply_all_fixes(cfg, apply=apply)
        if json_output:
            typer.echo(json.dumps(plan, indent=2))
        else:
            _print_fix_plan(plan)
        if apply:
            _auto_refresh_charts(cfg)
        return

    results = _run_all_checks(cfg, detect_contradictions=contradictions)

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        _print_lint_summary(results)


def _auto_refresh_charts(cfg: WikiConfig) -> None:
    """Run chart generation after lint fixes (best-effort)."""
    try:
        _generate_all_charts(cfg)
    except Exception as e:  # noqa: BLE001  # best-effort cosmetic refresh; convention permits logged catch-all
        typer.echo(f"Warning: chart refresh failed: {e}", err=True)
