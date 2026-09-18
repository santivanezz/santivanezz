"""Split note bodies into retrieval chunks, heading-aware."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .vault import HEADING_RE, content_hash


@dataclass
class Chunk:
    ordinal: int
    heading: str
    content: str
    char_start: int
    char_end: int

    @property
    def hash(self) -> str:
        return content_hash(self.heading + "\n" + self.content)


def _sections(body: str) -> list[tuple[str, int, int]]:
    """Return (heading, start, end) sections by markdown headings."""
    out: list[tuple[str, int, int]] = []
    last_head = ""
    last_pos = 0
    for m in HEADING_RE.finditer(body):
        if m.start() > last_pos:
            out.append((last_head, last_pos, m.start()))
        last_head = m.group(2).strip()
        last_pos = m.end()
    out.append((last_head, last_pos, len(body)))
    return [s for s in out if body[s[1]:s[2]].strip()]


def chunk_text(body: str, size: int = 900, overlap: int = 120) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    for heading, s, e in _sections(body):
        section = body[s:e]
        # split by paragraphs first
        paras = [(m.start() + s, m.end() + s) for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", section)]
        cur_start = None
        cur_end = None
        for ps, pe in paras:
            if cur_start is None:
                cur_start, cur_end = ps, pe
                continue
            if pe - cur_start <= size:
                cur_end = pe
            else:
                chunks.append(Chunk(ordinal, heading, body[cur_start:cur_end].strip(), cur_start, cur_end))
                ordinal += 1
                # overlap: back up a bit into the previous chunk
                cur_start = max(cur_start, cur_end - overlap) if pe - ps < size else ps
                if cur_start < ps:
                    cur_start = max(ps - overlap, cur_start)
                cur_start = ps if cur_start > ps else cur_start
                cur_end = pe
        if cur_start is not None and body[cur_start:cur_end].strip():
            text = body[cur_start:cur_end]
            # hard split very long paragraphs
            if len(text) > size * 2:
                for i in range(0, len(text), size):
                    piece = text[i:i + size + overlap]
                    chunks.append(Chunk(ordinal, heading, piece.strip(), cur_start + i, cur_start + i + len(piece)))
                    ordinal += 1
            else:
                chunks.append(Chunk(ordinal, heading, text.strip(), cur_start, cur_end))
                ordinal += 1
    if not chunks and body.strip():
        chunks.append(Chunk(0, "", body.strip(), 0, len(body)))
    return chunks
