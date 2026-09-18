"""Hybrid search: FTS5 (BM25) + vector similarity + entity match + metadata +
recency + importance, fused with reciprocal-rank fusion and reranked."""
from __future__ import annotations

import re
import time
from typing import Any

from .embeddings import content_words
from .extractors import find_dates

DAY = 86400.0


def _fts_query(q: str) -> str:
    words = content_words(q)
    if not words:
        words = [w for w in re.findall(r"\w+", q.lower()) if len(w) > 1]
    if not words:
        return ""
    # OR-query with prefix matching for robustness to inflections (es: proyecto/proyectos)
    parts = []
    for w in words[:12]:
        w = w.replace('"', "")
        parts.append(f'"{w}"*' if len(w) > 3 else f'"{w}"')
    return " OR ".join(parts)


class HybridSearch:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db

    def understand(self, query: str) -> dict[str, Any]:
        """Light query understanding: intent, time window, entities."""
        q = query.lower()
        intent = "search"
        if re.search(r"\b(pendiente|pendientes|tareas?|to ?do|qué debo|que debo|qué tengo que)\b", q):
            intent = "tasks"
        elif re.search(r"\b(decid|decisi[óo]n)", q):
            intent = "decisions"
        elif re.search(r"\b(aprend|learn)", q):
            intent = "learnings"
        elif re.search(r"\b(qué hice|que hice|ayer|esta semana|este mes|hoy|what did i do)\b", q):
            intent = "timeline"
        elif re.search(r"\b(por qué s[ée]|por qué tengo|why do i know|de d[óo]nde)", q):
            intent = "why"
        elif re.search(r"\b(qué cambi|que cambi|what changed)", q):
            intent = "changes"
        elif re.search(r"\b(qui[ée]n|personas?|people|who)\b", q):
            intent = "people"
        elif re.search(r"\b(proyectos?|projects?)\b", q) and re.search(r"relacionad|related", q):
            intent = "projects"
        now = time.time()
        since = None
        if "ayer" in q or "yesterday" in q:
            since = now - 2 * DAY
        elif "esta semana" in q or "this week" in q:
            since = now - 7 * DAY
        elif "este mes" in q or "this month" in q:
            since = now - 31 * DAY
        elif "hoy" in q or "today" in q:
            since = now - 1 * DAY
        entities = []
        for r in self.db.query("SELECT name, entity_type FROM entities WHERE mention_count>=1 ORDER BY mention_count DESC LIMIT 3000"):
            n = r["name"].lower()
            if len(n) > 2 and re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", q):
                entities.append({"name": r["name"], "type": r["entity_type"]})
        return {"intent": intent, "since": since, "entities": entities[:10], "dates": find_dates(query)}

    # ------------------------------------------------------------ retrieval
    def search(self, query: str, k: int = 10, mode: str = "hybrid", since: float | None = None,
               context: str | None = None, project: str | None = None, privacy_max: str | None = None) -> list[dict[str, Any]]:
        candidates: dict[int, dict[str, Any]] = {}  # chunk_id -> info
        ranks: dict[str, list[int]] = {}

        # 1. full text (BM25)
        fq = _fts_query(query)
        if fq and mode in ("hybrid", "keyword"):
            try:
                rows = self.db.query("SELECT chunk_id, bm25(chunks_fts) AS r FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY r LIMIT 60", (fq,))
                ranks["fts"] = [int(r["chunk_id"]) for r in rows]
            except Exception as exc:  # noqa: BLE001 - malformed query must not crash
                self.e.log.warning("fts query failed: %s", exc)
                ranks["fts"] = []
        # 2. vectors
        if mode in ("hybrid", "semantic"):
            try:
                qv = self.e.embedder.embed_one(query)
                ranks["vec"] = [cid for cid, s in self.e.vectors.search(qv, k=60) if s > 0.2]
            except Exception as exc:  # noqa: BLE001
                self.e.log.warning("vector search failed: %s", exc)
                ranks["vec"] = []
        # 3. entity match -> documents -> first chunk
        ent_docs: dict[int, int] = {}
        for ent in self.understand(query)["entities"]:
            for r in self.db.query("SELECT em.document_id, em.count FROM entity_mentions em JOIN entities e ON e.id=em.entity_id WHERE lower(e.name)=lower(?)", (ent["name"],)):
                ent_docs[r["document_id"]] = ent_docs.get(r["document_id"], 0) + r["count"]
        if ent_docs:
            ordered = sorted(ent_docs.items(), key=lambda kv: -kv[1])[:40]
            cids = []
            for did, _ in ordered:
                c = self.db.one("SELECT id FROM chunks WHERE document_id=? ORDER BY ordinal LIMIT 1", (did,))
                if c:
                    cids.append(int(c["id"]))
            ranks["entity"] = cids
        # 4. title match
        words = content_words(query)
        if words:
            like = " OR ".join(["lower(title) LIKE ?"] * len(words))
            rows = self.db.query(f"SELECT id FROM documents WHERE deleted=0 AND ({like}) LIMIT 30", [f"%{w}%" for w in words])
            cids = []
            for r in rows:
                c = self.db.one("SELECT id FROM chunks WHERE document_id=? ORDER BY ordinal LIMIT 1", (r["id"],))
                if c:
                    cids.append(int(c["id"]))
            ranks["title"] = cids

        # RRF fusion
        weights = {"fts": 1.0, "vec": 1.0, "entity": 0.8, "title": 0.9}
        fused: dict[int, float] = {}
        for source, lst in ranks.items():
            for rank, cid in enumerate(lst):
                fused[cid] = fused.get(cid, 0.0) + weights[source] / (60 + rank)
        if not fused:
            return []
        # hydrate + metadata/recency/importance boosts, one result per document
        now = time.time()
        best_by_doc: dict[int, dict[str, Any]] = {}
        for cid, base in sorted(fused.items(), key=lambda kv: -kv[1])[:120]:
            row = self.db.one("SELECT c.id, c.document_id, c.heading, c.content, d.path, d.title, d.updated_at, d.context, d.privacy, d.temporal_state, d.tags"
                              " FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=? AND d.deleted=0", (cid,))
            if not row:
                continue
            if since and row["updated_at"] < since:
                continue
            if context and (row["context"] or "").upper() != context.upper():
                continue
            if project:
                pr = self.db.one("SELECT 1 FROM relations r JOIN projects p ON p.id=r.target_id WHERE r.source_type='document' AND r.source_id=? AND r.target_type='project' AND p.normalized=lower(?)", (row["document_id"], project))
                if not pr:
                    continue
            age = (now - row["updated_at"]) / DAY
            recency = 1.0 + 0.25 * (1.0 if age < 7 else 0.5 if age < 30 else 0.2 if age < 180 else 0.0)
            imp = self.db.one("SELECT MAX(importance) AS i FROM memories WHERE document_id=?", (row["document_id"],))
            importance = 1.0 + 0.2 * float(imp["i"] or 0)
            state_pen = 0.8 if row["temporal_state"] in ("SUPERSEDED", "ARCHIVED") else 1.0
            score = base * recency * importance * state_pen
            info = {"chunk_id": cid, "document_id": row["document_id"], "path": row["path"], "title": row["title"],
                    "heading": row["heading"], "snippet": row["content"][:500], "content": row["content"], "score": score,
                    "updated_at": row["updated_at"], "privacy": row["privacy"], "temporal_state": row["temporal_state"],
                    "sources": [s for s, lst in ranks.items() if cid in lst]}
            cur = best_by_doc.get(row["document_id"])
            if cur is None or cur["score"] < score:
                best_by_doc[row["document_id"]] = info
        results = sorted(best_by_doc.values(), key=lambda r: -r["score"])
        results = self.rerank(query, results)[:k]
        # normalise score to 0..1 for display
        if results:
            top = results[0]["score"] or 1.0
            for r in results:
                r["score"] = round(r["score"] / top, 3) if top else 0.0
        return results

    def rerank(self, query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Lexical-overlap reranker (cheap, local). Multiplies fused score by term coverage."""
        qw = set(content_words(query))
        if not qw:
            return results
        for r in results:
            text = (r["title"] + " " + (r["heading"] or "") + " " + r["content"]).lower()
            covered = sum(1 for w in qw if w in text)
            coverage = covered / len(qw)
            title_hit = any(w in r["title"].lower() for w in qw)
            r["rerank"] = round(coverage, 2)
            r["score"] = r["score"] * (0.6 + 0.6 * coverage + (0.3 if title_hit else 0.0))
        return sorted(results, key=lambda r: -r["score"])

    def touch(self, doc_id: int) -> None:
        self.db.execute("UPDATE documents SET last_accessed_at=?, access_count=access_count+1 WHERE id=?", (time.time(), doc_id))
