"""Deduplication logic for wiki notes.

Uses the LanceDB vector index to detect near-duplicate notes via
cosine similarity of embeddings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_wiki.core.embeddings import search_index


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
