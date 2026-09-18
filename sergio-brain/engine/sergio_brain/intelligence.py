"""Temporal intelligence: contradictions, supersession, timeline,
"why do I know this?", "what changed?", and the active-recall relevance engine."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
from typing import Any

from .db import rows_to_dicts
from .embeddings import content_words
from .extractors import find_dates, TECHNOLOGIES, _MONTHS

DAY = 86400.0

NEGATION = re.compile(r"(?i)\b(no|nunca|ya no|dej[óo] de|not|never|no longer)\b")
CHANGE_VERBS = re.compile(r"(?i)\b(migr[óo]|cambi[óo]|pas[óo] a|reemplaz[óo]|ahora usa|ahora es|se movi[óo]|moved to|switched to|replaced|now uses|será|sera|will be|se implementar[áa]|se lanzar[áa]|fecha)\b")
SUBJECT_RE = re.compile(r"(?i)^(?:el|la|los|las|the)?\s*([\wáéíóúñ]+(?:\s+[\wáéíóúñ]+){0,3}?)\s+(?:usa|usará|utiliza|es|será|est[áa]|migr[óo]|cambi[óo]|se implementa|se implementar[áa]|will|is|uses|moved|switched)\b")


_TECH_RE = re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in sorted(TECHNOLOGIES, key=len, reverse=True)) + r")(?![\w])")
_MONTH_RE = re.compile(r"(?<![\w])(" + "|".join(m for m in _MONTHS if len(m) > 3) + r")(?![\w])")
_NUM_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?%?(?![\w])")


def _aspects(sentence: str) -> dict[str, set[str]]:
    low = sentence.lower()
    out: dict[str, set[str]] = {}
    tech = set(_TECH_RE.findall(low))
    if tech:
        out["technology"] = tech
    months = set(_MONTH_RE.findall(low)) | set(find_dates(sentence))
    if months:
        out["date"] = months
    nums = set(_NUM_RE.findall(low)) - {n for d in find_dates(sentence) for n in d.split("-")}
    if nums:
        out["number"] = nums
    return out


def _sentences(text: str) -> list[str]:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if 20 <= len(s.strip()) <= 300]


class Intelligence:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db

    # ------------------------------------------------------------ contradictions
    def detect_contradictions(self, max_docs: int = 400) -> int:
        """Heuristic: sentences about the same subject with change verbs/negation or different values."""
        docs = rows_to_dicts(self.db.query("SELECT id, title, path, updated_at, mtime FROM documents WHERE deleted=0 ORDER BY updated_at DESC LIMIT ?", (max_docs,)))
        statements: list[dict[str, Any]] = []
        for d in docs:
            chunks = self.db.query("SELECT content FROM chunks WHERE document_id=? ORDER BY ordinal", (d["id"],))
            text = "\n".join(c["content"] for c in chunks)
            for s in _sentences(text):
                m = SUBJECT_RE.match(s)
                if not m:
                    continue
                subject = " ".join(content_words(m.group(1)))
                if not subject or len(subject) < 3:
                    continue
                statements.append({"doc": d, "subject": subject, "text": s, "date": d["mtime"] or d["updated_at"],
                                   "dates": find_dates(s), "words": set(content_words(s)), "aspects": _aspects(s)})
        by_subject: dict[str, list[dict[str, Any]]] = {}
        for st in statements:
            by_subject.setdefault(st["subject"], []).append(st)
        created = 0
        now = time.time()
        for subject, group in by_subject.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if a["doc"]["id"] == b["doc"]["id"] or a["text"] == b["text"]:
                        continue
                    overlap = len(a["words"] & b["words"]) / max(1, min(len(a["words"]), len(b["words"])))
                    diff_words = (a["words"] ^ b["words"])
                    if not diff_words:
                        continue
                    neg = bool(NEGATION.search(a["text"])) != bool(NEGATION.search(b["text"]))
                    change = bool(CHANGE_VERBS.search(a["text"]) or CHANGE_VERBS.search(b["text"]))
                    # same aspect (technology / date / number) with different values
                    shared_aspects = set(a["aspects"]) & set(b["aspects"])
                    aspect_differs = any(a["aspects"][k] != b["aspects"][k] for k in shared_aspects)
                    dates_differ = "date" in shared_aspects and a["aspects"]["date"] != b["aspects"]["date"]
                    if neg:
                        if overlap < 0.3:
                            continue
                    elif not (shared_aspects and aspect_differs and (change or overlap >= 0.3)):
                        continue
                    kind = "SUPERSEDED_INFORMATION" if (dates_differ or change) and not neg else "POSSIBLE_CONTRADICTION"
                    conf = 0.5 + 0.2 * neg + 0.15 * change + 0.15 * dates_differ - 0.2 * (1 - overlap)
                    fp = hashlib.sha1(f"{subject}:{a['text'][:80]}:{b['text'][:80]}".encode()).hexdigest()
                    if self.db.one("SELECT id FROM contradictions WHERE fingerprint=?", (fp,)):
                        continue
                    first, second = (a, b) if a["date"] <= b["date"] else (b, a)
                    reason = (f"Mismo sujeto '{subject}'; " + ("una afirma y otra niega; " if neg else "") +
                              ("hay un verbo de cambio; " if change else "") + ("fechas distintas; " if dates_differ else "")).strip("; ")
                    self.db.execute(
                        "INSERT INTO contradictions(fingerprint, subject, statement_a, document_a, date_a, statement_b, document_b, date_b, kind, confidence, reason, status, created_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,'open',?)",
                        (fp, subject, first["text"], first["doc"]["id"], first["date"], second["text"], second["doc"]["id"], second["date"],
                         kind, round(max(0.2, min(0.95, conf)), 2), reason, now))
                    if kind == "SUPERSEDED_INFORMATION":
                        self.db.execute("INSERT OR IGNORE INTO relations(source_type, source_id, target_type, target_id, relation, weight, confidence, origin, created_at)"
                                        " VALUES('document',?,'document',?,'SUPERSEDES',1.0,'AI_INFERENCE','auto',?)", (second["doc"]["id"], first["doc"]["id"], now))
                    else:
                        self.db.execute("INSERT OR IGNORE INTO relations(source_type, source_id, target_type, target_id, relation, weight, confidence, origin, created_at)"
                                        " VALUES('document',?,'document',?,'CONTRADICTS',1.0,'AI_INFERENCE','auto',?)", (a["doc"]["id"], b["doc"]["id"], now))
                    self.e.events.emit("CONTRADICTION_DETECTED", {"subject": subject, "kind": kind})
                    created += 1
        return created

    def contradictions(self, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for r in self.db.query("SELECT * FROM contradictions WHERE status=? ORDER BY confidence DESC, created_at DESC LIMIT ?", (status, limit)):
            d = dict(r)
            for side in ("a", "b"):
                doc = self.db.one("SELECT title, path FROM documents WHERE id=?", (d[f"document_{side}"],))
                d[f"note_{side}"] = dict(doc) if doc else None
                d[f"date_{side}_iso"] = time.strftime("%Y-%m-%d", time.localtime(d[f"date_{side}"])) if d[f"date_{side}"] else None
            out.append(d)
        return out

    # ------------------------------------------------------------ timeline
    def timeline(self, since: float | None = None, until: float | None = None, project: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        since = since or (time.time() - 30 * DAY)
        until = until or time.time() + 365 * DAY
        items: list[dict[str, Any]] = []
        since_iso = time.strftime("%Y-%m-%d", time.localtime(since))
        until_iso = time.strftime("%Y-%m-%d", time.localtime(until))
        sql = ("SELECT m.id, m.memory_type, m.title, m.content, m.event_date, m.status, m.project, d.title AS note, d.path"
               " FROM memories m JOIN documents d ON d.id=m.document_id WHERE m.status!='dismissed' AND m.event_date IS NOT NULL AND m.event_date >= ? AND m.event_date < ?")
        params: list[Any] = [since_iso, until_iso]
        if project:
            sql += " AND lower(m.project)=lower(?)"
            params.append(project)
        for m in self.db.query(sql + " ORDER BY m.event_date DESC LIMIT ?", params + [limit]):
            items.append({"date": m["event_date"], "kind": m["memory_type"], "title": m["content"][:120], "note": m["note"], "path": m["path"], "memory_id": m["id"]})
        # note modifications as activity
        for d in self.db.query("SELECT id, title, path, mtime, updated_at, doc_type FROM documents WHERE deleted=0 AND mtime >= ? AND mtime < ? ORDER BY mtime DESC LIMIT ?", (since, until, limit)):
            items.append({"date": time.strftime("%Y-%m-%d", time.localtime(d["mtime"])), "kind": "NOTE_MODIFIED", "title": d["title"], "note": d["title"], "path": d["path"]})
        items.sort(key=lambda x: x["date"], reverse=True)
        seen: set[tuple[str, str, str]] = set()
        out = []
        for it in items:
            key = (it["date"], it["kind"], it["title"])
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out[:limit]

    # ------------------------------------------------------------ why do I know this?
    def why_do_i_know(self, query: str, k: int = 6) -> dict[str, Any]:
        """Reconstruct the provenance chain: conclusion <- decision <- meeting/note <- document <- source."""
        results = self.e.search.search(query, k=k)
        chain: list[dict[str, Any]] = []
        for r in results[:4]:
            doc = self.db.one("SELECT * FROM documents WHERE id=?", (r["document_id"],))
            if not doc:
                continue
            node: dict[str, Any] = {"level": "NOTE", "title": doc["title"], "path": doc["path"],
                                    "date": time.strftime("%Y-%m-%d", time.localtime(doc["mtime"] or doc["updated_at"])),
                                    "doc_type": doc["doc_type"], "evidence": r["snippet"][:240]}
            node["memories"] = [dict(m) for m in self.db.query(
                "SELECT memory_type, content, confidence, event_date FROM memories WHERE document_id=? AND memory_type IN ('DECISION','TASK','LEARNING') ORDER BY importance DESC LIMIT 5", (doc["id"],))]
            node["sources"] = [dict(s) for s in self.db.query("SELECT source_type, source_url, source_path, source_date, capture_method FROM sources WHERE document_id=?", (doc["id"],))]
            fm = json.loads(doc["frontmatter"] or "{}")
            for key in ("source", "source_url", "url", "fuente"):
                if fm.get(key):
                    node["sources"].append({"source_type": "frontmatter", "source_url": str(fm[key])})
            node["links_from"] = [dict(x) for x in self.db.query(
                "SELECT d.title, d.path FROM relations r JOIN documents d ON d.id=r.source_id WHERE r.target_type='document' AND r.target_id=? AND r.source_type='document' AND d.deleted=0 LIMIT 8", (doc["id"],))]
            node["links_to"] = [dict(x) for x in self.db.query(
                "SELECT d.title, d.path FROM relations r JOIN documents d ON d.id=r.target_id WHERE r.source_type='document' AND r.source_id=? AND r.target_type='document' AND d.deleted=0 LIMIT 8", (doc["id"],))]
            chain.append(node)
        if not chain:
            return {"question": query, "chain": [], "summary": "Not enough evidence in Boveda Sergio."}
        lines = []
        for n in chain:
            lines.append(f"{n['title']} ({n['date']}, {n['doc_type']})")
            for m in n["memories"]:
                lines.append(f"  ↳ {m['memory_type']}: {m['content'][:120]} [{m['confidence']}]")
            for s in n["sources"]:
                lines.append(f"  ↳ fuente: {s.get('source_url') or s.get('source_path') or s.get('source_type')}")
            for l in n["links_to"][:3]:
                lines.append(f"  ↳ enlaza a: {l['title']}")
        return {"question": query, "chain": chain, "summary": "\n".join(lines)}

    # ------------------------------------------------------------ what changed?
    def what_changed(self, doc_id: int, versions: int = 2) -> dict[str, Any]:
        doc = self.db.one("SELECT id, title, path FROM documents WHERE id=?", (doc_id,))
        rows = self.db.query("SELECT content, captured_at, content_hash FROM document_versions WHERE document_id=? ORDER BY captured_at DESC LIMIT ?", (doc_id, versions))
        if not doc or len(rows) < 2:
            return {"document": dict(doc) if doc else None, "changed": False, "message": "Solo existe una versión indexada de esta nota."}
        new, old = rows[0], rows[1]
        diff = list(difflib.unified_diff(old["content"].splitlines(), new["content"].splitlines(), lineterm="", n=1,
                                         fromfile=time.strftime("%Y-%m-%d %H:%M", time.localtime(old["captured_at"])),
                                         tofile=time.strftime("%Y-%m-%d %H:%M", time.localtime(new["captured_at"]))))
        added = [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]
        removed = [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]
        return {"document": dict(doc), "changed": True, "from": old["captured_at"], "to": new["captured_at"],
                "added": added[:40], "removed": removed[:40], "diff": "\n".join(diff[:200]),
                "message": f"{len(added)} líneas añadidas, {len(removed)} eliminadas entre {time.strftime('%Y-%m-%d', time.localtime(old['captured_at']))} y {time.strftime('%Y-%m-%d', time.localtime(new['captured_at']))}."}

    def what_changed_query(self, query: str) -> dict[str, Any]:
        results = self.e.search.search(query, k=3)
        out = {"query": query, "documents": []}
        for r in results:
            out["documents"].append(self.what_changed(r["document_id"]))
        supers = self.db.query("SELECT * FROM contradictions WHERE kind='SUPERSEDED_INFORMATION' AND status='open' ORDER BY created_at DESC LIMIT 10")
        out["superseded"] = [dict(s) for s in supers if any(w in (s["subject"] + s["statement_a"]).lower() for w in content_words(query))]
        return out

    # ------------------------------------------------------------ active recall / relevance engine
    def active_recall(self, max_items: int = 8) -> list[dict[str, Any]]:
        """Decide which reminders deserve attention today; avoids spam via recall_log + feedback."""
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        candidates: list[dict[str, Any]] = []
        weights = self.e.memory.feedback_weights()
        for t in self.e.memory.open_tasks(limit=100):
            if t["age_days"] >= 10 or t["overdue"]:
                score = 0.5 + min(0.4, t["age_days"] / 60) + (0.3 if t["overdue"] else 0)
                candidates.append({"kind": "old_task", "key": f"task:{t['id']}", "score": score,
                                   "message": f"Este pendiente lleva {t['age_days']} días abierto: {t['content'][:120]}", "note": t["note_title"], "path": t["path"]})
        for p in self.db.query("SELECT name, last_activity_at FROM projects WHERE status='active'"):
            if p["last_activity_at"] and (now - p["last_activity_at"]) / DAY >= 14:
                days = int((now - p["last_activity_at"]) / DAY)
                candidates.append({"kind": "stale_project", "key": f"project:{p['name']}", "score": 0.4 + min(0.4, days / 90),
                                   "message": f"El proyecto '{p['name']}' no se actualiza hace {days} días."})
        for d in self.db.query("SELECT m.id, m.content, d.title, d.path, m.created_at FROM memories m JOIN documents d ON d.id=m.document_id"
                               " WHERE m.memory_type='DECISION' AND m.status='open' AND m.last_reviewed_at IS NULL AND m.created_at<? ORDER BY m.importance DESC LIMIT 10", (now - 21 * DAY,)):
            candidates.append({"kind": "decision_review", "key": f"decision:{d['id']}", "score": 0.45,
                               "message": f"Hay una decisión pendiente de revisar: {d['content'][:120]}", "note": d["title"], "path": d["path"]})
        for c in self.contradictions(limit=5):
            candidates.append({"kind": "contradiction", "key": f"contradiction:{c['id']}", "score": 0.4 + c["confidence"] * 0.4,
                               "message": f"Posible contradicción sobre '{c['subject']}' entre [[{c['note_a']['title'] if c['note_a'] else '?'}]] y [[{c['note_b']['title'] if c['note_b'] else '?'}]]."})
        # "three weeks ago you worked on something related to what you touched this week"
        recent = rows_to_dicts(self.db.query("SELECT id, title FROM documents WHERE deleted=0 AND mtime>=? ORDER BY mtime DESC LIMIT 5", (now - 7 * DAY,)))
        for d in recent:
            for rel in self.e.graph.related_documents(d["id"], k=3):
                rd = self.db.one("SELECT mtime, title, path FROM documents WHERE id=?", (rel["id"],))
                if rd and 14 <= (now - rd["mtime"]) / DAY <= 90:
                    weeks = int((now - rd["mtime"]) / (7 * DAY))
                    candidates.append({"kind": "related_past", "key": f"related:{d['id']}:{rel['id']}", "score": 0.3 + rel["score"] * 0.2,
                                       "message": f"Hace {weeks} semanas trabajaste en '{rd['title']}', relacionado con '{d['title']}' que tocaste esta semana.", "path": rd["path"]})
        for s in self.e.graph.suggestions(kind="SERENDIPITY", limit=3):
            candidates.append({"kind": "serendipity", "key": f"suggestion:{s['id']}", "score": 0.3 + s["confidence"] * 0.3, "message": s["reason"]})
        # relevance filter: skip anything shown in the last 3 days, apply feedback weights
        shown = {r["target_key"] for r in self.db.query("SELECT target_key FROM recall_log WHERE shown_at>=?", (now - 3 * DAY,))}
        out = []
        for c in sorted(candidates, key=lambda c: -c["score"]):
            if c["key"] in shown:
                continue
            c["score"] = round(c["score"] * weights.get(c["kind"], 0.7) / 0.7, 3)
            out.append(c)
            if len(out) >= max_items:
                break
        return out

    def mark_recalled(self, items: list[dict[str, Any]]) -> None:
        now = time.time()
        self.db.executemany("INSERT INTO recall_log(kind, target_key, shown_at) VALUES(?,?,?)", [(i["kind"], i["key"], now) for i in items])

    # ------------------------------------------------------------ project memory
    def project_memory(self, name: str) -> dict[str, Any]:
        p = self.db.one("SELECT * FROM projects WHERE normalized=lower(?) OR lower(name)=lower(?)", (name, name))
        if not p:
            return {"project": None, "message": "Not enough evidence in Boveda Sergio."}
        docs = rows_to_dicts(self.db.query(
            "SELECT d.id, d.path, d.title, d.doc_type, d.mtime FROM relations r JOIN documents d ON d.id=r.source_id WHERE r.target_type='project' AND r.target_id=? AND d.deleted=0 ORDER BY d.mtime DESC", (p["id"],)))
        ids = [d["id"] for d in docs]
        q = ",".join("?" * len(ids)) if ids else "NULL"
        mems = rows_to_dicts(self.db.query(f"SELECT m.*, d.title AS note_title FROM memories m JOIN documents d ON d.id=m.document_id WHERE m.document_id IN ({q}) AND m.status!='dismissed' ORDER BY m.event_date DESC", ids)) if ids else []
        people = rows_to_dicts(self.db.query(f"SELECT DISTINCT e.name FROM entity_mentions em JOIN entities e ON e.id=em.entity_id WHERE em.document_id IN ({q}) AND e.entity_type='PERSON'", ids)) if ids else []
        concepts = rows_to_dicts(self.db.query(f"SELECT e.name, e.entity_type, SUM(em.count) AS n FROM entity_mentions em JOIN entities e ON e.id=em.entity_id WHERE em.document_id IN ({q}) AND e.entity_type IN ('CONCEPT','TECHNOLOGY') GROUP BY e.id ORDER BY n DESC LIMIT 15", ids)) if ids else []
        return {
            "project": dict(p), "documents": docs, "meetings": [d for d in docs if d["doc_type"] == "meeting"],
            "tasks": [m for m in mems if m["memory_type"] == "TASK"], "decisions": [m for m in mems if m["memory_type"] == "DECISION"],
            "learnings": [m for m in mems if m["memory_type"] == "LEARNING"], "people": [x["name"] for x in people], "concepts": concepts,
            "timeline": self.timeline(since=0, project=p["name"], limit=50),
            "objective": p["objective"], "status": p["status"],
            "last_activity": time.strftime("%Y-%m-%d", time.localtime(p["last_activity_at"])) if p["last_activity_at"] else None,
        }
