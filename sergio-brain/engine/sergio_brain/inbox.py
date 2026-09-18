"""Captures (clipboard, hotkey, browser, manual) -> classification -> Inbox note
with provenance. Nothing is saved silently as garbage: TRIVIAL/TEMPORARY captures
are recorded in the DB but not written to the vault unless forced."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

from .extractors import extract_tasks, keywords
from .security import redact

URL_RE = re.compile(r"https?://\S+")


def classify_capture(text: str, url: str | None = None) -> tuple[str, str]:
    t = text.strip()
    if len(t) < 12 and not url:
        return "TRIVIAL", "texto demasiado corto"
    if re.fullmatch(r"[\d\s\.,\-+()]+", t):
        return "TRIVIAL", "solo números"
    if re.fullmatch(r"\S+", t) and not url and not URL_RE.match(t):
        return "TEMPORARY", "un solo token (probablemente un identificador temporal)"
    if extract_tasks(t):
        return "TASK", "contiene lenguaje de tarea"
    if url or URL_RE.search(t):
        return "REFERENCE", "contiene una URL"
    if len(t) > 400 or t.count("\n") > 5:
        return "KNOWLEDGE", "texto largo / estructurado"
    if re.search(r"(?i)\b(es|son|sirve para|se usa|significa|definici[óo]n|is|means|used for)\b", t):
        return "KNOWLEDGE", "parece una definición o explicación"
    return "USEFUL", "texto breve con contenido"


def read_clipboard() -> str:
    try:
        import pyperclip  # optional
        return pyperclip.paste() or ""
    except Exception:  # noqa: BLE001
        pass
    if sys.platform.startswith("win"):
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True, timeout=10)
        return out.stdout
    for cmd in (["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"], ["pbpaste"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                return out.stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
    return ""


class Inbox:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db
        self.cfg = engine.cfg

    def capture(self, text: str, capture_type: str = "manual", title: str | None = None, url: str | None = None,
                source: dict[str, Any] | None = None, force: bool = False, tags: list[str] | None = None) -> dict[str, Any]:
        raw = text or ""
        if not raw.strip() and not url:
            return {"saved": False, "classification": "TRIVIAL", "reason": "vacío"}
        redacted, hits = redact(raw)
        classification, reason = classify_capture(redacted, url)
        now = time.time()
        title = title or self._auto_title(redacted, url)
        existing = self.e.memory.find_existing_for(redacted, title) if classification in ("KNOWLEDGE", "USEFUL", "REFERENCE") else []
        meta = {"reason": reason, "secret_hits": len(hits), "source": source or {}, "existing_candidates": existing[:3]}
        cur = self.db.execute("INSERT INTO captures(capture_type, classification, raw_text, title, url, status, created_at, metadata) VALUES(?,?,?,?,?,?,?,?)",
                              (capture_type, classification, redacted, title, url, "inbox", now, json.dumps(meta, ensure_ascii=False)))
        cid = int(cur.lastrowid)
        result: dict[str, Any] = {"capture_id": cid, "classification": classification, "reason": reason, "title": title,
                                  "secrets_redacted": len(hits), "existing_candidates": existing[:3], "saved": False}
        if classification in ("TRIVIAL", "TEMPORARY") and not force:
            self.db.execute("UPDATE captures SET status='discarded' WHERE id=?", (cid,))
            result["message"] = f"No guardado ({classification}: {reason}). Usa --force para guardarlo igualmente."
            return result
        fm: dict[str, Any] = {"type": "capture", "capture_type": capture_type, "classification": classification,
                              "source_type": (source or {}).get("source_type") or capture_type, "captured_at": datetime.now().isoformat(timespec="seconds"),
                              "tags": ["inbox", classification.lower()] + (tags or [])}
        if url:
            fm["source_url"] = url
        for k in ("source_path", "source_note", "source_date", "capture_method"):
            if source and source.get(k):
                fm[k] = source[k]
        body_lines = [f"# {title}", "", redacted.strip()]
        if url:
            body_lines += ["", f"Origen: <{url}>"]
        if classification == "TASK":
            body_lines += ["", "## Tareas detectadas"] + [f"- [ ] {t.text}" for t in extract_tasks(redacted)[:10]]
        if existing:
            body_lines += ["", "## Posiblemente relacionado (¿actualizar en lugar de crear?)"] + [f"- [[{x['title']}]] ({x['suggestion']}, {x['score']})" for x in existing[:3]]
        kws = keywords(redacted, 8)
        if kws:
            body_lines += ["", f"Keywords: {', '.join(kws)}"]
        path = self.e.writer.write_generated(self.cfg.layout.inbox_folder, f"{datetime.now().strftime('%Y-%m-%d %H%M')} {title}", "\n".join(body_lines), fm)
        rel = path.relative_to(self.e.vault.root).as_posix()
        self.db.execute("UPDATE captures SET note_path=? WHERE id=?", (rel, cid))
        self.db.execute("INSERT INTO sources(source_type, source_path, source_url, source_note, source_date, capture_method, processing_date, metadata) VALUES(?,?,?,?,?,?,?,?)",
                        ((source or {}).get("source_type") or capture_type, (source or {}).get("source_path"), url, rel,
                         (source or {}).get("source_date") or datetime.now().strftime("%Y-%m-%d"), capture_type, now, json.dumps(source or {}, ensure_ascii=False)))
        try:
            self.e.indexer.index_path(rel)
            doc = self.db.one("SELECT id FROM documents WHERE path=?", (rel,))
            if doc:
                self.db.execute("UPDATE sources SET document_id=? WHERE source_note=? AND document_id IS NULL", (doc["id"], rel))
        except Exception as exc:  # noqa: BLE001 - the capture is already on disk; indexing can retry
            self.e.log.error("index after capture failed: %s", exc)
            self.e.jobs.enqueue("index_note", {"path": rel}, delay=5)
        self.e.events.emit("CLIPBOARD_CAPTURED" if capture_type == "clipboard" else "WEB_CAPTURED" if capture_type == "web" else "FILE_IMPORTED" if capture_type == "file" else "NOTE_CREATED",
                           {"capture_id": cid, "path": rel})
        result.update({"saved": True, "path": rel, "message": f"Guardado en Inbox como {classification}."})
        return result

    def capture_clipboard(self, force: bool = False) -> dict[str, Any]:
        text = read_clipboard()
        return self.capture(text, capture_type="clipboard", force=force, source={"source_type": "clipboard", "capture_method": "hotkey"})

    @staticmethod
    def _auto_title(text: str, url: str | None) -> str:
        first = next((l.strip(" #-*>") for l in text.splitlines() if l.strip()), "")
        if first and len(first) > 6:
            first = re.split(r"[.!?;:](?:\s|$)", first)[0]
            return first[:60].rstrip(" ,")
        if url:
            return re.sub(r"^https?://(www\.)?", "", url)[:60]
        return "Captura"

    def list(self, status: str = "inbox", limit: int = 50) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT id, capture_type, classification, title, url, note_path, status, created_at FROM captures WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))]
