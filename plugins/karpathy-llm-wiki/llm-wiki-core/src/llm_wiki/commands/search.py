"""Semantic search across the wiki knowledge base.

Uses LanceDB vector index and sentence-transformers embeddings to find
notes that are semantically similar to the query.
"""

from __future__ import annotations

import json

import typer

from llm_wiki.core.config import load_config
from llm_wiki.core.embeddings import search_index


def search(
    query: str = typer.Argument(..., help="Search query string."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of results (default from config).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output results as JSON.",
    ),
) -> None:
    """Semantic search across wiki notes."""
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    if limit is None:
        limit = cfg.query_default_limit

    try:
        results = search_index(cfg.db_path, cfg.table_name, query, limit=limit)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e
    except Exception as e:  # surface any backend error to the user, then exit
        typer.echo(f"Search failed: {e}", err=True)
        raise typer.Exit(code=1) from e

    if json_output:
        typer.echo(json.dumps(results, indent=2))
    else:
        if not results:
            typer.echo("No results found.")
            return

        typer.echo(f"\nSearch results for: '{query}'\n")
        for i, r in enumerate(results, 1):
            typer.echo(f"  [{i}] {r['title']} (score: {r['score']:.4f})")
            typer.echo(f"      type: {r['knowledge_type']} | file: {r['file_path']}")
            typer.echo(f"      {r['snippet'][:120]}...")
            typer.echo("")
