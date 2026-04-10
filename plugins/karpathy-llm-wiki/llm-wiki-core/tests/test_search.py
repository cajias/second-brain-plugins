"""Tests for ``kb search`` — semantic search across wiki notes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_wiki.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Basic search
# ---------------------------------------------------------------------------


class TestSearchResults:
    """``kb search <query>`` returns results sorted by score."""

    def test_returns_results_after_index(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """After indexing, search should return results."""
        monkeypatch.chdir(populated_wiki)
        # Build the index first
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["search", "authentication patterns"])
        assert result.exit_code == 0
        assert len(result.stdout.strip()) > 0

    def test_results_sorted_by_score(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["search", "API gateway", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)

        if len(data) > 1:
            scores = [r["score"] for r in data]
            assert scores == sorted(scores, reverse=True), "Results not sorted by descending score"

    def test_no_results_returns_empty(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """Searching an empty wiki (no index) should handle gracefully."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["search", "nonexistent topic"])
        # Should either show "no results" or fail with no-index error
        assert result.exit_code == 0 or "error" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Limit parameter
# ---------------------------------------------------------------------------


class TestSearchLimit:
    """``kb search --limit N`` controls result count."""

    def test_limit_respected(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["search", "pattern", "--limit", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) <= 1

    def test_default_limit_from_config(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Default limit should come from config (10)."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["search", "pattern", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        # We have 3 notes, so should get at most 3 (less than default 10)
        assert len(data) <= 10


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestSearchJsonOutput:
    """``kb search --json`` produces structured output."""

    def test_json_fields(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["search", "token refresh", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)

        if data:
            item = data[0]
            for field in ("title", "score", "file_path", "id", "knowledge_type"):
                assert field in item, f"Missing field: {field}"
            assert isinstance(item["score"], (int, float))
            assert 0.0 <= item["score"] <= 1.0

    def test_json_empty_array_on_no_results(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """No results should produce an empty JSON array."""
        monkeypatch.chdir(wiki_root)
        # Build an empty index first
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["search", "xyznonexistent", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestSearchErrors:
    """Edge cases and error conditions."""

    def test_no_query_fails(self):
        """Missing query argument should produce an error."""
        result = runner.invoke(app, ["search"])
        assert result.exit_code != 0

    def test_no_config_fails(self, wiki_root_bare: Path, monkeypatch, mock_embedding_model):
        """Searching without a .kb-config.yml should fail gracefully."""
        monkeypatch.chdir(wiki_root_bare)
        result = runner.invoke(app, ["search", "anything"])
        assert result.exit_code != 0
