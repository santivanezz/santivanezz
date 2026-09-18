"""Generated notes: daily memory, morning briefing, weekly/monthly reviews,
brain health and the SERGIO BRAIN command center. All written into the
vault's `SERGIO BRAIN/` folder as generated notes (never touching user notes)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .db import rows_to_dicts

DAY = 86400.0


def _link(title: str) -> str:
    return f"[[{title}]]"


class Reviews:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db
        self.cfg = engine.cfg

    # ------------------------------------------------------------ daily
    def daily_note_path(self, day: datetime | None = None) -> Path:
        day = day or datetime.now()
        return self.e.vault.root / self.cfg.layout.daily_folder / f"{day.strftime(self.cfg.layout.daily_note_format)}.md"

    def daily_memory(self, day: datetime | None = None, write: bool = True) -> str:
        day = day or datetime.now()
        start = datetime(day.year, day.month, day.day).timestamp()
        end = start + DAY
        iso = day.strftime("%Y-%m-%d")
        events = self.e.intel.timeline(since=start, until=end, limit=50)
        tasks = [t for t in self.e.memory.open_tasks(limit=200) if start <= t["created_at"] < end]
        decisions = self.e.memory.list_memories("DECISION", since=start, limit=30)
        learnings = self.e.memory.list_memories("LEARNING", since=start, limit=30)
        captures = rows_to_dicts(self.db.query("SELECT title, note_path, classification FROM captures WHERE created_at BETWEEN ? AND ?", (start, end)))
        modified = rows_to_dicts(self.db.query("SELECT title, path FROM documents WHERE deleted=0 AND mtime BETWEEN ? AND ? ORDER BY mtime DESC LIMIT 40", (start, end)))
        important = self.e.memory.list_memories(limit=8)
        sections = [f"# {iso}", "", "# Events"]
        sections += [f"- {ev['kind']}: {ev['title']} — {_link(ev['note'])}" for ev in events if ev["kind"] != "NOTE_MODIFIED"] or ["- (sin eventos)"]
        sections += ["", "# Tasks"] + ([f"- [ ] {t['content'][:140]} — {_link(t['note_title'])}" for t in tasks] or ["- (sin tareas nuevas)"])
        sections += ["", "# Decisions"] + ([f"- {d['content'][:160]} — {_link(d['note_title'])}" for d in decisions] or ["- (sin decisiones)"])
        sections += ["", "# Captures"] + ([f"- {c['title']} ({c['classification']}) — [[{Path(c['note_path']).stem}]]" if c['note_path'] else f"- {c['title']}" for c in captures] or ["- (sin capturas)"])
        sections += ["", "# Learning"] + ([f"- {l['content'][:160]} — {_link(l['note_title'])}" for l in learnings] or ["- (sin aprendizajes)"])
        sections += ["", "# Notes"] + ([f"- {_link(m['title'])}" for m in modified if not m["path"].startswith(self.cfg.layout.brain_folder)] or ["- (sin notas modificadas)"])
        sections += ["", "# Important Memories"] + ([f"- ({m['memory_type']}) {m['content'][:120]} — {_link(m['note_title'])}" for m in important if m.get("note_title")] or ["- (ninguna)"])
        body = "\n".join(sections)
        if write:
            self.e.writer.update_managed_block(self.daily_note_path(day), "daily", body, create_with_title=None)
        return body

    def daily_consolidation(self, day: datetime | None = None) -> dict[str, Any]:
        """RAW events -> daily summary -> important memories -> long-term knowledge (promotion, never deletion)."""
        day = day or datetime.now()
        start = datetime(day.year, day.month, day.day).timestamp()
        end = start + DAY
        promoted = 0
        # promote LEARNING/DECISION with high importance to LONG_TERM (as a new memory copy, original untouched)
        for m in self.db.query("SELECT * FROM memories WHERE memory_type IN ('LEARNING','DECISION') AND importance>=0.5 AND created_at BETWEEN ? AND ?", (start, end)):
            fp = "LT:" + m["fingerprint"]
            if not self.db.one("SELECT id FROM memories WHERE fingerprint=?", (fp,)):
                self.db.execute("""INSERT INTO memories(memory_type, title, content, document_id, fingerprint, confidence, status, event_date, project, context, importance, importance_reason, created_at, updated_at)
                                   VALUES('LONG_TERM',?,?,?,?,?,'open',?,?,?,?,?,?,?)""",
                                (m["title"], m["content"], m["document_id"], fp, m["confidence"], m["event_date"], m["project"], m["context"],
                                 m["importance"], "promovida en la consolidación diaria: " + (m["importance_reason"] or ""), time.time(), time.time()))
                promoted += 1
        # RAW captures processed today become 'processed' if they were turned into notes
        self.db.execute("UPDATE captures SET status='processed' WHERE status='inbox' AND note_path IS NOT NULL AND created_at<?", (start,))
        summary = self.daily_memory(day, write=True)
        self.e.events.emit("MEMORY_CONSOLIDATED", {"day": day.strftime("%Y-%m-%d"), "promoted": promoted})
        return {"promoted": promoted, "summary": summary}

    # ------------------------------------------------------------ morning briefing
    def morning_briefing(self, write: bool = True) -> str:
        now = time.time()
        today = datetime.now()
        y_start = datetime(today.year, today.month, today.day).timestamp() - DAY
        y_end = y_start + DAY
        today_iso = today.strftime("%Y-%m-%d")
        yesterday = self.e.intel.timeline(since=y_start, until=y_end, limit=30)
        done_yesterday = rows_to_dicts(self.db.query("SELECT m.content, d.title FROM memories m JOIN documents d ON d.id=m.document_id WHERE m.memory_type='TASK' AND m.status='done' AND m.updated_at BETWEEN ? AND ?", (y_start, y_end)))
        new_mem = rows_to_dicts(self.db.query("SELECT m.memory_type, m.content, d.title FROM memories m JOIN documents d ON d.id=m.document_id WHERE m.created_at BETWEEN ? AND ? AND m.memory_type IN ('LEARNING','DECISION','EPISODIC') LIMIT 10", (y_start, y_end)))
        tasks = self.e.memory.open_tasks(limit=60)
        due_today = [t for t in tasks if t.get("due_date") == today_iso]
        overdue = [t for t in tasks if t["overdue"]]
        upcoming = rows_to_dicts(self.db.query("SELECT m.content, m.event_date, d.title FROM memories m JOIN documents d ON d.id=m.document_id WHERE m.event_date>=? AND m.event_date<=? AND m.memory_type IN ('EPISODIC','TASK') ORDER BY m.event_date LIMIT 10",
                                               (today_iso, (today + timedelta(days=3)).strftime("%Y-%m-%d"))))
        recall = self.e.intel.active_recall(max_items=6)
        self.e.intel.mark_recalled(recall)
        stale = self.e.memory.stale_documents(limit=5)
        contradictions = self.e.intel.contradictions(limit=3)
        connections = self.e.graph.suggestions(kind="SERENDIPITY", limit=3) + self.e.graph.suggestions(kind="LINK", limit=2)
        L = [f"# GOOD MORNING SERGIO — {today_iso}", "", "## AYER"]
        L += [f"- {ev['kind']}: {ev['title']} — {_link(ev['note'])}" for ev in yesterday[:8] if ev["kind"] != "NOTE_MODIFIED"] or ["- Sin actividad registrada ayer."]
        if done_yesterday:
            L += ["", "Tareas completadas:"] + [f"- [x] {t['content'][:120]} — {_link(t['title'])}" for t in done_yesterday[:8]]
        if new_mem:
            L += ["", "Nuevas memorias:"] + [f"- ({m['memory_type']}) {m['content'][:120]} — {_link(m['title'])}" for m in new_mem]
        L += ["", "## HOY"]
        L += [f"- [ ] {t['content'][:120]} — {_link(t['note_title'])} (vence hoy)" for t in due_today]
        L += [f"- [ ] ⚠ {t['content'][:120]} — {_link(t['note_title'])} (atrasada, {t['due_date']})" for t in overdue[:8]]
        L += [f"- {u['event_date']}: {u['content'][:120]} — {_link(u['title'])}" for u in upcoming[:8] if u["event_date"] != today_iso]
        if len(L) and L[-1] == "## HOY":
            L.append("- Nada con fecha para hoy. Tareas abiertas: " + str(len(tasks)))
        L += ["", "## ATENCIÓN"] + ([f"- {r['message']}" for r in recall] or ["- Nada urgente detectado."])
        L += [f"- Información sin revisar: {_link(s['title'])} ({s['days_since_review']} días)" for s in stale[:3]]
        L += [f"- Posible contradicción sobre '{c['subject']}': {_link(c['note_a']['title'])} vs {_link(c['note_b']['title'])}" for c in contradictions if c["note_a"] and c["note_b"]]
        L += ["", "## MEMORY"]
        L += [f"- ({m['memory_type']}) {m['content'][:120]} — {_link(m['note_title'])}" for m in self.e.memory.list_memories(limit=5) if m.get("note_title")] or ["- (sin memorias destacadas)"]
        L += ["", "## CONNECTIONS"] + ([f"- {c['reason']} → " + ", ".join(_link(d['title']) for d in c['documents'][:4]) for c in connections] or ["- Sin nuevas conexiones."])
        body = "\n".join(L)
        if write:
            self.e.writer.write_generated(self.cfg.layout.reviews_folder, f"Morning Briefing {today_iso}", body, {"type": "morning-briefing"}, overwrite_if_ours=True)
        return body

    # ------------------------------------------------------------ weekly / monthly
    def _period_review(self, days: int, title: str) -> str:
        now = time.time()
        since = now - days * DAY
        since_iso = time.strftime("%Y-%m-%d", time.localtime(since))
        today_iso = time.strftime("%Y-%m-%d")
        modified = rows_to_dicts(self.db.query("SELECT title, path, context FROM documents WHERE deleted=0 AND mtime>=? AND path NOT LIKE ? ORDER BY mtime DESC LIMIT 60", (since, self.cfg.layout.brain_folder + "%")))
        learnings = self.e.memory.list_memories("LEARNING", since=since, limit=25)
        decisions = self.e.memory.list_memories("DECISION", since=since, limit=25)
        projects = rows_to_dicts(self.db.query("SELECT name, last_activity_at FROM projects WHERE last_activity_at>=? ORDER BY last_activity_at DESC", (since,)))
        tasks = self.e.memory.open_tasks(limit=200)
        overdue = [t for t in tasks if t["overdue"] or t["age_days"] > 14]
        problems = rows_to_dicts(self.db.query("SELECT c.content, d.title FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.mtime>=? AND (lower(c.content) LIKE '%problema%' OR lower(c.content) LIKE '%bloqueo%' OR lower(c.content) LIKE '%riesgo%' OR lower(c.heading) LIKE '%problema%') LIMIT 10", (since,)))
        suggestions = self.e.graph.suggestions(limit=8)
        stale = self.e.memory.stale_documents(limit=8)
        topics = rows_to_dicts(self.db.query("SELECT e.name, e.entity_type, COUNT(DISTINCT em.document_id) AS n FROM entity_mentions em JOIN entities e ON e.id=em.entity_id JOIN documents d ON d.id=em.document_id WHERE d.mtime>=? AND e.entity_type IN ('CONCEPT','TECHNOLOGY','TOPIC') GROUP BY e.id ORDER BY n DESC LIMIT 12", (since,)))
        L = [f"# {title} ({since_iso} → {today_iso})", "", "## Qué hice"] + ([f"- {_link(m['title'])} ({m['context']})" for m in modified[:30]] or ["- (sin notas modificadas)"])
        L += ["", "## Qué aprendí"] + ([f"- {l['content'][:160]} — {_link(l['note_title'])}" for l in learnings] or ["- (sin aprendizajes detectados)"])
        L += ["", "## Proyectos que avanzaron"] + ([f"- {p['name']}" for p in projects] or ["- (ninguno)"])
        L += ["", "## Tareas pendientes"] + ([f"- [ ] {t['content'][:120]} — {_link(t['note_title'])}" for t in tasks[:20]] or ["- (ninguna)"])
        L += ["", "## Tareas atrasadas / antiguas"] + ([f"- [ ] {t['content'][:120]} ({t['age_days']} días) — {_link(t['note_title'])}" for t in overdue[:15]] or ["- (ninguna)"])
        L += ["", "## Decisiones"] + ([f"- {d['content'][:160]} — {_link(d['note_title'])}" for d in decisions] or ["- (ninguna)"])
        L += ["", "## Problemas"] + ([f"- {' '.join(p['content'].split())[:160]} — {_link(p['title'])}" for p in problems] or ["- (ninguno detectado)"])
        L += ["", "## Nuevas conexiones"] + ([f"- [{s['kind']}] {s['reason']} → " + ", ".join(_link(d['title']) for d in s['documents'][:4]) for s in suggestions] or ["- (ninguna)"])
        L += ["", "## Posible conocimiento obsoleto"] + ([f"- {_link(s['title'])}: {s['days_since_review']} días sin revisar" for s in stale] or ["- (nada)"])
        L += ["", "## Temas recurrentes"] + ([f"- {t['name']} ({t['n']} notas)" for t in topics] or ["- (ninguno)"])
        if days >= 28:
            L += ["", "## Evolución del conocimiento"]
            L += [f"- {c['subject']}: '{c['statement_a'][:80]}' → '{c['statement_b'][:80]}'" for c in self.db.query("SELECT subject, statement_a, statement_b FROM contradictions WHERE kind='SUPERSEDED_INFORMATION' AND created_at>=? LIMIT 10", (since,))] or ["- (sin cambios detectados)"]
        return "\n".join(L)

    def weekly_review(self, write: bool = True) -> str:
        body = self._period_review(7, "Weekly Brain Review")
        if write:
            self.e.writer.write_generated(self.cfg.layout.reviews_folder, f"Weekly Brain Review {time.strftime('%Y-W%W')}", body, {"type": "weekly-review"}, overwrite_if_ours=True)
        return body

    def monthly_review(self, write: bool = True) -> str:
        body = self._period_review(30, "Monthly Brain Review")
        if write:
            self.e.writer.write_generated(self.cfg.layout.reviews_folder, f"Monthly Brain Review {time.strftime('%Y-%m')}", body, {"type": "monthly-review"}, overwrite_if_ours=True)
        return body

    # ------------------------------------------------------------ brain health
    def brain_health(self) -> dict[str, Any]:
        orphans = self.e.graph.orphan_documents()
        dups = self.e.graph.suggestions(kind="DUPLICATE", limit=50)
        unlinked = self.e.graph.unlinked_concepts()
        missing = self.e.graph.missing_metadata()
        stale = self.e.memory.stale_documents(limit=100)
        contradictions = self.e.intel.contradictions(limit=50)
        fragmented = self.e.graph.suggestions(kind="CONSOLIDATE", limit=20)
        tasks = self.e.memory.open_tasks(limit=500)
        overdue = [t for t in tasks if t["overdue"]]
        now = time.time()
        incomplete = rows_to_dicts(self.db.query("SELECT name, last_activity_at FROM projects WHERE status='active' AND (last_activity_at IS NULL OR last_activity_at<?)", (now - 30 * DAY,)))
        stats = self.db.stats()
        total = max(1, stats["documents_active"])
        score = 100
        score -= min(25, int(100 * len(orphans) / total * 0.5))
        score -= min(15, len(dups) * 2)
        score -= min(15, int(100 * len(stale) / total * 0.3))
        score -= min(15, len(contradictions) * 2)
        score -= min(15, len(overdue))
        score -= min(15, int(100 * len(missing) / total * 0.2))
        return {"score": max(0, score), "stats": stats, "orphans": orphans, "duplicates": dups, "unlinked_concepts": unlinked,
                "missing_metadata": missing, "stale": stale, "contradictions": contradictions, "fragmented": fragmented,
                "incomplete_projects": incomplete, "overdue_tasks": overdue, "pending_jobs": self.e.jobs.pending_count(),
                "embedding_provider": self.e.embedder.name, "llm_provider": self.e.llm.name, "ai_costs": self.e.costs.summary()}

    def brain_health_note(self) -> str:
        h = self.brain_health()
        L = [f"# BRAIN HEALTH — {time.strftime('%Y-%m-%d %H:%M')}", "", f"**Score:** {h['score']}/100", "",
             f"Notas: {h['stats']['documents_active']} · Chunks: {h['stats']['chunks']} · Memorias: {h['stats']['memories']} · Entidades: {h['stats']['entities']} · Relaciones: {h['stats']['relations']}", ""]
        def sec(title: str, items: list[str]) -> None:
            L.extend(["", f"## {title} ({len(items)})"] + (items[:25] or ["- ✓ nada"]))
        sec("Orphan notes", [f"- {_link(o['title'])}" for o in h["orphans"]])
        sec("Duplicate notes", [f"- {s['reason']}: " + ", ".join(_link(d['title']) for d in s['documents']) for s in h["duplicates"]])
        sec("Unlinked concepts", [f"- {u['name']} ({u['entity_type']}, {u['docs']} notas) → crear nota" for u in h["unlinked_concepts"]])
        sec("Missing metadata", [f"- {_link(m['title'])}: {', '.join(m['missing'])}" for m in h["missing_metadata"]])
        sec("Stale information", [f"- {_link(s['title'])}: {s['days_since_review']} días" for s in h["stale"]])
        sec("Contradictions", [f"- {c['subject']}: {_link(c['note_a']['title'])} vs {_link(c['note_b']['title'])} ({c['kind']}, {c['confidence']})" for c in h["contradictions"] if c["note_a"] and c["note_b"]])
        sec("Fragmented knowledge", [f"- {s['reason']}" for s in h["fragmented"]])
        sec("Incomplete projects", [f"- {p['name']}" for p in h["incomplete_projects"]])
        sec("Overdue tasks", [f"- [ ] {t['content'][:120]} ({t['due_date']}) — {_link(t['note_title'])}" for t in h["overdue_tasks"]])
        body = "\n".join(L)
        self.e.writer.write_generated(self.cfg.layout.brain_folder, "Brain Health", body, {"type": "brain-health"}, overwrite_if_ours=True)
        return body

    # ------------------------------------------------------------ command center
    def command_center(self) -> str:
        today_iso = time.strftime("%Y-%m-%d")
        tasks = self.e.memory.open_tasks(limit=100)
        now = time.time()
        meetings = rows_to_dicts(self.db.query("SELECT m.content, m.event_date, d.title FROM memories m JOIN documents d ON d.id=m.document_id WHERE m.memory_type='EPISODIC' AND m.event_date=? LIMIT 10", (today_iso,)))
        activity = rows_to_dicts(self.db.query("SELECT title FROM documents WHERE deleted=0 AND mtime>=? AND path NOT LIKE ? ORDER BY mtime DESC LIMIT 10", (now - DAY, self.cfg.layout.brain_folder + "%")))
        projects = rows_to_dicts(self.db.query("SELECT name, last_activity_at, document_id FROM projects WHERE status='active' ORDER BY last_activity_at DESC LIMIT 15"))
        recent = self.e.memory.list_memories(since=now - 7 * DAY, limit=10)
        important = self.e.memory.list_memories(limit=10)
        suggestions = self.e.graph.suggestions(limit=8)
        contradictions = self.e.intel.contradictions(limit=6)
        stale = self.e.memory.stale_documents(limit=8)
        L = ["# SERGIO BRAIN", "", f"_Actualizado {time.strftime('%Y-%m-%d %H:%M')}_ · [[Brain Health]] · Reviews en `{self.cfg.layout.reviews_folder}` · Inbox en `{self.cfg.layout.inbox_folder}`", "",
             "## TODAY", "", "### Tasks"] + ([f"- [ ] {t['content'][:120]} — {_link(t['note_title'])}" + (" ⚠" if t["overdue"] else "") for t in tasks[:12]] or ["- (ninguna)"])
        L += ["", "### Meetings"] + ([f"- {m['title']}: {m['content'][:100]}" for m in meetings] or ["- (ninguna hoy)"])
        L += ["", "### Memories"] + ([f"- ({m['memory_type']}) {m['content'][:110]} — {_link(m['note_title'])}" for m in recent[:6] if m.get("note_title")] or ["- (ninguna)"])
        L += ["", "### Activity"] + ([f"- {_link(a['title'])}" for a in activity] or ["- (sin actividad en 24h)"])
        L += ["", "## ACTIVE PROJECTS"] + ([f"- {_link(p['name'])}" + (f" · última actividad {time.strftime('%Y-%m-%d', time.localtime(p['last_activity_at']))}" if p['last_activity_at'] else "") for p in projects] or ["- (sin proyectos detectados; usa `project:` en frontmatter o tags `proyecto/nombre`)"])
        L += ["", "## RECENT MEMORY"] + ([f"- ({m['memory_type']}) {m['content'][:110]} — {_link(m['note_title'])}" for m in recent if m.get("note_title")] or ["- (ninguna)"])
        L += ["", "## IMPORTANT MEMORY"] + ([f"- ({m['memory_type']}, {m['importance']}) {m['content'][:110]} — {_link(m['note_title'])}" for m in important if m.get("note_title")] or ["- (ninguna)"])
        L += ["", "## SUGGESTED CONNECTIONS"] + ([f"- [{s['kind']} · {s['confidence']}] {s['reason']} → " + ", ".join(_link(d['title']) for d in s['documents'][:4]) for s in suggestions] or ["- (ninguna)"])
        L += ["", "## CONTRADICTIONS"] + ([f"- {c['subject']}: «{c['statement_a'][:70]}» ({c['date_a_iso']}, {_link(c['note_a']['title'])}) vs «{c['statement_b'][:70]}» ({c['date_b_iso']}, {_link(c['note_b']['title'])})" for c in contradictions if c["note_a"] and c["note_b"]] or ["- (ninguna detectada)"])
        L += ["", "## STALE KNOWLEDGE"] + ([f"- {_link(s['title'])}: {s['days_since_review']} días sin revisar" for s in stale] or ["- (nada)"])
        L += ["", "## BRAIN HEALTH", "", "Ver [[Brain Health]] (comando: `sergio-brain health`)."]
        L += ["", "## ASK SERGIO BRAIN", "", "Usa `Ctrl+Shift+B` en Obsidian (Omnibar) o `sergio-brain ask \"¿Qué tengo pendiente?\"`."]
        body = "\n".join(L)
        self.e.writer.write_generated(self.cfg.layout.brain_folder, "SERGIO BRAIN", body, {"type": "command-center"}, overwrite_if_ours=True)
        return body
