"""resolve_entities - free text to canonical IDs."""

from __future__ import annotations

from .. import db
from ..tenant import TenantContext

ALL_KINDS = ("product", "category", "store", "brand", "region")

# Trigram similarity floor.
LEXICAL_THRESHOLD = 0.18

# Reciprocal Rank Fusion constant.
RRF_K = 60

LEXICAL_SQL = """
SELECT kind, entity_id, label, path,
       GREATEST(similarity(label, $1), similarity(synonyms, $1)) AS score
  FROM entity_search
 WHERE kind = ANY($2::text[])
   AND (similarity(label, $1) > $3
        OR similarity(synonyms, $1) > $3
        OR label ILIKE '%' || $1 || '%'
        OR synonyms ILIKE '%' || $1 || '%')
 ORDER BY score DESC, label
 LIMIT $4
"""

SEMANTIC_SQL = """
SELECT kind, entity_id, label, path,
       1 - (embedding <=> $1::vector) AS score
  FROM entity_search
 WHERE kind = ANY($2::text[])
   AND embedding IS NOT NULL
 ORDER BY embedding <=> $1::vector
 LIMIT $3
"""


async def resolve_entities(tenant: TenantContext, text: str, kinds: list[str] | None = None,
                          limit: int = 8) -> dict:
    kinds = list(kinds) if kinds else list(ALL_KINDS)
    unknown = set(kinds) - set(ALL_KINDS)
    if unknown:
        return {"matches": [], "hint": f"okända kinds: {sorted(unknown)}. "
                                       f"Tillåtna: {list(ALL_KINDS)}"}

    text = (text or "").strip()
    if not text:
        return {"matches": [], "hint": "tom söktext"}

    # Over-fetch each retriever so fusion has something to work with, then trim.
    fetch = max(limit * 3, 20)

    async with db.tenant_connection(tenant.supplier_id) as connection:
        lexical = await connection.fetch(
            LEXICAL_SQL, text, kinds, LEXICAL_THRESHOLD, fetch)

        semantic = []
        retrieval = "lexical"
        embedding = await _embed(text)
        if embedding is not None:
            semantic = await connection.fetch(SEMANTIC_SQL, embedding, kinds, fetch)
            if semantic:
                retrieval = "hybrid (pg_trgm + pgvector, RRF)"

    matches = _fuse(lexical, semantic)[:limit]

    if not matches:
        return {
            "matches": [],
            "hint": f"Ingen träff på '{text}'. Kontrollera stavningen, eller använd "
                    f"get_capabilities för att se vilka kategorier och län som finns. "
                    f"Gissa inte ett ID.",
            "meta": {"tool": "resolve_entities", "retrieval": retrieval, "query": text},
        }

    return {
        "matches": matches,
        "meta": {"tool": "resolve_entities", "retrieval": retrieval, "query": text,
                 "threshold": LEXICAL_THRESHOLD,
                 "note": "Flera kandidater betyder att frågan är tvetydig - fråga användaren "
                         "istället för att välja själv."},
    }


def _fuse(lexical, semantic) -> list[dict]:
    """Reciprocal Rank Fusion over the two ranked lists."""
    fused: dict[tuple[str, int], dict] = {}

    for source, records in (("lexical", lexical), ("semantic", semantic)):
        for rank, record in enumerate(records, start=1):
            key = (record["kind"], record["entity_id"])
            entry = fused.setdefault(key, {
                "kind": record["kind"],
                "id": record["entity_id"],
                "label": record["label"],
                "path": record["path"],
                "score": 0.0,
                "matched_by": [],
            })
            entry["score"] += 1.0 / (RRF_K + rank)
            entry["matched_by"].append(source)

    ranked = sorted(fused.values(), key=lambda entry: entry["score"], reverse=True)
    for entry in ranked:
        entry["score"] = round(entry["score"], 5)
    return ranked


async def _embed(text: str):
    """Embed the query, or return None so retrieval degrades to lexical only."""
    try:
        from ..embeddings import embed_query
    except ImportError:
        return None
    return await embed_query(text)
