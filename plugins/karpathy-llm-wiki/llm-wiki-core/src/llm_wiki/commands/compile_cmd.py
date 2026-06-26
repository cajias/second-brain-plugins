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
import logging
import secrets
import string
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from llm_wiki.commands.charts import _generate_all_charts
from llm_wiki.core.config import WikiConfig, load_config
from llm_wiki.core.dedup import check_duplicate, check_duplicates_batch, resolve_threshold
from llm_wiki.core.frontmatter import MAX_TAGS, dump, parse_file
from llm_wiki.core.taxonomy import load_taxonomy_safe, validate_tags
from llm_wiki.core.text import slugify


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOTE_ID_RANDOM_LEN = 5
_VALID_VERDICTS = {"yes", "no", "maybe"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_id() -> str:
    """Generate a note ID in the format perm-YYYYMMDD-XXXXX."""
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    alphabet = string.ascii_lowercase + string.digits
    random_chars = "".join(secrets.choice(alphabet) for _ in range(_NOTE_ID_RANDOM_LEN))
    return f"perm-{date_str}-{random_chars}"


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def _check_dedup(query: str, cfg: WikiConfig, threshold: float) -> dict[str, Any]:
    """Check for duplicate/similar content in the LanceDB index."""
    result = check_duplicate(query, cfg.db_path, cfg.table_name, threshold=threshold)
    result["threshold"] = threshold
    return result


def _resolve_write_target(
    base_slug: str, note_id: str, cfg: WikiConfig, force_overwrite: bool
) -> tuple[str, Path, str | None]:
    """Resolve the final (filename, filepath) for a note, honoring existing files.

    Returns ``(filename, filepath, skip_reason)``. When ``skip_reason`` is not
    None the caller must skip the write: the target exists, is human-reviewed,
    and ``force_overwrite`` was not set. Evaluated independently of dry-run so a
    preview reports the same skip a real run would take.

    Collision policy when a same-slug file already exists:
      - reviewed + not force  -> skip (return a reason)
      - not force             -> write a renamed ``slug-<id>.md`` sibling
      - force                 -> overwrite the target in place
    """
    filename = f"{base_slug}.md"
    filepath = cfg.wiki_permanent / filename
    if not filepath.exists():
        return filename, filepath, None

    existing_meta, _ = parse_file(filepath)
    if str(existing_meta.get("reviewed")).lower() == "true" and not force_overwrite:
        reason = (
            f"Target '{filename}' is reviewed (reviewed: "
            f"{existing_meta.get('reviewed')}); not overwriting. "
            "Pass --force-overwrite to overwrite it in place."
        )
        return filename, filepath, reason

    if not force_overwrite:
        slug = f"{base_slug}-{note_id.rsplit('-', maxsplit=1)[-1]}"
        filename = f"{slug}.md"
        filepath = cfg.wiki_permanent / filename

    return filename, filepath, None


def _write_note(  # noqa: PLR0913  # Note fields are intrinsic to the call signature
    title: str,
    knowledge_type: str,
    tags: list[str],
    confidence: str,
    source: str,
    body: str,
    cfg: WikiConfig,
    dry_run: bool = False,
    force_overwrite: bool = False,
) -> dict[str, Any]:
    """Create a new permanent note with full frontmatter."""
    taxonomy_path = cfg.wiki_meta / "tag-taxonomy.md"
    taxonomy = load_taxonomy_safe(taxonomy_path)

    warnings: list[str] = []
    if taxonomy["knowledge_types"] and knowledge_type not in taxonomy["knowledge_types"]:
        warnings.append(
            f"knowledge_type '{knowledge_type}' not in approved list: {sorted(taxonomy['knowledge_types'])}"
        )
    invalid = validate_tags(tags, taxonomy_path)
    if invalid:
        warnings.append(f"Tags not in approved taxonomy: {invalid}. Approved: {sorted(taxonomy['tags'])}")
    if len(tags) > MAX_TAGS:
        warnings.append(f"Too many tags ({len(tags)}). Maximum is {MAX_TAGS}.")

    note_id = _generate_id()
    slug = slugify(title) or note_id
    filename, filepath, skip_reason = _resolve_write_target(slug, note_id, cfg, force_overwrite)

    result: dict[str, Any] = {
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

    if skip_reason is not None:
        result["skipped"] = True
        result["reason"] = skip_reason
        return result

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

    if dry_run:
        result["preview"] = note_content
        return result

    cfg.wiki_permanent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(note_content, encoding="utf-8")

    result["written"] = True
    return result


def _merge_note(
    file_path: Path,
    body: str,
    cfg: WikiConfig,  # noqa: ARG001  # part of the contracted (file_path, body, cfg) signature
    dry_run: bool = False,
) -> dict[str, Any]:
    """Append a dated ``## Update`` section to an existing note, preserving frontmatter."""
    if not file_path.exists():
        return {"success": False, "error": f"Merge target not found: {file_path}"}

    metadata, existing_body = parse_file(file_path)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    section = f"\n## Update ({date_str})\n\n{body}\n"
    new_body = existing_body.rstrip("\n") + "\n" + section
    merged = dump(metadata, new_body)

    result: dict[str, Any] = {
        "success": True,
        "filepath": str(file_path),
        "dry_run": dry_run,
    }
    if dry_run:
        result["preview"] = merged
        return result

    file_path.write_text(merged, encoding="utf-8")
    result["written"] = True
    return result


def _list_inbox(cfg: WikiConfig) -> list[dict[str, Any]]:
    """List all entries in the inbox manifest."""
    manifest_path = cfg.raw_inbox / ".manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(manifest, list):
        return list(manifest)
    if isinstance(manifest, dict) and "entries" in manifest:
        entries = manifest["entries"]
        if isinstance(entries, list):
            return list(entries)
    return []


def _load_manifest_entries(manifest_path: Path) -> tuple[Any | None, list[dict[str, Any]] | None, str | None]:
    """Load + normalize the manifest into a (manifest, entries, error) tuple.

    Returns (manifest, entries, None) on success, or (None, None, error_message) on failure.
    """
    if not manifest_path.exists():
        return None, None, "Manifest file not found."
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, None, f"Could not read manifest: {e}"

    if isinstance(manifest, list):
        entries = manifest
    elif isinstance(manifest, dict) and "entries" in manifest:
        entries = manifest["entries"]
    else:
        return None, None, "Unexpected manifest format."

    return manifest, entries, None


def _write_manifest(manifest: object, path: Path) -> None:
    """Atomically write the manifest: write to a temp file then replace.

    ``Path.replace`` is atomic on the same filesystem, so a crash mid-write
    cannot leave a truncated manifest behind.
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _mark_processed_batch(entry_ids: list[str], cfg: WikiConfig) -> dict[str, Any]:
    """Mark many manifest entries as processed in a single read-modify-write.

    Loads the manifest once, marks each requested id that exists, and writes the
    file once (only if at least one id matched). Existing manifest keys are
    preserved.

    Returns ``{"success", "processed", "not_found"}`` where ``success`` is True
    iff at least one requested id was found and marked.
    """
    manifest_path = cfg.raw_inbox / ".manifest.json"
    manifest, entries, err = _load_manifest_entries(manifest_path)
    if err is not None or entries is None:
        return {"success": False, "processed": [], "not_found": list(entry_ids), "error": err}

    by_id = {entry.get("id"): entry for entry in entries}
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    processed: list[str] = []
    not_found: list[str] = []
    for entry_id in entry_ids:
        entry = by_id.get(entry_id)
        if entry is None:
            not_found.append(entry_id)
            continue
        entry["status"] = "processed"
        entry["processed_at"] = now
        processed.append(entry_id)

    if not processed:
        return {"success": False, "processed": [], "not_found": not_found}

    try:
        _write_manifest(manifest, manifest_path)
    except OSError as e:
        return {"success": False, "processed": [], "not_found": not_found, "error": f"Could not write manifest: {e}"}

    return {"success": True, "processed": processed, "not_found": not_found}


def _validate_candidate_inputs(
    verdict: str, score: float, suggested_type: str | None, cfg: WikiConfig
) -> tuple[str | None, list[str]]:
    """Validate verdict/score/suggested_type. Returns (error_message, warnings)."""
    warnings: list[str] = []
    if verdict not in _VALID_VERDICTS:
        return f"Invalid verdict '{verdict}'. Must be one of: {sorted(_VALID_VERDICTS)}", warnings
    if not 0.0 <= score <= 1.0:
        return f"Invalid score {score}. Must be between 0.0 and 1.0 inclusive.", warnings

    if suggested_type is not None:
        taxonomy = load_taxonomy_safe(cfg.wiki_meta / "tag-taxonomy.md")
        if taxonomy["knowledge_types"] and suggested_type not in taxonomy["knowledge_types"]:
            warnings.append(
                f"suggested_type '{suggested_type}' not in approved list: {sorted(taxonomy['knowledge_types'])}"
            )

    return None, warnings


def _tag_candidate(  # Verdict fields are intrinsic to the call signature
    entry_id: str,
    verdict: str,
    score: float,
    reason: str,
    suggested_type: str | None,
    suggested_tags: list[str],
    cfg: WikiConfig,
) -> dict[str, Any]:
    """Record a pre-filter verdict on a manifest entry.

    The verdict is one of "yes", "no", or "maybe". The kb-compile skill
    calls this during the lightweight first pass; the second extraction
    pass reads it back via --list-inbox --candidates-only.
    """
    err, warnings = _validate_candidate_inputs(verdict, score, suggested_type, cfg)
    if err is not None:
        return {"success": False, "error": err}

    manifest_path = cfg.raw_inbox / ".manifest.json"
    manifest, entries, load_err = _load_manifest_entries(manifest_path)
    if load_err is not None or entries is None:
        return {"success": False, "error": load_err}

    found_entry: dict[str, Any] | None = None
    for entry in entries:
        if entry.get("id") == entry_id:
            entry["candidate"] = {
                "verdict": verdict,
                "score": score,
                "reason": reason,
                "suggested_type": suggested_type,
                "suggested_tags": list(suggested_tags),
                "tagged_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            }
            found_entry = entry
            break

    if found_entry is None:
        return {"success": False, "error": f"Entry '{entry_id}' not found in manifest."}

    try:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError as e:
        return {"success": False, "error": f"Could not write manifest: {e}"}

    result: dict[str, Any] = {"success": True, "entry_id": entry_id, "candidate": found_entry["candidate"]}
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Sub-command handlers (one per CLI mode)
# ---------------------------------------------------------------------------


def _print_dedup_result(result: dict[str, Any]) -> None:
    """Render a dedup-check result as text."""
    status = result["status"]
    top = result["top_score"]
    threshold = result.get("threshold", 0.92)
    status_labels = {
        "duplicate": f"DUPLICATE (>={threshold:.2f})",
        "similar": "SIMILAR (0.80-threshold) -- review recommended",
        "unique": "UNIQUE (<0.80)",
        "error": "ERROR",
    }
    typer.echo(f"Dedup check: {status_labels.get(status, status)}")
    typer.echo(f"Top similarity score: {top:.4f}")
    typer.echo(f"Threshold used: {threshold:.4f}")
    if result.get("message"):
        typer.echo(f"Note: {result['message']}")
    if result["matches"]:
        typer.echo("\nClosest matches:")
        for m in result["matches"]:
            typer.echo(f"  - {m['title']} (score: {m['score']:.4f})")
            typer.echo(f"    {m['file_path']}")


def _handle_check_dedup(query: str, cfg: WikiConfig, threshold: float, json_output: bool) -> None:
    result = _check_dedup(query, cfg, threshold)
    if json_output:
        typer.echo(json.dumps(result, indent=2))
    else:
        _print_dedup_result(result)


def _read_dedup_batch_items(path: str) -> list[dict[str, Any]]:
    """Read + validate the batch-dedup input (file path, or '-' for stdin).

    Expects a JSON list of objects each having ``key`` and ``query``. Raises
    ``typer.Exit(code=1)`` with a clear message on any malformed input.
    """
    try:
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as e:
        typer.echo(f"Error: could not read batch input: {e}", err=True)
        raise typer.Exit(code=1) from e

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        typer.echo(f"Error: invalid JSON in batch input: {e}", err=True)
        raise typer.Exit(code=1) from e

    if not isinstance(items, list):
        typer.echo("Error: batch input must be a JSON array of {key, query} objects.", err=True)
        raise typer.Exit(code=1)

    for item in items:
        if not isinstance(item, dict) or "key" not in item or "query" not in item:
            typer.echo("Error: each batch item must be an object with 'key' and 'query'.", err=True)
            raise typer.Exit(code=1)

    return items


def _handle_check_dedup_batch(path: str, cfg: WikiConfig, json_output: bool) -> None:
    items = _read_dedup_batch_items(path)
    queries = [str(item["query"]) for item in items]
    results = check_duplicates_batch(queries, cfg.db_path, cfg.table_name)

    output = [
        {
            "key": item["key"],
            "status": res["status"],
            "top_score": res["top_score"],
            "matches": res["matches"],
        }
        for item, res in zip(items, results, strict=True)
    ]

    # This subcommand is machine-facing, so it always emits JSON. --json picks
    # the compact form; otherwise the same array is pretty-printed.
    typer.echo(json.dumps(output) if json_output else json.dumps(output, indent=2))


def _validate_write_note_fields(  # one parameter per CLI flag
    title: str | None,
    knowledge_type: str | None,
    tags: str | None,
    confidence: str | None,
    source: str | None,
    body: str | None,
) -> tuple[str, str, str, str, str, str]:
    """Ensure all required --write-note fields are present; return narrowed strings."""
    missing = [
        name
        for name, value in (
            ("--title", title),
            ("--knowledge-type", knowledge_type),
            ("--tags", tags),
            ("--confidence", confidence),
            ("--source", source),
            ("--body", body),
        )
        if not value
    ]
    if (
        missing
        or title is None
        or knowledge_type is None
        or tags is None
        or confidence is None
        or source is None
        or body is None
    ):
        typer.echo(f"Error: --write-note requires: {', '.join(missing)}", err=True)
        raise typer.Exit(code=1)
    return title, knowledge_type, tags, confidence, source, body


def _print_write_result(result: dict[str, Any], dry_run: bool) -> None:
    """Render a write-note result as human-readable text."""
    if result.get("skipped"):
        typer.echo(f"SKIPPED: {result['reason']}")
        return

    if result.get("warnings"):
        for w in result["warnings"]:
            typer.echo(f"WARNING: {w}")

    if dry_run:
        typer.echo("\n[DRY RUN] Would create note:")
        typer.echo(f"  ID:       {result['id']}")
        typer.echo(f"  Title:    {result['title']}")
        typer.echo(f"  File:     {result['filepath']}")
        typer.echo(f"  Type:     {result['knowledge_type']}")
        typer.echo(f"  Tags:     {result['tags']}")
        typer.echo(f"  Confidence: {result['confidence']}")
        if result.get("preview"):
            typer.echo("\n--- Preview ---")
            typer.echo(result["preview"])
            typer.echo("--- End Preview ---")
    else:
        typer.echo(f"Created note: {result['filepath']}")
        typer.echo(f"  ID:   {result['id']}")
        typer.echo(f"  Type: {result['knowledge_type']}")
        typer.echo(f"  Tags: {result['tags']}")


def _handle_write_note(  # noqa: PLR0913  # Each note field is a discrete CLI input
    title: str | None,
    knowledge_type: str | None,
    tags: str | None,
    confidence: str | None,
    source: str | None,
    body: str | None,
    cfg: WikiConfig,
    dry_run: bool,
    json_output: bool,
    force_overwrite: bool = False,
) -> None:
    valid_title, valid_kt, valid_tags, valid_conf, valid_source, valid_body = _validate_write_note_fields(
        title, knowledge_type, tags, confidence, source, body
    )
    tag_list = [t.strip() for t in valid_tags.split(",") if t.strip()]
    result = _write_note(
        title=valid_title,
        knowledge_type=valid_kt,
        tags=tag_list,
        confidence=valid_conf,
        source=valid_source,
        body=valid_body,
        cfg=cfg,
        dry_run=dry_run,
        force_overwrite=force_overwrite,
    )

    if json_output:
        typer.echo(json.dumps(result, indent=2))
    else:
        _print_write_result(result, dry_run)

    if not dry_run and result.get("written"):
        _auto_refresh_charts(cfg)


def _print_merge_result(result: dict[str, Any], dry_run: bool) -> None:
    """Render a merge-note result as human-readable text."""
    if not result.get("success"):
        typer.echo(f"Error: {result['error']}", err=True)
        return
    if dry_run:
        typer.echo(f"[DRY RUN] Would append update to {result['filepath']}")
        if result.get("preview"):
            typer.echo("\n--- Preview ---")
            typer.echo(result["preview"])
            typer.echo("--- End Preview ---")
    else:
        typer.echo(f"Merged update into {result['filepath']}")


def _handle_merge_note(merge_into: str, body: str | None, cfg: WikiConfig, dry_run: bool, json_output: bool) -> None:
    if not body:
        typer.echo("Error: --merge-into requires --body", err=True)
        raise typer.Exit(code=1)
    result = _merge_note(Path(merge_into), body, cfg, dry_run=dry_run)

    if json_output:
        typer.echo(json.dumps(result, indent=2))
    else:
        _print_merge_result(result, dry_run)

    if not result.get("success"):
        raise typer.Exit(code=1)
    if not dry_run and result.get("written"):
        _auto_refresh_charts(cfg)


def _filter_candidate_entries(entries: list[dict[str, Any]], include_maybe: bool) -> list[dict[str, Any]]:
    """Filter entries to those tagged verdict=yes (and verdict=maybe if include_maybe)."""
    allowed = {"yes"} | ({"maybe"} if include_maybe else set())
    return [e for e in entries if isinstance(e.get("candidate"), dict) and e["candidate"].get("verdict") in allowed]


def _print_inbox_entries(entries: list[dict[str, Any]], candidates_only: bool) -> None:
    """Render inbox entries in human-readable form."""
    if not entries:
        if candidates_only:
            typer.echo("No candidate entries found. Run pass-1 tagging first.")
        else:
            typer.echo("Inbox is empty. No pending items.")
        return

    pending = [e for e in entries if e.get("status") == "pending"]
    header = (
        f"Inbox: {len(entries)} candidate(s) shown"
        if candidates_only
        else f"Inbox: {len(entries)} total, {len(pending)} pending"
    )
    typer.echo(f"{header}\n")
    for entry in entries:
        status_marker = "[x]" if entry.get("status") == "processed" else "[ ]"
        typer.echo(f"  {status_marker} {entry.get('id', 'no-id')}")
        typer.echo(f"      source: {entry.get('source', 'unknown')}")
        typer.echo(f"      type:   {entry.get('type', 'unknown')}")
        typer.echo(f"      date:   {entry.get('date', entry.get('ingested_at', 'unknown'))}")
        typer.echo(f"      status: {entry.get('status', 'unknown')}")
        if entry.get("file"):
            typer.echo(f"      file:   {entry['file']}")
        cand = entry.get("candidate")
        if isinstance(cand, dict):
            typer.echo(
                f"      candidate: verdict={cand.get('verdict')} score={cand.get('score')} reason={cand.get('reason')}"
            )
        typer.echo("")


def _handle_list_inbox(cfg: WikiConfig, candidates_only: bool, include_maybe: bool, json_output: bool) -> None:
    entries = _list_inbox(cfg)
    if candidates_only:
        entries = _filter_candidate_entries(entries, include_maybe)

    if json_output:
        typer.echo(json.dumps(entries, indent=2))
    else:
        _print_inbox_entries(entries, candidates_only)


def _handle_mark_processed(entry_ids: list[str], cfg: WikiConfig, json_output: bool) -> None:
    # Flatten comma-separated and/or repeated values into a clean id list.
    flat_ids = [piece.strip() for raw in entry_ids for piece in raw.split(",") if piece.strip()]
    result = _mark_processed_batch(flat_ids, cfg)

    if json_output:
        typer.echo(json.dumps(result, indent=2))
    else:
        if result["processed"]:
            typer.echo(f"Marked {len(result['processed'])} entry(ies) as processed: {', '.join(result['processed'])}")
        if result["not_found"]:
            typer.echo(f"Not found: {', '.join(result['not_found'])}")
        if result.get("error") and not result["processed"]:
            typer.echo(f"Error: {result['error']}", err=True)

    # Error (exit 1) only when nothing was found/marked; partial success exits 0.
    if not result["processed"]:
        raise typer.Exit(code=1)


def _validate_tag_candidate_inputs(
    verdict: str | None, score: float | None, reason: str | None
) -> tuple[str, float, str]:
    """Ensure --tag-candidate's required flags are present; return narrowed values."""
    if not verdict:
        typer.echo("Error: --tag-candidate requires --verdict", err=True)
        raise typer.Exit(code=1)
    if score is None:
        typer.echo("Error: --tag-candidate requires --score", err=True)
        raise typer.Exit(code=1)
    if not reason:
        typer.echo("Error: --tag-candidate requires --reason", err=True)
        raise typer.Exit(code=1)
    return verdict, score, reason


def _handle_tag_candidate(  # noqa: PLR0913  # Each verdict field is a discrete CLI input
    entry_id: str,
    verdict: str | None,
    score: float | None,
    reason: str | None,
    suggested_type: str | None,
    suggested_tags: str | None,
    cfg: WikiConfig,
    json_output: bool,
) -> None:
    valid_verdict, valid_score, valid_reason = _validate_tag_candidate_inputs(verdict, score, reason)
    tag_list = [t.strip() for t in suggested_tags.split(",") if t.strip()] if suggested_tags else []
    result = _tag_candidate(
        entry_id=entry_id,
        verdict=valid_verdict,
        score=valid_score,
        reason=valid_reason,
        suggested_type=suggested_type,
        suggested_tags=tag_list,
        cfg=cfg,
    )

    if json_output:
        typer.echo(json.dumps(result, indent=2))
    elif result["success"]:
        cand = result["candidate"]
        typer.echo(f"Tagged '{entry_id}' as candidate (verdict={cand['verdict']}, score={cand['score']:.2f})")
        typer.echo(f"  reason: {cand['reason']}")
        if cand.get("suggested_type"):
            typer.echo(f"  suggested_type: {cand['suggested_type']}")
        if cand.get("suggested_tags"):
            typer.echo(f"  suggested_tags: {cand['suggested_tags']}")
    else:
        typer.echo(f"Error: {result['error']}", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


def compile_notes(  # noqa: PLR0913  # Each option is a discrete CLI flag
    check_dedup: str | None = typer.Option(
        None,
        "--check-dedup",
        help="Check for duplicate/similar content in the index.",
    ),
    check_dedup_batch: str | None = typer.Option(
        None,
        "--check-dedup-batch",
        help='Batch dedup-check: path to a JSON file of [{"key","query"}], or \'-\' for stdin.',
    ),
    write_note: bool = typer.Option(
        False,
        "--write-note",
        help="Create a new permanent note.",
    ),
    list_inbox: bool = typer.Option(
        False,
        "--list-inbox",
        help="List pending items in the inbox manifest.",
    ),
    candidates_only: bool = typer.Option(
        False,
        "--candidates-only",
        help="With --list-inbox, show only entries tagged verdict=yes (the pass-1 keepers).",
    ),
    include_maybe: bool = typer.Option(
        False,
        "--include-maybe",
        help="With --candidates-only, also include verdict=maybe entries.",
    ),
    mark_processed: list[str] | None = typer.Option(  # noqa: B008  # Typer requires the call in the default
        None,
        "--mark-processed",
        help="Mark manifest entry(ies) as processed. Accepts comma-separated and/or repeated values.",
    ),
    # Tag-candidate fields (used with --tag-candidate)
    tag_candidate: str | None = typer.Option(
        None,
        "--tag-candidate",
        help="Record a pre-filter verdict on a manifest entry (pass 1 of two-pass compile).",
    ),
    verdict: str | None = typer.Option(
        None,
        "--verdict",
        help="Verdict for --tag-candidate: yes, no, or maybe.",
    ),
    score: float | None = typer.Option(
        None,
        "--score",
        help="Confidence score 0.0-1.0 for --tag-candidate.",
    ),
    reason: str | None = typer.Option(
        None,
        "--reason",
        help="Short justification for --tag-candidate verdict.",
    ),
    suggested_type: str | None = typer.Option(
        None,
        "--suggested-type",
        help="Hint for second-pass extractor: knowledge_type to consider.",
    ),
    suggested_tags: str | None = typer.Option(
        None,
        "--suggested-tags",
        help="Comma-separated tag hints for second-pass extractor.",
    ),
    # Note fields (used with --write-note)
    title: str | None = typer.Option(None, "--title", help="Note title."),
    knowledge_type: str | None = typer.Option(
        None,
        "--knowledge-type",
        help="Knowledge type (fact, pattern, decision, etc.).",
    ),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated tags."),
    confidence: str | None = typer.Option(
        None,
        "--confidence",
        help="Confidence level: high, medium, low.",
    ),
    source: str | None = typer.Option(None, "--source", help="Origin description."),
    body: str | None = typer.Option(None, "--body", help="Note body content."),
    # Merge
    merge_into: str | None = typer.Option(
        None,
        "--merge-into",
        help="Append --body as a dated update into the existing note at this path (preserves frontmatter).",
    ),
    # Modifiers
    source_class: str | None = typer.Option(
        None,
        "--source-class",
        help="Source class for dedup tuning: chat (default, 0.92), doc (0.93), book (0.94), paper (0.94).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Preview what would be created without writing.",
    ),
    force_overwrite: bool = typer.Option(
        False,
        "--force-overwrite",
        help="With --write-note: overwrite the target in place even if it exists or is reviewed "
        "(default writes a renamed sibling on collision and skips reviewed targets).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
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
        raise typer.Exit(code=1) from e

    if check_dedup:
        try:
            threshold = resolve_threshold(source_class)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1) from e
        _handle_check_dedup(check_dedup, cfg, threshold, json_output)
    elif check_dedup_batch:
        _handle_check_dedup_batch(check_dedup_batch, cfg, json_output)
    elif write_note:
        _handle_write_note(
            title, knowledge_type, tags, confidence, source, body, cfg, dry_run, json_output, force_overwrite
        )
    elif merge_into:
        _handle_merge_note(merge_into, body, cfg, dry_run, json_output)
    elif list_inbox:
        _handle_list_inbox(cfg, candidates_only, include_maybe, json_output)
    elif mark_processed:
        _handle_mark_processed(mark_processed, cfg, json_output)
    elif tag_candidate:
        _handle_tag_candidate(tag_candidate, verdict, score, reason, suggested_type, suggested_tags, cfg, json_output)
    else:
        typer.echo(
            "Error: Specify one of --check-dedup, --check-dedup-batch, --write-note, --merge-into, "
            "--list-inbox, --mark-processed, or --tag-candidate",
            err=True,
        )
        raise typer.Exit(code=1)


def _auto_refresh_charts(cfg: WikiConfig) -> None:
    """Run chart generation after compile operations (best-effort)."""
    try:
        _generate_all_charts(cfg)
    except Exception:  # noqa: BLE001  # best-effort: chart failures must never block note writing
        logger.debug("Chart auto-refresh failed (best-effort)", exc_info=True)
