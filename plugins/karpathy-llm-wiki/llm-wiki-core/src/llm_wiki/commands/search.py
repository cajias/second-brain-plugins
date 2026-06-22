"""Semantic and/or frontmatter-filtered search across the wiki knowledge base."""

from __future__ import annotations

import json

import typer

from llm_wiki.core.config import load_config
from llm_wiki.core.embeddings import search_index


def search(  # noqa: PLR0913  # each filter is a discrete CLI dimension
    query: str | None = typer.Argument(None, help="Search query string (optional if a filter is given)."),
    knowledge_type: str | None = typer.Option(
        None,
        "--knowledge-type",
        help="Filter by knowledge_type frontmatter field.",
    ),
    tag: list[str] | None = typer.Option(  # noqa: B008  # Typer requires the call in the default
        None,
        "--tag",
        help="Filter by tag (repeatable; AND across all given tags, token-exact).",
    ),
    type_: str | None = typer.Option(None, "--type", help="Filter by frontmatter type field."),
    scope: str | None = typer.Option(None, "--scope", help="Filter by frontmatter scope field."),
    where: str | None = typer.Option(
        None,
        "--where",
        help="Raw DataFusion SQL predicate appended with AND to any other filters.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help=(
            "Max results (defaults to config query.default_limit for semantic search, or all matches for filter-only)."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output results as JSON array."),
) -> None:
    """Search wiki notes by semantic similarity, frontmatter filters, or both."""
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e

    has_filter = bool(knowledge_type or tag or type_ or scope or where)
    if query is None and not has_filter:
        typer.echo(
            "Error: provide a query and/or a filter (--knowledge-type/--tag/--type/--scope/--where).",
            err=True,
        )
        raise typer.Exit(code=1)

    if limit is None:
        limit = None if query is None else cfg.query_default_limit

    try:
        results = search_index(
            cfg.db_path,
            cfg.table_name,
            query,
            limit=limit,
            knowledge_type=knowledge_type,
            tags=tag or None,
            type_=type_,
            scope=scope,
            where=where,
        )
    except Exception as e:  # surface any backend error to the user, then exit
        typer.echo(f"Search failed: {e}", err=True)
        raise typer.Exit(code=1) from e

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        typer.echo("No results found.")
        return

    label = query if query is not None else "(filter-only)"
    typer.echo(f"\nSearch results for: '{label}'\n")
    for i, r in enumerate(results, 1):
        score_str = f" (score: {r['score']:.4f})" if r["score"] is not None else ""
        typer.echo(f"  [{i}] {r['title']}{score_str}")
        typer.echo(f"      type: {r['knowledge_type']} | tags: {', '.join(r['tags'])} | file: {r['file_path']}")
        typer.echo(f"      {r['snippet'][:120]}...")
        typer.echo("")
