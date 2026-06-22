"""Rebuild the LanceDB vector index from wiki notes.

Reads all permanent wiki notes, generates embeddings via sentence-transformers,
and upserts them into the LanceDB table. Supports full and incremental modes.
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import lancedb
import pyarrow as pa
import typer

from llm_wiki.core.config import WikiConfig, load_config
from llm_wiki.core.embeddings import (
    EMBEDDING_DIM,
    embed_texts,
    get_last_index_time,
    set_last_index_time,
)
from llm_wiki.core.frontmatter import parse_file
from llm_wiki.core.tags import normalize_tags


if TYPE_CHECKING:
    from pathlib import Path


# Map qualitative confidence labels to numeric scores for sorting/filtering.
CONFIDENCE_LABEL_MAP: dict[str, float] = {"high": 0.9, "medium": 0.6, "low": 0.3}
DEFAULT_CONFIDENCE = 0.5
CONTENT_PREVIEW_CHARS = 1000
EMBEDDING_TEXT_PREVIEW_CHARS = 500


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def _collect_md_files(permanent_dir: Path) -> list[Path]:
    """Collect all .md files from the permanent notes directory."""
    if not permanent_dir.exists():
        return []
    return sorted(permanent_dir.glob("**/*.md"))


def _collect_tags(tags_val: object) -> list[str]:
    """Normalize a tags column value (list, ndarray, or legacy CSV string) into a flat list."""
    if tags_val is None:
        return []
    if isinstance(tags_val, str):
        return [t.strip() for t in tags_val.split(",") if t.strip()]
    try:
        return [str(t) for t in tags_val if t]  # type: ignore[attr-defined]
    except TypeError:
        return []


def _normalize_confidence(raw: object) -> float:
    """Coerce a frontmatter confidence (numeric or string label) into a float."""
    if raw is None:
        return 0.0
    if isinstance(raw, str):
        return CONFIDENCE_LABEL_MAP.get(raw.lower(), DEFAULT_CONFIDENCE)
    if isinstance(raw, (int, float)):
        return float(raw)
    return DEFAULT_CONFIDENCE


def _build_record(
    filepath: Path,
    metadata: dict[str, Any],
    body: str,
    embedding: list[float],
    project_root: Path,
) -> dict[str, Any]:
    """Build a single index record from a parsed file."""
    rel_path = str(filepath.relative_to(project_root))
    return {
        "id": metadata.get("id", filepath.stem),
        "title": metadata.get("title", filepath.stem),
        "knowledge_type": metadata.get("knowledge_type", "unknown"),
        "tags": normalize_tags(metadata.get("tags", [])),
        "type": metadata.get("type", "permanent"),
        "scope": metadata.get("scope", ""),
        "confidence": _normalize_confidence(metadata.get("confidence", 0.0)),
        "source": metadata.get("source", ""),
        "created": str(metadata.get("created", "")),
        "content": body[:CONTENT_PREVIEW_CHARS],
        "file_path": rel_path,
        "embedding": embedding,
    }


def _build_records_for_files(
    files: list[Path],
    project_root: Path,
) -> list[dict[str, Any]]:
    """Parse, embed, and assemble index records for a list of markdown files."""
    parsed = [(fp, *parse_file(fp)) for fp in files]
    typer.echo("Loading embedding model...")
    texts = [f"{meta.get('title', '')} {body[:EMBEDDING_TEXT_PREVIEW_CHARS]}" for _, meta, body in parsed]
    typer.echo(f"Generating embeddings for {len(texts)} documents...")
    embeddings = embed_texts(texts)
    return [
        _build_record(fp, meta, body, emb, project_root)
        for (fp, meta, body), emb in zip(parsed, embeddings, strict=True)
    ]


def _empty_index_schema() -> pa.Schema:
    """Return the LanceDB schema used when seeding an empty table."""
    return pa.schema(
        [
            pa.field("id", pa.utf8()),
            pa.field("title", pa.utf8()),
            pa.field("knowledge_type", pa.utf8()),
            pa.field("tags", pa.list_(pa.utf8())),
            pa.field("type", pa.utf8()),
            pa.field("scope", pa.utf8()),
            pa.field("confidence", pa.float64()),
            pa.field("source", pa.utf8()),
            pa.field("created", pa.utf8()),
            pa.field("content", pa.utf8()),
            pa.field("file_path", pa.utf8()),
            pa.field("embedding", pa.list_(pa.float32(), EMBEDDING_DIM)),
        ]
    )


# ---------------------------------------------------------------------------
# Index operations
# ---------------------------------------------------------------------------


def _do_full_index(cfg: WikiConfig) -> dict[str, Any]:
    """Drop and rebuild the entire index."""
    md_files = _collect_md_files(cfg.wiki_permanent)
    typer.echo(f"Found {len(md_files)} markdown files in {cfg.wiki_permanent}")

    db = lancedb.connect(str(cfg.db_path))

    if not md_files:
        if cfg.table_name in db.table_names():
            db.drop_table(cfg.table_name)
        db.create_table(cfg.table_name, schema=_empty_index_schema())
        typer.echo("Created empty index table (no files to index).")
        set_last_index_time(cfg.db_path)
        _write_stats(cfg)
        return {"indexed": 0, "mode": "full"}

    records = _build_records_for_files(md_files, cfg.project_root)

    if cfg.table_name in db.table_names():
        db.drop_table(cfg.table_name)
    db.create_table(cfg.table_name, data=records)

    set_last_index_time(cfg.db_path)
    typer.echo(f"Indexed {len(records)} notes into LanceDB table '{cfg.table_name}'.")
    _write_stats(cfg)
    return {"indexed": len(records), "mode": "full"}


def _do_incremental_index(cfg: WikiConfig) -> dict[str, Any]:
    """Only index files modified since the last run."""
    last_time = get_last_index_time(cfg.db_path)
    if last_time == 0.0:
        typer.echo("No previous index found. Running full index instead.")
        return _do_full_index(cfg)

    md_files = _collect_md_files(cfg.wiki_permanent)
    modified_files = [f for f in md_files if f.stat().st_mtime > last_time]

    typer.echo(f"Found {len(modified_files)} modified files since last index.")
    if not modified_files:
        typer.echo("Nothing to update.")
        return {"indexed": 0, "mode": "incremental"}

    records = _build_records_for_files(modified_files, cfg.project_root)

    db = lancedb.connect(str(cfg.db_path))
    if cfg.table_name not in db.table_names():
        db.create_table(cfg.table_name, data=records)
    else:
        table = db.open_table(cfg.table_name)
        modified_paths = [str(f.relative_to(cfg.project_root)) for f in modified_files]
        for path in modified_paths:
            # Pre-delete row(s) for this path so we can re-insert. delete() can
            # raise if no rows match — that's expected and fine on first sight.
            with contextlib.suppress(Exception):
                table.delete(f'file_path = "{path}"')
        table.add(records)

    set_last_index_time(cfg.db_path)
    typer.echo(f"Updated {len(records)} notes in LanceDB table '{cfg.table_name}'.")
    _write_stats(cfg)
    return {"indexed": len(records), "mode": "incremental"}


def _do_stats(cfg: WikiConfig) -> dict[str, Any]:
    """Gather statistics about the current index."""
    db = lancedb.connect(str(cfg.db_path))
    if cfg.table_name not in db.table_names():
        return {"error": "No index found. Run 'kb index --full' first."}

    table = db.open_table(cfg.table_name)
    df = table.to_pandas()

    total = len(df)
    stats: dict[str, Any] = {"total": total}

    if total == 0:
        stats["empty"] = True
        return stats

    # By knowledge_type
    kt_counts = df["knowledge_type"].value_counts().to_dict()
    stats["by_knowledge_type"] = kt_counts

    # By tag
    all_tags: list[str] = [tag for tags_val in df["tags"] for tag in _collect_tags(tags_val)]
    stats["by_tag"] = dict(Counter(all_tags).most_common())

    # Embedding dimensions
    if total > 0 and "embedding" in df.columns:
        first_emb = df["embedding"].iloc[0]
        if first_emb is not None:
            stats["embedding_dim"] = len(first_emb)

    return stats


def _write_stats(cfg: WikiConfig) -> None:
    """Write stats to wiki/_meta/stats.md."""
    db = lancedb.connect(str(cfg.db_path))
    if cfg.table_name not in db.table_names():
        return

    table = db.open_table(cfg.table_name)
    df = table.to_pandas()
    total = len(df)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "---",
        "title: Wiki Statistics",
        f'updated: "{now}"',
        "---",
        "# Wiki Statistics",
        "",
        f"**Last indexed:** {now}",
        f"**Total notes:** {total}",
        "",
    ]

    if total > 0:
        lines.append("## By Knowledge Type")
        lines.append("")
        for kt, count in df["knowledge_type"].value_counts().items():
            lines.append(f"- **{kt}:** {count}")
        lines.append("")

        lines.append("## By Tag")
        lines.append("")
        all_tags: list[str] = [tag for tags_val in df["tags"] for tag in _collect_tags(tags_val)]
        if all_tags:
            for tag, count in Counter(all_tags).most_common():
                lines.append(f"- **{tag}:** {count}")
        else:
            lines.append("*(no tags)*")
        lines.append("")

        if "embedding" in df.columns and total > 0:
            first_emb = df["embedding"].iloc[0]
            if first_emb is not None:
                lines.append(f"**Embedding dimensions:** {len(first_emb)}")
                lines.append("")
    else:
        lines.append("*(Index is empty - no permanent notes yet)*")
        lines.append("")

    cfg.wiki_meta.mkdir(parents=True, exist_ok=True)
    stats_path = cfg.wiki_meta / "stats.md"
    stats_path.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Stats written to {stats_path}")


# ---------------------------------------------------------------------------
# Stats text rendering (extracted from index() to reduce branch count)
# ---------------------------------------------------------------------------


def _print_stats_text(result: dict[str, Any]) -> None:
    """Render stats result as human-readable text."""
    if "error" in result:
        typer.echo(result["error"])
        return
    typer.echo("\n=== Knowledge Base Index Statistics ===")
    typer.echo(f"Total notes: {result['total']}")
    if result.get("empty"):
        typer.echo("(Index is empty)")
        return
    if result.get("by_knowledge_type"):
        typer.echo("\nBy knowledge_type:")
        for kt, count in result["by_knowledge_type"].items():
            typer.echo(f"  {kt}: {count}")
    if result.get("by_tag"):
        typer.echo("\nBy tag:")
        for tag, count in result["by_tag"].items():
            typer.echo(f"  {tag}: {count}")
    if result.get("embedding_dim"):
        typer.echo(f"\nEmbedding dimensions: {result['embedding_dim']}")
    typer.echo("")


def _handle_stats_mode(cfg: WikiConfig, *, json_output: bool) -> None:
    """Run stats and emit either JSON or text."""
    result = _do_stats(cfg)
    if json_output:
        typer.echo(json.dumps(result, indent=2))
    else:
        _print_stats_text(result)


# ---------------------------------------------------------------------------
# Typer command
# ---------------------------------------------------------------------------


def index(
    full: bool = typer.Option(
        False,
        "--full",
        help="Drop and rebuild entire index.",
    ),
    incremental: bool = typer.Option(
        False,
        "--incremental",
        help="Only index files modified since last run.",
    ),
    stats: bool = typer.Option(
        False,
        "--stats",
        help="Print index statistics.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON.",
    ),
) -> None:
    """Rebuild the vector search index.

    Use --full for a complete rebuild, --incremental for updates only,
    or --stats to view index information.
    """
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    if full:
        result = _do_full_index(cfg)
        if json_output:
            typer.echo(json.dumps(result, indent=2))
    elif incremental:
        result = _do_incremental_index(cfg)
        if json_output:
            typer.echo(json.dumps(result, indent=2))
    elif stats:
        _handle_stats_mode(cfg, json_output=json_output)
    else:
        typer.echo("Error: Specify --full, --incremental, or --stats", err=True)
        msg = "no mode specified"
        raise typer.Exit(code=1) from RuntimeError(msg)
