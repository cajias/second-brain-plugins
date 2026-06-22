"""Deduplication logic for wiki notes.

Uses the LanceDB vector index to detect near-duplicate notes via
cosine similarity of embeddings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from llm_wiki.core.embeddings import search_index


if TYPE_CHECKING:
    from pathlib import Path


# Cosine-similarity tiers (see CLAUDE.md "Deduplication Thresholds").
# Default `threshold` for "duplicate" classification is the function arg (0.92);
# the constants below are the lower bounds for "similar" and "noteworthy match".
SIMILAR_SCORE_THRESHOLD = 0.80
MATCH_DISPLAY_THRESHOLD = 0.50

# Per-source-class duplicate thresholds. Denser sources (books, papers) tolerate
# higher overlap before being flagged as duplicates than free-form chat.
SOURCE_CLASS_THRESHOLDS: dict[str, float] = {
    "chat": 0.92,
    "doc": 0.93,
    "book": 0.94,
    "paper": 0.94,
    "tool": 0.93,  # tool READMEs/docs pages are dense and doc-like; same tolerance as "doc"
}


def resolve_threshold(source_class: str | None) -> float:
    """Map a source class label to its cosine-similarity duplicate threshold.

    Args:
        source_class: One of {"chat", "doc", "book", "paper", "tool"}, or None/"" for chat default.

    Returns:
        Cosine threshold above which a candidate is considered a duplicate.

    Raises:
        ValueError: If source_class is given but not one of the known labels.
    """
    if not source_class:
        return SOURCE_CLASS_THRESHOLDS["chat"]
    key = source_class.lower()
    if key not in SOURCE_CLASS_THRESHOLDS:
        msg = f"unknown source_class {source_class!r}; expected one of {sorted(SOURCE_CLASS_THRESHOLDS)}"
        raise ValueError(msg)  # message includes the offending value for the CLI user
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
    except Exception as e:  # noqa: BLE001  # any backend failure → fall back to "unique"
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
        if r["score"] >= MATCH_DISPLAY_THRESHOLD
    ]

    if top_score >= threshold:
        status = "duplicate"
    elif top_score >= SIMILAR_SCORE_THRESHOLD:
        status = "similar"
    else:
        status = "unique"

    return {
        "status": status,
        "top_score": top_score,
        "matches": matches,
    }


def check_duplicates_batch(
    queries: list[str],
    db_path: Path,
    table_name: str,
    threshold: float = 0.92,
) -> list[dict[str, Any]]:
    """Check many candidates for duplicates in a single process.

    Returns one result dict per query, in the same order as the input.

    The win here is process-collapse: the embedding model is cached in a
    module-level global (see ``core/embeddings.py``), so it cold-loads from
    disk only once for the whole batch instead of once per spawned ``kb``
    process. A future optimization could embed every query in a single
    ``embed_texts`` call and then run one LanceDB query per vector, to also
    amortize the encode pass — not implemented here, since the dominant cost
    is the per-process model cold-load, not the encode.

    Args:
        queries: Texts to check for duplicates.
        db_path: Path to the LanceDB database.
        table_name: Name of the LanceDB table.
        threshold: Cosine similarity threshold for "duplicate" status.

    Returns:
        List of result dicts (same shape as ``check_duplicate``), in order.
    """
    return [check_duplicate(query, db_path, table_name, threshold) for query in queries]
