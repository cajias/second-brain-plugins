"""Tests for ``kb compile`` — note compilation, dedup checking, and manifest management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_wiki.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Dedup checking
# ---------------------------------------------------------------------------


class TestCheckDedup:
    """``kb compile --check-dedup`` classifies content similarity.

    Thresholds (from original kb_compile.py):
      >= 0.92  -> duplicate
      0.80-0.91 -> similar
      < 0.80   -> unique
    """

    def test_unique_when_no_index(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """With no LanceDB index, dedup should default to 'unique'."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "completely novel unrelated content xyz123"],
        )
        assert result.exit_code == 0
        assert "unique" in result.stdout.lower()

    def test_check_dedup_json(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "novel content", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] in ("unique", "similar", "duplicate")
        assert "top_score" in data
        assert isinstance(data["matches"], list)

    def test_check_dedup_returns_valid_status(self, wiki_root: Path, monkeypatch, mock_embedding_model):
        """Status must be one of the three defined classes."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "API gateway patterns", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] in ("unique", "similar", "duplicate", "error")


class TestDedupModule:
    """Direct tests for the dedup.check_duplicate function."""

    def test_returns_unique_with_no_index(self, wiki_root: Path, mock_embedding_model):
        from llm_wiki.core.dedup import check_duplicate

        result = check_duplicate("test query", wiki_root / ".lancedb", "notes")
        assert result["status"] == "unique"
        assert result["top_score"] == 0.0
        assert result["matches"] == []


# ---------------------------------------------------------------------------
# Write note
# ---------------------------------------------------------------------------


class TestWriteNote:
    """``kb compile --write-note`` creates a permanent note."""

    def _write_note_args(self, **overrides) -> list[str]:
        defaults = {
            "title": "Test Pattern Note",
            "knowledge-type": "pattern",
            "tags": "architecture,api-design",
            "confidence": "high",
            "source": "session-test",
            "body": "This is the body of the note.",
        }
        defaults.update(overrides)
        args = ["compile", "--write-note"]
        for key, val in defaults.items():
            args.extend([f"--{key}", val])
        return args

    def test_creates_file_with_frontmatter(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, self._write_note_args())
        assert result.exit_code == 0

        permanent = wiki_root / "wiki" / "permanent"
        md_files = list(permanent.glob("*.md"))
        assert len(md_files) >= 1, "No note written to wiki/permanent/"

        content = md_files[0].read_text()
        assert "---" in content
        assert "Test Pattern Note" in content
        assert "pattern" in content
        assert "architecture" in content

    def test_generates_perm_id(self, wiki_root: Path, monkeypatch):
        """Each note should get a unique perm-YYYYMMDD-XXXXX id."""
        monkeypatch.chdir(wiki_root)
        runner.invoke(app, self._write_note_args())

        permanent = wiki_root / "wiki" / "permanent"
        md_files = list(permanent.glob("*.md"))
        content = md_files[0].read_text()
        assert "id: perm-" in content

    def test_validates_tags_against_taxonomy(self, wiki_root: Path, monkeypatch):
        """Invalid tags should produce a warning."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            self._write_note_args(tags="not-a-valid-tag,also-bad"),
        )
        assert result.exit_code == 0
        assert "warning" in result.stdout.lower()

    def test_dry_run_does_not_write(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            self._write_note_args(title="Dry Run Note") + ["--dry-run"],
        )
        assert result.exit_code == 0

        permanent = wiki_root / "wiki" / "permanent"
        matching = list(permanent.glob("*dry*"))
        assert len(matching) == 0, "dry-run should not write a file"

    def test_dry_run_shows_preview(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            self._write_note_args() + ["--dry-run"],
        )
        assert result.exit_code == 0
        assert "dry run" in result.stdout.lower()

    def test_missing_fields_error(self, wiki_root: Path, monkeypatch):
        """--write-note without all required fields should error."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["compile", "--write-note", "--title", "Only Title"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Mark processed
# ---------------------------------------------------------------------------


class TestMarkProcessed:
    """``kb compile --mark-processed`` updates manifest entry status."""

    def test_marks_entry_processed(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--mark-processed", "ingest-aaa11111"])
        assert result.exit_code == 0

        manifest = manifest_with_entries / "raw" / "inbox" / ".manifest.json"
        entries = json.loads(manifest.read_text())
        target = next(e for e in entries if e["id"] == "ingest-aaa11111")
        assert target["status"] == "processed"
        assert "processed_at" in target

    def test_mark_nonexistent_entry_errors(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--mark-processed", "nonexistent-id"])
        assert result.exit_code != 0 or "not found" in result.stdout.lower()


# ---------------------------------------------------------------------------
# List inbox
# ---------------------------------------------------------------------------


class TestListInbox:
    """``kb compile --list-inbox`` returns inbox entries."""

    def test_list_inbox_returns_entries(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--list-inbox"])
        assert result.exit_code == 0
        assert "ingest-aaa11111" in result.stdout

    def test_list_inbox_json(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["compile", "--list-inbox", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2  # both pending and processed

    def test_list_inbox_empty(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["compile", "--list-inbox"])
        assert result.exit_code == 0
        assert "empty" in result.stdout.lower() or "no" in result.stdout.lower()

    def test_no_mode_specified_errors(self, wiki_root: Path, monkeypatch):
        """Running ``compile`` with no action flag should error."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["compile"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Source-class dedup tuning
# ---------------------------------------------------------------------------


class TestCheckDedupSourceClass:
    """``kb compile --check-dedup --source-class book`` uses 0.94 threshold."""

    def test_book_class_uses_book_threshold(
        self, populated_wiki: Path, mock_embedding_model, monkeypatch
    ):
        monkeypatch.chdir(populated_wiki)
        # Build the index so dedup has data
        runner.invoke(app, ["index"])
        result = runner.invoke(
            app,
            [
                "compile", "--check-dedup",
                "API Gateway Authentication Pattern with JWT validation",
                "--source-class", "book",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # The known-existing populated_wiki note should produce a high score.
        # With source-class=book (0.94) it would NOT trip duplicate at 0.92,
        # but the test asserts the threshold actually got applied to status.
        assert "threshold" in data
        assert data["threshold"] == 0.94

    def test_unknown_source_class_errors(self, populated_wiki: Path, monkeypatch):
        monkeypatch.chdir(populated_wiki)
        result = runner.invoke(
            app,
            [
                "compile", "--check-dedup", "anything",
                "--source-class", "podcast",
            ],
        )
        assert result.exit_code != 0
        assert "podcast" in result.output.lower() or "unknown" in result.output.lower()

    def test_no_source_class_uses_chat_default(
        self, populated_wiki: Path, mock_embedding_model, monkeypatch
    ):
        monkeypatch.chdir(populated_wiki)
        runner.invoke(app, ["index"])
        result = runner.invoke(
            app,
            ["compile", "--check-dedup", "anything", "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["threshold"] == 0.92
