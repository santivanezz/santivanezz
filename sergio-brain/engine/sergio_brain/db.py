"""SQLite schema and connection management.

Design goals: one file, versioned migrations, never destructive. Every
migration only ADDS tables/columns. Dropping data requires an explicit backup.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

-- One row per vault file (markdown note or imported document)
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,          -- relative to vault
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'note',  -- note | daily | meeting | import | capture
    content_hash TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    indexed_at REAL,
    last_accessed_at REAL,
    access_count INTEGER NOT NULL DEFAULT 0,
    privacy TEXT NOT NULL DEFAULT 'PERSONAL',
    context TEXT,                        -- WORK | STUDY | PERSONAL | FINANCE | PROJECT | LEARNING
    frontmatter TEXT,                    -- JSON
    tags TEXT,                           -- JSON list
    links TEXT,                          -- JSON list of outgoing wikilink targets
    word_count INTEGER NOT NULL DEFAULT 0,
    temporal_state TEXT NOT NULL DEFAULT 'CURRENT',  -- CURRENT|HISTORICAL|FUTURE|STALE|SUPERSEDED|ARCHIVED
    deleted INTEGER NOT NULL DEFAULT 0,  -- soft delete: file vanished from disk; never hard-deleted
    secret_hits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at);
CREATE INDEX IF NOT EXISTS idx_documents_deleted ON documents(deleted);

-- Every version of a document we have seen (content snapshot hash + text for "what changed")
CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    captured_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docver_doc ON document_versions(document_id, captured_at);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    heading TEXT,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content, heading, title, path UNINDEXED, chunk_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at REAL NOT NULL
);

-- Atomic memories extracted from notes (a note can produce 0..n memories)
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    memory_type TEXT NOT NULL,          -- RAW|EPISODIC|SEMANTIC|PROJECT|TASK|DECISION|LEARNING|LONG_TERM|ARCHIVED
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    document_id INTEGER REFERENCES documents(id),
    chunk_id INTEGER REFERENCES chunks(id),
    fingerprint TEXT NOT NULL,          -- stable hash used for incremental updates
    confidence TEXT NOT NULL DEFAULT 'AI_INFERENCE', -- FACT|USER_ASSERTION|EXTERNAL_SOURCE|AI_INFERENCE|POSSIBLE|UNKNOWN
    status TEXT NOT NULL DEFAULT 'open', -- open|done|superseded|archived|dismissed
    temporal_state TEXT NOT NULL DEFAULT 'CURRENT',
    event_date TEXT,                    -- ISO date this memory refers to (WHEN)
    due_date TEXT,
    priority TEXT,
    project TEXT,
    context TEXT,
    people TEXT,                        -- JSON list
    metadata TEXT,                      -- JSON
    importance REAL NOT NULL DEFAULT 0,
    importance_reason TEXT,
    user_importance INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_reviewed_at REAL,
    UNIQUE(fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type, status);
CREATE INDEX IF NOT EXISTS idx_memories_doc ON memories(document_id);

CREATE TABLE IF NOT EXISTS memory_versions (
    id INTEGER PRIMARY KEY,
    memory_id INTEGER NOT NULL REFERENCES memories(id),
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    changed_at REAL NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL,
    entity_type TEXT NOT NULL,          -- PERSON|ORGANIZATION|PROJECT|CONCEPT|TECHNOLOGY|COURSE|SUBJECT|BOOK|DOCUMENT|PROCESS|TASK|DECISION|EVENT|TOPIC|NOTE
    document_id INTEGER REFERENCES documents(id),  -- the note that defines this entity, if any
    mention_count INTEGER NOT NULL DEFAULT 0,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    metadata TEXT,
    UNIQUE(normalized, entity_type)
);
CREATE INDEX IF NOT EXISTS idx_entities_norm ON entities(normalized);

CREATE TABLE IF NOT EXISTS entity_mentions (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (entity_id, document_id)
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,          -- document | entity | memory
    source_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    relation TEXT NOT NULL,             -- RELATED_TO|PART_OF|DEPENDS_ON|USED_IN|CREATED_BY|DISCUSSED_IN|LEARNED_FROM|MENTIONED_IN|SUPERSEDES|CONTRADICTS|CONNECTED_TO|RELEVANT_TO|CAUSED_BY|LINKS_TO
    weight REAL NOT NULL DEFAULT 1.0,
    confidence TEXT NOT NULL DEFAULT 'AI_INFERENCE',
    origin TEXT NOT NULL DEFAULT 'auto', -- auto | user | wikilink
    created_at REAL NOT NULL,
    UNIQUE(source_type, source_id, target_type, target_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_relations_src ON relations(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_relations_tgt ON relations(target_type, target_id);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    normalized TEXT NOT NULL UNIQUE,
    document_id INTEGER REFERENCES documents(id),
    status TEXT NOT NULL DEFAULT 'active',
    objective TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_activity_at REAL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at REAL NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id INTEGER PRIMARY KEY,
    job_type TEXT NOT NULL,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'pending', -- pending|running|done|failed
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    run_after REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON processing_jobs(status, run_after);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    source_type TEXT NOT NULL,          -- note | web | clipboard | file | meeting | manual | pdf | docx ...
    source_path TEXT,
    source_url TEXT,
    source_note TEXT,
    source_date TEXT,
    capture_method TEXT,
    processing_date REAL NOT NULL,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY,
    capture_type TEXT NOT NULL,         -- clipboard | web | manual | file | hotkey
    classification TEXT,                -- TRIVIAL|TEMPORARY|USEFUL|KNOWLEDGE|TASK|REFERENCE
    raw_text TEXT NOT NULL,             -- redacted before storage
    title TEXT,
    url TEXT,
    note_path TEXT,                     -- where it was written in the vault (Inbox)
    status TEXT NOT NULL DEFAULT 'inbox', -- inbox | processed | discarded
    created_at REAL NOT NULL,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS contradictions (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL,
    statement_a TEXT NOT NULL,
    document_a INTEGER REFERENCES documents(id),
    date_a REAL,
    statement_b TEXT NOT NULL,
    document_b INTEGER REFERENCES documents(id),
    date_b REAL,
    kind TEXT NOT NULL DEFAULT 'POSSIBLE_CONTRADICTION', -- POSSIBLE_CONTRADICTION | SUPERSEDED_INFORMATION
    confidence REAL NOT NULL DEFAULT 0.5,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'open', -- open | resolved | dismissed
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS suggested_links (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,                 -- LINK | CONSOLIDATE | SERENDIPITY | DUPLICATE
    document_ids TEXT NOT NULL,         -- JSON list
    reason TEXT NOT NULL,
    shared_concepts TEXT,               -- JSON list
    confidence REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', -- open | accepted | rejected
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL,          -- memory | suggestion | contradiction | answer | document
    target_id TEXT NOT NULL,
    verdict TEXT NOT NULL,              -- USEFUL|NOT_USEFUL|WRONG|DUPLICATE|IMPORTANT|IGNORE
    note TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- llm | embedding | rerank
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS recall_log (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    target_key TEXT NOT NULL,
    shown_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    """Thread-safe wrapper around one SQLite file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self.migrate()

    # --- connections ---
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    def migrate(self) -> None:
        with self._write_lock:
            c = self.conn()
            c.executescript(SCHEMA)
            row = c.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            current = row["v"] or 0
            if current < SCHEMA_VERSION:
                c.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                          (SCHEMA_VERSION, time.time()))
            c.commit()

    # --- helpers ---
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._write_lock:
            cur = self.conn().execute(sql, tuple(params))
            self.conn().commit()
            return cur

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._write_lock:
            self.conn().executemany(sql, [tuple(r) for r in rows])
            self.conn().commit()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn().execute(sql, tuple(params)).fetchone()

    def transaction(self):
        return _Transaction(self)

    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row and row["value"] is not None else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value)))

    def log_event(self, event_type: str, payload: dict[str, Any] | None = None) -> int:
        cur = self.execute("INSERT INTO events(event_type, payload, created_at) VALUES(?,?,?)",
                           (event_type, json.dumps(payload or {}, ensure_ascii=False), time.time()))
        return int(cur.lastrowid)

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("documents", "chunks", "embeddings", "memories", "entities", "relations",
                      "contradictions", "suggested_links", "captures", "processing_jobs", "ai_calls"):
            out[table] = int(self.one(f"SELECT COUNT(*) AS n FROM {table}")["n"])
        out["documents_active"] = int(self.one("SELECT COUNT(*) AS n FROM documents WHERE deleted=0")["n"])
        return out


class _Transaction:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db._write_lock.acquire()
        c = self.db.conn()
        c.execute("BEGIN")
        return c

    def __exit__(self, exc_type, exc, tb) -> None:
        c = self.db.conn()
        try:
            if exc_type is None:
                c.commit()
            else:
                c.rollback()
        finally:
            self.db._write_lock.release()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
