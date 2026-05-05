"""Deduplication logic for wiki notes.

Uses the LanceDB vector index to detect near-duplicate notes via
cosine similarity of embeddings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_wiki.core.embeddings import search_index


SOURCE_CLASS_THRESHOLDS: dict[str, float] = {
    "chat": 0.92,
    "doc": 0.93,
    "book": 0.94,
    "paper": 0.94,
}


def resolve_threshold(source_class: str | None) -> float:
    """Map a source class label to its cosine-similarity duplicate threshold.

    Args:
        source_class: One of {"chat", "doc", "book", "paper"}, or None/"" for chat default.

    Returns:
        Cosine threshold above which a candidate is considered a duplicate.

    Raises:
        ValueError: If source_class is given but not one of the known labels.
    """
    if not source_class:
        return SOURCE_CLASS_THRESHOLDS["chat"]
    key = source_class.lower()
    if key not in SOURCE_CLASS_THRESHOLDS:
        raise ValueError(
            f"unknown source_class {source_class!r}; "
            f"expected one of {sorted(SOURCE_CLASS_THRESHOLDS)}"
        )
    return SOURCE_CLASS_THRESHOLDS[key]


def check_duplicate(
    query: str,
    db_path: Path,
    table_name: str,
    threshold: float = 0.92,
) -> dict[str, Any]:
    """Check for duplicate/similar content in the LanceDB index.

    Args:
        query: Text to check for duplicates.
        db_path: Path to the LanceDB database.
        table_name: Name of the LanceDB table.
        threshold: Cosine similarity threshold for "duplicate" status.

    Returns:
        Dict with:
          - status: 'duplicate' (>=threshold), 'similar' (>=0.80), 'unique' (<0.80)
          - top_score: highest similarity score found
          - matches: list of matching notes with scores
    """
    try:
        results = search_index(db_path, table_name, query, limit=5)
    except Exception as e:
        return {
            "status": "unique",
            "message": f"No index available ({e}). Treating as unique.",
            "top_score": 0.0,
            "matches": [],
        }

    if not results:
        return {
            "status": "unique",
            "top_score": 0.0,
            "matches": [],
        }

    top_score = results[0]["score"]
    matches = [
        {
            "title": r["title"],
            "score": r["score"],
            "file_path": r["file_path"],
            "snippet": r["snippet"][:150],
        }
        for r in results
        if r["score"] >= 0.50
    ]

    if top_score >= threshold:
        status = "duplicate"
    elif top_score >= 0.80:
        status = "similar"
    else:
        status = "unique"

    return {
        "status": status,
        "top_score": top_score,
        "matches": matches,
    }
