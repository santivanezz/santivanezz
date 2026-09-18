"""Lightweight knowledge graph on SQLite: related notes, orphans, suggested
links and the serendipity engine."""
from __future__ import annotations

import hashlib
import json
import time
from itertools import combinations
from typing import Any

import numpy as np

from .db import rows_to_dicts
from .embeddings import content_words


class GraphEngine:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db

    # ------------------------------------------------------------ neighbours
    def related_documents(self, doc_id: int, k: int = 10) -> list[dict[str, Any]]:
        """Related notes by explicit links, shared entities and vector similarity, with reasons."""
        scores: dict[int, float] = {}
        reasons: dict[int, list[str]] = {}

        def bump(other: int, w: float, why: str) -> None:
            if other == doc_id:
                return
            scores[other] = scores.get(other, 0.0) + w
            reasons.setdefault(other, [])
            if why not in reasons[other]:
                reasons[other].append(why)

        for r in self.db.query("SELECT target_id FROM relations WHERE source_type='document' AND source_id=? AND target_type='document'", (doc_id,)):
            bump(r["target_id"], 1.0, "enlace directo")
        for r in self.db.query("SELECT source_id FROM relations WHERE target_type='document' AND target_id=? AND source_type='document'", (doc_id,)):
            bump(r["source_id"], 0.9, "enlace entrante")
        for r in self.db.query(
                "SELECT em2.document_id, e.name, e.entity_type, MIN(em1.count, em2.count) AS c FROM entity_mentions em1"
                " JOIN entity_mentions em2 ON em1.entity_id=em2.entity_id JOIN entities e ON e.id=em1.entity_id"
                " JOIN documents d ON d.id=em2.document_id"
                " WHERE em1.document_id=? AND em2.document_id!=? AND d.deleted=0 AND e.entity_type!='TOPIC'", (doc_id, doc_id)):
            w = 0.25 if r["entity_type"] in ("PROJECT", "PERSON", "NOTE") else 0.12
            bump(r["document_id"], w * min(3, r["c"]), f"comparte '{r['name']}'")
        # vector neighbours
        row = self.db.one("SELECT id FROM chunks WHERE document_id=? ORDER BY ordinal LIMIT 1", (doc_id,))
        if row:
            v = self.e.vectors.vector_for(row["id"])
            if v is not None:
                own = {r["id"] for r in self.db.query("SELECT id FROM chunks WHERE document_id=?", (doc_id,))}
                for cid, s in self.e.vectors.search(v, k=15, exclude_chunk_ids=own):
                    d = self.db.one("SELECT document_id FROM chunks WHERE id=?", (cid,))
                    if d and s > 0.3:
                        bump(d["document_id"], float(s) * 0.8, f"contenido similar ({s:.2f})")
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        out = []
        for did, s in ranked:
            d = self.db.one("SELECT id, path, title FROM documents WHERE id=? AND deleted=0", (did,))
            if d:
                out.append({"id": d["id"], "path": d["path"], "title": d["title"], "score": round(s, 3), "reasons": reasons[did]})
        return out

    def entities_for_document(self, doc_id: int) -> list[dict[str, Any]]:
        return rows_to_dicts(self.db.query(
            "SELECT e.id, e.name, e.entity_type, em.count FROM entity_mentions em JOIN entities e ON e.id=em.entity_id"
            " WHERE em.document_id=? ORDER BY em.count DESC", (doc_id,)))

    def entity_neighbourhood(self, entity_name: str) -> dict[str, Any]:
        rows = self.db.query("SELECT * FROM entities WHERE lower(name)=lower(?) OR normalized=lower(?)", (entity_name, entity_name))
        if not rows:
            return {"entity": None, "documents": [], "co_entities": []}
        ent = dict(rows[0])
        docs = rows_to_dicts(self.db.query(
            "SELECT d.id, d.path, d.title, d.updated_at, em.count FROM entity_mentions em JOIN documents d ON d.id=em.document_id"
            " WHERE em.entity_id=? AND d.deleted=0 ORDER BY em.count DESC, d.updated_at DESC LIMIT 50", (ent["id"],)))
        co = rows_to_dicts(self.db.query(
            "SELECT e.name, e.entity_type, COUNT(*) AS shared FROM entity_mentions a JOIN entity_mentions b ON a.document_id=b.document_id"
            " JOIN entities e ON e.id=b.entity_id WHERE a.entity_id=? AND b.entity_id!=? GROUP BY b.entity_id ORDER BY shared DESC LIMIT 20",
            (ent["id"], ent["id"])))
        return {"entity": ent, "documents": docs, "co_entities": co}

    def graph_export(self, limit_nodes: int = 400) -> dict[str, Any]:
        docs = rows_to_dicts(self.db.query("SELECT id, title, path FROM documents WHERE deleted=0 ORDER BY updated_at DESC LIMIT ?", (limit_nodes,)))
        ids = {d["id"] for d in docs}
        nodes = [{"id": f"d{d['id']}", "label": d["title"], "type": "NOTE", "path": d["path"]} for d in docs]
        edges = []
        for r in self.db.query("SELECT source_id, target_id, relation FROM relations WHERE source_type='document' AND target_type='document'"):
            if r["source_id"] in ids and r["target_id"] in ids:
                edges.append({"from": f"d{r['source_id']}", "to": f"d{r['target_id']}", "relation": r["relation"]})
        ents = rows_to_dicts(self.db.query("SELECT id, name, entity_type FROM entities WHERE entity_type IN ('PROJECT','PERSON','TECHNOLOGY','CONCEPT') ORDER BY mention_count DESC LIMIT 150"))
        for en in ents:
            nodes.append({"id": f"e{en['id']}", "label": en["name"], "type": en["entity_type"]})
            for m in self.db.query("SELECT document_id FROM entity_mentions WHERE entity_id=?", (en["id"],)):
                if m["document_id"] in ids:
                    edges.append({"from": f"d{m['document_id']}", "to": f"e{en['id']}", "relation": "MENTIONED_IN"})
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------ health
    def orphan_documents(self) -> list[dict[str, Any]]:
        return rows_to_dicts(self.db.query(
            "SELECT d.id, d.path, d.title FROM documents d WHERE d.deleted=0"
            " AND NOT EXISTS (SELECT 1 FROM relations r WHERE r.relation='LINKS_TO' AND ((r.source_type='document' AND r.source_id=d.id) OR (r.target_type='document' AND r.target_id=d.id)))"
            " ORDER BY d.updated_at DESC"))

    def unlinked_concepts(self, min_docs: int = 3) -> list[dict[str, Any]]:
        """Entities mentioned in several notes but with no dedicated note."""
        return rows_to_dicts(self.db.query(
            "SELECT e.name, e.entity_type, COUNT(em.document_id) AS docs FROM entities e JOIN entity_mentions em ON em.entity_id=e.id"
            " JOIN documents d ON d.id=em.document_id WHERE e.document_id IS NULL AND d.deleted=0 AND e.entity_type IN ('CONCEPT','TECHNOLOGY','PROJECT','PERSON')"
            " GROUP BY e.id HAVING docs>=? ORDER BY docs DESC LIMIT 50", (min_docs,)))

    def missing_metadata(self) -> list[dict[str, Any]]:
        out = []
        for d in self.db.query("SELECT id, path, title, tags, frontmatter FROM documents WHERE deleted=0"):
            tags = json.loads(d["tags"] or "[]")
            fm = json.loads(d["frontmatter"] or "{}")
            missing = []
            if not tags:
                missing.append("tags")
            if not fm:
                missing.append("frontmatter")
            if missing:
                out.append({"id": d["id"], "path": d["path"], "title": d["title"], "missing": missing})
        return out

    # ------------------------------------------------------------ suggestions
    def refresh_suggestions(self, max_new: int = 200) -> int:
        """Compute suggested links and serendipity connections. Suggestions are never auto-applied."""
        now = time.time()
        created = 0
        # 1. Notes sharing 2+ strong entities but not linked
        pairs: dict[tuple[int, int], list[str]] = {}
        for r in self.db.query(
                "SELECT a.document_id AS x, b.document_id AS y, e.name FROM entity_mentions a JOIN entity_mentions b"
                " ON a.entity_id=b.entity_id AND a.document_id<b.document_id JOIN entities e ON e.id=a.entity_id"
                " JOIN documents d1 ON d1.id=a.document_id JOIN documents d2 ON d2.id=b.document_id"
                " WHERE d1.deleted=0 AND d2.deleted=0 AND e.entity_type IN ('PROJECT','PERSON','TECHNOLOGY','CONCEPT')"
                " AND e.mention_count<200"):
            pairs.setdefault((r["x"], r["y"]), []).append(r["name"])
        linked = {(r["source_id"], r["target_id"]) for r in self.db.query("SELECT source_id, target_id FROM relations WHERE source_type='document' AND target_type='document'")}
        for (x, y), names in pairs.items():
            if len(names) < 2 or (x, y) in linked or (y, x) in linked:
                continue
            fp = hashlib.sha1(f"LINK:{x}:{y}".encode()).hexdigest()
            conf = min(0.95, 0.4 + 0.15 * len(names))
            if self._insert_suggestion(fp, "LINK", [x, y], f"comparten {len(names)} conceptos sin estar enlazadas", names[:6], conf, now):
                created += 1
                if created >= max_new:
                    return created
        # 2. Serendipity: entity clusters that are not connected to each other via any note link
        created += self._serendipity(now, max_new - created)
        # 3. Consolidation candidates
        for cand in self.e.memory.consolidation_candidates():
            ids = [d["id"] for d in cand["documents"]]
            fp = hashlib.sha1(("CONSOLIDATE:" + ",".join(map(str, sorted(ids)))).encode()).hexdigest()
            if self._insert_suggestion(fp, "CONSOLIDATE", ids, cand["reason"] + f" → sugerencia: {cand['suggested_action']}",
                                       [cand["concept"]], 0.6, now):
                created += 1
        # 4. Duplicates
        for dup in self.e.memory.find_duplicates():
            ids = [d["id"] for d in dup["documents"]]
            fp = hashlib.sha1(("DUPLICATE:" + ",".join(map(str, sorted(ids)))).encode()).hexdigest()
            if self._insert_suggestion(fp, "DUPLICATE", ids, dup["reason"], [], dup["confidence"], now):
                created += 1
        return created

    def _serendipity(self, now: float, budget: int) -> int:
        """Find concept pairs (e.g. Lean / BPM / Automation) whose notes never link but whose content is close."""
        if budget <= 0:
            return 0
        ents = rows_to_dicts(self.db.query(
            "SELECT e.id, e.name, e.entity_type FROM entities e WHERE e.entity_type IN ('CONCEPT','TECHNOLOGY','TOPIC','NOTE')"
            " AND e.mention_count>=2 ORDER BY e.mention_count DESC LIMIT 60"))
        if len(ents) < 2:
            return 0
        docs_of: dict[int, set[int]] = {}
        for en in ents:
            docs_of[en["id"]] = {r["document_id"] for r in self.db.query("SELECT document_id FROM entity_mentions WHERE entity_id=?", (en["id"],))}
        centroid: dict[int, np.ndarray] = {}
        kw_of: dict[int, set[str]] = {}
        for en in ents:
            words: dict[str, int] = {}
            for did in list(docs_of[en["id"]])[:20]:
                for c in self.db.query("SELECT content FROM chunks WHERE document_id=? LIMIT 5", (did,)):
                    for w in content_words(c["content"]):
                        words[w] = words.get(w, 0) + 1
            kw_of[en["id"]] = {w for w, _ in sorted(words.items(), key=lambda kv: -kv[1])[:40]}
            vecs = []
            for did in list(docs_of[en["id"]])[:20]:
                row = self.db.one("SELECT id FROM chunks WHERE document_id=? ORDER BY ordinal LIMIT 1", (did,))
                if row:
                    v = self.e.vectors.vector_for(row["id"])
                    if v is not None:
                        vecs.append(v)
            if vecs:
                c = np.mean(np.vstack(vecs), axis=0)
                n = np.linalg.norm(c)
                if n:
                    centroid[en["id"]] = c / n
        linked = {(r["source_id"], r["target_id"]) for r in self.db.query("SELECT source_id, target_id FROM relations WHERE source_type='document' AND target_type='document'")}
        created = 0
        for a, b in combinations(ents, 2):
            if a["id"] not in centroid or b["id"] not in centroid:
                continue
            da, db_ = docs_of[a["id"]], docs_of[b["id"]]
            if da & db_:
                continue  # already co-mentioned somewhere -> not serendipitous
            if any((x, y) in linked or (y, x) in linked for x in da for y in db_):
                continue
            ka, kb = kw_of.get(a["id"], set()), kw_of.get(b["id"], set())
            jacc = len(ka & kb) / max(1, len(ka | kb))
            sim = max(float(centroid[a["id"]] @ centroid[b["id"]]), jacc * 2.5)
            if sim < 0.45:
                continue
            ids = sorted(list(da)[:3] + list(db_)[:3])
            fp = hashlib.sha1(("SERENDIPITY:" + ",".join(map(str, ids))).encode()).hexdigest()
            if self._insert_suggestion(fp, "SERENDIPITY", ids,
                                       f"Encontré una posible conexión entre '{a['name']}' y '{b['name']}': sus notas no están enlazadas pero hablan de temas cercanos (similitud {sim:.2f}).",
                                       [a["name"], b["name"]], round(min(0.9, sim), 2), now):
                created += 1
                if created >= budget:
                    break
        return created

    def _insert_suggestion(self, fp: str, kind: str, doc_ids: list[int], reason: str, concepts: list[str], conf: float, now: float) -> bool:
        if self.db.one("SELECT id FROM suggested_links WHERE fingerprint=?", (fp,)):
            return False
        self.db.execute("INSERT INTO suggested_links(fingerprint, kind, document_ids, reason, shared_concepts, confidence, status, created_at)"
                        " VALUES(?,?,?,?,?,?,'open',?)", (fp, kind, json.dumps(doc_ids), reason, json.dumps(concepts, ensure_ascii=False), conf, now))
        self.e.events.emit("SUGGESTION_CREATED" if kind != "SERENDIPITY" else "RELATION_DISCOVERED", {"kind": kind, "documents": doc_ids})
        return True

    def suggestions(self, kind: str | None = None, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM suggested_links WHERE status=?"
        params: list[Any] = [status]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)
        out = []
        for r in self.db.query(sql, params):
            d = dict(r)
            ids = json.loads(d["document_ids"])
            d["documents"] = rows_to_dicts(self.db.query(f"SELECT id, path, title FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)) if ids else []
            d["shared_concepts"] = json.loads(d["shared_concepts"] or "[]")
            out.append(d)
        return out
