"""Tests for ``kb ingest`` — raw document ingestion into the inbox pipeline."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from llm_wiki.cli import app


if TYPE_CHECKING:
    from pathlib import Path


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
    return runner.invoke(app, ["ingest", *args], env={"KB_ROOT": str(wiki_root)})


# ---------------------------------------------------------------------------
# File mode
# ---------------------------------------------------------------------------


class TestIngestFile:
    """``kb ingest --mode file --source <path>`` copies the file and updates the manifest."""

    def test_copies_to_artifacts(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "doc.bin", "binary content")
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
# PDF extraction
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_marker(monkeypatch):
    """Patch _extract_pdf so Marker models are never loaded in tests."""
    monkeypatch.setattr(
        "llm_wiki.commands.ingest._extract_pdf",
        lambda _path: "# Extracted\n\nMocked PDF content about transformers.",
    )


@pytest.mark.usefixtures("_mock_marker")
class TestIngestPdf:
    """``kb ingest --mode file --source <path>.pdf`` extracts markdown via Marker."""

    def test_pdf_extracts_markdown(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "paper.pdf", "%PDF-fake-content")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        assert result.exit_code == 0, f"stderr: {result.output}"

        artifacts = wiki_root / "raw" / "artifacts"
        md_files = list(artifacts.glob("*.md"))
        assert len(md_files) >= 1, "No extracted .md file created"
        assert "Mocked PDF content" in md_files[0].read_text()

    def test_pdf_preserves_original(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "paper.pdf", "%PDF-fake-content")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])

        artifacts = wiki_root / "raw" / "artifacts"
        pdf_files = list(artifacts.glob("*.pdf"))
        assert len(pdf_files) >= 1, "Original PDF not preserved"

    def test_pdf_manifest_points_to_markdown(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "paper.pdf", "%PDF-fake-content")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])

        entries = _read_manifest(wiki_root)
        pdf_entries = [e for e in entries if e.get("status") == "pending"]
        assert len(pdf_entries) >= 1
        assert pdf_entries[-1]["file"].endswith(".md"), "Manifest should point to .md"

    def test_pdf_manifest_has_extracted_from(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "paper.pdf", "%PDF-fake-content")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])

        entries = _read_manifest(wiki_root)
        entry = entries[-1]
        assert "extracted_from" in entry
        assert entry["extracted_from"].endswith(".pdf")

    def test_pdf_meta_has_original_format(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "paper.pdf", "%PDF-fake-content")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])

        artifacts = wiki_root / "raw" / "artifacts"
        meta_files = list(artifacts.glob("*.meta.json"))
        assert len(meta_files) >= 1
        meta = json.loads(meta_files[0].read_text())
        assert meta.get("original_format") == "pdf"

    def test_non_pdf_unchanged(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "notes.txt", "plain text notes")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])

        entries = _read_manifest(wiki_root)
        entry = entries[-1]
        assert entry["file"].endswith(".txt"), "Non-PDF should keep original extension"
        assert "extracted_from" not in entry

    def test_pdf_uppercase_extension(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "SCAN.PDF", "%PDF-fake")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        assert result.exit_code == 0

        entries = _read_manifest(wiki_root)
        assert entries[-1]["file"].endswith(".md"), ".PDF should trigger extraction"


# ---------------------------------------------------------------------------
# PDF error handling (outside TestIngestPdf to avoid _mock_marker fixture)
# ---------------------------------------------------------------------------


class TestIngestPdfErrors:
    """Error cases for PDF ingestion — these use their own mocks."""

    def test_extraction_failure_reports_error(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        monkeypatch.setattr(
            "llm_wiki.commands.ingest._extract_pdf",
            lambda _path: (_ for _ in ()).throw(RuntimeError("corrupt PDF")),
        )
        src = _create_source_file(tmp_path, "bad.pdf", "%PDF-corrupt")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        assert result.exit_code != 0
        assert "corrupt PDF" in result.output

    def test_empty_extraction_reports_error(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        monkeypatch.setattr(
            "llm_wiki.commands.ingest._extract_pdf",
            lambda _path: "   \n  ",
        )
        src = _create_source_file(tmp_path, "scanned.pdf", "%PDF-scanned")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        assert result.exit_code != 0
        assert "No text could be extracted" in result.output


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


# ---------------------------------------------------------------------------
# Source class
# ---------------------------------------------------------------------------


class TestIngestSourceClass:
    """``kb ingest --source-class X`` records X on the manifest entry."""

    def test_book_source_class_persisted_on_manifest(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "chapter.md", "# Chapter 1\n\nbody")
        result = runner.invoke(
            app,
            ["ingest", "--mode", "file", "--source", str(src), "--source-class", "book"],
        )
        assert result.exit_code == 0, result.output
        manifest = _read_manifest(wiki_root)
        assert manifest[-1]["source_class"] == "book"

    def test_default_source_class_is_chat(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "msg.txt", "a message")
        runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        manifest = _read_manifest(wiki_root)
        assert manifest[-1].get("source_class", "chat") == "chat"

    def test_invalid_source_class_errors(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "x.txt", "x")
        result = runner.invoke(
            app,
            ["ingest", "--mode", "file", "--source", str(src), "--source-class", "podcast"],
        )
        assert result.exit_code != 0

    def test_tool_source_class_persisted_on_manifest(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "readme.md", "# Tool\n\nbody")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src), "--source-class", "tool"])
        assert result.exit_code == 0, result.output
        manifest = _read_manifest(wiki_root)
        assert manifest[-1]["source_class"] == "tool"


# ---------------------------------------------------------------------------
# Slugify fallback — empty / all-non-alphanum input
# ---------------------------------------------------------------------------


class TestIngestSlugifyFallback:
    """When the stem/source slugifies to empty, a default name is used."""

    def test_file_all_symbol_stem_uses_default(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        """A filename whose stem is all non-alphanum (e.g. '---') must not produce an empty slug.

        The ingest call site uses ``slugify(...) or "document"``, so the manifest
        entry's file path must contain "document" as the fallback slug.
        """
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "---.txt", "content")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        assert result.exit_code == 0, f"stderr: {result.output}"

        entries = _read_manifest(wiki_root)
        assert len(entries) >= 1
        filename = entries[-1]["file"]
        # The fallback should ensure the filename contains "document", not an empty slug
        assert "document" in filename, f"Expected 'document' fallback in filename, got: {filename}"

    def test_text_all_symbol_source_uses_default(self, wiki_root: Path, monkeypatch):
        """Inline text that is all non-alphanum must fall back to 'note' in the filename."""
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["ingest", "--mode", "text", "--source", "!!!---???"])
        assert result.exit_code == 0, f"stderr: {result.output}"

        inbox = wiki_root / "raw" / "inbox"
        md_files = [f for f in inbox.glob("*.md") if not f.name.startswith(".")]
        assert len(md_files) >= 1, "No markdown file created in inbox"
        # The fallback should ensure the file contains "note", not an empty slug
        assert any("note" in f.name for f in md_files), (
            f"Expected 'note' fallback in filename, got: {[f.name for f in md_files]}"
        )
