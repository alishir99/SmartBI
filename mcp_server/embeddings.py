"""Optional local embedding model for the semantic half of entity resolution.

Kept in its own module with a guarded import so `resolve_entities` can degrade to lexical
retrieval when the model is not installed. Enable with:

    pip install "sentence-transformers>=3.0"
    ENABLE_VECTOR_SEARCH=true
    python scripts/embed_entities.py       # populate entity_search.embedding

Model: intfloat/multilingual-e5-small — 384 dimensions, handles Swedish, runs on CPU, and
costs nothing per call. No data leaves the machine, which matters more here than a couple of
points of retrieval quality: the entity labels being embedded are the customer's product
catalogue.

e5 models require the "query: " / "passage: " prefixes. Getting that wrong quietly degrades
retrieval rather than failing, so both sides live in this file where they can be compared.
"""

from __future__ import annotations

import asyncio
import os

_model = None

MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384


def enabled() -> bool:
    return os.getenv("ENABLE_VECTOR_SEARCH", "false").lower() in ("1", "true", "yes")


def _load():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _encode(texts: list[str]) -> list[list[float]]:
    model = _load()
    vectors = model.encode(texts, normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]


async def embed_query(text: str) -> str | None:
    """Return a pgvector literal for the query, or None when unavailable.

    Returns None rather than raising when the flag is off *or* the package is missing, so a
    misconfigured deployment loses semantic recall instead of losing the tool.
    """
    if not enabled():
        return None
    try:
        vectors = await asyncio.to_thread(_encode, [f"query: {text}"])
    except ImportError:
        return None
    return to_pgvector(vectors[0])


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Synchronous batch embedding, used by scripts/embed_entities.py."""
    return _encode([f"passage: {text}" for text in texts])


def to_pgvector(vector: list[float]) -> str:
    """asyncpg has no native vector codec, so pass the literal text form and cast in SQL."""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
