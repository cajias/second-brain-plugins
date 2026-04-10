"""Ingest raw documents into the wiki inbox.

Routes raw documents into the appropriate raw/ subdirectory with metadata
sidecars, and appends entries to the manifest queue for compilation.

Supports 4 modes: session, file, url, text.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen

import typer

from llm_wiki.core.config import load_config, get_project_root, WikiConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    """Return an ISO-8601 timestamp in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_id() -> str:
    """Return a short unique hex ID."""
    return uuid.uuid4().hex[:8]


def _slugify(text: str, max_len: int = 60) -> str:
    """Turn arbitrary text into a filesystem-safe kebab-case slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML-to-text converter."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []

    def handle_data(self, data: str) -> None:
        self._pieces.append(data)

    def get_text(self) -> str:
        return " ".join(self._pieces)


def _html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _load_manifest(path: Path) -> list:
    """Load the manifest, returning an empty list on any error."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_manifest(path: Path, entries: list) -> None:
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def _append_manifest(cfg: WikiConfig, entry: dict) -> None:
    """Append an entry to the manifest queue."""
    cfg.raw_inbox.mkdir(parents=True, exist_ok=True)
    mp = cfg.raw_inbox / ".manifest.json"
    entries = _load_manifest(mp)
    entries.append(entry)
    _save_manifest(mp, entries)


def _write_meta(dest_path: Path, meta: dict) -> Path:
    """Write a .meta.json sidecar next to dest_path."""
    meta_path = dest_path.parent / (dest_path.name + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta_path


# ---------------------------------------------------------------------------
# Ingest modes
# ---------------------------------------------------------------------------


def _ingest_session(source: str, cfg: WikiConfig) -> dict:
    """Ingest a Claude Code session log (.jsonl)."""
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Session file not found: {source}")

    cfg.raw_sessions.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = _slugify(source_path.stem, max_len=40) or "session"
    dest_name = f"{ts}-{stem}{source_path.suffix}"
    dest_path = cfg.raw_sessions / dest_name

    shutil.copy2(str(source_path), str(dest_path))

    meta = {
        "source": str(source_path),
        "date": _timestamp(),
        "type": "session",
        "original_path": str(source_path),
        "status": "pending",
    }
    _write_meta(dest_path, meta)

    manifest_entry = {
        "id": f"ingest-{_short_id()}",
        "file": str(dest_path.relative_to(cfg.project_root)),
        "type": "session",
        "source": str(source_path),
        "date": meta["date"],
        "status": "pending",
    }
    _append_manifest(cfg, manifest_entry)

    return {
        "mode": "session",
        "dest": str(dest_path),
        "meta": meta,
        "manifest_id": manifest_entry["id"],
    }


def _ingest_file(source: str, cfg: WikiConfig) -> dict:
    """Ingest a document (PDF, markdown, text, etc.)."""
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"File not found: {source}")

    cfg.raw_artifacts.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = _slugify(source_path.stem, max_len=40) or "document"
    dest_name = f"{ts}-{stem}{source_path.suffix}"
    dest_path = cfg.raw_artifacts / dest_name

    shutil.copy2(str(source_path), str(dest_path))

    meta = {
        "source": str(source_path),
        "date": _timestamp(),
        "type": "file",
        "original_path": str(source_path),
        "status": "pending",
    }
    _write_meta(dest_path, meta)

    manifest_entry = {
        "id": f"ingest-{_short_id()}",
        "file": str(dest_path.relative_to(cfg.project_root)),
        "type": "file",
        "source": str(source_path),
        "date": meta["date"],
        "status": "pending",
    }
    _append_manifest(cfg, manifest_entry)

    return {
        "mode": "file",
        "dest": str(dest_path),
        "meta": meta,
        "manifest_id": manifest_entry["id"],
    }


