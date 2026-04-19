"""One-shot frontmatter migration: simplified schema -> canonical schema.

Upgrades notes that use the compact shape (``type: <knowledge-type>``, no
``knowledge_type`` field, no ``id``/``status``/``confidence``/``scope``) to
the canonical 9-field shape emitted by ``kb compile --write-note``.

Idempotent: notes already on canonical schema are skipped.
"""

from __future__ import annotations

import json
import random
import re
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from llm_wiki.core.config import load_config
from llm_wiki.core.frontmatter import (
    KNOWLEDGE_TYPES,
    dump,
    get_knowledge_type,
    parse_file,
)


_FILENAME_DATE_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


def _extract_date_from_filename(filename: str) -> str:
    """Return YYYYMMDD from a filename if one is embedded, else today's date."""
    m = _FILENAME_DATE_RE.search(filename)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _extract_date_from_created(created: Any) -> str | None:
    """Return YYYYMMDD from the ``created`` field if parseable."""
    if not isinstance(created, str):
        return None
    m = _FILENAME_DATE_RE.search(created)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


def _random_suffix(k: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=k))


def _generate_id(meta: dict[str, Any], filename: str) -> str:
    """Generate perm-YYYYMMDD-XXXXX preferring dates already attached to the note."""
    date = _extract_date_from_created(meta.get("created")) or _extract_date_from_filename(filename)
    return f"perm-{date}-{_random_suffix()}"


def _migrate_one(
    meta: dict[str, Any],
    filename: str,
    defaults: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    """Return (upgraded_metadata, list_of_changes) for a single note."""
    changes: list[str] = []
    new_meta = dict(meta)

    kt = get_knowledge_type(meta)

    # Collapse simplified schema: if `type` holds a knowledge-type value,
    # promote it to `knowledge_type` and set `type: permanent`.
    current_type = meta.get("type")
    if isinstance(current_type, str) and current_type in KNOWLEDGE_TYPES:
        new_meta["knowledge_type"] = current_type
        new_meta["type"] = "permanent"
        changes.append(f"type: {current_type} -> permanent + knowledge_type: {current_type}")
    elif kt is not None and "knowledge_type" not in new_meta:
        # Edge case: knowledge_type resolvable but stored oddly — normalize.
        new_meta["knowledge_type"] = kt
        changes.append(f"knowledge_type: <inferred> -> {kt}")

    # Ensure type is present
    if "type" not in new_meta or new_meta["type"] is None:
        new_meta["type"] = "permanent"
        changes.append("type: <missing> -> permanent")

    # Fill recommended fields with defaults (only if missing)
    if "id" not in new_meta or not new_meta["id"]:
        new_meta["id"] = _generate_id(meta, filename)
        changes.append(f"id: <missing> -> {new_meta['id']}")

    for field, default in defaults.items():
        if field not in new_meta or new_meta[field] is None:
            new_meta[field] = default
            changes.append(f"{field}: <missing> -> {default}")

    # Ensure `source` is present (required). If absent and we have no way
    # to recover it, synthesize a provenance marker so lint passes but the
    # migration is auditable.
    if "source" not in new_meta or not new_meta["source"]:
        new_meta["source"] = "migrated:unknown"
        changes.append('source: <missing> -> "migrated:unknown"')

    if "created" not in new_meta or not new_meta["created"]:
        new_meta["created"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        changes.append(f"created: <missing> -> {new_meta['created']}")

    return new_meta, changes


def migrate_frontmatter(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write changes to disk. Without this flag, runs a dry-run preview.",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Emit structured migration report as JSON.",
    ),
) -> None:
    """Migrate simplified-schema notes in the wiki to the canonical schema.

    Safe to run repeatedly; notes already on canonical schema are left untouched.
    """
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    permanent_dir = cfg.project_root / "wiki" / "permanent"
    if not permanent_dir.exists():
        typer.echo("No wiki/permanent directory found. Nothing to migrate.")
        return

    defaults = {
        "status": "pending",
        "confidence": "medium",
        "scope": "universal",
    }

    migrated: list[dict[str, Any]] = []
    already_canonical: list[str] = []
    errors: list[dict[str, str]] = []

    for md_file in sorted(permanent_dir.glob("*.md")):
        try:
            meta, body = parse_file(md_file)
        except Exception as exc:
            errors.append({"file": md_file.name, "error": str(exc)})
            continue

        if not meta:
            errors.append({"file": md_file.name, "error": "no frontmatter"})
            continue

        already_on_canonical = (
            meta.get("type") == "permanent"
            and meta.get("knowledge_type") in KNOWLEDGE_TYPES
            and meta.get("id")
            and all(meta.get(f) for f in defaults)
            and meta.get("source")
            and meta.get("created")
        )
        if already_on_canonical:
            already_canonical.append(md_file.name)
            continue

        new_meta, changes = _migrate_one(meta, md_file.name, defaults)
        if not changes:
            already_canonical.append(md_file.name)
            continue

        migrated.append({
            "file": md_file.name,
            "changes": changes,
        })

        if apply:
            new_content = dump(new_meta, body)
            md_file.write_text(new_content, encoding="utf-8")

    report = {
        "mode": "apply" if apply else "dry-run",
        "migrated_count": len(migrated),
        "skipped_canonical_count": len(already_canonical),
        "error_count": len(errors),
        "migrated": migrated,
        "errors": errors,
    }

    if json_output:
        typer.echo(json.dumps(report, indent=2))
        return

    mode_label = "APPLIED" if apply else "DRY RUN (no changes written)"
    typer.echo(f"\nFrontmatter migration — {mode_label}")
    typer.echo("=" * 50)
    typer.echo(f"To migrate:     {len(migrated)}")
    typer.echo(f"Already canon.: {len(already_canonical)}")
    typer.echo(f"Errors:         {len(errors)}")

    if migrated:
        typer.echo("\nChanges per file:")
        for entry in migrated[:20]:
            typer.echo(f"\n  {entry['file']}:")
            for change in entry["changes"]:
                typer.echo(f"    - {change}")
        if len(migrated) > 20:
            typer.echo(f"\n  ... and {len(migrated) - 20} more files")

    if errors:
        typer.echo("\nErrors:")
        for e in errors:
            typer.echo(f"  {e['file']}: {e['error']}")

    if not apply and migrated:
        typer.echo("\nRe-run with --apply to write these changes.")
