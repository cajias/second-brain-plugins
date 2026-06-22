"""Ingest raw documents into the wiki inbox.

Routes raw documents into the appropriate raw/ subdirectory with metadata
sidecars, and appends entries to the manifest queue for compilation.

Supports 4 modes: session, file, url, text.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import typer

from llm_wiki.core.config import WikiConfig, load_config
from llm_wiki.core.dedup import SOURCE_CLASS_THRESHOLDS
from llm_wiki.core.html_extract import extract_main_content
from llm_wiki.core.text import slugify


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_MODES = ("session", "file", "url", "text")
_ALLOWED_URL_SCHEMES = {"http", "https"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    """Return an ISO-8601 timestamp in UTC."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_id() -> str:
    """Return a short unique hex ID."""
    return uuid.uuid4().hex[:8]


_marker_models: dict[str, Any] | None = None


def _extract_pdf(pdf_path: Path) -> str:
    """Extract markdown text from a PDF using Marker."""
    global _marker_models  # noqa: PLW0603
    try:
        # marker is an optional [pdf] extra — must stay lazy.
        from marker.converters.pdf import PdfConverter  # noqa: PLC0415
        from marker.models import create_model_dict  # noqa: PLC0415
        from marker.output import text_from_rendered  # noqa: PLC0415
    except ImportError as e:
        msg = "PDF extraction requires marker-pdf: pip install karpathy-llm-wiki[pdf]"
        raise RuntimeError(msg) from e

    try:
        if _marker_models is None:
            _marker_models = create_model_dict()
        converter = PdfConverter(artifact_dict=_marker_models)
        rendered = converter(str(pdf_path))
        text, _, _ = text_from_rendered(rendered)
    except Exception as e:
        msg = f"Failed to extract text from {pdf_path.name}: {e}"
        raise RuntimeError(msg) from e

    return str(text)


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _load_manifest(path: Path) -> list[dict[str, Any]]:
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


