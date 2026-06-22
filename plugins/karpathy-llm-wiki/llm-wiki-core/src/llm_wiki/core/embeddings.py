"""Embedding generation and LanceDB vector operations.

Provides lazy-loaded sentence-transformers model, batch embedding generation,
and LanceDB table management (create, upsert, search).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import lancedb
import numpy as np
from sentence_transformers import SentenceTransformer

from llm_wiki.core.tags import normalize_tags


if TYPE_CHECKING:
    from pathlib import Path


MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Threshold above which sentence-transformers shows a progress bar during encoding.
_PROGRESS_BAR_BATCH_THRESHOLD = 10

# Module-level cache for the model
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Lazily load and cache the sentence-transformers embedding model.

    Returns:
        A SentenceTransformer model instance.
    """
    global _model  # noqa: PLW0603  # module-level cache for the embedding model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of text strings.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors (each a list of floats).
    """
    if not texts:
        return []
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=len(texts) > _PROGRESS_BAR_BATCH_THRESHOLD)
    return [emb.tolist() for emb in embeddings]


def search_index(
    db_path: Path,
    table_name: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search the LanceDB vector index for notes similar to the query.

    Args:
        db_path: Path to the LanceDB database directory.
        table_name: Name of the table to search.
        query: Natural language search query.
        limit: Maximum number of results.

    Returns:
        List of matching records with similarity scores. Each dict has:
        id, title, file_path, score, snippet, knowledge_type, tags.
    """
    db = lancedb.connect(str(db_path))
    if table_name not in db.table_names():
        return []

    table = db.open_table(table_name)
    if table.count_rows() == 0:
        return []

    model = get_model()
    query_embedding = model.encode([query])[0].tolist()

    results_df = table.search(query_embedding).metric("cosine").limit(limit).to_pandas()

    if results_df.empty:
        return []

    results = []
    for _, row in results_df.iterrows():
        score = 1.0 - row.get("_distance", 0.0)
        snippet = row.get("content", "")[:200].replace("\n", " ").strip()
        results.append(
            {
                "id": row.get("id", ""),
                "title": row.get("title", ""),
                "file_path": row.get("file_path", ""),
                "score": round(score, 4),
                "snippet": snippet,
                "knowledge_type": row.get("knowledge_type", ""),
                "tags": normalize_tags(
                    row.get("tags").tolist() if isinstance(row.get("tags"), np.ndarray) else row.get("tags")
                ),
            }
        )

    return results


def get_last_index_time(lancedb_path: Path) -> float:
    """Read the timestamp of the last index run."""
    ts_file = lancedb_path / ".last_index"
    if ts_file.exists():
        try:
            return float(ts_file.read_text().strip())
        except ValueError:
            return 0.0
    return 0.0


def set_last_index_time(lancedb_path: Path) -> None:
    """Write the current timestamp as the last index time."""
    lancedb_path.mkdir(parents=True, exist_ok=True)
    ts_file = lancedb_path / ".last_index"
    ts_file.write_text(str(time.time()))