def _ingest_url(source: str, cfg: WikiConfig) -> dict:
    """Ingest a web article by downloading and extracting text."""
    cfg.raw_web.mkdir(parents=True, exist_ok=True)

    req = Request(source, headers={"User-Agent": "kb-ingest/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise RuntimeError(f"Failed to fetch URL: {e}")

    text = _html_to_text(raw_html)

    parsed = urlparse(source)
    slug = _slugify(parsed.netloc + "-" + parsed.path, max_len=50) or "web-page"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest_name = f"{ts}-{slug}.md"
    dest_path = cfg.raw_web / dest_name

    dest_path.write_text(
        f"# {source}\n\n> Fetched: {_timestamp()}\n\n{text.strip()}\n",
        encoding="utf-8",
    )

    meta = {
        "source": source,
        "date": _timestamp(),
        "type": "url",
        "original_path": source,
        "status": "pending",
    }
    _write_meta(dest_path, meta)

    manifest_entry = {
        "id": f"ingest-{_short_id()}",
        "file": str(dest_path.relative_to(cfg.project_root)),
        "type": "url",
        "source": source,
        "date": meta["date"],
        "status": "pending",
    }
    _append_manifest(cfg, manifest_entry)

    return {
        "mode": "url",
        "dest": str(dest_path),
        "meta": meta,
        "manifest_id": manifest_entry["id"],
    }


def _ingest_text(source: str, cfg: WikiConfig) -> dict:
    """Ingest a quick text snippet as a timestamped markdown file."""
    cfg.raw_inbox.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = _slugify(source[:50], max_len=40) or "note"
    dest_name = f"{ts}-{slug}.md"
    dest_path = cfg.raw_inbox / dest_name

    dest_path.write_text(
        f"# Note\n\n> Created: {_timestamp()}\n\n{source.strip()}\n",
        encoding="utf-8",
    )

    meta = {
        "source": "inline-text",
        "date": _timestamp(),
        "type": "text",
        "original_path": None,
        "status": "pending",
    }
    _write_meta(dest_path, meta)

    manifest_entry = {
        "id": f"ingest-{_short_id()}",
        "file": str(dest_path.relative_to(cfg.project_root)),
        "type": "text",
        "source": "inline-text",
        "date": meta["date"],
        "status": "pending",
    }
    _append_manifest(cfg, manifest_entry)

    return {
        "mode": "text",
        "dest": str(dest_path),
        "meta": meta,
        "manifest_id": manifest_entry["id"],
    }


# ---------------------------------------------------------------------------
# List pending
# ---------------------------------------------------------------------------


def _list_pending(cfg: WikiConfig) -> list:
    """Return all pending manifest entries."""
    mp = cfg.raw_inbox / ".manifest.json"
    entries = _load_manifest(mp)
    return [e for e in entries if e.get("status") == "pending"]


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


def ingest(
    mode: Optional[str] = typer.Option(
        None, "--mode", "-m",
        help="Ingest mode: session, file, url, or text.",
    ),
    source: Optional[str] = typer.Option(
        None, "--source", "-s",
        help="Source path, URL, or text to ingest.",
    ),
    list_pending: bool = typer.Option(
        False, "--list", "-l",
        help="List pending inbox items.",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="Output as JSON.",
    ),
) -> None:
    """Ingest raw documents into the wiki inbox.

    Supports 4 modes: session (JSONL logs), file (PDF/md/txt),
    url (web pages), text (inline snippets).
    """
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    # --list mode
    if list_pending:
        pending = _list_pending(cfg)
        if json_output:
            typer.echo(json.dumps(pending, indent=2))
        else:
            if not pending:
                typer.echo("No pending items in the inbox.")
                return
            typer.echo(f"\nPending inbox items ({len(pending)}):\n")
            for i, entry in enumerate(pending, 1):
                typer.echo(f"  [{i}] {entry['id']}  ({entry['type']})")
                typer.echo(f"      file: {entry['file']}")
                typer.echo(f"      source: {entry['source']}")
                typer.echo(f"      date: {entry['date']}")
                typer.echo("")
        return

    # Validate ingest mode
    if not mode:
        typer.echo("Error: --mode is required (unless using --list)", err=True)
        raise typer.Exit(code=1)

    valid_modes = ("session", "file", "url", "text")
    if mode not in valid_modes:
        typer.echo(f"Error: --mode must be one of {valid_modes}", err=True)
        raise typer.Exit(code=1)

    if not source:
        typer.echo("Error: --source is required for ingest", err=True)
        raise typer.Exit(code=1)

    dispatch = {
        "session": _ingest_session,
        "file": _ingest_file,
        "url": _ingest_url,
        "text": _ingest_text,
    }

    try:
        result = dispatch[mode](source, cfg)
    except (FileNotFoundError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        typer.echo(f"\nIngested ({result['mode']}):")
        typer.echo(f"  Destination: {result['dest']}")
        typer.echo(f"  Manifest ID: {result['manifest_id']}")
        typer.echo(f"  Status: pending")
        typer.echo(f"\nRun 'kb compile' to process the inbox.")
