"""Tests for the single trafilatura-backed HTML extractor."""

from __future__ import annotations

from llm_wiki.core import html_extract


class TestExtractMainContent:
    def test_returns_markdown_and_metadata(self, monkeypatch):
        monkeypatch.setattr(html_extract.trafilatura, "extract", lambda *_a, **_k: "# Deepeval\n\nLLM eval framework.")

        class _Meta:
            title = "Deepeval"
            description = "The LLM evaluation framework"

        monkeypatch.setattr(html_extract.trafilatura, "extract_metadata", lambda _html: _Meta())
        doc = html_extract.extract_main_content("<html>...</html>", url="https://deepeval.com")
        assert doc.text.startswith("# Deepeval")
        assert doc.title == "Deepeval"
        assert doc.description == "The LLM evaluation framework"

    def test_empty_extraction_yields_empty_text(self, monkeypatch):
        monkeypatch.setattr(html_extract.trafilatura, "extract", lambda *_a, **_k: None)
        monkeypatch.setattr(html_extract.trafilatura, "extract_metadata", lambda _html: None)
        doc = html_extract.extract_main_content("<html></html>", url="https://x.test")
        assert doc.text == ""
        assert doc.title is None

    def test_extract_forwards_required_kwargs(self, monkeypatch):
        """Ensure extract() is called with output_format, include_links, and favor_recall."""
        captured: dict = {}

        def _capture(*_a, **kw):
            captured.update(kw)
            return "content"

        monkeypatch.setattr(html_extract.trafilatura, "extract", _capture)
        monkeypatch.setattr(html_extract.trafilatura, "extract_metadata", lambda _html: None)
        html_extract.extract_main_content("<html>hi</html>", url="https://x.test")
        assert captured.get("output_format") == "markdown"
        assert captured.get("include_links") is True
        assert captured.get("favor_recall") is True
