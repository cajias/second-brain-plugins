"""Compile utilities for the LLM knowledge base.

Provides mechanical infrastructure for the /kb-compile Claude Code skill:
  - Dedup checking against the LanceDB index
  - Writing new permanent notes with proper frontmatter
  - Listing and managing the inbox manifest
  - Tag/knowledge-type validation against the approved taxonomy

This module does NOT call an LLM. The /kb-compile skill (Claude) reads raw
documents, decides what notes to create, and calls these functions for the
mechanical steps.
"""

from __future__ import annotations

import json
import random
import re
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from llm_wiki.core.config import load_config, WikiConfig
from llm_wiki.core.dedup import check_duplicate
from llm_wiki.core.taxonomy import load_taxonomy_safe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert text to a kebab-case slug suitable for filenames."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if len(text) > 80:
        text = text[:80].rsplit("-", 1)[0]
    return text


def _generate_id() -> str:
    """Generate a note ID in the format perm-YYYYMMDD-XXXXX."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_chars = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"perm-{date_str}-{random_chars}"


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def _check_dedup(query: str, cfg: WikiConfig) -> dict:
    """Check for duplicate/similar content in the LanceDB index."""
    return check_duplicate(query, cfg.db_path, cfg.table_name)


def _write_note(
    title: str,
    knowledge_type: str,
    tags: list[str],
    confidence: str,
    source: str,
    body: str,
    cfg: WikiConfig,
    dry_run: bool = False,
) -> dict:
    """Create a new permanent note with full frontmatter."""
    # Validate against taxonomy
    taxonomy_path = cfg.wiki_meta / "tag-taxonomy.md"
    taxonomy = load_taxonomy_safe(taxonomy_path)

    warnings = []
    if taxonomy["knowledge_types"] and knowledge_type not in taxonomy["knowledge_types"]:
        warnings.append(
            f"knowledge_type '{knowledge_type}' not in approved list: "
            f"{sorted(taxonomy['knowledge_types'])}"
        )

    if taxonomy["tags"]:
        invalid_tags = [t for t in tags if t not in taxonomy["tags"]]
        if invalid_tags:
            warnings.append(
                f"Tags not in approved taxonomy: {invalid_tags}. "
                f"Approved: {sorted(taxonomy['tags'])}"
            )

    if len(tags) > 6:
        warnings.append(f"Too many tags ({len(tags)}). Maximum is 6.")

    note_id = _generate_id()
    slug = _slugify(title)
    filename = f"{slug}.md"
    filepath = cfg.wiki_permanent / filename

    # Handle filename collision
    if filepath.exists() and not dry_run:
        slug = f"{slug}-{note_id.split('-')[-1]}"
        filename = f"{slug}.md"
        filepath = cfg.wiki_permanent / filename

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # Build note content with deterministic field ordering
    lines = ["---"]
    lines.append(f"id: {note_id}")
    lines.append("type: permanent")
    lines.append(f"knowledge_type: {knowledge_type}")
    lines.append("status: pending")
    lines.append(f"confidence: {confidence}")
    lines.append("scope: universal")
    lines.append("tags:")
    for tag in tags:
        lines.append(f"  - {tag}")
    lines.append(f'source: "{source}"')
    lines.append(f'created: "{now}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(body)
    lines.append("")

    note_content = "\n".join(lines)

    result = {
        "id": note_id,
        "title": title,
        "filename": filename,
        "filepath": str(filepath),
        "knowledge_type": knowledge_type,
        "tags": tags,
        "confidence": confidence,
        "warnings": warnings,
        "dry_run": dry_run,
    }

    if dry_run:
        result["preview"] = note_content
        return result

    cfg.wiki_permanent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(note_content, encoding="utf-8")

    result["written"] = True
    return result


def _list_inbox(cfg: WikiConfig) -> list[dict]:
    """List all entries in the inbox manifest."""
    manifest_path = cfg.raw_inbox / ".manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return []
    if isinstance(manifest, list):
        return manifest
    elif isinstance(manifest, dict) and "entries" in manifest:
        return manifest["entries"]
    return []


def _mark_processed(entry_id: str, cfg: WikiConfig) -> dict:
    """Update a manifest entry's status from 'pending' to 'processed'."""
    manifest_path = cfg.raw_inbox / ".manifest.json"
    if not manifest_path.exists():
        return {"success": False, "error": "Manifest file not found."}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        return {"success": False, "error": f"Could not read manifest: {e}"}

    if isinstance(manifest, list):
        entries = manifest
    elif isinstance(manifest, dict) and "entries" in manifest:
        entries = manifest["entries"]
    else:
        return {"success": False, "error": "Unexpected manifest format."}

    found = False
    for entry in entries:
        if entry.get("id") == entry_id:
            entry["status"] = "processed"
            entry["processed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            found = True
            break

    if not found:
        return {"success": False, "error": f"Entry '{entry_id}' not found in manifest."}

    try:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except IOError as e:
        return {"success": False, "error": f"Could not write manifest: {e}"}

    return {"success": True, "entry_id": entry_id, "new_status": "processed"}


_VALID_VERDICTS = {"yes", "no", "maybe"}


def _tag_candidate(
    entry_id: str,
    verdict: str,
    score: float,
    reason: str,
    suggested_type: Optional[str],
    suggested_tags: list[str],
    cfg: WikiConfig,
) -> dict:
    """Record a pre-filter verdict on a manifest entry.

    The verdict is one of "yes", "no", or "maybe". The kb-compile skill
    calls this during the lightweight first pass; the second extraction
    pass reads it back via --list-inbox --candidates-only.
    """
    if verdict not in _VALID_VERDICTS:
        return {
            "success": False,
            "error": f"Invalid verdict '{verdict}'. Must be one of: {sorted(_VALID_VERDICTS)}",
        }

    manifest_path = cfg.raw_inbox / ".manifest.json"
    if not manifest_path.exists():
        return {"success": False, "error": "Manifest file not found."}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        return {"success": False, "error": f"Could not read manifest: {e}"}

    if isinstance(manifest, list):
        entries = manifest
    elif isinstance(manifest, dict) and "entries" in manifest:
        entries = manifest["entries"]
    else:
        return {"success": False, "error": "Unexpected manifest format."}

    found = False
    for entry in entries:
        if entry.get("id") == entry_id:
            entry["candidate"] = {
                "verdict": verdict,
                "score": score,
                "reason": reason,
                "suggested_type": suggested_type,
                "suggested_tags": list(suggested_tags),
                "tagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            }
            found = True
            break

    if not found:
        return {"success": False, "error": f"Entry '{entry_id}' not found in manifest."}

    try:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except IOError as e:
        return {"success": False, "error": f"Could not write manifest: {e}"}

    return {"success": True, "entry_id": entry_id, "candidate": entry["candidate"]}


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


def compile_notes(
    check_dedup: Optional[str] = typer.Option(
        None, "--check-dedup",
        help="Check for duplicate/similar content in the index.",
    ),
    write_note: bool = typer.Option(
        False, "--write-note",
        help="Create a new permanent note.",
    ),
    list_inbox: bool = typer.Option(
        False, "--list-inbox",
        help="List pending items in the inbox manifest.",
    ),
    mark_processed: Optional[str] = typer.Option(
        None, "--mark-processed",
        help="Mark a manifest entry as processed.",
    ),
    # Tag-candidate fields (used with --tag-candidate)
    tag_candidate: Optional[str] = typer.Option(
        None, "--tag-candidate",
        help="Record a pre-filter verdict on a manifest entry (pass 1 of two-pass compile).",
    ),
    verdict: Optional[str] = typer.Option(
        None, "--verdict",
        help="Verdict for --tag-candidate: yes, no, or maybe.",
    ),
    score: Optional[float] = typer.Option(
        None, "--score",
        help="Confidence score 0.0-1.0 for --tag-candidate.",
    ),
    reason: Optional[str] = typer.Option(
        None, "--reason",
        help="Short justification for --tag-candidate verdict.",
    ),
    suggested_type: Optional[str] = typer.Option(
        None, "--suggested-type",
        help="Hint for second-pass extractor: knowledge_type to consider.",
    ),
    suggested_tags: Optional[str] = typer.Option(
        None, "--suggested-tags",
        help="Comma-separated tag hints for second-pass extractor.",
    ),
    # Note fields (used with --write-note)
    title: Optional[str] = typer.Option(None, "--title", help="Note title."),
    knowledge_type: Optional[str] = typer.Option(
        None, "--knowledge-type", help="Knowledge type (fact, pattern, decision, etc.).",
    ),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags."),
    confidence: Optional[str] = typer.Option(
        None, "--confidence", help="Confidence level: high, medium, low.",
    ),
    source: Optional[str] = typer.Option(None, "--source", help="Origin description."),
    body: Optional[str] = typer.Option(None, "--body", help="Note body content."),
    # Modifiers
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n",
        help="Preview what would be created without writing.",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="Output as JSON.",
    ),
) -> None:
    """Compile inbox notes into permanent wiki entries (mechanical parts only).

    This command handles dedup checking, note writing, inbox listing, and
    manifest management. The LLM intelligence lives in the /kb-compile
    slash command, not here.
    """
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    # Determine which mode we're in
    if check_dedup:
        result = _check_dedup(check_dedup, cfg)
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            status = result["status"]
            top = result["top_score"]
            status_labels = {
                "duplicate": "DUPLICATE (>=0.92)",
                "similar": "SIMILAR (0.80-0.91) -- review recommended",
                "unique": "UNIQUE (<0.80)",
                "error": "ERROR",
            }
            typer.echo(f"Dedup check: {status_labels.get(status, status)}")
            typer.echo(f"Top similarity score: {top:.4f}")
            if result.get("message"):
                typer.echo(f"Note: {result['message']}")
            if result["matches"]:
                typer.echo("\nClosest matches:")
                for m in result["matches"]:
                    typer.echo(f"  - {m['title']} (score: {m['score']:.4f})")
                    typer.echo(f"    {m['file_path']}")

    elif write_note:
        # Validate required fields
        missing = []
        if not title:
            missing.append("--title")
        if not knowledge_type:
            missing.append("--knowledge-type")
        if not tags:
            missing.append("--tags")
        if not confidence:
            missing.append("--confidence")
        if not source:
            missing.append("--source")
        if not body:
            missing.append("--body")
        if missing:
            typer.echo(f"Error: --write-note requires: {', '.join(missing)}", err=True)
            raise typer.Exit(code=1)

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        result = _write_note(
            title=title,
            knowledge_type=knowledge_type,
            tags=tag_list,
            confidence=confidence,
            source=source,
            body=body,
            cfg=cfg,
            dry_run=dry_run,
        )

        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            if result.get("warnings"):
                for w in result["warnings"]:
                    typer.echo(f"WARNING: {w}")

            if dry_run:
                typer.echo(f"\n[DRY RUN] Would create note:")
                typer.echo(f"  ID:       {result['id']}")
                typer.echo(f"  Title:    {result['title']}")
                typer.echo(f"  File:     {result['filepath']}")
                typer.echo(f"  Type:     {result['knowledge_type']}")
                typer.echo(f"  Tags:     {result['tags']}")
                typer.echo(f"  Confidence: {result['confidence']}")
                if result.get("preview"):
                    typer.echo(f"\n--- Preview ---")
                    typer.echo(result["preview"])
                    typer.echo(f"--- End Preview ---")
            else:
                typer.echo(f"Created note: {result['filepath']}")
                typer.echo(f"  ID:   {result['id']}")
                typer.echo(f"  Type: {result['knowledge_type']}")
                typer.echo(f"  Tags: {result['tags']}")

        # Auto-refresh charts after writing a note (unless dry run)
        if not dry_run and result.get("written"):
            _auto_refresh_charts(cfg)

    elif list_inbox:
        entries = _list_inbox(cfg)
        if json_output:
            typer.echo(json.dumps(entries, indent=2))
        else:
            if not entries:
                typer.echo("Inbox is empty. No pending items.")
            else:
                pending = [e for e in entries if e.get("status") == "pending"]
                typer.echo(f"Inbox: {len(entries)} total, {len(pending)} pending\n")
                for entry in entries:
                    status_marker = "[x]" if entry.get("status") == "processed" else "[ ]"
                    typer.echo(f"  {status_marker} {entry.get('id', 'no-id')}")
                    typer.echo(f"      source: {entry.get('source', 'unknown')}")
                    typer.echo(f"      type:   {entry.get('type', 'unknown')}")
                    typer.echo(f"      date:   {entry.get('date', entry.get('ingested_at', 'unknown'))}")
                    typer.echo(f"      status: {entry.get('status', 'unknown')}")
                    if entry.get("file"):
                        typer.echo(f"      file:   {entry['file']}")
                    typer.echo("")

    elif mark_processed:
        result = _mark_processed(mark_processed, cfg)
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            if result["success"]:
                typer.echo(f"Marked '{mark_processed}' as processed.")
            else:
                typer.echo(f"Error: {result['error']}", err=True)
                raise typer.Exit(code=1)

    elif tag_candidate:
        if not verdict:
            typer.echo("Error: --tag-candidate requires --verdict", err=True)
            raise typer.Exit(code=1)
        if score is None:
            typer.echo("Error: --tag-candidate requires --score", err=True)
            raise typer.Exit(code=1)
        if not reason:
            typer.echo("Error: --tag-candidate requires --reason", err=True)
            raise typer.Exit(code=1)

        tag_list = (
            [t.strip() for t in suggested_tags.split(",") if t.strip()]
            if suggested_tags else []
        )
        result = _tag_candidate(
            entry_id=tag_candidate,
            verdict=verdict,
            score=score,
            reason=reason,
            suggested_type=suggested_type,
            suggested_tags=tag_list,
            cfg=cfg,
        )

        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            if result["success"]:
                cand = result["candidate"]
                typer.echo(
                    f"Tagged '{tag_candidate}' as candidate "
                    f"(verdict={cand['verdict']}, score={cand['score']:.2f})"
                )
                typer.echo(f"  reason: {cand['reason']}")
                if cand.get("suggested_type"):
                    typer.echo(f"  suggested_type: {cand['suggested_type']}")
                if cand.get("suggested_tags"):
                    typer.echo(f"  suggested_tags: {cand['suggested_tags']}")
            else:
                typer.echo(f"Error: {result['error']}", err=True)
                raise typer.Exit(code=1)

    else:
        typer.echo(
            "Error: Specify one of --check-dedup, --write-note, --list-inbox, --mark-processed, or --tag-candidate",
            err=True,
        )
        raise typer.Exit(code=1)


def _auto_refresh_charts(cfg: WikiConfig) -> None:
    """Run chart generation after compile operations."""
    try:
        from llm_wiki.commands.charts import _generate_all_charts
        _generate_all_charts(cfg)
    except Exception:
        pass  # Charts are best-effort
