"""Text utilities — the single core ``slugify`` shared by compile and ingest."""

from __future__ import annotations

import re


def slugify(text: str, max_len: int = 80) -> str:
    """Convert text to a kebab-case slug suitable for filenames.

    Args:
        text: Arbitrary input text.
        max_len: Maximum slug length; truncates on a word boundary.

    Returns:
        A filesystem-safe kebab-case slug.
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text