def _save_manifest(path: Path, entries: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def _append_manifest(cfg: WikiConfig, entry: dict[str, Any]) -> None:
    """Append an entry to the manifest queue."""
    cfg.raw_inbox.mkdir(parents=True, exist_ok=True)
    mp = cfg.raw_inbox / ".manifest.json"
    entries = _load_manifest(mp)
    entries.append(entry)
    _save_manifest(mp, entries)


def _write_meta(dest_path: Path, meta: dict[str, Any]) -> Path:
    """Write a .meta.json sidecar next to dest_path."""
    meta_path = dest_path.parent / (dest_path.name + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta_path


# ---------------------------------------------------------------------------
# Ingest modes
# ---------------------------------------------------------------------------


def _ingest_session(source: str, cfg: WikiConfig, source_class: str = "chat") -> dict[str, Any]:
    """Ingest a Claude Code session log (.jsonl)."""
    source_path = Path(source).resolve()
    if not source_path.exists():
        msg = f"Session file not found: {source}"
        raise FileNotFoundError(msg)

    cfg.raw_sessions.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    stem = slugify(source_path.stem, max_len=40) or "session"
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
        "source_class": source_class,
    }
    _append_manifest(cfg, manifest_entry)

    return {
        "mode": "session",
        "dest": str(dest_path),
        "meta": meta,
        "manifest_id": manifest_entry["id"],
    }


def _ingest_file(source: str, cfg: WikiConfig, source_class: str = "chat") -> dict[str, Any]:
    """Ingest a document (PDF, markdown, text, etc.)."""
    source_path = Path(source).resolve()
    if not source_path.exists():
        msg = f"File not found: {source}"
        raise FileNotFoundError(msg)

    cfg.raw_artifacts.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    stem = slugify(source_path.stem, max_len=40) or "document"
    dest_name = f"{ts}-{stem}{source_path.suffix}"
    dest_path = cfg.raw_artifacts / dest_name

    shutil.copy2(str(source_path), str(dest_path))

    is_pdf = source_path.suffix.lower() == ".pdf"
    manifest_file = dest_path
    pdf_extras_meta: dict[str, Any] = {}
    pdf_extras_manifest: dict[str, Any] = {}

    if is_pdf:
        markdown_text = _extract_pdf(dest_path)
        if not markdown_text.strip():
            msg = f"No text could be extracted from {source_path.name} — the PDF may be scanned/image-only"
            raise RuntimeError(msg)
        md_path = dest_path.with_suffix(".md")
        md_path.write_text(
            f"# {source_path.stem}\n\n> Extracted from PDF: {source_path.name}\n\n{markdown_text.strip()}\n",
            encoding="utf-8",
        )
        manifest_file = md_path
        pdf_extras_meta = {"original_format": "pdf"}
        pdf_extras_manifest = {"extracted_from": str(dest_path.relative_to(cfg.project_root))}

    meta: dict[str, Any] = {
        "source": str(source_path),
        "date": _timestamp(),
        "type": "file",
        "original_path": str(source_path),
        "status": "pending",
        **pdf_extras_meta,
    }
    _write_meta(dest_path, meta)

    manifest_entry: dict[str, Any] = {
        "id": f"ingest-{_short_id()}",
        "file": str(manifest_file.relative_to(cfg.project_root)),
        "type": "file",
        "source": str(source_path),
        "date": meta["date"],
        "status": "pending",
        "source_class": source_class,
        **pdf_extras_manifest,
    }
    _append_manifest(cfg, manifest_entry)

    return {
        "mode": "file",
        "dest": str(manifest_file),
        "meta": meta,
        "manifest_id": manifest_entry["id"],
    }


def _ingest_url(source: str, cfg: WikiConfig, source_class: str = "chat") -> dict[str, Any]:
    """Ingest a web article by downloading and extracting text."""
    parsed = urlparse(source)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        msg = f"Unsupported URL scheme '{parsed.scheme}'. Only {sorted(_ALLOWED_URL_SCHEMES)} are allowed."
        raise RuntimeError(msg)

    cfg.raw_web.mkdir(parents=True, exist_ok=True)

    req = Request(source, headers={"User-Agent": "kb-ingest/1.0"})  # noqa: S310  # scheme validated above
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310  # scheme validated above
            raw_html = resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        msg = f"Failed to fetch URL: {e}"
        raise RuntimeError(msg) from e

    doc = extract_main_content(raw_html, url=source)
    if not doc.text.strip():
        msg = f"No content could be extracted from {source} (empty/boilerplate-only page)."
        raise RuntimeError(msg)
    text = doc.text

    slug = slugify(parsed.netloc + "-" + parsed.path, max_len=50) or "web-page"
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dest_name = f"{ts}-{slug}.md"
    dest_path = cfg.raw_web / dest_name

    dest_path.write_text(
        f"# {source}\n\n> Fetched: {_timestamp()}\n\nSource: {source}\n\n{text.strip()}\n",
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
        "source_class": source_class,
    }
    _append_manifest(cfg, manifest_entry)

    return {
        "mode": "url",
        "dest": str(dest_path),
        "meta": meta,
        "manifest_id": manifest_entry["id"],
    }


def _ingest_text(source: str, cfg: WikiConfig, source_class: str = "chat") -> dict[str, Any]:
    """Ingest a quick text snippet as a timestamped markdown file."""
    cfg.raw_inbox.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    slug = slugify(source[:50], max_len=40) or "note"
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
        "source_class": source_class,
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


def _list_pending(cfg: WikiConfig) -> list[dict[str, Any]]:
    """Return all pending manifest entries."""
    mp = cfg.raw_inbox / ".manifest.json"
    entries = _load_manifest(mp)
    return [e for e in entries if e.get("status") == "pending"]


# ---------------------------------------------------------------------------
# Typer command helpers
# ---------------------------------------------------------------------------


def _print_pending(pending: list[dict[str, Any]]) -> None:
    """Print pending inbox entries in the human-readable format."""
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


def _handle_list_mode(cfg: WikiConfig, json_output: bool) -> None:
    """Handle the --list flag: print pending items."""
    pending = _list_pending(cfg)
    if json_output:
        typer.echo(json.dumps(pending, indent=2))
    else:
        _print_pending(pending)


def _validate_mode_and_source(mode: str | None, source: str | None) -> tuple[str, str]:
    """Ensure --mode/--source are present and valid; return narrowed (mode, source)."""
    if not mode:
        typer.echo("Error: --mode is required (unless using --list)", err=True)
        raise typer.Exit(code=1)
    if mode not in _VALID_MODES:
        typer.echo(f"Error: --mode must be one of {_VALID_MODES}", err=True)
        raise typer.Exit(code=1)
    if not source:
        typer.echo("Error: --source is required for ingest", err=True)
        raise typer.Exit(code=1)
    return mode, source


def _dispatch_ingest(mode: str, source: str, cfg: WikiConfig, source_class: str = "chat") -> dict[str, Any]:
    """Dispatch to the right per-mode helper. Caller catches FileNotFoundError/RuntimeError."""
    dispatch = {
        "session": _ingest_session,
        "file": _ingest_file,
        "url": _ingest_url,
        "text": _ingest_text,
    }
    return dispatch[mode](source, cfg, source_class)


def _print_ingest_result(result: dict[str, Any], json_output: bool) -> None:
    """Render an ingest result as JSON or human-readable text."""
    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return
    typer.echo(f"\nIngested ({result['mode']}):")
    typer.echo(f"  Destination: {result['dest']}")
    typer.echo(f"  Manifest ID: {result['manifest_id']}")
    typer.echo("  Status: pending")
    typer.echo("\nRun 'kb compile' to process the inbox.")


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


def ingest(
    mode: str | None = typer.Option(
        None,
        "--mode",
        "-m",
        help="Ingest mode: session, file, url, or text.",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Source path, URL, or text to ingest.",
    ),
    source_class: str = typer.Option(
        "chat",
        "--source-class",
        help="Source class for dedup tuning: chat, doc, book, paper, or tool.",
    ),
    list_pending: bool = typer.Option(
        False,
        "--list",
        "-l",
        help="List pending inbox items.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
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
        raise typer.Exit(code=1) from e

    if list_pending:
        _handle_list_mode(cfg, json_output)
        return

    valid_mode, valid_source = _validate_mode_and_source(mode, source)

    if source_class.lower() not in SOURCE_CLASS_THRESHOLDS:
        typer.echo(
            f"Error: --source-class must be one of {sorted(SOURCE_CLASS_THRESHOLDS)}",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        result = _dispatch_ingest(valid_mode, valid_source, cfg, source_class.lower())
    except (FileNotFoundError, RuntimeError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    _print_ingest_result(result, json_output)
