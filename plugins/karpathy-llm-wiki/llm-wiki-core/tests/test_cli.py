"""Tests for the top-level CLI (``kb``) — help, subcommands, and error handling."""

from __future__ import annotations

from typer.testing import CliRunner

from llm_wiki.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Help output
# ---------------------------------------------------------------------------


class TestHelpOutput:
    """``kb --help`` should advertise all subcommands."""

    EXPECTED_SUBCOMMANDS = ["init", "ingest", "compile", "search", "lint", "index", "charts"]

    def test_help_shows_all_subcommands(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in self.EXPECTED_SUBCOMMANDS:
            assert cmd in result.stdout, f"Missing subcommand in help: {cmd}"

    def test_help_shows_description(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "wiki" in result.stdout.lower()

    def test_no_args_shows_help(self):
        """Running ``kb`` with no arguments should show help (no_args_is_help=True).

        Typer returns exit code 2 when displaying help via no_args_is_help,
        but the help text is still printed to stdout.
        """
        result = runner.invoke(app, [])
        assert result.exit_code in (0, 2)
        assert "init" in result.stdout


# ---------------------------------------------------------------------------
# Subcommand help
# ---------------------------------------------------------------------------


class TestSubcommandHelp:
    """Each subcommand should have its own --help."""

    def test_init_help(self):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "init" in result.stdout.lower() or "knowledge base" in result.stdout.lower()

    def test_ingest_help(self):
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0
        assert "ingest" in result.stdout.lower() or "source" in result.stdout.lower()

    def test_compile_help(self):
        result = runner.invoke(app, ["compile", "--help"])
        assert result.exit_code == 0

    def test_search_help(self):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0
        assert "query" in result.stdout.lower()

    def test_lint_help(self):
        result = runner.invoke(app, ["lint", "--help"])
        assert result.exit_code == 0

    def test_index_help(self):
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0

    def test_charts_help(self):
        result = runner.invoke(app, ["charts", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Invalid usage should produce clear errors."""

    def test_unknown_subcommand(self):
        result = runner.invoke(app, ["nonexistent-command"])
        assert result.exit_code != 0

    def test_maintenance_subgroup_help(self):
        """``kb maintenance --help`` should list enable/disable/status."""
        result = runner.invoke(app, ["maintenance", "--help"])
        assert result.exit_code == 0
        assert "enable" in result.stdout.lower()
        assert "disable" in result.stdout.lower()
        assert "status" in result.stdout.lower()
