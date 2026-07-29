"""resolve_entities — free text to canonical IDs.

This closes one of the two main hallucination entry points (§5.4). A user types "hörlurar",
"sthlm", "trådlösa lurar", "vårt bästa märke" — none of which are column values. Without a
resolution step the model must either guess an ID or invent a filter, and both produce
confident nonsense.

The contract that matters: this tool returns *candidates with scores*, never a single silent
guess. When nothing clears the threshold it returns an empty list and a hint, and the agent
is instructed to ask a clarifying question rather than proceed.

Retrieval is lexical (pg_trgm over names and curated synonyms) fused with semantic (pgvector
cosine) when embeddings have been generated. Lexical alone handles Swedish compounds and the
common abbreviations because the seeder writes synonyms like "sthlm" for Stockholms län; the
vector half earns its place on paraphrases such as "trådlösa lurar" that share no trigrams
with "Hörlurar". `meta.retrieval` says which ran, so a demo never overclaims.
"""

from __future__ import annotations

from .. import db
from ..tenant import TenantContext

ALL_KINDS = ("product", "category", "store", "brand", "region")

# Trigram similarity floor. Postgres' default of 0.3 is too strict for Swedish compound
# words — "lurar" against "Hörlurar" scores below it — and too loose a floor returns noise.
LEXICAL_THRESHOLD = 0.18

# Reciprocal Rank Fusion constant. 60 is the value from the original RRF paper and is not
# worth tuning on a dataset this size.
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
                 "note": "Flera kandidater betyder att frågan är tvetydig — fråga användaren "
                         "istället för att välja själv."},
    }


def _fuse(lexical, semantic) -> list[dict]:
    """Reciprocal Rank Fusion over the two ranked lists.

    RRF rather than score averaging because trigram similarity and cosine similarity are not
    on a comparable scale; only their orderings are meaningful.
    """
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
    """Embed the query, or return None so retrieval degrades to lexical only.

    The embedding model is an optional dependency: it adds roughly 2 GB to the image, so the
    default compose profile ships without it and resolution runs on trigrams and synonyms.
    Returning None here rather than raising is what makes that a graceful degradation instead
    of a broken tool.
    """
    try:
        from ..embeddings import embed_query
    except ImportError:
        return None
    return await embed_query(text)
