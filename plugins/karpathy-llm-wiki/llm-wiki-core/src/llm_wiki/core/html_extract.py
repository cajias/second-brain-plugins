"""Single HTML main-content extractor (trafilatura).

The one HTML→text path for the toolkit: both ``kb ingest --mode url`` and the
tool ingester (generic-URL branch) call this. Replaces the minimal stdlib
``HTMLParser`` that produced junk on marketing/landing pages.
"""

from __future__ import annotations

from dataclasses import dataclass

import trafilatura


@dataclass(frozen=True)
class ExtractedDoc:
    """The result of extracting a web page's main content."""

    text: str
    title: str | None
    description: str | None


def extract_main_content(html: str, url: str | None = None) -> ExtractedDoc:
    """Extract boilerplate-stripped markdown plus title/description.

    Args:
        html: Raw HTML document text.
        url: Source URL (improves trafilatura's extraction heuristics).

    Returns:
        An ExtractedDoc; ``text`` is "" when nothing could be extracted.
    """
    text = trafilatura.extract(html, output_format="markdown", include_links=True, url=url) or ""
    meta = trafilatura.extract_metadata(html)
    title = getattr(meta, "title", None) if meta is not None else None
    description = getattr(meta, "description", None) if meta is not None else None
    return ExtractedDoc(text=text, title=title, description=description)
