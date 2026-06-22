"""Tests for ``kb search`` — semantic search across wiki notes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from llm_wiki.cli import app


if TYPE_CHECKING:
    from pathlib import Path


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

    def test_tags_is_list_in_json_output(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Tags field in --json output must be a plain list (not ndarray/str) so JSON round-trips cleanly."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])

        result = runner.invoke(app, ["search", "pattern", "--json"])
        assert result.exit_code == 0, f"search failed: {result.output}"
        data = json.loads(result.stdout)

        for item in data:
            assert isinstance(item["tags"], list), f"tags must be a list, got {type(item['tags'])!r}: {item['tags']!r}"
            for tag in item["tags"]:
                assert isinstance(tag, str), f"each tag must be a str, got {type(tag)!r}"

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
        """No query AND no filter should produce an error (non-zero exit)."""
        result = runner.invoke(app, ["search"])
        assert result.exit_code != 0

    def test_no_config_fails(self, wiki_root_bare: Path, monkeypatch, mock_embedding_model):
        """Searching without a .kb-config.yml should fail gracefully."""
        monkeypatch.chdir(wiki_root_bare)
        result = runner.invoke(app, ["search", "anything"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Filter CLI
# ---------------------------------------------------------------------------


class TestSearchFilterCLI:
    """``kb search --knowledge-type / --tag / --type / --scope / --where`` flags."""

    def test_filter_only_enumerates_all(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Filter-only with --knowledge-type should return all matching notes."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--knowledge-type", "pattern", "--json"])
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert all(r["knowledge_type"] == "pattern" for r in data)

    def test_repeated_tag_flag_anded(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Repeated --tag flags are AND-ed: only notes with all tags match."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--tag", "security", "--tag", "authentication", "--json"])
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        data = json.loads(result.stdout)
        assert len(data) == 1

    def test_no_query_no_filter_errors(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Bare ``kb search`` with no query and no filter must exit non-zero."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search"])
        assert result.exit_code != 0

    def test_score_none_renders_safely(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Human-readable output for filter-only results (score=None) must not crash."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--knowledge-type", "idea"])
        assert result.exit_code == 0, f"crashed on score=None: {result.output}"
        # No score line should contain "None" as a float; should show no score or "—"
        assert ":.4f" not in result.stdout
        assert "None" not in result.stdout

    def test_score_none_in_json_output(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Filter-only --json output: score field must be null (not crash on None)."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--knowledge-type", "idea", "--json"])
        assert result.exit_code == 0, f"crashed on score=None JSON: {result.output}"
        data = json.loads(result.stdout)
        assert data
        assert all(r["score"] is None for r in data)

    def test_query_with_filter_backward_compat(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Positional query + filter combo works and returns scored results."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "authentication", "--knowledge-type", "pattern", "--json"])
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        data = json.loads(result.stdout)
        for r in data:
            assert r["knowledge_type"] == "pattern"
            assert r["score"] is not None

    def test_filter_only_large_result_set_not_capped(self, large_wiki: Path, monkeypatch, mock_embedding_model):
        """Filter-only must return ALL matching notes, not be silently capped at 10."""
        monkeypatch.chdir(large_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--knowledge-type", "concept", "--json"])
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        data = json.loads(result.stdout)
        # large_wiki has 12 concept notes — we must get all 12, not just 10
        assert len(data) == 12, f"expected 12 results (uncapped), got {len(data)}"
        assert all(r["knowledge_type"] == "concept" for r in data)

    def test_type_option(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """--type flag filters by the frontmatter type field; all 3 notes are permanent."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--type", "permanent", "--json"])
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        data = json.loads(result.stdout)
        assert len(data) == 3

    def test_scope_option(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """--scope flag filters by the frontmatter scope field; only orphan-note is project."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        result = runner.invoke(app, ["search", "--scope", "project", "--json"])
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        data = json.loads(result.stdout)
        assert len(data) == 1

    def test_where_option(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """--where raw SQL predicate is forwarded to the index."""
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        # scope='project' matches only orphan-note
        result = runner.invoke(app, ["search", "--where", "scope = 'project'", "--json"])
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        data = json.loads(result.stdout)
        assert len(data) == 1


# ---------------------------------------------------------------------------
# Filter predicate builder
# ---------------------------------------------------------------------------


class TestFilterPredicate:
    """Unit tests for ``_build_filter_predicate`` — pure SQL predicate builder."""

    def test_no_filters_returns_none(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate(None, None, None, None, None) is None

    def test_knowledge_type_clause(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate("tool", None, None, None, None) == "knowledge_type = 'tool'"

    def test_single_tag_via_array_has_any(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate(None, ["tool-cli"], None, None, None) == "array_has_any(tags, ['tool-cli'])"

    def test_repeated_tags_anded_via_array_has_any(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        pred = _build_filter_predicate(None, ["tool-cli", "phase-testing"], None, None, None)
        assert pred == "array_has_any(tags, ['tool-cli']) AND array_has_any(tags, ['phase-testing'])"

    def test_type_clause(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate(None, None, "permanent", None, None) == "type = 'permanent'"

    def test_scope_clause(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate(None, None, None, "universal", None) == "scope = 'universal'"

    def test_combined_clauses_anded(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        pred = _build_filter_predicate("tool", ["tool-cli"], "permanent", "universal", None)
        assert pred == (
            "knowledge_type = 'tool' AND array_has_any(tags, ['tool-cli']) "
            "AND type = 'permanent' AND scope = 'universal'"
        )

    def test_where_passthrough_appended(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate("tool", None, None, None, "confidence > 0.5") == (
            "knowledge_type = 'tool' AND (confidence > 0.5)"
        )

    def test_where_only(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate(None, None, None, None, "confidence > 0.5") == "(confidence > 0.5)"

    def test_single_quote_escaped(self):
        from llm_wiki.core.embeddings import _build_filter_predicate

        assert _build_filter_predicate("o'brien", None, None, None, None) == "knowledge_type = 'o''brien'"


# ---------------------------------------------------------------------------
# search_index filter params + filter-only path
# ---------------------------------------------------------------------------


class TestSearchIndexFilters:
    """Tests for ``search_index`` frontmatter filters and filter-only path."""

    def test_filter_only_returns_all_matching(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Filter-only (query=None) should return ALL rows matching the predicate."""
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        db = populated_wiki / ".lancedb"
        # populated_wiki has two knowledge_type=pattern notes
        res = search_index(db, "notes", query=None, knowledge_type="pattern")
        kinds = {r["knowledge_type"] for r in res}
        assert kinds == {"pattern"}
        assert len(res) == 2

    def test_filter_only_score_is_none(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Filter-only results must have score=None (no semantic ranking)."""
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(populated_wiki / ".lancedb", "notes", query=None, knowledge_type="pattern")
        assert res
        for r in res:
            assert r["score"] is None

    def test_tags_returned_as_list(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Tags in filter-only results must be a plain Python list."""
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(populated_wiki / ".lancedb", "notes", query=None, knowledge_type="idea")
        assert res
        assert isinstance(res[0]["tags"], list)
        assert res[0]["tags"] == ["llm"]

    def test_and_tag_filter(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Multiple tags must be AND-filtered (narrows the result set)."""
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(populated_wiki / ".lancedb", "notes", query=None, tags=["security", "authentication"])
        assert len(res) == 1  # only token-refresh-strategy has both

    def test_vector_plus_filter(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Vector search with a filter should return scored results matching the predicate."""
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(populated_wiki / ".lancedb", "notes", query="authentication", knowledge_type="concept")
        for r in res:
            assert r["knowledge_type"] == "concept"
            assert r["score"] is not None
            assert 0.0 <= r["score"] <= 1.0

    def test_empty_result_set(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """Filtering on a knowledge_type with no matches returns an empty list."""
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(populated_wiki / ".lancedb", "notes", query=None, knowledge_type="nonexistent_type")
        assert res == []

    def test_query_none_no_filters_returns_all(self, populated_wiki: Path, monkeypatch, mock_embedding_model):
        """query=None with no filters returns all rows (unscored)."""
        from llm_wiki.core.embeddings import search_index

        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index", "--full"])
        res = search_index(populated_wiki / ".lancedb", "notes", query=None)
        # populated_wiki has notes; we get them all back unscored
        assert len(res) > 0
        for r in res:
            assert r["score"] is None
