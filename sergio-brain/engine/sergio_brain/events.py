"""Event bus + persistent job queue (retry, debounce)."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from typing import Any, Callable

from .db import Database

EVENT_TYPES = (
    "NOTE_CREATED", "NOTE_UPDATED", "NOTE_DELETED", "FILE_IMPORTED", "CLIPBOARD_CAPTURED", "WEB_CAPTURED",
    "ENTITY_DISCOVERED", "EMBEDDING_CREATED", "RELATION_DISCOVERED", "MEMORY_CONSOLIDATED", "TASK_DISCOVERED",
    "DECISION_DISCOVERED", "LEARNING_DISCOVERED", "CONTRADICTION_DETECTED", "SUGGESTION_CREATED", "BACKUP_CREATED",
)


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self._subs: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs[event_type].append(handler)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self.db.log_event(event_type, payload)
        with self._lock:
            handlers = list(self._subs.get(event_type, [])) + list(self._subs.get("*", []))
        for h in handlers:
            try:
                h({"type": event_type, **payload})
            except Exception:  # noqa: BLE001 - a bad subscriber must not break ingestion
                pass


class JobQueue:
    """Persistent job queue in SQLite. Jobs survive crashes; failures retry with backoff."""

    def __init__(self, db: Database):
        self.db = db
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {}

    def register(self, job_type: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._handlers[job_type] = handler

    def enqueue(self, job_type: str, payload: dict[str, Any] | None = None, delay: float = 0.0, dedupe: bool = True) -> int:
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        if dedupe:
            row = self.db.one("SELECT id FROM processing_jobs WHERE job_type=? AND payload=? AND status='pending'",
                              (job_type, payload_json))
            if row:
                self.db.execute("UPDATE processing_jobs SET run_after=?, updated_at=? WHERE id=?",
                                (time.time() + delay, time.time(), row["id"]))
                return int(row["id"])
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO processing_jobs(job_type, payload, status, created_at, updated_at, run_after) VALUES(?,?,'pending',?,?,?)",
            (job_type, payload_json, now, now, now + delay))
        return int(cur.lastrowid)

    def pending_count(self) -> int:
        return int(self.db.one("SELECT COUNT(*) AS n FROM processing_jobs WHERE status IN ('pending','running')")["n"])

    def run_once(self, limit: int = 50) -> int:
        """Run due jobs. Returns number processed."""
        now = time.time()
        rows = self.db.query("SELECT * FROM processing_jobs WHERE status='pending' AND run_after<=? ORDER BY id LIMIT ?",
                             (now, limit))
        n = 0
        for row in rows:
            handler = self._handlers.get(row["job_type"])
            self.db.execute("UPDATE processing_jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=?",
                            (time.time(), row["id"]))
            if handler is None:
                self.db.execute("UPDATE processing_jobs SET status='failed', last_error='no handler', updated_at=? WHERE id=?",
                                (time.time(), row["id"]))
                continue
            try:
                handler(json.loads(row["payload"] or "{}"))
                self.db.execute("UPDATE processing_jobs SET status='done', updated_at=? WHERE id=?", (time.time(), row["id"]))
            except Exception as exc:  # noqa: BLE001
                attempts = row["attempts"] + 1
                if attempts >= row["max_attempts"]:
                    status = "failed"
                    run_after = now
                else:
                    status = "pending"
                    run_after = time.time() + min(300, 5 * (2 ** attempts))
                self.db.execute("UPDATE processing_jobs SET status=?, last_error=?, run_after=?, updated_at=? WHERE id=?",
                                (status, f"{type(exc).__name__}: {exc}"[:500], run_after, time.time(), row["id"]))
            n += 1
        return n

    def drain(self, max_rounds: int = 20) -> int:
        total = 0
        for _ in range(max_rounds):
            n = self.run_once()
            total += n
            if n == 0:
                break
        return total


class Debouncer:
    """Coalesce bursts of events per key (e.g. a note saved 10 times in 2 seconds)."""

    def __init__(self, seconds: float, action: Callable[[str], None]):
        self.seconds = seconds
        self.action = action
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def trigger(self, key: str) -> None:
        with self._lock:
            t = self._timers.pop(key, None)
            if t:
                t.cancel()
            timer = threading.Timer(self.seconds, self._fire, args=(key,))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key: str) -> None:
        with self._lock:
            self._timers.pop(key, None)
        self.action(key)

    def flush(self) -> None:
        with self._lock:
            timers = list(self._timers.items())
            self._timers.clear()
        for key, t in timers:
            t.cancel()
            self.action(key)
