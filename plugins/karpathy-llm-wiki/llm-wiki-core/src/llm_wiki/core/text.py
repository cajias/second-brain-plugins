"""Text utilities — the single core ``slugify`` shared by compile and ingest."""

from __future__ import annotations

import hashlib
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


def content_hash(body: str) -> str:
    """Return a sha256 hex digest of the whitespace-collapsed, lowercased body.

    Two bodies that differ only in casing or whitespace yield the same hash, so this
    acts as an exact-duplicate gate for ingestion.

    Args:
        body: Arbitrary text content.

    Returns:
        A 64-char hex sha256 digest.
    """
    normalized = " ".join(body.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
