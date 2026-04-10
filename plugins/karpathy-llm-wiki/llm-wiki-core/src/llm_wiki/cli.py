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


def _get_cron_block(root: str) -> str:
    """Build the cron block for the given project root."""
    return "\n".join(line.format(root=root) for line in _CRON_LINES)


def _read_crontab() -> str:
    """Read the current crontab, returning empty string if none."""
    import subprocess
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _write_crontab(content: str) -> None:
    """Write content as the new crontab."""
    import subprocess
    subprocess.run(
        ["crontab", "-"],
        input=content,
        text=True,
        timeout=5,
        check=True,
    )


def _remove_kb_block(crontab_text: str) -> str:
    """Remove the LLM Wiki maintenance block from crontab text."""
    lines = crontab_text.splitlines()
    result = []
    skip = False
    for line in lines:
        if line.strip() == "# LLM Wiki maintenance jobs":
            skip = True
            continue
        if skip and line.strip() == "":
            skip = False
            continue
        if skip and (line.strip().startswith("0 ") or line.strip().startswith("*")):
            continue
        skip = False
        result.append(line)
    return "\n".join(result).rstrip("\n") + "\n" if result else ""


@maintenance_app.command("enable")
def maintenance_enable(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON."),
) -> None:
    """Install maintenance cron jobs into the system crontab."""
    from llm_wiki.core.config import load_config
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    root = str(cfg.project_root)
    cron_block = _get_cron_block(root)

    existing = _read_crontab()
    cleaned = _remove_kb_block(existing)
    new_crontab = cleaned.rstrip("\n") + "\n\n" + cron_block + "\n" if cleaned.strip() else cron_block + "\n"

    _write_crontab(new_crontab)

    if json_output:
        typer.echo(json.dumps({"action": "enabled", "cron_block": cron_block}))
    else:
        typer.echo("Maintenance cron jobs installed:\n")
        typer.echo(cron_block)
        typer.echo("\nSchedule:")
        typer.echo("  - Incremental index rebuild every night at 2am")
        typer.echo("  - Full lint report every Sunday at 3am")
        typer.echo("  - Chart regeneration every Sunday at 4am")
        typer.echo("\nRun 'kb maintenance status' to verify.")


@maintenance_app.command("disable")
def maintenance_disable(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON."),
) -> None:
    """Remove maintenance cron jobs from the system crontab."""
    existing = _read_crontab()
    cleaned = _remove_kb_block(existing)

    if cleaned.strip() == existing.strip():
        if json_output:
            typer.echo(json.dumps({"action": "disable", "status": "not_found"}))
        else:
            typer.echo("No LLM Wiki maintenance jobs found in crontab.")
        return

    _write_crontab(cleaned)

    if json_output:
        typer.echo(json.dumps({"action": "disabled"}))
    else:
        typer.echo("LLM Wiki maintenance jobs removed from crontab.")


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
