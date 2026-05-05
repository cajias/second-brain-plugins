"""Tests for ``kb compile`` — note compilation, dedup checking, and manifest management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_wiki.cli import app
from llm_wiki.commands.compile_cmd import _tag_candidate

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
# Tag candidate
# ---------------------------------------------------------------------------


def _make_cfg(tmp_path: Path):
    """Build a minimal WikiConfig pointing into tmp_path."""
    from llm_wiki.core.config import WikiConfig

    return WikiConfig(
        project_root=tmp_path,
        vault_root=tmp_path / "vault",
        raw_inbox=tmp_path / "raw" / "inbox",
        raw_sessions=tmp_path / "raw" / "sessions",
        raw_artifacts=tmp_path / "raw" / "artifacts",
        raw_web=tmp_path / "raw" / "web",
        wiki_permanent=tmp_path / "wiki" / "permanent",
        wiki_index=tmp_path / "wiki" / "_index",
        wiki_meta=tmp_path / "wiki" / "_meta",
        output=tmp_path / "output",
        fleeting=tmp_path / "fleeting",
        db_path=tmp_path / ".lancedb",
        table_name="notes",
        compile_batch_size=10,
        auto_link_threshold=0.75,
        lint_orphan_threshold=0,
        lint_tag_compliance="strict",
        lint_index_staleness_hours=24,
        lint_index_min_coverage_pct=80,
        query_default_limit=10,
    )


class TestTagCandidate:
    def test_tags_existing_entry_with_candidate_metadata(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([
            {"id": "ingest-abc", "source": "url", "type": "web",
             "file": "raw/web/x.md", "status": "pending"}
        ]))
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-abc",
            verdict="yes",
            score=0.85,
            reason="concrete pattern with measurable result",
            suggested_type="pattern",
            suggested_tags=["agent-patterns", "llm"],
            cfg=cfg,
        )

        assert result["success"] is True
        loaded = json.loads(manifest.read_text())
        entry = loaded[0]
        assert entry["candidate"]["verdict"] == "yes"
        assert entry["candidate"]["score"] == 0.85
        assert entry["candidate"]["reason"] == "concrete pattern with measurable result"
        assert entry["candidate"]["suggested_type"] == "pattern"
        assert entry["candidate"]["suggested_tags"] == ["agent-patterns", "llm"]
        assert "tagged_at" in entry["candidate"]

    def test_rejects_unknown_entry_id(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([
            {"id": "ingest-abc", "status": "pending"}
        ]))
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-missing",
            verdict="no",
            score=0.1,
            reason="not found",
            suggested_type=None,
            suggested_tags=[],
            cfg=cfg,
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_rejects_invalid_verdict(self, tmp_path):
        manifest = tmp_path / "raw" / "inbox" / ".manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([{"id": "ingest-abc", "status": "pending"}]))
        cfg = _make_cfg(tmp_path)

        result = _tag_candidate(
            entry_id="ingest-abc",
            verdict="probably",  # not yes/no/maybe
            score=0.5,
            reason="ambiguous",
            suggested_type=None,
            suggested_tags=[],
            cfg=cfg,
        )

        assert result["success"] is False
        assert "verdict" in result["error"].lower()

    def test_cli_tag_candidate_flag(self, tmp_path, monkeypatch):
        # Set up minimal wiki + manifest
        wiki_root = tmp_path / "wiki"
        (wiki_root / "_meta").mkdir(parents=True)
        (wiki_root / "permanent").mkdir(parents=True)
        (tmp_path / "raw" / "inbox").mkdir(parents=True)
        (tmp_path / ".kb-config.yml").write_text(
            "vault_root: .\n"
        )
        (tmp_path / "raw" / "inbox" / ".manifest.json").write_text(json.dumps([
            {"id": "ingest-abc", "source": "url", "type": "web",
             "file": "raw/web/x.md", "status": "pending"}
        ]))

        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, [
            "compile",
            "--tag-candidate", "ingest-abc",
            "--verdict", "yes",
            "--score", "0.85",
            "--reason", "good pattern",
            "--suggested-type", "pattern",
            "--suggested-tags", "agent-patterns,llm",
            "--json",
        ])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["success"] is True

        loaded = json.loads(
            (tmp_path / "raw" / "inbox" / ".manifest.json").read_text()
        )
        assert loaded[0]["candidate"]["verdict"] == "yes"
        assert loaded[0]["candidate"]["suggested_tags"] == ["agent-patterns", "llm"]
