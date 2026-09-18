"""Incremental indexer.

For every markdown note: hash -> skip if unchanged -> chunks -> FTS -> embeddings
-> entities/relations -> memories (tasks, decisions, learnings, events) -> version
snapshot. Only changed notes are processed. Deleted notes are soft-deleted.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from .chunking import chunk_text
from .embeddings import to_blob
from .extractors import (detect_context, detect_project, extract_decisions, extract_entities, extract_learnings,
                         extract_tasks, normalize_entity, find_dates)
from .security import find_secrets, normalize_privacy, redact
from .vault import Note, parse_note


class Indexer:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db
        self.cfg = engine.cfg

    # ------------------------------------------------------------ jobs
    def register_jobs(self) -> None:
        self.e.jobs.register("index_note", lambda p: self.index_path(p["path"]))
        self.e.jobs.register("remove_note", lambda p: self.mark_deleted(p["path"]))
        self.e.jobs.register("analyze", lambda p: self.post_analysis())
        self.e.jobs.register("embed_doc", lambda p: self.reembed_missing())

    # ------------------------------------------------------------ public
    def index_all(self, force: bool = False, progress=None) -> dict[str, int]:
        stats = {"scanned": 0, "indexed": 0, "skipped": 0, "deleted": 0, "errors": 0}
        seen: set[str] = set()
        self.e.vault.invalidate_cache()
        for path in self.e.vault.iter_markdown():
            rel = path.relative_to(self.e.vault.root).as_posix()
            seen.add(rel)
            stats["scanned"] += 1
            try:
                result = self.index_path(rel, force=force)
                stats["indexed" if result else "skipped"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                self.e.log.exception("index error for %s: %s", rel, exc)
            if progress and stats["scanned"] % 50 == 0:
                progress(stats)
        for row in self.db.query("SELECT path FROM documents WHERE deleted=0"):
            if row["path"] not in seen and (row["path"].endswith(".md")):
                if not (self.e.vault.root / row["path"]).exists():
                    self.mark_deleted(row["path"])
                    stats["deleted"] += 1
        self.post_analysis()
        self.db.kv_set("last_full_index", time.time())
        return stats

    def index_path(self, rel_path: str, force: bool = False) -> bool:
        abs_path = self.e.vault.root / rel_path
        if not abs_path.exists():
            self.mark_deleted(rel_path)
            return False
        if self.e.vault.is_excluded(rel_path):
            return False
        note = parse_note(abs_path, self.e.vault.root)
        return self.index_note(note, force=force)

    def mark_deleted(self, rel_path: str) -> None:
        row = self.db.one("SELECT id FROM documents WHERE path=? AND deleted=0", (rel_path,))
        if row:
            self.db.execute("UPDATE documents SET deleted=1, updated_at=? WHERE id=?", (time.time(), row["id"]))
            self.e.events.emit("NOTE_DELETED", {"path": rel_path, "document_id": row["id"]})

    # ------------------------------------------------------------ core
    def index_note(self, note: Note, force: bool = False) -> bool:
        existing = self.db.one("SELECT * FROM documents WHERE path=?", (note.path,))
        if existing and existing["content_hash"] == note.content_hash and not force and not existing["deleted"]:
            return False
        # privacy gates
        tags = set(note.tags)
        fm_privacy = note.frontmatter.get("privacy") or note.frontmatter.get("privacidad")
        privacy = normalize_privacy(fm_privacy, self.cfg.privacy.default_level)
        if "sensitive" in tags or "sensible" in tags:
            privacy = "SENSITIVE"
        if tags & {t.lower() for t in self.cfg.privacy.do_not_index_tags} or note.frontmatter.get("do_not_index") is True:
            self.e.log.info("skipping (do_not_index): %s", note.path)
            if existing:
                self.db.execute("UPDATE documents SET deleted=1 WHERE id=?", (existing["id"],))
            return False
        # secrets: never indexed, never logged in full
        redacted_raw, hits = redact(note.raw)
        redacted_body, _ = redact(note.body)
        now = time.time()
        context = detect_context(redacted_body, note.tags, note.frontmatter, note.path)
        project = detect_project(redacted_body, note.tags, note.frontmatter, note.path)
        doc_type = "daily" if note.is_daily else ("capture" if note.path.startswith(self.cfg.layout.inbox_folder) else
                                                   "meeting" if ("reunion" in note.path.lower() or "reunión" in note.path.lower()
                                                                 or "meeting" in tags) else "note")
        created_at = existing["created_at"] if existing else (note.ctime or now)
        with self.db.transaction() as c:
            if existing:
                doc_id = existing["id"]
                c.execute("""UPDATE documents SET title=?, doc_type=?, content_hash=?, size=?, mtime=?, updated_at=?, indexed_at=?,
                             privacy=?, context=?, frontmatter=?, tags=?, links=?, word_count=?, deleted=0, secret_hits=? WHERE id=?""",
                          (note.title, doc_type, note.content_hash, note.size, note.mtime, now, now, privacy, context,
                           json.dumps(note.frontmatter, ensure_ascii=False, default=str), json.dumps(note.tags, ensure_ascii=False),
                           json.dumps(note.links, ensure_ascii=False), note.word_count, len(hits), doc_id))
                c.execute("DELETE FROM chunks_fts WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id=?)", (doc_id,))
                c.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id=?)", (doc_id,))
                c.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
                c.execute("DELETE FROM entity_mentions WHERE document_id=?", (doc_id,))
                c.execute("DELETE FROM relations WHERE source_type='document' AND source_id=? AND origin IN ('wikilink','auto')", (doc_id,))
            else:
                cur = c.execute("""INSERT INTO documents(path, title, doc_type, content_hash, size, mtime, created_at, updated_at, indexed_at,
                                   privacy, context, frontmatter, tags, links, word_count, secret_hits)
                                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (note.path, note.title, doc_type, note.content_hash, note.size, note.mtime, created_at, now, now,
                                 privacy, context, json.dumps(note.frontmatter, ensure_ascii=False, default=str),
                                 json.dumps(note.tags, ensure_ascii=False), json.dumps(note.links, ensure_ascii=False),
                                 note.word_count, len(hits)))
                doc_id = int(cur.lastrowid)
            # version snapshot (for WHAT CHANGED); store redacted content
            last_ver = c.execute("SELECT content_hash FROM document_versions WHERE document_id=? ORDER BY captured_at DESC LIMIT 1",
                                 (doc_id,)).fetchone()
            if not last_ver or last_ver["content_hash"] != note.content_hash:
                c.execute("INSERT INTO document_versions(document_id, content_hash, content, captured_at) VALUES(?,?,?,?)",
                          (doc_id, note.content_hash, redacted_raw, now))
            # chunks + FTS
            chunks = chunk_text(redacted_body, self.cfg.chunk_size, self.cfg.chunk_overlap)
            chunk_ids: list[int] = []
            for ch in chunks:
                cur = c.execute("INSERT INTO chunks(document_id, ordinal, heading, content, content_hash, char_start, char_end) VALUES(?,?,?,?,?,?,?)",
                                (doc_id, ch.ordinal, ch.heading, ch.content, ch.hash, ch.char_start, ch.char_end))
                cid = int(cur.lastrowid)
                chunk_ids.append(cid)
                c.execute("INSERT INTO chunks_fts(content, heading, title, path, chunk_id) VALUES(?,?,?,?,?)",
                          (ch.content, ch.heading, note.title, note.path, cid))
        # embeddings (outside the transaction: may be slow)
        self._embed_chunks(doc_id, [(cid, ch) for cid, ch in zip(chunk_ids, chunks)])
        # entities & relations
        self._index_entities(doc_id, note, redacted_body, project)
        # memories
        self._extract_memories(doc_id, note, redacted_body, context, project, privacy)
        # project registry
        if project:
            self._touch_project(project, doc_id, note)
        self.e.vectors.invalidate()
        self.e.events.emit("NOTE_UPDATED" if existing else "NOTE_CREATED", {"path": note.path, "document_id": doc_id})
        if hits:
            self.e.log.warning("possible secrets redacted in %s (%d hits)", note.path, len(hits))
        return True

    def _embed_chunks(self, doc_id: int, items: list[tuple[int, Any]]) -> None:
        if not items:
            return
        try:
            texts = [(ch.heading + "\n" if ch.heading else "") + ch.content for _, ch in items]
            vecs = self.e.embedder.embed(texts)
            now = time.time()
            self.db.executemany("INSERT OR REPLACE INTO embeddings(chunk_id, model, dim, vector, created_at) VALUES(?,?,?,?,?)",
                                [(cid, self.e.embedder.model, int(vecs.shape[1]), to_blob(vecs[i]), now) for i, (cid, _) in enumerate(items)])
            self.e.events.emit("EMBEDDING_CREATED", {"document_id": doc_id, "chunks": len(items)})
        except Exception as exc:  # noqa: BLE001 - embeddings failing must never lose the note
            self.e.log.error("embedding failed for doc %s: %s (queued for retry)", doc_id, exc)
            self.e.jobs.enqueue("embed_doc", {"document_id": doc_id}, delay=30)

    def _index_entities(self, doc_id: int, note: Note, body: str, project: str | None) -> None:
        now = time.time()
        ents = extract_entities(body, note.links, note.tags, note.frontmatter)
        if project:
            ents.append((project, "PROJECT", 3))
        for name, etype, count in ents:
            norm = normalize_entity(name)
            row = self.db.one("SELECT id FROM entities WHERE normalized=? AND entity_type=?", (norm, etype))
            if row:
                eid = row["id"]
                self.db.execute("UPDATE entities SET last_seen=?, mention_count=mention_count+? WHERE id=?", (now, count, eid))
            else:
                cur = self.db.execute("INSERT INTO entities(name, normalized, entity_type, mention_count, first_seen, last_seen) VALUES(?,?,?,?,?,?)",
                                      (name, norm, etype, count, now, now))
                eid = int(cur.lastrowid)
                self.e.events.emit("ENTITY_DISCOVERED", {"entity_id": eid, "name": name, "type": etype})
            self.db.execute("INSERT OR REPLACE INTO entity_mentions(entity_id, document_id, count) VALUES(?,?,?)", (eid, doc_id, count))
            self.db.execute("INSERT OR IGNORE INTO relations(source_type, source_id, target_type, target_id, relation, weight, confidence, origin, created_at)"
                            " VALUES('document',?,'entity',?,'MENTIONED_IN',?,?,'auto',?)",
                            (doc_id, eid, float(count), "USER_ASSERTION" if etype == "NOTE" else "AI_INFERENCE", now))
        # entity defined by this note (note title == entity)
        norm_title = normalize_entity(note.title)
        self.db.execute("UPDATE entities SET document_id=? WHERE normalized=? AND document_id IS NULL", (doc_id, norm_title))
        # wikilinks -> document relations
        for target in note.links:
            resolved = self.e.vault.resolve_link(target)
            if not resolved:
                continue
            trow = self.db.one("SELECT id FROM documents WHERE path=?", (resolved,))
            if trow and trow["id"] != doc_id:
                self.db.execute("INSERT OR IGNORE INTO relations(source_type, source_id, target_type, target_id, relation, weight, confidence, origin, created_at)"
                                " VALUES('document',?,'document',?,'LINKS_TO',1.0,'USER_ASSERTION','wikilink',?)", (doc_id, trow["id"], now))

    def _extract_memories(self, doc_id: int, note: Note, body: str, context: str, project: str | None, privacy: str) -> None:
        now = time.time()
        note_date = note.note_date
        year = int(note_date[:4]) if note_date else None
        items = extract_tasks(body, year) + extract_decisions(body, year) + extract_learnings(body)
        active_fps: set[str] = set()
        for it in items:
            fp = hashlib.sha1(f"{doc_id}:{it.kind}:{it.text.lower()[:200]}".encode()).hexdigest()
            active_fps.add(fp)
            md = dict(it.metadata)
            status = md.pop("status", "open")
            due = md.pop("due", None)
            priority = md.pop("priority", None)
            event_date = md.pop("date", None) or note_date
            existing = self.db.one("SELECT id, status, content FROM memories WHERE fingerprint=?", (fp,))
            if existing:
                if existing["status"] != status and existing["status"] not in ("dismissed",):
                    self.db.execute("INSERT INTO memory_versions(memory_id, content, status, changed_at, reason) VALUES(?,?,?,?,?)",
                                    (existing["id"], existing["content"], existing["status"], now, "status changed in note"))
                    self.db.execute("UPDATE memories SET status=?, updated_at=? WHERE id=?", (status, now, existing["id"]))
                self.db.execute("UPDATE memories SET due_date=COALESCE(?, due_date), priority=COALESCE(?, priority), updated_at=? WHERE id=?",
                                (due, priority, now, existing["id"]))
                continue
            cur = self.db.execute(
                """INSERT INTO memories(memory_type, title, content, document_id, fingerprint, confidence, status, event_date, due_date,
                   priority, project, context, metadata, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (it.kind, it.text[:120], it.text, doc_id, fp, it.confidence, status, event_date, due, priority, project, context,
                 json.dumps(md, ensure_ascii=False), now, now))
            mid = int(cur.lastrowid)
            self.e.events.emit(f"{it.kind}_DISCOVERED", {"memory_id": mid, "document_id": doc_id, "text": it.text[:200]})
        # tasks that disappeared from the note are not deleted: marked 'removed_from_note' in metadata
        for row in self.db.query("SELECT id, fingerprint, memory_type, metadata FROM memories WHERE document_id=? AND memory_type IN ('TASK','DECISION','LEARNING')", (doc_id,)):
            if row["fingerprint"] not in active_fps:
                md = json.loads(row["metadata"] or "{}")
                if not md.get("removed_from_note"):
                    md["removed_from_note"] = now
                    self.db.execute("UPDATE memories SET metadata=?, updated_at=? WHERE id=?", (json.dumps(md), now, row["id"]))
        # EPISODIC memory: one per dated note (daily notes, meetings, notes with a date)
        if note_date or note.is_daily or "meeting" in note.tags or "reunion" in note.tags:
            fp = hashlib.sha1(f"{doc_id}:EPISODIC".encode()).hexdigest()
            summary = self._first_paragraph(body)
            if summary and not self.db.one("SELECT id FROM memories WHERE fingerprint=?", (fp,)):
                self.db.execute(
                    """INSERT INTO memories(memory_type, title, content, document_id, fingerprint, confidence, status, event_date, project, context, metadata, created_at, updated_at)
                       VALUES('EPISODIC',?,?,?,?,'USER_ASSERTION','open',?,?,?,?,?,?)""",
                    (note.title, summary[:600], doc_id, fp, note_date, project, context,
                     json.dumps({"what": note.title, "when": note_date, "where": note.path}), now, now))
        # RAW memory for captures in the Inbox
        if note.path.startswith(self.cfg.layout.inbox_folder):
            fp = hashlib.sha1(f"{doc_id}:RAW".encode()).hexdigest()
            if not self.db.one("SELECT id FROM memories WHERE fingerprint=?", (fp,)):
                self.db.execute(
                    """INSERT INTO memories(memory_type, title, content, document_id, fingerprint, confidence, status, event_date, project, context, created_at, updated_at)
                       VALUES('RAW',?,?,?,?,'EXTERNAL_SOURCE','open',?,?,?,?,?)""",
                    (note.title, self._first_paragraph(body)[:600], doc_id, fp, note_date, project, context, now, now))

    @staticmethod
    def _first_paragraph(body: str) -> str:
        for para in body.split("\n\n"):
            p = para.strip()
            if p and not p.startswith(("#", "---", "Origen:", "Fuente:", "Keywords:")):
                return " ".join(p.split())
        return " ".join(body.strip().split())[:400]

    def _touch_project(self, project: str, doc_id: int, note: Note) -> None:
        now = time.time()
        norm = normalize_entity(project)
        row = self.db.one("SELECT id FROM projects WHERE normalized=?", (norm,))
        if row:
            self.db.execute("UPDATE projects SET updated_at=?, last_activity_at=MAX(COALESCE(last_activity_at,0), ?) WHERE id=?",
                            (now, note.mtime or now, row["id"]))
            pid = row["id"]
        else:
            cur = self.db.execute("INSERT INTO projects(name, normalized, created_at, updated_at, last_activity_at) VALUES(?,?,?,?,?)",
                                  (project, norm, now, now, note.mtime or now))
            pid = int(cur.lastrowid)
        if normalize_entity(note.title) == norm:
            self.db.execute("UPDATE projects SET document_id=? WHERE id=?", (doc_id, pid))
        self.db.execute("INSERT OR IGNORE INTO relations(source_type, source_id, target_type, target_id, relation, weight, confidence, origin, created_at)"
                        " VALUES('document',?,'project',?,'PART_OF',1.0,'AI_INFERENCE','auto',?)", (doc_id, pid, now))

    # ------------------------------------------------------------ analysis after indexing
    def post_analysis(self) -> None:
        """Cross-note analysis: memory scores, temporal states, suggestions, contradictions."""
        try:
            self.rebuild_link_relations()
            self.e.memory.recompute_scores()
            self.e.memory.update_temporal_states()
            self.e.graph.refresh_suggestions()
            self.e.intel.detect_contradictions()
        except Exception as exc:  # noqa: BLE001
            self.e.log.exception("post_analysis failed: %s", exc)

    def rebuild_link_relations(self) -> int:
        """Wikilinks whose target note was indexed later than the source are resolved here."""
        now = time.time()
        self.e.vault.invalidate_cache()
        n = 0
        for d in self.db.query("SELECT id, links FROM documents WHERE deleted=0"):
            for target in json.loads(d["links"] or "[]"):
                resolved = self.e.vault.resolve_link(target)
                if not resolved:
                    continue
                t = self.db.one("SELECT id FROM documents WHERE path=? AND deleted=0", (resolved,))
                if t and t["id"] != d["id"]:
                    cur = self.db.execute("INSERT OR IGNORE INTO relations(source_type, source_id, target_type, target_id, relation, weight, confidence, origin, created_at)"
                                          " VALUES('document',?,'document',?,'LINKS_TO',1.0,'USER_ASSERTION','wikilink',?)", (d["id"], t["id"], now))
                    n += cur.rowcount if cur.rowcount > 0 else 0
        if True:
            # drop LINK suggestions that are now real links
            for s in self.db.query("SELECT id, document_ids FROM suggested_links WHERE kind='LINK' AND status='open'"):
                ids = json.loads(s["document_ids"])
                if len(ids) == 2 and self.db.one("SELECT 1 FROM relations WHERE relation='LINKS_TO' AND source_type='document' AND target_type='document' AND ((source_id=? AND target_id=?) OR (source_id=? AND target_id=?))", (ids[0], ids[1], ids[1], ids[0])):
                    self.db.execute("UPDATE suggested_links SET status='accepted' WHERE id=?", (s["id"],))
        return n

    def reembed_missing(self) -> int:
        rows = self.db.query("SELECT c.id, c.heading, c.content FROM chunks c LEFT JOIN embeddings e ON e.chunk_id=c.id WHERE e.chunk_id IS NULL LIMIT 2000")
        if not rows:
            return 0
        texts = [((r["heading"] + "\n") if r["heading"] else "") + r["content"] for r in rows]
        vecs = self.e.embedder.embed(texts)
        now = time.time()
        self.db.executemany("INSERT OR REPLACE INTO embeddings(chunk_id, model, dim, vector, created_at) VALUES(?,?,?,?,?)",
                            [(r["id"], self.e.embedder.model, int(vecs.shape[1]), to_blob(vecs[i]), now) for i, r in enumerate(rows)])
        self.e.vectors.invalidate()
        return len(rows)
