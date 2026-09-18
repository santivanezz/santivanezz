"""Local Personal Memory API (stdlib HTTP server, JSON, localhost only).

FastAPI was deliberately not used: the plugin only needs a handful of JSON
endpoints and zero extra dependencies keeps installation trivial (DECISIONS.md).
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__


class BrainAPI:
    """Pure functions behind each endpoint (also used by the CLI and tests)."""

    def __init__(self, engine):
        self.e = engine

    def health(self) -> dict[str, Any]:
        return {"ok": True, "version": __version__, "vault": str(self.e.vault.root), "stats": self.e.db.stats(),
                "pending_jobs": self.e.jobs.pending_count(), "embedding": self.e.embedder.name, "llm": self.e.llm.name,
                "llm_available": self.e.llm.available(), "ai_mode": self.e.cfg.ai.mode, "costs": self.e.costs.summary(),
                "last_full_index": self.e.db.kv_get("last_full_index")}

    def search(self, q: str, k: int = 10, mode: str = "hybrid") -> dict[str, Any]:
        res = self.e.search.search(q, k=k, mode=mode)
        return {"query": q, "results": [{k2: v for k2, v in r.items() if k2 != "content"} for r in res]}

    def ask(self, q: str, k: int = 8, use_llm: bool = True) -> dict[str, Any]:
        return self.e.assistant.ask(q, k=k, use_llm=use_llm)

    def related(self, path: str, k: int = 10) -> dict[str, Any]:
        doc = self.e.db.one("SELECT id, title FROM documents WHERE path=?", (path,))
        if not doc:
            return {"path": path, "related": [], "entities": [], "message": "nota no indexada todavía"}
        return {"path": path, "title": doc["title"], "related": self.e.graph.related_documents(doc["id"], k=k),
                "entities": self.e.graph.entities_for_document(doc["id"]),
                "memories": [dict(m) for m in self.e.db.query("SELECT id, memory_type, content, status, confidence, importance, importance_reason FROM memories WHERE document_id=? AND status!='dismissed' ORDER BY importance DESC LIMIT 20", (doc["id"],))]}

    def memory(self, memory_id: int) -> dict[str, Any]:
        m = self.e.db.one("SELECT m.*, d.title AS note_title, d.path FROM memories m LEFT JOIN documents d ON d.id=m.document_id WHERE m.id=?", (memory_id,))
        if not m:
            return {"error": "not found"}
        d = dict(m)
        d["versions"] = [dict(v) for v in self.e.db.query("SELECT * FROM memory_versions WHERE memory_id=? ORDER BY changed_at", (memory_id,))]
        return d

    def memories(self, memory_type: str | None = None, status: str | None = None, project: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"memories": self.e.memory.list_memories(memory_type, status, project, limit=limit)}

    def create_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.e.inbox.capture(payload.get("text", ""), capture_type=payload.get("capture_type", "manual"), title=payload.get("title"),
                                    url=payload.get("url"), source=payload.get("source"), force=bool(payload.get("force")), tags=payload.get("tags"))

    def project(self, name: str) -> dict[str, Any]:
        return self.e.intel.project_memory(name)

    def projects(self) -> dict[str, Any]:
        return {"projects": [dict(p) for p in self.e.db.query("SELECT * FROM projects ORDER BY last_activity_at DESC")]}

    def timeline(self, days: int = 30, project: str | None = None) -> dict[str, Any]:
        return {"timeline": self.e.intel.timeline(since=time.time() - days * 86400, project=project)}

    def tasks(self) -> dict[str, Any]:
        return {"tasks": self.e.memory.open_tasks()}

    def entities(self, q: str | None = None) -> dict[str, Any]:
        if q:
            return self.e.graph.entity_neighbourhood(q)
        return {"entities": [dict(r) for r in self.e.db.query("SELECT id, name, entity_type, mention_count FROM entities ORDER BY mention_count DESC LIMIT 200")]}

    def graph(self) -> dict[str, Any]:
        return self.e.graph.graph_export()

    def suggestions(self, kind: str | None = None) -> dict[str, Any]:
        return {"suggestions": self.e.graph.suggestions(kind=kind)}

    def contradictions(self) -> dict[str, Any]:
        return {"contradictions": self.e.intel.contradictions()}

    def stale(self) -> dict[str, Any]:
        return {"stale": self.e.memory.stale_documents()}

    def why(self, q: str) -> dict[str, Any]:
        return self.e.intel.why_do_i_know(q)

    def changed(self, path: str | None = None, q: str | None = None) -> dict[str, Any]:
        if path:
            doc = self.e.db.one("SELECT id FROM documents WHERE path=?", (path,))
            return self.e.intel.what_changed(doc["id"]) if doc else {"changed": False, "message": "nota no indexada"}
        return self.e.intel.what_changed_query(q or "")

    def recall(self) -> dict[str, Any]:
        items = self.e.intel.active_recall()
        self.e.intel.mark_recalled(items)
        return {"recall": items}

    def briefing(self, write: bool = True) -> dict[str, Any]:
        return {"markdown": self.e.reviews.morning_briefing(write=write)}

    def dashboard(self) -> dict[str, Any]:
        return {"markdown": self.e.reviews.command_center()}

    def brain_health(self, write: bool = False) -> dict[str, Any]:
        h = self.e.reviews.brain_health()
        if write:
            h["markdown"] = self.e.reviews.brain_health_note()
        return h

    def review(self, period: str) -> dict[str, Any]:
        if period == "weekly":
            return {"markdown": self.e.reviews.weekly_review()}
        if period == "monthly":
            return {"markdown": self.e.reviews.monthly_review()}
        return {"markdown": self.e.reviews.daily_memory()}

    def feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        fid = self.e.memory.record_feedback(payload["target_type"], str(payload["target_id"]), payload["verdict"], payload.get("note"))
        return {"ok": True, "feedback_id": fid}

    def notify_change(self, path: str, deleted: bool = False) -> dict[str, Any]:
        """Called by the Obsidian plugin on file events (in addition to the watcher)."""
        if deleted:
            self.e.jobs.enqueue("remove_note", {"path": path})
        else:
            self.e.jobs.enqueue("index_note", {"path": path})
        self.e.jobs.enqueue("analyze", {}, delay=15)
        return {"queued": True}

    def reindex(self, force: bool = False) -> dict[str, Any]:
        return self.e.indexer.index_all(force=force)

    def backup(self, kind: str = "snapshot") -> dict[str, Any]:
        return self.e.backups.incremental() if kind == "incremental" else self.e.backups.snapshot()

    def costs(self) -> dict[str, Any]:
        return self.e.costs.summary()

    def ai_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .ai_chats import AIChatMemory
        mem = AIChatMemory(self.e)
        conv = mem.from_payload(payload)
        if not conv.messages:
            return {"action": "ignored", "reason": "sin mensajes"}
        return mem.upsert(conv)


def make_handler(api: BrainAPI, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SergioBrain/" + __version__

        def log_message(self, fmt, *args):  # quiet; engine log has its own
            api.e.log.debug("http %s", fmt % args)

        def _send(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            origin = self.headers.get("Origin", "")
            if origin.startswith(("app://obsidian.md", "chrome-extension://", "moz-extension://", "http://127.0.0.1", "http://localhost")):
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Brain-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _auth(self) -> bool:
            if not token:
                return True
            return self.headers.get("X-Brain-Token", "") == token

        def do_OPTIONS(self):
            self._send(204, {})

        def do_GET(self):
            if not self._auth():
                return self._send(401, {"error": "unauthorized"})
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                route = u.path.rstrip("/")
                if route == "/health":
                    return self._send(200, api.health())
                if route == "/search":
                    return self._send(200, api.search(q.get("q", ""), int(q.get("k", 10)), q.get("mode", "hybrid")))
                if route == "/related":
                    return self._send(200, api.related(q.get("path", ""), int(q.get("k", 10))))
                if route.startswith("/memory/"):
                    return self._send(200, api.memory(int(route.split("/")[-1])))
                if route == "/memories":
                    return self._send(200, api.memories(q.get("type"), q.get("status"), q.get("project"), int(q.get("limit", 100))))
                if route.startswith("/project/"):
                    return self._send(200, api.project(route.split("/", 2)[2]))
                if route == "/projects":
                    return self._send(200, api.projects())
                if route == "/timeline":
                    return self._send(200, api.timeline(int(q.get("days", 30)), q.get("project")))
                if route == "/tasks":
                    return self._send(200, api.tasks())
                if route == "/entities":
                    return self._send(200, api.entities(q.get("q")))
                if route == "/graph":
                    return self._send(200, api.graph())
                if route == "/suggestions":
                    return self._send(200, api.suggestions(q.get("kind")))
                if route == "/contradictions":
                    return self._send(200, api.contradictions())
                if route == "/stale":
                    return self._send(200, api.stale())
                if route == "/why":
                    return self._send(200, api.why(q.get("q", "")))
                if route == "/changed":
                    return self._send(200, api.changed(q.get("path"), q.get("q")))
                if route == "/recall":
                    return self._send(200, api.recall())
                if route == "/briefing":
                    return self._send(200, api.briefing(q.get("write", "1") == "1"))
                if route == "/dashboard":
                    return self._send(200, api.dashboard())
                if route == "/brain-health":
                    return self._send(200, api.brain_health(q.get("write", "0") == "1"))
                if route == "/review":
                    return self._send(200, api.review(q.get("period", "daily")))
                if route == "/costs":
                    return self._send(200, api.costs())
                if route == "/inbox":
                    return self._send(200, {"captures": api.e.inbox.list(q.get("status", "inbox"))})
                return self._send(404, {"error": "unknown route", "route": route})
            except Exception as exc:  # noqa: BLE001
                api.e.log.exception("GET %s failed", self.path)
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_POST(self):
            if not self._auth():
                return self._send(401, {"error": "unauthorized"})
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            route = urlparse(self.path).path.rstrip("/")
            try:
                if route == "/ask":
                    return self._send(200, api.ask(payload.get("q", ""), int(payload.get("k", 8)), bool(payload.get("use_llm", True))))
                if route == "/memory":
                    return self._send(200, api.create_memory(payload))
                if route == "/capture":
                    return self._send(200, api.create_memory(payload))
                if route == "/feedback":
                    return self._send(200, api.feedback(payload))
                if route == "/notify":
                    return self._send(200, api.notify_change(payload.get("path", ""), bool(payload.get("deleted"))))
                if route == "/reindex":
                    return self._send(200, api.reindex(bool(payload.get("force"))))
                if route == "/backup":
                    return self._send(200, api.backup(payload.get("kind", "snapshot")))
                if route == "/consolidate":
                    return self._send(200, api.e.reviews.daily_consolidation())
                if route == "/ai-chat":
                    return self._send(200, api.ai_chat(payload))
                if route == "/ai-memory":
                    from .ai_chats import AIChatMemory
                    return self._send(200, AIChatMemory(api.e).import_memory(payload.get("provider", "other"), payload.get("text", "")))
                if route == "/import":
                    from .documents import DocumentImporter
                    return self._send(200, DocumentImporter(api.e).import_file(Path(payload["path"]), summarize=bool(payload.get("summarize", True))))
                return self._send(404, {"error": "unknown route", "route": route})
            except Exception as exc:  # noqa: BLE001
                api.e.log.exception("POST %s failed", self.path)
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


class BrainServer:
    def __init__(self, engine, host: str | None = None, port: int | None = None):
        self.e = engine
        self.api = BrainAPI(engine)
        self.host = host or engine.cfg.server.host
        self.port = port or engine.cfg.server.port
        self.httpd = ThreadingHTTPServer((self.host, self.port), make_handler(self.api, engine.cfg.server.token))
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="brain-http", daemon=True)
        self._thread.start()
        self.e.log.info("API listening on http://%s:%s", self.host, self.port)

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class Scheduler:
    """Tiny in-process scheduler: daily consolidation, morning briefing, weekly/monthly reviews, incremental backups."""

    def __init__(self, engine, briefing_hour: int = 7, consolidation_hour: int = 22):
        self.e = engine
        self.briefing_hour = briefing_hour
        self.consolidation_hour = consolidation_hour
        self._stop = threading.Event()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            key_day = now.strftime("%Y-%m-%d")
            try:
                if now.hour >= self.briefing_hour and self.e.db.kv_get("last_briefing") != key_day:
                    self.e.reviews.morning_briefing()
                    self.e.reviews.command_center()
                    self.e.db.kv_set("last_briefing", key_day)
                if now.hour >= self.consolidation_hour and self.e.db.kv_get("last_consolidation") != key_day:
                    self.e.reviews.daily_consolidation()
                    self.e.backups.incremental()
                    self.e.db.kv_set("last_consolidation", key_day)
                    if now.weekday() == 6:
                        self.e.reviews.weekly_review()
                    if now.day == 1 or (now.month != datetime.strptime(self.e.db.kv_get("last_monthly", "1970-01-01"), "%Y-%m-%d").month and now.day <= 2):
                        self.e.reviews.monthly_review()
                        self.e.db.kv_set("last_monthly", key_day)
                if self.e.db.kv_get("last_health_day") != key_day and now.hour >= self.briefing_hour:
                    self.e.reviews.brain_health_note()
                    self.e.db.kv_set("last_health_day", key_day)
            except Exception as exc:  # noqa: BLE001
                self.e.log.exception("scheduler task failed: %s", exc)
            self._stop.wait(300)

    def start(self) -> None:
        threading.Thread(target=self._loop, name="brain-scheduler", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
