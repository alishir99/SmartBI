"""Populate entity_search.embedding so resolve_entities can run hybrid retrieval.

Optional. Without it, entity resolution runs on trigrams plus the curated synonyms the
seeder writes, which already covers typos and the common Swedish abbreviations. This adds
the semantic half — the one that connects "trådlösa lurar" to "Hörlurar" despite the two
sharing almost no trigrams.

    pip install "sentence-transformers>=3.0"
    ENABLE_VECTOR_SEARCH=true python scripts/embed_entities.py

The IVFFlat index is created here rather than in db/sql/02_indexes.sql because an IVFFlat
index built over an all-NULL column has nothing to cluster and would have to be rebuilt
anyway.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seed import dsn  # noqa: E402

from mcp_server.embeddings import (  # noqa: E402
    EMBEDDING_DIM,
    MODEL_NAME,
    embed_passages,
    to_pgvector,
)

BATCH = 256

# IVFFlat list count. The usual heuristic is rows/1000 for small tables; with a few hundred
# entities a handful of lists is plenty, and too many would leave most nearly empty.
LISTS = 16


async def main() -> None:
    if os.getenv("ENABLE_VECTOR_SEARCH", "false").lower() not in ("1", "true", "yes"):
        raise SystemExit("set ENABLE_VECTOR_SEARCH=true to run this")

    connection = await asyncpg.connect(dsn())
    try:
        rows = await connection.fetch(
            "SELECT kind, entity_id, label, path, synonyms FROM entity_search "
            "ORDER BY kind, entity_id")
        if not rows:
            raise SystemExit("entity_search is empty — run scripts/seed.py first")

        print(f"embedding {len(rows):,} entities with {MODEL_NAME} ({EMBEDDING_DIM}d)…")
        for start in range(0, len(rows), BATCH):
            batch = rows[start:start + BATCH]
            # Embed the path and synonyms alongside the label: "Hörlurar" alone is a weaker
            # target than "Ljud & Bild › Hörlurar › lurar headset trådlösa lurar".
            texts = [f"{row['path']} {row['synonyms']}".strip() for row in batch]
            vectors = embed_passages(texts)
            await connection.executemany(
                "UPDATE entity_search SET embedding = $3::vector "
                " WHERE kind = $1 AND entity_id = $2",
                [(row["kind"], row["entity_id"], to_pgvector(vector))
                 for row, vector in zip(batch, vectors, strict=True)])
            print(f"  {min(start + BATCH, len(rows)):,}/{len(rows):,}")

        print("building IVFFlat index…")
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_embedding ON entity_search "
            f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = {LISTS})")
        await connection.execute("ANALYZE entity_search")
        print("done — resolve_entities will now report retrieval='hybrid'.")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
