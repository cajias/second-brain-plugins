"""PDF text extraction and normalization.

Two pure functions used by ingest to turn binary PDFs into clean markdown:
  - extract_pdf_text(path)  : pypdf wrapper that returns raw extracted text.
  - normalize_pdf_text(s)   : whitespace + zero-width-char cleanup, page-marker stripping.

These run once at ingest time so downstream compile-agents read clean text.
"""
from __future__ import annotations

import re
from pathlib import Path

import pypdf


_INTER_CHAR_RUN = re.compile(r"(?:\b\w\s){2,}\w\b")
_PAGE_MARKER = re.compile(r"--- PAGE \d+ ---", re.IGNORECASE)
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")


def normalize_pdf_text(text: str) -> str:
    """Clean whitespace artifacts, page markers, and zero-width chars."""
    text = _ZERO_WIDTH.sub("", text)
    text = _PAGE_MARKER.sub("", text)
    text = _INTER_CHAR_RUN.sub(lambda m: m.group(0).replace(" ", ""), text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(path: Path) -> str:
    """Extract concatenated text from every page of a PDF, separated by blank lines."""
    reader = pypdf.PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n\n".join(parts)
