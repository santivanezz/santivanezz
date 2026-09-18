"""Memory engine: importance score, decay, temporal states, consolidation,
duplicate detection and feedback."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import numpy as np

from .db import rows_to_dicts
from .embeddings import content_words

DAY = 86400.0


class MemoryEngine:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db
        self.cfg = engine.cfg

    # ------------------------------------------------------------ scoring
    def score_document(self, doc: dict[str, Any], now: float | None = None) -> tuple[float, str]:
        """Interpretable importance score in [0, 1] with an explanation."""
        now = now or time.time()
        parts: list[tuple[str, float]] = []
        age_days = max(0.0, (now - (doc.get("updated_at") or now)) / DAY)
        recency = float(np.exp(-age_days / 45.0))
        parts.append(("reciente" if recency > 0.5 else "antigua", recency * 0.25))
        access = min(1.0, (doc.get("access_count") or 0) / 10.0)
        if access:
            parts.append(("consultada con frecuencia", access * 0.15))
        inbound = self.db.one("SELECT COUNT(*) AS n FROM relations WHERE target_type='document' AND target_id=? AND relation='LINKS_TO'", (doc["id"],))["n"]
        outbound = self.db.one("SELECT COUNT(*) AS n FROM relations WHERE source_type='document' AND source_id=? AND relation='LINKS_TO'", (doc["id"],))["n"]
        conn = min(1.0, (inbound * 2 + outbound) / 12.0)
        if conn:
            parts.append((f"{inbound} enlaces entrantes, {outbound} salientes", conn * 0.2))
        mem = self.db.one("SELECT SUM(CASE WHEN memory_type='TASK' AND status='open' THEN 1 ELSE 0 END) AS tasks,"
                          " SUM(CASE WHEN memory_type='DECISION' THEN 1 ELSE 0 END) AS decisions,"
                          " SUM(CASE WHEN memory_type='LEARNING' THEN 1 ELSE 0 END) AS learnings, MAX(user_importance) AS ui"
                          " FROM memories WHERE document_id=?", (doc["id"],))
        tasks, decisions, learnings = (mem["tasks"] or 0), (mem["decisions"] or 0), (mem["learnings"] or 0)
        if tasks:
            parts.append((f"{tasks} tareas abiertas", min(1.0, tasks / 5) * 0.15))
        if decisions:
            parts.append((f"{decisions} decisiones", min(1.0, decisions / 3) * 0.15))
        if learnings:
            parts.append((f"{learnings} aprendizajes", min(1.0, learnings / 3) * 0.1))
        proj = self.db.one("SELECT p.name, p.status FROM relations r JOIN projects p ON p.id=r.target_id WHERE r.source_type='document' AND r.source_id=? AND r.target_type='project' LIMIT 1", (doc["id"],))
        if proj and proj["status"] == "active":
            parts.append((f"parte del proyecto activo {proj['name']}", 0.15))
        fb = self.db.one("SELECT verdict FROM feedback WHERE target_type='document' AND target_id=? ORDER BY created_at DESC LIMIT 1", (str(doc["id"]),))
        if fb:
            if fb["verdict"] == "IMPORTANT":
                parts.append(("marcada como importante por ti", 0.3))
            elif fb["verdict"] in ("IGNORE", "NOT_USEFUL"):
                parts.append(("marcada como no útil", -0.3))
        if mem["ui"]:
            parts.append(("importancia explícita", 0.2))
        score = max(0.0, min(1.0, sum(w for _, w in parts)))
        reason = "Esta memoria es importante porque: " + ", ".join(p for p, w in parts if w > 0) if score > 0.3 else \
            "Importancia baja: " + ", ".join(p for p, _ in parts)
        return round(score, 3), reason

    def recompute_scores(self) -> int:
        now = time.time()
        n = 0
        for doc in self.db.query("SELECT * FROM documents WHERE deleted=0"):
            d = dict(doc)
            score, reason = self.score_document(d, now)
            self.db.execute("UPDATE memories SET importance=?, importance_reason=? WHERE document_id=?", (score, reason, d["id"]))
            n += 1
        return n

    # ------------------------------------------------------------ temporal / decay
    def update_temporal_states(self) -> dict[str, int]:
        now = time.time()
        counts = {"ACTIVE": 0, "STALE": 0, "OUTDATED": 0, "SUPERSEDED": 0, "FUTURE": 0}
        for doc in self.db.query("SELECT id, updated_at, mtime, last_accessed_at, temporal_state, path FROM documents WHERE deleted=0"):
            if doc["temporal_state"] in ("SUPERSEDED", "ARCHIVED", "HISTORICAL"):
                counts["SUPERSEDED" if doc["temporal_state"] == "SUPERSEDED" else "ACTIVE"] += 1
                continue
            last = max(doc["mtime"] or 0, doc["last_accessed_at"] or 0, doc["updated_at"] or 0)
            age = (now - last) / DAY
            if age > self.cfg.outdated_days:
                state = "OUTDATED"
            elif age > self.cfg.stale_days:
                state = "STALE"
            else:
                state = "CURRENT"
            if state != doc["temporal_state"] and doc["temporal_state"] in ("CURRENT", "STALE", "OUTDATED"):
                self.db.execute("UPDATE documents SET temporal_state=? WHERE id=?", (state, doc["id"]))
            counts["ACTIVE" if state == "CURRENT" else state] += 1
        # memories referring to future dates
        today = time.strftime("%Y-%m-%d")
        self.db.execute("UPDATE memories SET temporal_state='FUTURE' WHERE event_date>? AND temporal_state='CURRENT'", (today,))
        self.db.execute("UPDATE memories SET temporal_state='CURRENT' WHERE event_date<=? AND temporal_state='FUTURE'", (today,))
        return counts

    def stale_documents(self, limit: int = 50) -> list[dict[str, Any]]:
        now = time.time()
        rows = self.db.query("SELECT id, path, title, temporal_state, updated_at, mtime, last_accessed_at FROM documents"
                             " WHERE deleted=0 AND temporal_state IN ('STALE','OUTDATED') ORDER BY mtime ASC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            last = max(d["mtime"] or 0, d["last_accessed_at"] or 0)
            d["days_since_review"] = int((now - last) / DAY)
            d["message"] = f"Esta información no ha sido revisada en {d['days_since_review']} días."
            out.append(d)
        return out

    # ------------------------------------------------------------ duplicates & consolidation
    def find_duplicates(self, threshold: float = 0.9) -> list[dict[str, Any]]:
        """Near-duplicate notes by title similarity + chunk vector similarity."""
        docs = rows_to_dicts(self.db.query("SELECT id, path, title, word_count FROM documents WHERE deleted=0"))
        out: list[dict[str, Any]] = []
        by_norm: dict[str, list[dict[str, Any]]] = {}
        for d in docs:
            key = " ".join(content_words(d["title"]))
            key = key.replace(" final", "").replace(" copia", "").replace(" copy", "")
            key = " ".join(w for w in key.split() if not w.isdigit() and w not in ("v2", "v3", "nuevo", "new"))
            if key:
                by_norm.setdefault(key, []).append(d)
        for key, group in by_norm.items():
            if len(group) > 1:
                out.append({"kind": "DUPLICATE", "reason": f"títulos casi idénticos ('{key}')", "documents": group, "confidence": 0.7})
        # semantic duplicates: first chunk vectors nearly identical
        vec_rows = self.db.query("SELECT c.document_id, e.dim, e.vector FROM chunks c JOIN embeddings e ON e.chunk_id=c.id WHERE c.ordinal=0")
        if len(vec_rows) > 1:
            ids = [r["document_id"] for r in vec_rows]
            dim = vec_rows[0]["dim"]
            mat = np.vstack([np.frombuffer(r["vector"], dtype=np.float32, count=dim) for r in vec_rows if r["dim"] == dim])
            sims = mat @ mat.T
            titles = {d["id"]: d for d in docs}
            seen: set[tuple[int, int]] = set()
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    if sims[i, j] >= threshold and (ids[i], ids[j]) not in seen and ids[i] in titles and ids[j] in titles:
                        seen.add((ids[i], ids[j]))
                        out.append({"kind": "DUPLICATE", "reason": f"contenido casi idéntico (similitud {sims[i, j]:.2f})",
                                    "documents": [titles[ids[i]], titles[ids[j]]], "confidence": float(sims[i, j])})
        return out

    def find_existing_for(self, text: str, title: str | None = None, k: int = 5) -> list[dict[str, Any]]:
        """Before creating new information: is there an existing note to update instead?"""
        results = self.e.search.search(title or text[:200], k=k, mode="hybrid")
        out = []
        for r in results:
            if r["score"] >= 0.35:
                out.append({"path": r["path"], "title": r["title"], "score": r["score"],
                            "suggestion": "UPDATE EXISTING NOTE" if r["score"] > 0.6 else "LINK"})
        return out

    def consolidation_candidates(self, days: int = 7, min_notes: int = 3) -> list[dict[str, Any]]:
        """Groups of recent notes sharing entities/keywords -> suggest CONSOLIDATE / LINK / KEEP SEPARATE."""
        since = time.time() - days * DAY
        rows = self.db.query(
            "SELECT em.entity_id, e.name, e.entity_type, GROUP_CONCAT(d.id) AS doc_ids, COUNT(DISTINCT d.id) AS n"
            " FROM entity_mentions em JOIN entities e ON e.id=em.entity_id JOIN documents d ON d.id=em.document_id"
            " WHERE d.deleted=0 AND d.updated_at>=? AND e.entity_type IN ('CONCEPT','TECHNOLOGY','PROJECT','TOPIC','NOTE')"
            " GROUP BY em.entity_id HAVING n>=? ORDER BY n DESC LIMIT 30", (since, min_notes))
        out = []
        for r in rows:
            doc_ids = [int(x) for x in r["doc_ids"].split(",")]
            docs = rows_to_dicts(self.db.query(f"SELECT id, path, title, word_count FROM documents WHERE id IN ({','.join('?' * len(doc_ids))})", doc_ids))
            total_words = sum(d["word_count"] for d in docs)
            if total_words < 2500 and len(docs) >= min_notes:
                action = "CONSOLIDATE"
            elif len(docs) >= min_notes:
                action = "LINK"
            else:
                action = "KEEP SEPARATE"
            out.append({"concept": r["name"], "type": r["entity_type"], "documents": docs, "suggested_action": action,
                        "reason": f"{len(docs)} notas de los últimos {days} días mencionan '{r['name']}'"})
        return out

    # ------------------------------------------------------------ feedback
    def record_feedback(self, target_type: str, target_id: str, verdict: str, note: str | None = None) -> int:
        verdict = verdict.upper()
        cur = self.db.execute("INSERT INTO feedback(target_type, target_id, verdict, note, created_at) VALUES(?,?,?,?,?)",
                              (target_type, str(target_id), verdict, note, time.time()))
        if target_type == "suggestion":
            self.db.execute("UPDATE suggested_links SET status=? WHERE id=?",
                            ("accepted" if verdict in ("USEFUL", "IMPORTANT") else "rejected", int(target_id)))
        elif target_type == "contradiction":
            self.db.execute("UPDATE contradictions SET status=? WHERE id=?",
                            ("resolved" if verdict in ("USEFUL", "IMPORTANT") else "dismissed", int(target_id)))
        elif target_type == "memory":
            if verdict == "IMPORTANT":
                self.db.execute("UPDATE memories SET user_importance=1 WHERE id=?", (int(target_id),))
            elif verdict in ("IGNORE", "WRONG", "NOT_USEFUL"):
                self.db.execute("UPDATE memories SET status='dismissed' WHERE id=?", (int(target_id),))
            elif verdict == "DUPLICATE":
                self.db.execute("UPDATE memories SET status='superseded' WHERE id=?", (int(target_id),))
        return int(cur.lastrowid)

    def feedback_weights(self) -> dict[str, float]:
        """Learn simple per-kind weights from feedback (used by the relevance engine)."""
        rows = self.db.query("SELECT target_type, verdict, COUNT(*) AS n FROM feedback GROUP BY target_type, verdict")
        pos: dict[str, int] = {}
        neg: dict[str, int] = {}
        for r in rows:
            (pos if r["verdict"] in ("USEFUL", "IMPORTANT") else neg)[r["target_type"]] = r["n"]
        out = {}
        for k in set(pos) | set(neg):
            p, n = pos.get(k, 0), neg.get(k, 0)
            out[k] = (p + 1) / (p + n + 2)
        return out

    # ------------------------------------------------------------ queries
    def list_memories(self, memory_type: str | None = None, status: str | None = None, project: str | None = None,
                      since: float | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT m.*, d.path, d.title AS note_title FROM memories m LEFT JOIN documents d ON d.id=m.document_id WHERE 1=1"
        params: list[Any] = []
        if memory_type:
            sql += " AND m.memory_type=?"
            params.append(memory_type)
        if status:
            sql += " AND m.status=?"
            params.append(status)
        if project:
            sql += " AND lower(m.project)=lower(?)"
            params.append(project)
        if since:
            sql += " AND m.updated_at>=?"
            params.append(since)
        sql += " ORDER BY m.importance DESC, m.updated_at DESC LIMIT ?"
        params.append(limit)
        out = rows_to_dicts(self.db.query(sql, params))
        for m in out:
            m["metadata"] = json.loads(m.get("metadata") or "{}")
        return out

    def open_tasks(self, limit: int = 200) -> list[dict[str, Any]]:
        now = time.time()
        tasks = self.list_memories("TASK", "open", limit=limit)
        today = time.strftime("%Y-%m-%d")
        for t in tasks:
            t["age_days"] = int((now - t["created_at"]) / DAY)
            t["overdue"] = bool(t.get("due_date") and t["due_date"] < today)
            if t["metadata"].get("removed_from_note"):
                t["note_status"] = "removed_from_note"
        tasks.sort(key=lambda t: (not t["overdue"], -(t.get("priority") == "high"), -t["age_days"]))
        return tasks

    def memory_key(self, kind: str, target: str) -> str:
        return hashlib.sha1(f"{kind}:{target}".encode()).hexdigest()
