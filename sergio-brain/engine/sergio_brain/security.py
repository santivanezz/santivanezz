"""Security: secret detection and redaction.

SERGIO BRAIN never stores or sends credentials. Text is scanned before it is
indexed, logged or sent to any LLM. Detected secrets are replaced by
``[REDACTED:<kind>]``. Detection is heuristic (regex + entropy) and errs on the
side of redacting.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

PRIVACY_LEVELS = ("PUBLIC", "PERSONAL", "WORK", "SENSITIVE")

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{16,}")),
    ("password_assignment", re.compile(
        r"(?i)\b(password|passwd|pwd|contrase[nñ]a|clave|secret|api[_\- ]?key|token|access[_\- ]?key)\b\s*[:=]\s*[\"']?([^\s\"',;]{4,})")),
    ("cookie", re.compile(r"(?i)\b(cookie|set-cookie)\s*[:=]\s*[^\n]{10,}")),
    ("connection_string", re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?|redis|mssql|amqp)://[^\s\"']*:[^\s\"'@]+@[^\s\"']+")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
]


@dataclass
class SecretHit:
    kind: str
    start: int
    end: int
    preview: str


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def find_secrets(text: str) -> list[SecretHit]:
    hits: list[SecretHit] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            if kind == "credit_card":
                digits = re.sub(r"\D", "", m.group(0))
                if not (13 <= len(digits) <= 16 and _luhn_ok(digits)):
                    continue
            if kind == "password_assignment":
                value = m.group(2)
                # skip obvious placeholders / prose
                if value.lower() in {"none", "null", "true", "false", "xxx", "****", "<redacted>", "redacted"}:
                    continue
                if value.startswith("${") or value.startswith("{{"):
                    continue
            hits.append(SecretHit(kind, m.start(), m.end(), text[m.start():m.start() + 6] + "..."))
    # High-entropy long tokens that look like credentials
    for m in re.finditer(r"\b[A-Za-z0-9_\-]{32,}\b", text):
        tok = m.group(0)
        if any(h.start <= m.start() < h.end for h in hits):
            continue
        if re.fullmatch(r"[0-9a-f]{32,64}", tok):  # sha/md5 hashes are fine to keep
            continue
        if _entropy(tok) > 4.3 and re.search(r"\d", tok) and re.search(r"[A-Za-z]", tok):
            hits.append(SecretHit("high_entropy_token", m.start(), m.end(), tok[:6] + "..."))
    hits.sort(key=lambda h: h.start)
    return hits


def redact(text: str) -> tuple[str, list[SecretHit]]:
    hits = find_secrets(text)
    if not hits:
        return text, hits
    out: list[str] = []
    pos = 0
    for h in hits:
        if h.start < pos:
            continue
        out.append(text[pos:h.start])
        if h.kind == "password_assignment":
            # keep the key name, drop the value
            seg = text[h.start:h.end]
            key = re.split(r"[:=]", seg, 1)[0]
            out.append(f"{key}= [REDACTED:{h.kind}]")
        else:
            out.append(f"[REDACTED:{h.kind}]")
        pos = h.end
    out.append(text[pos:])
    return "".join(out), hits


def normalize_privacy(level: str | None, default: str = "PERSONAL") -> str:
    if not level:
        return default
    lv = str(level).strip().upper()
    return lv if lv in PRIVACY_LEVELS else default
