"""Tests for ``kb init`` — wiki project scaffolding."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.commands.init_cmd import DIRECTORIES

runner = CliRunner()


# ---------------------------------------------------------------------------
# Directory scaffolding
# ---------------------------------------------------------------------------


class TestInitCreatesDirectories:
    """``kb init`` should create all expected subdirectories."""

    def test_creates_all_dirs(self, tmp_path: Path):
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0, f"stdout: {result.stdout}"

        for subdir in DIRECTORIES:
            assert (tmp_path / subdir).is_dir(), f"Missing directory: {subdir}"

    def test_creates_config_file(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        config_path = tmp_path / ".kb-config.yml"
        assert config_path.exists(), ".kb-config.yml not created"

        cfg = yaml.safe_load(config_path.read_text())
        assert "paths" in cfg
        assert "lancedb" in cfg

    def test_creates_taxonomy(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        taxonomy = tmp_path / "wiki" / "_meta" / "tag-taxonomy.md"
        assert taxonomy.exists(), "tag-taxonomy.md not created"

        content = taxonomy.read_text()
        assert "## Knowledge Types" in content
        assert "## Approved Tags" in content

    def test_creates_gitignore(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists(), ".gitignore not created"

        content = gitignore.read_text()
        assert ".lancedb" in content

    def test_creates_empty_manifest(self, tmp_path: Path):
        runner.invoke(app, ["init", str(tmp_path)])
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        assert manifest.exists(), ".manifest.json not created"

        import json
        data = json.loads(manifest.read_text())
        assert data == []


# ---------------------------------------------------------------------------
# Idempotency / safety
# ---------------------------------------------------------------------------


class TestInitSafety:
    """``kb init`` should refuse to overwrite an existing wiki."""

    def test_refuses_overwrite(self, tmp_path: Path):
        # First init
        result1 = runner.invoke(app, ["init", str(tmp_path)])
        assert result1.exit_code == 0

        # Second init should fail
        result2 = runner.invoke(app, ["init", str(tmp_path)])
        assert result2.exit_code != 0

    def test_preserves_existing_config(self, tmp_path: Path):
        # Create a config with custom content
        config_path = tmp_path / ".kb-config.yml"
        custom_cfg = {"version": "custom", "paths": {"raw_inbox": "my-inbox"}}
        config_path.write_text(yaml.dump(custom_cfg))

        # Init should not overwrite it
        runner.invoke(app, ["init", str(tmp_path)])

        restored = yaml.safe_load(config_path.read_text())
        assert restored["version"] == "custom"


# ---------------------------------------------------------------------------
# Default path (cwd)
# ---------------------------------------------------------------------------


class TestInitDefaultPath:
    """``kb init`` with no arguments should use current directory."""

    def test_init_cwd(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / ".kb-config.yml").exists()


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestInitJsonOutput:
    """``kb init --json`` produces machine-readable output."""

    def test_json_on_success(self, tmp_path: Path):
        import json

        result = runner.invoke(app, ["init", "--json", str(tmp_path)])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert "directories" in data
        assert "files" in data

    def test_json_on_duplicate(self, tmp_path: Path):
        import json

        runner.invoke(app, ["init", str(tmp_path)])
        result = runner.invoke(app, ["init", "--json", str(tmp_path)])
        assert result.exit_code != 0

        data = json.loads(result.stdout)
        assert data["status"] == "error"
