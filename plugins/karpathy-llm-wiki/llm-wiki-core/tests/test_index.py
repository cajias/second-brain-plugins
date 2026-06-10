"""Tests for ``kb index`` — LanceDB vector index building."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from llm_wiki.cli import app


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


# ---------------------------------------------------------------------------
# Full index build
# ---------------------------------------------------------------------------


class TestFullIndex:
    """``kb index --full`` should build the LanceDB table from all notes."""

    def test_indexes_all_notes(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["index", "--full"])
        assert result.exit_code == 0
        assert "3" in result.stdout  # 3 notes indexed

    def test_creates_lancedb_directory(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        lancedb_dir = populated_wiki / ".lancedb"
        assert lancedb_dir.exists()

    def test_empty_wiki_creates_empty_index(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """Indexing a wiki with no notes should create an empty table, not error."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["index", "--full"])
        assert result.exit_code == 0
        assert "0" in result.stdout or "empty" in result.stdout.lower()

    def test_writes_stats_file(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        stats_file = populated_wiki / "wiki" / "_meta" / "stats.md"
        assert stats_file.exists()
        content = stats_file.read_text()
        assert "Total notes" in content


# ---------------------------------------------------------------------------
# Incremental index
# ---------------------------------------------------------------------------


class TestIncrementalIndex:
    """``kb index --incremental`` only processes modified files."""

    def test_incremental_skips_unmodified(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """After a full index, incremental with no changes should do nothing."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["index", "--incremental"])
        assert result.exit_code == 0
        assert "0" in result.stdout or "nothing" in result.stdout.lower()

    def test_incremental_processes_modified(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """After modifying a file, incremental should reindex just that file."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        # Touch one file to make it appear modified
        time.sleep(0.1)
        note = populated_wiki / "wiki" / "permanent" / "orphan-note.md"
        content = note.read_text()
        note.write_text(content + "\nAppended content.\n")

        result = runner.invoke(app, ["index", "--incremental"])
        assert result.exit_code == 0
        assert "1" in result.stdout

    def test_incremental_falls_back_to_full(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """If no previous index exists, incremental should do a full index."""
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(app, ["index", "--incremental"])
        assert result.exit_code == 0
        assert "full" in result.stdout.lower() or "3" in result.stdout


# ---------------------------------------------------------------------------
# Stats mode
# ---------------------------------------------------------------------------


class TestIndexStats:
    """``kb index --stats`` shows index statistics."""

    def test_stats_after_index(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["index", "--stats"])
        assert result.exit_code == 0
        assert "3" in result.stdout  # total notes
        assert "knowledge_type" in result.stdout.lower()

    def test_stats_json(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        import json

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["index", "--stats", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["total"] == 3
        assert "by_knowledge_type" in data

    def test_stats_no_index_error(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["index", "--stats"])
        assert result.exit_code == 0
        assert "no index" in result.stdout.lower() or "error" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestIndexValidation:
    """Edge cases for the index command."""

    def test_no_mode_errors(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """Running ``index`` with no flags should error."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["index"])
        assert result.exit_code != 0
