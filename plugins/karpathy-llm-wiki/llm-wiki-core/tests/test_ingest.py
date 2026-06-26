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

    def test_duplicate_pdf_skip_leaves_no_orphan(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        """A duplicate PDF (same bytes, different filename) must not orphan the extracted .md.

        Dedup keys on the raw PDF bytes, so two identical-content PDFs collide, but
        their distinct stems yield distinct dest/.md filenames. The skip must clean up
        the manifest-canonical .md *and* the copied .pdf *and* the .pdf sidecar — not
        just the .pdf — so raw/artifacts keeps exactly one of each.
        """
        monkeypatch.chdir(wiki_root)
        first = _create_source_file(tmp_path, "paper-a.pdf", "%PDF-identical-bytes")
        second = _create_source_file(tmp_path, "paper-b.pdf", "%PDF-identical-bytes")

        r1 = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(first)])
        assert r1.exit_code == 0, r1.output
        before = _read_manifest(wiki_root)

        r2 = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(second)])
        assert r2.exit_code == 0, r2.output
        after = _read_manifest(wiki_root)
        assert len(after) == len(before), "Duplicate PDF must not grow the manifest"

        artifacts = wiki_root / "raw" / "artifacts"
        md_files = list(artifacts.glob("*.md"))
        pdf_files = list(artifacts.glob("*.pdf"))
        assert len(md_files) == 1, f"Duplicate PDF orphaned an extracted .md: {[f.name for f in md_files]}"
        assert len(pdf_files) == 1, f"Expected one surviving .pdf, got: {[f.name for f in pdf_files]}"
        assert (wiki_root / after[-1]["file"]).exists(), "Surviving manifest entry points to a deleted .md"


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


# ---------------------------------------------------------------------------
# URL mode — trafilatura extractor
# ---------------------------------------------------------------------------


class TestIngestUrlTrafilatura:
    def test_url_mode_uses_extractor(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        import io

        from llm_wiki.commands import ingest as ingest_mod
        from llm_wiki.core.html_extract import ExtractedDoc

        monkeypatch.setattr(ingest_mod, "urlopen", lambda *_a, **_k: io.BytesIO(b"<html><body>raw</body></html>"))
        monkeypatch.setattr(
            ingest_mod,
            "extract_main_content",
            lambda _html, url=None: ExtractedDoc(text="# Extracted\n\nClean body.", title="T", description="D"),  # noqa: ARG005
        )
        result = runner.invoke(app, ["ingest", "--mode", "url", "--source", "https://example.test/page"])
        assert result.exit_code == 0, result.output
        web = wiki_root / "raw" / "web"
        md = next(web.glob("*.md")).read_text()
        assert "Clean body." in md

    def test_url_empty_extraction_errors(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        import io

        from llm_wiki.commands import ingest as ingest_mod
        from llm_wiki.core.html_extract import ExtractedDoc

        monkeypatch.setattr(ingest_mod, "urlopen", lambda *_a, **_k: io.BytesIO(b"<html></html>"))
        monkeypatch.setattr(
            ingest_mod,
            "extract_main_content",
            lambda _html, url=None: ExtractedDoc(text="", title=None, description=None),  # noqa: ARG005
        )
        result = runner.invoke(app, ["ingest", "--mode", "url", "--source", "https://example.test/empty"])
        assert result.exit_code != 0
        assert "no content" in result.output.lower() or "empty" in result.output.lower()


# ---------------------------------------------------------------------------
# Content-hash exact-duplicate gate
# ---------------------------------------------------------------------------


class TestIngestDedup:
    """``_append_manifest`` skips appends whose content already exists in the queue."""

    def test_duplicate_text_skipped(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        body = "A unique thought about idempotent ingestion"
        first = runner.invoke(app, ["ingest", "--mode", "text", "--source", body])
        assert first.exit_code == 0, first.output
        before = _read_manifest(wiki_root)

        second = runner.invoke(app, ["ingest", "--mode", "text", "--source", body])
        assert second.exit_code == 0, second.output
        after = _read_manifest(wiki_root)
        assert len(after) == len(before), "Second identical ingest must not grow the manifest"

        # The kept entry must still point at a real file: a same-second duplicate
        # resolves to the same dest path, so the skip must not unlink the original.
        inbox = wiki_root / "raw" / "inbox"
        md_files = [f for f in inbox.glob("*.md") if not f.name.startswith(".")]
        assert len(md_files) == 1, "Original inbox file must survive a duplicate skip"
        assert (wiki_root / after[-1]["file"]).exists(), "Kept manifest entry points to a deleted file"

    def test_duplicate_skip_is_whitespace_and_case_insensitive(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        runner.invoke(app, ["ingest", "--mode", "text", "--source", "Caching Beats Recompute"])
        before = _read_manifest(wiki_root)

        runner.invoke(app, ["ingest", "--mode", "text", "--source", "  caching   beats\trecompute "])
        after = _read_manifest(wiki_root)
        assert len(after) == len(before), "Whitespace/case-only variants must be treated as duplicates"

    def test_manifest_entry_has_content_hash(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        runner.invoke(app, ["ingest", "--mode", "text", "--source", "a note that should carry a hash"])
        entry = _read_manifest(wiki_root)[-1]
        assert "content_hash" in entry
        assert len(entry["content_hash"]) == 64

    def test_whitespace_only_text_rejected(self, wiki_root: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        result = runner.invoke(app, ["ingest", "--mode", "text", "--source", "   \n\t  "])
        assert result.exit_code != 0
        assert _read_manifest(wiki_root) == []

    def test_whitespace_only_file_rejected(self, wiki_root: Path, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(wiki_root)
        src = _create_source_file(tmp_path, "blank.txt", "   \n  \t\n")
        result = runner.invoke(app, ["ingest", "--mode", "file", "--source", str(src)])
        assert result.exit_code != 0
        assert _read_manifest(wiki_root) == []
