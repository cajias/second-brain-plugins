"""Main CLI entry point for the llm-wiki knowledge base toolkit.

Uses Typer to expose subcommands: init, ingest, compile, search, lint, index, charts, maintenance.
"""

from __future__ import annotations

import json

import typer

from llm_wiki.commands.init_cmd import init
from llm_wiki.commands.ingest import ingest
from llm_wiki.commands.compile_cmd import compile_notes
from llm_wiki.commands.search import search
from llm_wiki.commands.lint import lint
from llm_wiki.commands.index import index
from llm_wiki.commands.charts import charts

app = typer.Typer(
    name="kb",
    help="llm-wiki -- Karpathy-style personal knowledge wiki toolkit.",
    no_args_is_help=True,
)

# -- Top-level commands --------------------------------------------------------

app.command("init")(init)
app.command("ingest")(ingest)
app.command("compile")(compile_notes)
app.command("search")(search)
app.command("lint")(lint)
app.command("index")(index)
app.command("charts")(charts)

# -- Maintenance subcommand group ----------------------------------------------

maintenance_app = typer.Typer(
    name="maintenance",
    help="Manage scheduled maintenance jobs (cron-based).",
    no_args_is_help=True,
)
app.add_typer(maintenance_app, name="maintenance")

_CRON_LINES = [
    "# LLM Wiki maintenance jobs",
    "0 2 * * * cd {root} && kb index --incremental 2>&1 | logger -t kb-index",
    "0 3 * * 0 cd {root} && kb lint --json > {root}/output/reports/lint-weekly.json 2>&1",
    "0 4 * * 0 cd {root} && kb charts --all 2>&1 | logger -t kb-charts",
]


@maintenance_app.command("enable")
def maintenance_enable(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON."),
) -> None:
    """Print cron setup instructions for scheduled maintenance."""
    from llm_wiki.core.config import load_config
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    root = str(cfg.project_root)
    lines = [line.format(root=root) for line in _CRON_LINES]
    cron_block = "\n".join(lines)

    if json_output:
        typer.echo(json.dumps({"action": "enable", "cron_block": cron_block}))
    else:
        typer.echo("Add the following lines to your crontab (crontab -e):\n")
        typer.echo(cron_block)
        typer.echo("\nThis will run:")
        typer.echo("  - Incremental index rebuild every night at 2am")
        typer.echo("  - Full lint report every Sunday at 3am")
        typer.echo("  - Chart regeneration every Sunday at 4am")


@maintenance_app.command("disable")
def maintenance_disable(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON."),
) -> None:
    """Print instructions to remove maintenance cron jobs."""
    if json_output:
        typer.echo(json.dumps({"action": "disable", "instructions": "Run 'crontab -e' and remove the LLM Wiki lines."}))
    else:
        typer.echo("To disable maintenance, run 'crontab -e' and remove the lines")
        typer.echo("between '# LLM Wiki maintenance jobs' and the next blank line.")


@maintenance_app.command("status")
def maintenance_status(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON."),
) -> None:
    """Check if maintenance cron jobs exist."""
    import subprocess

    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        crontab_text = result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        crontab_text = ""

    has_index = "kb index" in crontab_text or "kb-index" in crontab_text
    has_lint = "kb lint" in crontab_text or "kb-lint" in crontab_text
    has_charts = "kb charts" in crontab_text or "kb-charts" in crontab_text

    status = {
        "index_job": has_index,
        "lint_job": has_lint,
        "charts_job": has_charts,
        "all_enabled": has_index and has_lint and has_charts,
    }

    if json_output:
        typer.echo(json.dumps(status, indent=2))
    else:
        typer.echo("Maintenance cron job status:")
        typer.echo(f"  Index rebuild:    {'enabled' if has_index else 'not found'}")
        typer.echo(f"  Lint report:      {'enabled' if has_lint else 'not found'}")
        typer.echo(f"  Chart generation: {'enabled' if has_charts else 'not found'}")
        if not status["all_enabled"]:
            typer.echo("\nRun 'kb maintenance enable' for setup instructions.")
