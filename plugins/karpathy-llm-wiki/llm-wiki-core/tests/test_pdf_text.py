"""Tests for PDF text extraction and normalization."""
from __future__ import annotations

import pytest

from llm_wiki.core.pdf_text import extract_pdf_text, normalize_pdf_text


class TestNormalizePdfText:
    def test_collapses_runs_of_whitespace_to_single_space(self):
        assert normalize_pdf_text("hello   world") == "hello world"

    def test_strips_inter_character_bloat(self):
        # "h e l l o" patterns from broken PDF font metrics
        assert normalize_pdf_text("h e l l o   w o r l d") == "hello world"

    def test_preserves_paragraph_breaks(self):
        src = "First paragraph.\n\nSecond paragraph."
        assert normalize_pdf_text(src) == "First paragraph.\n\nSecond paragraph."

    def test_strips_page_markers(self):
        src = "Body text.\n\n--- PAGE 5 ---\n\nMore text."
        out = normalize_pdf_text(src)
        assert "PAGE 5" not in out
        assert "Body text." in out
        assert "More text." in out

    def test_strips_zero_width_chars(self):
        src = "hello\u200bworld\u200cfoo\u200dbar\ufeff"
        assert normalize_pdf_text(src) == "helloworldfoobar"

    def test_strips_repeated_blank_lines(self):
        src = "line1\n\n\n\n\nline2"
        assert normalize_pdf_text(src) == "line1\n\nline2"

    def test_empty_input_is_empty_output(self):
        assert normalize_pdf_text("") == ""

    def test_does_not_mangle_capitalized_acronyms(self):
        # Real PDFs contain spaced acronyms in headings — must be preserved.
        assert normalize_pdf_text("A B testing") == "A B testing"
        assert normalize_pdf_text("I a b c") == "I a b c"

    def test_does_not_mangle_normal_words(self):
        assert normalize_pdf_text("a quick brown fox") == "a quick brown fox"


class TestExtractPdfText:
    def test_returns_extracted_text(self, sample_pdf_path):
        out = extract_pdf_text(sample_pdf_path)
        # The hand-crafted PDF has "h e l l o   w o r l d" — pre-normalize
        assert "hello" in out.replace(" ", "") or "h e l l o" in out

    def test_empty_pdf_returns_empty_string(self, tmp_path):
        # PDF with no content streams
        empty_pdf = tmp_path / "empty.pdf"
        empty_pdf.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
            b"xref\n0 3\n"
            b"0000000000 65535 f\n"
            b"0000000009 00000 n\n"
            b"0000000052 00000 n\n"
            b"trailer<</Size 3/Root 1 0 R>>\n"
            b"startxref\n95\n%%EOF\n"
        )
        assert extract_pdf_text(empty_pdf) == ""

    def test_extract_then_normalize_pipeline(self, sample_pdf_path):
        raw = extract_pdf_text(sample_pdf_path)
        clean = normalize_pdf_text(raw)
        assert "hello world" in clean.lower()
