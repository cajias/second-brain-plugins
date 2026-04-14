"""Main CLI entry point for the llm-wiki knowledge base toolkit.

Uses Typer to expose subcommands: init, ingest, compile, search, lint, index, charts, maintenance.
"""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path

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

_CRON_HEADER = "# LLM Wiki maintenance jobs"

# Default PATH segments merged with the dir of the active `kb` binary.
# Covers common install locations (Homebrew Intel/ARM, /usr/local, system).
_DEFAULT_PATH_DIRS = [
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/usr/bin",
    "/bin",
]

_CRON_JOB_TEMPLATES = [
    "0 2 * * * cd {root} && kb index --incremental 2>&1 | logger -t kb-index",
    "0 3 * * 0 cd {root} && kb lint --json > {lint_out} 2>&1",
    "0 4 * * 0 cd {root} && kb charts --all 2>&1 | logger -t kb-charts",
]


def _build_cron_path() -> str:
    """Build a PATH value for cron that includes the active `kb` binary's dir.

    cron runs with a minimal PATH (usually /usr/bin:/bin), so user-installed
    tools like `kb` at ~/.local/bin/ are invisible. We detect the active
    install location and prepend it to a list of common bin dirs.
    """
    dirs: list[str] = []
    kb_path = shutil.which("kb")
    if kb_path:
        kb_dir = str(Path(kb_path).parent)
        dirs.append(kb_dir)
    for d in _DEFAULT_PATH_DIRS:
        if d not in dirs:
            dirs.append(d)
    return ":".join(dirs)


def _get_cron_block(root: str) -> str:
    """Build the cron block for the given project root.

    Shell-quotes the root path (handles spaces and special chars) and
    prepends a PATH= line so cron can find the `kb` binary.
    """
    quoted_root = shlex.quote(root)
    lint_out = shlex.quote(f"{root}/output/reports/lint-weekly.json")
    path_line = f"PATH={_build_cron_path()}"
    lines = [_CRON_HEADER, path_line]
    for tmpl in _CRON_JOB_TEMPLATES:
        lines.append(tmpl.format(root=quoted_root, lint_out=lint_out))
    return "\n".join(lines)


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
    """Remove the LLM Wiki maintenance block from crontab text.

    The block starts with the header comment and continues until a line
    outside the block's expected shapes (PATH=, schedule entries, or
    blank separator). This is resilient to both the legacy format
    (no PATH= line) and the current format.
    """
    lines = crontab_text.splitlines()
    result = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped == _CRON_HEADER:
            skip = True
            continue
        if skip and stripped == "":
            skip = False
            continue
        if skip and (
            stripped.startswith("0 ")
            or stripped.startswith("*")
            or stripped.startswith("PATH=")
        ):
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
