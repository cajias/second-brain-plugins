"""Tests for ``kb ingest`` — raw document ingestion into the inbox pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_wiki.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_source_file(tmp_path: Path, name: str = "sample.txt", content: str = "hello world") -> Path:
    src = tmp_path / name
    src.write_text(content)
    return src


def _read_manifest(wiki_root: Path) -> list[dict]:
    manifest = wiki_root / "raw" / "inbox" / ".manifest.json"
    if not manifest.exists():
        return []
    return json.loads(manifest.read_text())


def _invoke_ingest(args: list[str], wiki_root: Path):
    """Invoke ingest with cwd set to the wiki_root so config is found."""
    return runner.invoke(app, ["ingest"] + args, env={"KB_ROOT": str(wiki_root)})


# ---------------------------------------------------------------------------
# File mode
# ---------------------------------------------------------------------------


class TestIngestFile:
    """``kb ingest --mode file --source <path>`` copies the file and updates the manifest."""

    def test_copies_to_artifacts(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "doc.pdf", "pdf content")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        assert result.exit_code == 0, f"stderr: {result.output}"

        artifacts = wiki_root / "raw" / "artifacts"
        copied = list(artifacts.glob("*doc*"))
        assert len(copied) >= 1, "File not copied to raw/artifacts/"

    def test_creates_metadata_sidecar(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "notes.md", "# My Notes\nSome content.")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])

        artifacts = wiki_root / "raw" / "artifacts"
        meta_files = list(artifacts.glob("*.meta.json"))
        assert len(meta_files) >= 1, "No .meta.json sidecar created"

        meta = json.loads(meta_files[0].read_text())
        assert meta["type"] == "file"
        assert meta["status"] == "pending"

    def test_updates_manifest(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "report.txt", "quarterly report")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])

        entries = _read_manifest(wiki_root)
        pending = [e for e in entries if e.get("status") == "pending"]
        assert len(pending) >= 1, "No pending entry added to manifest"
        assert pending[0]["type"] == "file"

    def test_missing_file_errors(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", "/nonexistent/file.txt"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Text mode
# ---------------------------------------------------------------------------


class TestIngestText:
    """``kb ingest --mode text --source "..."`` creates a file in raw/inbox/."""

    def test_text_creates_inbox_file(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(
            app,
            ["ingest", "--mode", "text", "--source", "Quick note about dependency injection"],
        )
        assert result.exit_code == 0

        inbox = wiki_root / "raw" / "inbox"
        md_files = [f for f in inbox.glob("*.md") if not f.name.startswith(".")]
        assert len(md_files) >= 1, "No markdown file created in inbox"

    def test_text_updates_manifest(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        runner.invoke(
            app,
            ["ingest", "--mode", "text", "--source", "A quick thought about caching"],
        )
        entries = _read_manifest(wiki_root)
        text_entries = [e for e in entries if e.get("type") == "text"]
        assert len(text_entries) >= 1

    def test_text_manifest_has_correct_fields(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        runner.invoke(
            app,
            ["ingest", "--mode", "text", "--source", "Testing manifest fields"],
        )
        entries = _read_manifest(wiki_root)
        entry = entries[-1]  # last added
        assert "id" in entry
        assert entry["id"].startswith("ingest-")
        assert entry["source"] == "inline-text"
        assert entry["status"] == "pending"
        assert "date" in entry


# ---------------------------------------------------------------------------
# List / JSON output
# ---------------------------------------------------------------------------


class TestIngestList:
    """``kb ingest --list`` shows pending items."""

    def test_list_shows_pending(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["ingest", "--list"])
        assert result.exit_code == 0
        assert "ingest-aaa11111" in result.stdout

    def test_list_json_format(self, manifest_with_entries: Path, monkeypatch):
        monkeypatch.chdir(manifest_with_entries)
        result = runner.invoke(app, ["ingest", "--list", "--json"])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert isinstance(data, list)
        # --list --json returns only pending items
        for entry in data:
            assert entry["status"] == "pending"

    def test_list_empty_inbox(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["ingest", "--list"])
        assert result.exit_code == 0
        assert "no" in result.stdout.lower() or "0" in result.stdout


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestIngestValidation:
    """Edge cases and error conditions."""

    def test_mode_required(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["ingest"])
        assert result.exit_code != 0

    def test_source_required_for_ingest(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["ingest", "--mode", "text"])
        assert result.exit_code != 0

    def test_invalid_mode_rejected(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["ingest", "--mode", "invalid-mode", "--source", "test"])
        assert result.exit_code != 0
