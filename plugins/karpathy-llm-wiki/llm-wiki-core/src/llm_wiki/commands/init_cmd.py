"""Initialize a new llm-wiki knowledge base in the current directory.

Scaffolds the directory structure, copies default config templates
(.kb-config.yml, tag-taxonomy.md, .gitignore), and creates the raw/
and wiki/ folder hierarchy expected by other commands.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import typer

from llm_wiki.core.config import CONFIG_FILENAME


DIRECTORIES = [
    "wiki/permanent",
    "wiki/_meta",
    "raw/inbox",
    "raw/sessions",
    "raw/artifacts",
    "raw/web",
    "output/reports",
    "output/charts",
]


def init(
    path: Path = typer.Argument(  # noqa: B008  # Typer requires `Argument()` evaluated at definition
        Path(),
        help="Directory to initialize the wiki in (defaults to current directory).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output result as JSON.",
    ),
) -> None:
    """Initialize a new knowledge base wiki."""
    target = path.resolve()

    # Check if already initialized
    if (target / CONFIG_FILENAME).exists():
        if json_output:
            typer.echo(json.dumps({"status": "error", "message": "Already initialized"}))
        else:
            typer.echo(f"Error: {CONFIG_FILENAME} already exists in {target}")
        raise typer.Exit(code=1)

    # Create directory structure
    for d in DIRECTORIES:
        (target / d).mkdir(parents=True, exist_ok=True)

    # Copy templates
    templates_dir = Path(__file__).resolve().parent.parent / "templates"

    # kb-config.yml
    shutil.copy2(str(templates_dir / "kb-config.yml"), str(target / CONFIG_FILENAME))

    # tag-taxonomy.md -> wiki/_meta/
    shutil.copy2(
        str(templates_dir / "tag-taxonomy.md"),
        str(target / "wiki" / "_meta" / "tag-taxonomy.md"),
    )

    # .gitignore
    shutil.copy2(str(templates_dir / "gitignore"), str(target / ".gitignore"))

    # Initialize empty manifest
    manifest_path = target / "raw" / "inbox" / ".manifest.json"
    manifest_path.write_text("[]\n")

    if json_output:
        result = {
            "status": "ok",
            "path": str(target),
            "directories": DIRECTORIES,
            "files": [
                CONFIG_FILENAME,
                "wiki/_meta/tag-taxonomy.md",
                ".gitignore",
                "raw/inbox/.manifest.json",
            ],
        }
        typer.echo(json.dumps(result, indent=2))
    else:
        typer.echo(f"Initialized knowledge base in {target}\n")
        typer.echo("Created:")
        for d in DIRECTORIES:
            typer.echo(f"  {d}/")
        typer.echo(f"  {CONFIG_FILENAME}")
        typer.echo("  wiki/_meta/tag-taxonomy.md")
        typer.echo("  .gitignore")
        typer.echo("  raw/inbox/.manifest.json")
        typer.echo("")
        typer.echo("Next steps:")
        typer.echo("  1. Edit .kb-config.yml to customize paths")
        typer.echo("  2. Run 'kb ingest --mode text --source \"Your first note\"'")
        typer.echo("  3. Run 'kb compile' to process the inbox")
