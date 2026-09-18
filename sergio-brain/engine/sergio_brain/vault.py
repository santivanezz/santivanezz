"""Reading the Obsidian vault: notes, frontmatter, tags, wikilinks, hashing.

The vault is read-only for this module. Writing is done only by
``writer.py`` under explicit rules (never overwrite user notes).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import Config

WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)")
TAG_RE = re.compile(r"(?<![\w/#])#([A-Za-z0-9_\-/áéíóúñÁÉÍÓÚÑ]+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
DATE_IN_NAME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass
class Note:
    path: str                      # relative path with forward slashes
    abs_path: Path
    title: str
    raw: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    mtime: float = 0.0
    ctime: float = 0.0
    size: int = 0
    content_hash: str = ""

    @property
    def word_count(self) -> int:
        return len(self.body.split())

    @property
    def is_daily(self) -> bool:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.title))

    @property
    def note_date(self) -> str | None:
        """Best-effort date for the note (frontmatter date, date in name, else None)."""
        for key in ("date", "fecha", "created", "day"):
            v = self.frontmatter.get(key)
            if v:
                m = DATE_IN_NAME_RE.search(str(v))
                if m:
                    return m.group(0)
        m = DATE_IN_NAME_RE.search(self.title) or DATE_IN_NAME_RE.search(self.path)
        return m.group(0) if m else None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ---------- frontmatter (small YAML subset; enough for Obsidian properties) ----------
def _parse_scalar(v: str) -> Any:
    v = v.strip()
    if v == "" or v.lower() in ("null", "~"):
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in re.split(r",(?=(?:[^\"']*[\"'][^\"']*[\"'])*[^\"']*$)", inner)]
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        return {}, raw
    m = re.match(r"^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)", raw)
    if not m:
        return {}, raw
    block = m.group(1)
    fm: dict[str, Any] = {}
    current_key: str | None = None
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        lm = re.match(r"^\s*-\s*(.*)$", line)
        if lm and current_key is not None and isinstance(fm.get(current_key), list):
            fm[current_key].append(_parse_scalar(lm.group(1)))
            continue
        km = re.match(r"^([A-Za-z0-9_\-\. ]+):\s*(.*)$", line)
        if km:
            key = km.group(1).strip()
            val = km.group(2)
            if val.strip() == "":
                fm[key] = []
                current_key = key
            else:
                fm[key] = _parse_scalar(val)
                current_key = key
                if not isinstance(fm[key], list):
                    current_key = None
    body = raw[m.end():]
    return fm, body


def _norm_tag(t: Any) -> str:
    return str(t).strip().lstrip("#").lower()


def extract_tags(body: str, fm: dict[str, Any]) -> list[str]:
    tags: set[str] = set()
    fmt = fm.get("tags") or fm.get("tag")
    if isinstance(fmt, list):
        tags.update(_norm_tag(t) for t in fmt if t)
    elif isinstance(fmt, str):
        tags.update(_norm_tag(t) for t in re.split(r"[,\s]+", fmt) if t)
    stripped = CODE_BLOCK_RE.sub("", body)
    for m in TAG_RE.finditer(stripped):
        tag = m.group(1)
        if re.fullmatch(r"\d+", tag):
            continue
        tags.add(tag.lower())
    return sorted(tags)


def extract_links(body: str) -> list[str]:
    links: list[str] = []
    for m in WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        if target and target not in links:
            links.append(target)
    for m in MD_LINK_RE.finditer(body):
        target = m.group(1).strip()
        target = os.path.basename(target)[:-3]
        if target and target not in links:
            links.append(target)
    return links


def parse_note(abs_path: Path, vault_root: Path, raw: str | None = None) -> Note:
    if raw is None:
        raw = abs_path.read_text(encoding="utf-8", errors="replace")
    st = abs_path.stat() if abs_path.exists() else None
    fm, body = parse_frontmatter(raw)
    rel = abs_path.relative_to(vault_root).as_posix()
    title = str(fm.get("title") or abs_path.stem)
    headings = [h.strip() for _, h in HEADING_RE.findall(body)]
    return Note(
        path=rel,
        abs_path=abs_path,
        title=title,
        raw=raw,
        body=body,
        frontmatter=fm,
        tags=extract_tags(body, fm),
        links=extract_links(body),
        headings=headings,
        mtime=st.st_mtime if st else 0.0,
        ctime=getattr(st, "st_ctime", 0.0) if st else 0.0,
        size=st.st_size if st else len(raw),
        content_hash=content_hash(raw),
    )


class Vault:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.vault

    def is_excluded(self, rel_path: str) -> bool:
        parts = rel_path.replace("\\", "/").split("/")
        for folder in self.cfg.privacy.do_not_process_folders:
            f = folder.replace("\\", "/").strip("/")
            if rel_path.startswith(f + "/") or rel_path == f:
                return True
        if any(p.startswith(".") for p in parts[:-1]):
            return True
        return False

    def iter_markdown(self) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = Path(dirpath).relative_to(self.root).as_posix()
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and not self.is_excluded((rel_dir + "/" + d).strip("./"))]
            for fn in filenames:
                if fn.lower().endswith(".md"):
                    p = Path(dirpath) / fn
                    if not self.is_excluded(p.relative_to(self.root).as_posix()):
                        yield p

    def iter_all_files(self) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in (".git",)]
            for fn in filenames:
                yield Path(dirpath) / fn

    def read(self, rel_path: str) -> Note:
        return parse_note(self.root / rel_path, self.root)

    def notes(self) -> Iterator[Note]:
        for p in self.iter_markdown():
            try:
                yield parse_note(p, self.root)
            except (OSError, UnicodeDecodeError):
                continue

    def resolve_link(self, target: str) -> str | None:
        """Resolve a wikilink target to a relative note path (Obsidian shortest-path rules, simplified)."""
        target = target.strip()
        if target.lower().endswith(".md"):
            target = target[:-3]
        candidates = [target + ".md"]
        base = os.path.basename(target)
        if not hasattr(self, "_name_index"):
            self._name_index: dict[str, list[str]] = {}
            for p in self.iter_markdown():
                rel = p.relative_to(self.root).as_posix()
                self._name_index.setdefault(p.stem.lower(), []).append(rel)
        for c in candidates:
            if (self.root / c).exists():
                return c
        hits = self._name_index.get(base.lower())
        if hits:
            return sorted(hits, key=len)[0]
        return None

    def invalidate_cache(self) -> None:
        if hasattr(self, "_name_index"):
            del self._name_index


def iso_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
