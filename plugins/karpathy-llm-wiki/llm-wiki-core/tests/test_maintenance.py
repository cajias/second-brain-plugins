"""Tests for ``kb maintenance`` -- cron-based scheduler integration.

These tests never touch the real user crontab. ``_read_crontab`` /
``_write_crontab`` (and the inline ``subprocess.run`` call in
``maintenance_status``) are monkeypatched so writes are captured in a
list and reads return canned strings.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from llm_wiki import cli as cli_mod
from llm_wiki.cli import (
    _CRON_HEADER,
    _build_cron_path,
    _get_cron_block,
    _read_crontab,
    _remove_kb_block,
    _write_crontab,
    app,
)


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


# ---------------------------------------------------------------------------
# _build_cron_path
# ---------------------------------------------------------------------------


class TestBuildCronPath:
    def test_includes_kb_install_dir_first(self, monkeypatch):
        monkeypatch.setattr(cli_mod.shutil, "which", lambda _: "/Users/me/.local/bin/kb")
        path = _build_cron_path()
        parts = path.split(":")
        assert parts[0] == "/Users/me/.local/bin"
        # Default dirs still present
        assert "/usr/local/bin" in parts
        assert "/opt/homebrew/bin" in parts

    def test_handles_kb_not_found(self, monkeypatch):
        monkeypatch.setattr(cli_mod.shutil, "which", lambda _: None)
        path = _build_cron_path()
        # Falls back to defaults only
        assert path == "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

    def test_no_duplicate_when_kb_in_default_dir(self, monkeypatch):
        monkeypatch.setattr(cli_mod.shutil, "which", lambda _: "/usr/local/bin/kb")
        path = _build_cron_path()
        assert path.count("/usr/local/bin") == 1


# ---------------------------------------------------------------------------
# _get_cron_block
# ---------------------------------------------------------------------------


class TestGetCronBlock:
    def test_contains_header_path_and_three_jobs(self, monkeypatch):
        monkeypatch.setattr(cli_mod.shutil, "which", lambda _: "/usr/local/bin/kb")
        block = _get_cron_block("/tmp/wiki")
        lines = block.splitlines()
        assert lines[0] == _CRON_HEADER
        assert lines[1].startswith("PATH=")
        assert "kb index --incremental" in block
        assert "kb lint --json" in block
        assert "kb charts --all" in block

    def test_shell_quotes_root_with_spaces(self, monkeypatch):
        monkeypatch.setattr(cli_mod.shutil, "which", lambda _: None)
        block = _get_cron_block("/tmp/path with space")
        # shlex.quote on a path with a space produces single-quoted string
        assert "'/tmp/path with space'" in block
        # Lint output path also quoted
        assert "'/tmp/path with space/output/reports/lint-weekly.json'" in block


# ---------------------------------------------------------------------------
# _remove_kb_block
# ---------------------------------------------------------------------------


class TestRemoveKbBlock:
    def test_removes_current_format_block(self):
        existing = (
            "# Some user job\n"
            "0 1 * * * /usr/local/bin/backup\n"
            f"{_CRON_HEADER}\n"
            "PATH=/usr/local/bin:/usr/bin:/bin\n"
            "0 2 * * * cd '/tmp/wiki' && kb index --incremental\n"
            "0 3 * * 0 cd '/tmp/wiki' && kb lint --json\n"
            "0 4 * * 0 cd '/tmp/wiki' && kb charts --all\n"
            "\n"
            "# Other unrelated job\n"
            "*/5 * * * * /usr/bin/foo\n"
        )
        cleaned = _remove_kb_block(existing)
        assert _CRON_HEADER not in cleaned
        assert "kb index" not in cleaned
        assert "kb lint" not in cleaned
        assert "kb charts" not in cleaned
        # Unrelated jobs preserved
        assert "/usr/local/bin/backup" in cleaned
        assert "/usr/bin/foo" in cleaned

    def test_removes_legacy_format_without_path(self):
        """Legacy block has no PATH= line; removal must still work."""
        existing = (
            f"{_CRON_HEADER}\n"
            "0 2 * * * cd /tmp/wiki && kb index --incremental\n"
            "0 3 * * 0 cd /tmp/wiki && kb lint --json\n"
            "\n"
            "# kept\n"
            "0 0 * * * echo hi\n"
        )
        cleaned = _remove_kb_block(existing)
        assert "kb index" not in cleaned
        assert "kb lint" not in cleaned
        assert "echo hi" in cleaned

    def test_idempotent_when_no_kb_block(self):
        existing = "# user only\n0 1 * * * echo hello\n"
        cleaned = _remove_kb_block(existing)
        # Content preserved
        assert "0 1 * * * echo hello" in cleaned

    def test_empty_input_returns_empty(self):
        assert _remove_kb_block("") == ""

    def test_only_kb_block_returns_empty(self, monkeypatch):
        monkeypatch.setattr(cli_mod.shutil, "which", lambda _: None)
        block = _get_cron_block("/tmp/wiki")
        cleaned = _remove_kb_block(block)
        # When the only content was the kb block, result is empty string
        assert cleaned == ""


# ---------------------------------------------------------------------------
# _read_crontab / _write_crontab (subprocess wrappers)
# ---------------------------------------------------------------------------


class TestReadCrontab:
    def test_returns_stdout_on_success(self, monkeypatch):
        fake = MagicMock(returncode=0, stdout="line1\nline2\n")
        monkeypatch.setattr("subprocess.run", lambda *_a, **_kw: fake)
        assert _read_crontab() == "line1\nline2\n"

    def test_returns_empty_on_nonzero_exit(self, monkeypatch):
        fake = MagicMock(returncode=1, stdout="ignored")
        monkeypatch.setattr("subprocess.run", lambda *_a, **_kw: fake)
        assert _read_crontab() == ""

    def test_returns_empty_when_crontab_missing(self, monkeypatch):
        def _raise(*a: Any, **kw: Any):
            raise FileNotFoundError

        monkeypatch.setattr("subprocess.run", _raise)
        assert _read_crontab() == ""

    def test_returns_empty_on_timeout(self, monkeypatch):
        import subprocess

        def _raise(*a: Any, **kw: Any):
            raise subprocess.TimeoutExpired(cmd="crontab", timeout=5)

        monkeypatch.setattr("subprocess.run", _raise)
        assert _read_crontab() == ""


class TestWriteCrontab:
    def test_invokes_subprocess_with_input(self, monkeypatch):
        captured: dict[str, Any] = {}

        def _fake_run(cmd, input, text, timeout, check):  # noqa: A002
            captured["cmd"] = cmd
            captured["input"] = input
            captured["check"] = check

        monkeypatch.setattr("subprocess.run", _fake_run)
        _write_crontab("hello\n")
        assert captured["cmd"] == ["crontab", "-"]
        assert captured["input"] == "hello\n"
        assert captured["check"] is True


# ---------------------------------------------------------------------------
# maintenance_enable / disable / status -- via CliRunner
# ---------------------------------------------------------------------------


@pytest.fixture
def cron_sandbox(monkeypatch):
    """Patch crontab IO and shutil.which so no real crontab is touched.

    Returns a dict the tests can read/write to control the simulated crontab
    state: ``state["current"]`` is what ``_read_crontab`` returns;
    ``state["written"]`` accumulates calls to ``_write_crontab``.
    """
    state: dict[str, Any] = {"current": "", "written": []}

    monkeypatch.setattr(cli_mod, "_read_crontab", lambda: state["current"])
    monkeypatch.setattr(cli_mod, "_write_crontab", state["written"].append)
    monkeypatch.setattr(cli_mod.shutil, "which", lambda _: "/usr/local/bin/kb")
    return state


class TestMaintenanceEnable:
    def test_installs_block_in_empty_crontab(self, cron_sandbox, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["maintenance", "enable"])
        assert result.exit_code == 0, result.output
        assert len(cron_sandbox["written"]) == 1
        written = cron_sandbox["written"][0]
        assert _CRON_HEADER in written
        assert "kb index --incremental" in written

    def test_preserves_existing_unrelated_jobs(self, cron_sandbox, wiki_root: Path, monkeypatch):
        cron_sandbox["current"] = "0 6 * * * /usr/local/bin/backup\n"
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["maintenance", "enable"])
        assert result.exit_code == 0, result.output
        written = cron_sandbox["written"][0]
        assert "/usr/local/bin/backup" in written
        assert _CRON_HEADER in written

    def test_replaces_existing_kb_block(self, cron_sandbox, wiki_root: Path, monkeypatch):
        # Pre-existing (stale) kb block in crontab
        cron_sandbox["current"] = f"{_CRON_HEADER}\nPATH=/old\n0 2 * * * cd /old && kb index --incremental\n"
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["maintenance", "enable"])
        assert result.exit_code == 0, result.output
        written = cron_sandbox["written"][0]
        # Only one header in the new crontab (no duplicate)
        assert written.count(_CRON_HEADER) == 1
        assert "/old" not in written

    def test_json_output(self, cron_sandbox, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["maintenance", "enable", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["action"] == "enabled"
        assert _CRON_HEADER in payload["cron_block"]

    def test_errors_when_no_config(self, cron_sandbox, wiki_root_bare: Path, monkeypatch):
        monkeypatch.chdir(wiki_root_bare)
        result = runner.invoke(app, ["maintenance", "enable"])
        assert result.exit_code != 0
        # No write should have happened
        assert cron_sandbox["written"] == []


class TestMaintenanceDisable:
    def test_removes_block_when_present(self, cron_sandbox, monkeypatch):
        cron_sandbox["current"] = (
            "# user job\n0 1 * * * echo hi\n"
            f"{_CRON_HEADER}\n"
            "PATH=/usr/local/bin:/usr/bin:/bin\n"
            "0 2 * * * cd /tmp/wiki && kb index --incremental\n"
            "0 3 * * 0 cd /tmp/wiki && kb lint --json\n"
            "0 4 * * 0 cd /tmp/wiki && kb charts --all\n"
        )
        result = runner.invoke(app, ["maintenance", "disable"])
        assert result.exit_code == 0, result.output
        assert len(cron_sandbox["written"]) == 1
        written = cron_sandbox["written"][0]
        assert _CRON_HEADER not in written
        assert "echo hi" in written  # unrelated job preserved

    def test_no_op_when_block_absent(self, cron_sandbox):
        cron_sandbox["current"] = "0 1 * * * echo only-user\n"
        result = runner.invoke(app, ["maintenance", "disable"])
        assert result.exit_code == 0, result.output
        # Disable must NOT write when there's nothing to remove
        assert cron_sandbox["written"] == []
        assert "no llm wiki" in result.stdout.lower()

    def test_no_op_json(self, cron_sandbox):
        cron_sandbox["current"] = "0 1 * * * echo only-user\n"
        result = runner.invoke(app, ["maintenance", "disable", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "not_found"
        assert cron_sandbox["written"] == []

    def test_disable_json_when_present(self, cron_sandbox):
        cron_sandbox["current"] = f"{_CRON_HEADER}\n0 2 * * * cd /tmp && kb index --incremental\n"
        result = runner.invoke(app, ["maintenance", "disable", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["action"] == "disabled"


class TestMaintenanceStatus:
    """Tests for the ``maintenance status`` command.

    ``maintenance_status`` calls ``subprocess.run`` directly (not the helper),
    so we patch subprocess.run for these tests.
    """

    def _patch_crontab_output(self, monkeypatch, stdout: str, returncode: int = 0):
        fake = MagicMock(returncode=returncode, stdout=stdout)
        monkeypatch.setattr("subprocess.run", lambda *_a, **_kw: fake)

    def test_reports_all_enabled(self, monkeypatch):
        self._patch_crontab_output(
            monkeypatch,
            "0 2 * * * kb index --incremental\n0 3 * * 0 kb lint --json\n0 4 * * 0 kb charts --all\n",
        )
        result = runner.invoke(app, ["maintenance", "status", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["all_enabled"] is True
        assert payload["index_job"] is True
        assert payload["lint_job"] is True
        assert payload["charts_job"] is True

    def test_reports_partial(self, monkeypatch):
        self._patch_crontab_output(monkeypatch, "0 2 * * * kb index --incremental\n")
        result = runner.invoke(app, ["maintenance", "status", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["all_enabled"] is False
        assert payload["index_job"] is True
        assert payload["lint_job"] is False
        assert payload["charts_job"] is False

    def test_reports_none_when_empty(self, monkeypatch):
        self._patch_crontab_output(monkeypatch, "")
        result = runner.invoke(app, ["maintenance", "status", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["all_enabled"] is False

    def test_handles_missing_crontab(self, monkeypatch):
        def _raise(*a: Any, **kw: Any):
            raise FileNotFoundError

        monkeypatch.setattr("subprocess.run", _raise)
        result = runner.invoke(app, ["maintenance", "status", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["all_enabled"] is False

    def test_human_readable_output(self, monkeypatch):
        self._patch_crontab_output(
            monkeypatch,
            "0 2 * * * kb index --incremental\n0 3 * * 0 kb lint --json\n0 4 * * 0 kb charts --all\n",
        )
        result = runner.invoke(app, ["maintenance", "status"])
        assert result.exit_code == 0, result.output
        assert "enabled" in result.stdout.lower()
        assert "Index rebuild" in result.stdout
