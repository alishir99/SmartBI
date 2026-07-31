"""Optional local embedding model for the semantic half of entity resolution."""

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
    """Return a pgvector literal for the query, or None when unavailable."""
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
