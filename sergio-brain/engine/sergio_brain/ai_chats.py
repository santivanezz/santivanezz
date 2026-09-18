"""AI chat memory: import conversations (and "memory") from ChatGPT, Claude and
Gemini exports, or receive them live from the browser extension, and write them
into the vault as one note per conversation (upserted by conversation id).

Supported export formats
  * ChatGPT  : conversations.json (Settings > Data controls > Export data)
  * Claude   : conversations.json (Settings > Privacy > Export data)
  * Gemini   : Google Takeout > "My Activity" > Gemini Apps > MyActivity.json
  * memory   : any .txt/.md you paste from "what do you remember about me?"
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .security import redact
from .writer import safe_filename

PROVIDER_NAMES = {"chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini", "other": "AI"}


@dataclass
class Message:
    role: str            # user | assistant | system
    text: str
    ts: float | None = None


@dataclass
class Conversation:
    provider: str
    chat_id: str
    title: str
    messages: list[Message] = field(default_factory=list)
    created: float | None = None
    updated: float | None = None
    url: str | None = None

    @property
    def date(self) -> str:
        ts = self.created or self.updated or time.time()
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ parsers
def _ts(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.replace("Z", "+0000") if fmt.endswith("%z") else s, fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_chatgpt(data: Any) -> list[Conversation]:
    out: list[Conversation] = []
    for conv in data if isinstance(data, list) else [data]:
        mapping = conv.get("mapping") or {}
        chain: list[dict[str, Any]] = []
        node_id = conv.get("current_node")
        if node_id and node_id in mapping:
            while node_id:
                node = mapping.get(node_id) or {}
                if node.get("message"):
                    chain.append(node["message"])
                node_id = node.get("parent")
            chain.reverse()
        else:
            chain = [n["message"] for n in mapping.values() if n.get("message")]
            chain.sort(key=lambda m: m.get("create_time") or 0)
        msgs: list[Message] = []
        for m in chain:
            role = (m.get("author") or {}).get("role", "assistant")
            if role in ("system", "tool"):
                continue
            content = m.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if parts:
                text = "\n".join(p if isinstance(p, str) else json.dumps(p, ensure_ascii=False) for p in parts)
            else:
                text = content.get("text", "") if isinstance(content, dict) else str(content)
            if text.strip():
                msgs.append(Message(role, text.strip(), m.get("create_time")))
        if msgs:
            out.append(Conversation("chatgpt", str(conv.get("conversation_id") or conv.get("id") or hashlib.sha1(conv.get("title", "").encode()).hexdigest()),
                                    conv.get("title") or "Sin título", msgs, _ts(conv.get("create_time")), _ts(conv.get("update_time")),
                                    f"https://chatgpt.com/c/{conv.get('conversation_id') or conv.get('id')}" if conv.get("conversation_id") or conv.get("id") else None))
    return out


def parse_claude(data: Any) -> list[Conversation]:
    out: list[Conversation] = []
    for conv in data if isinstance(data, list) else [data]:
        msgs: list[Message] = []
        for m in conv.get("chat_messages") or []:
            role = "user" if m.get("sender") == "human" else "assistant"
            text = m.get("text") or ""
            if not text and isinstance(m.get("content"), list):
                text = "\n".join(c.get("text", "") for c in m["content"] if isinstance(c, dict) and c.get("type") == "text")
            if text.strip():
                msgs.append(Message(role, text.strip(), _ts(m.get("created_at"))))
        if msgs:
            cid = str(conv.get("uuid") or hashlib.sha1((conv.get("name") or "").encode()).hexdigest())
            out.append(Conversation("claude", cid, conv.get("name") or "Sin título", msgs, _ts(conv.get("created_at")), _ts(conv.get("updated_at")),
                                    f"https://claude.ai/chat/{cid}" if conv.get("uuid") else None))
    return out


def parse_gemini_takeout(data: Any) -> list[Conversation]:
    """Takeout MyActivity.json: one prompt per item; responses are sometimes absent. Grouped per day."""
    by_day: dict[str, Conversation] = {}
    for item in data if isinstance(data, list) else [data]:
        if "Gemini" not in str(item.get("header", "")) and "Bard" not in str(item.get("header", "")):
            continue
        title = html.unescape(str(item.get("title", "")))
        prompt = re.sub(r"^(Prompted|Preguntaste|Consultaste)\s*", "", title).strip()
        ts = _ts(item.get("time"))
        day = datetime.fromtimestamp(ts or time.time()).strftime("%Y-%m-%d")
        conv = by_day.setdefault(day, Conversation("gemini", f"gemini-{day}", f"Gemini {day}", [], ts, ts, "https://gemini.google.com/app"))
        if prompt:
            conv.messages.append(Message("user", prompt, ts))
        for key in ("subtitles", "details"):
            for sub in item.get(key) or []:
                name = sub.get("name") if isinstance(sub, dict) else str(sub)
                if name and len(name) > 20:
                    conv.messages.append(Message("assistant", html.unescape(name), ts))
        conv.updated = max(conv.updated or 0, ts or 0)
    return [c for c in by_day.values() if c.messages]


def parse_export(path: Path, provider: str = "auto") -> list[Conversation]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".txt", ".md"):
        return [Conversation(provider if provider != "auto" else "other", hashlib.sha1(raw.encode()).hexdigest()[:12], path.stem,
                             [Message("assistant", raw.strip())], path.stat().st_mtime, path.stat().st_mtime)]
    data = json.loads(raw)
    sample = data[0] if isinstance(data, list) and data else data
    if provider == "auto":
        if isinstance(sample, dict) and "mapping" in sample:
            provider = "chatgpt"
        elif isinstance(sample, dict) and "chat_messages" in sample:
            provider = "claude"
        elif isinstance(sample, dict) and "header" in sample and "title" in sample:
            provider = "gemini"
        else:
            raise RuntimeError("formato no reconocido; usa --provider chatgpt|claude|gemini")
    return {"chatgpt": parse_chatgpt, "claude": parse_claude, "gemini": parse_gemini_takeout}[provider](data)


# ------------------------------------------------------------------ writer
class AIChatMemory:
    FOLDER = "SERGIO BRAIN/AI Chats"
    MEMORY_FOLDER = "SERGIO BRAIN/AI Memory"

    def __init__(self, engine):
        self.e = engine
        self.db = engine.db

    def _existing_path(self, provider: str, chat_id: str) -> str | None:
        return self.db.kv_get(f"ai_chat:{provider}:{chat_id}")

    def render(self, conv: Conversation) -> tuple[str, dict[str, Any], int]:
        pname = PROVIDER_NAMES.get(conv.provider, conv.provider.title())
        lines = [f"# {conv.title}", "", f"Conversación con **{pname}** · {conv.date}" + (f" · [abrir]({conv.url})" if conv.url else ""), ""]
        secrets = 0
        for m in conv.messages:
            text, hits = redact(m.text)
            secrets += len(hits)
            who = "**Yo**" if m.role == "user" else f"**{pname}**"
            stamp = f" _{datetime.fromtimestamp(m.ts).strftime('%H:%M')}_" if m.ts else ""
            lines += [f"## {who}{stamp}", "", text, ""]
        fm = {"type": "ai-chat", "provider": conv.provider, "ai_chat_id": conv.chat_id, "chat_title": conv.title, "date": conv.date,
              "source_type": "ai_chat", "source_url": conv.url, "messages": len(conv.messages), "tags": ["ai-chat", conv.provider],
              "privacy": "PERSONAL"}
        return "\n".join(lines), fm, secrets

    def upsert(self, conv: Conversation) -> dict[str, Any]:
        body, fm, secrets = self.render(conv)
        folder = f"{self.FOLDER}/{PROVIDER_NAMES.get(conv.provider, conv.provider.title())}"
        existing = self._existing_path(conv.provider, conv.chat_id)
        vault = self.e.vault.root
        if existing and (vault / existing).exists() and self.e.writer.is_ours(vault / existing):
            path = vault / existing
            fm["updated"] = datetime.now().isoformat(timespec="seconds")
            from .writer import frontmatter_block
            meta = {"sergio_brain": "generated", "generated_at": datetime.now().isoformat(timespec="seconds"), **fm}
            new_text = frontmatter_block(meta) + "\n" + body.rstrip() + "\n"
            old_text = path.read_text(encoding="utf-8", errors="replace")
            strip_fm = lambda t: t.split("\n---\n", 1)[1] if t.startswith("---") and "\n---\n" in t else t  # noqa: E731
            changed = strip_fm(old_text).strip() != strip_fm(new_text).strip()
            if changed:
                path.write_text(new_text, encoding="utf-8")
            action = "updated" if changed else "unchanged"
        else:
            title = f"{conv.date} {safe_filename(conv.title)[:70]}"
            path = self.e.writer.write_generated(folder, title, body, fm)
            action = "created"
        rel = path.relative_to(vault).as_posix()
        self.db.kv_set(f"ai_chat:{conv.provider}:{conv.chat_id}", rel)
        if action != "unchanged":
            try:
                self.e.indexer.index_path(rel)
            except Exception as exc:  # noqa: BLE001
                self.e.log.error("index ai chat failed: %s", exc)
                self.e.jobs.enqueue("index_note", {"path": rel}, delay=5)
            self.db.execute("INSERT INTO sources(source_type, source_url, source_note, source_date, capture_method, processing_date, metadata) VALUES(?,?,?,?,?,?,?)",
                            ("ai_chat", conv.url, rel, conv.date, f"ai_chat:{conv.provider}", time.time(), json.dumps({"provider": conv.provider, "chat_id": conv.chat_id})))
            self.e.events.emit("WEB_CAPTURED", {"kind": "ai_chat", "provider": conv.provider, "path": rel})
        return {"action": action, "path": rel, "messages": len(conv.messages), "secrets_redacted": secrets}

    def import_file(self, path: Path, provider: str = "auto") -> dict[str, Any]:
        convs = parse_export(Path(path), provider)
        stats = {"conversations": len(convs), "created": 0, "updated": 0, "unchanged": 0, "secrets_redacted": 0}
        for c in convs:
            r = self.upsert(c)
            stats[r["action"]] += 1
            stats["secrets_redacted"] += r["secrets_redacted"]
        self.e.jobs.enqueue("analyze", {}, delay=5)
        return stats

    def import_memory(self, provider: str, text: str) -> dict[str, Any]:
        """The provider's 'memory about you' (paste of "what do you remember about me?")."""
        redacted, hits = redact(text)
        pname = PROVIDER_NAMES.get(provider, provider.title())
        body = [f"# Memoria de {pname} sobre mí", "", f"Importado el {datetime.now().strftime('%Y-%m-%d %H:%M')}. Fuente: lo que {pname} dice recordar sobre mí (EXTERNAL_SOURCE).", "", redacted.strip()]
        fm = {"type": "ai-memory", "provider": provider, "source_type": "ai_memory", "tags": ["ai-memory", provider], "privacy": "PERSONAL"}
        path = self.e.writer.write_generated(self.MEMORY_FOLDER, f"{pname} Memory", "\n".join(body), fm, overwrite_if_ours=True)
        rel = path.relative_to(self.e.vault.root).as_posix()
        self.e.indexer.index_path(rel, force=True)
        return {"path": rel, "secrets_redacted": len(hits)}

    def from_payload(self, payload: dict[str, Any]) -> Conversation:
        """Live capture from the browser extension: {provider, id, url, title, messages:[{role,text}]}"""
        provider = (payload.get("provider") or "other").lower()
        msgs = [Message("user" if m.get("role") == "user" else "assistant", str(m.get("text", "")).strip()) for m in payload.get("messages") or [] if str(m.get("text", "")).strip()]
        chat_id = str(payload.get("id") or hashlib.sha1((payload.get("url") or payload.get("title") or "").encode()).hexdigest()[:16])
        return Conversation(provider, chat_id, payload.get("title") or "Sin título", msgs, time.time(), time.time(), payload.get("url"))
