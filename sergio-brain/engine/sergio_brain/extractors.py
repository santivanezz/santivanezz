"""Heuristic extractors: tasks, decisions, learnings, entities, context, dates.

These run without any LLM (offline, deterministic). Every result carries a
confidence label; nothing extracted here is ever presented as FACT.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .embeddings import content_words
from .vault import WIKILINK_RE, CODE_BLOCK_RE

# ---------------------------------------------------------------- dates
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12,
}
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DMY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
TEXT_DATE_RE = re.compile(r"\b(\d{1,2})\s+(?:de\s+)?([A-Za-zé]+)(?:\s+(?:de\s+|del\s+)?(\d{4}))?\b", re.IGNORECASE)


def find_dates(text: str, default_year: int | None = None) -> list[str]:
    out: list[str] = []
    for m in ISO_DATE_RE.finditer(text):
        out.append(m.group(0))
    for m in DMY_RE.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.append(f"{y:04d}-{mo:02d}-{d:02d}")
    for m in TEXT_DATE_RE.finditer(text):
        mon = _MONTHS.get(m.group(2).lower())
        if not mon:
            continue
        d = int(m.group(1))
        if not 1 <= d <= 31:
            continue
        y = int(m.group(3)) if m.group(3) else default_year
        if y:
            out.append(f"{y:04d}-{mon:02d}-{d:02d}")
    seen: list[str] = []
    for d in out:
        if d not in seen:
            seen.append(d)
    return seen


# ---------------------------------------------------------------- tasks
TASK_VERBS = r"(?:tengo que|tenemos que|debo|debemos|hay que|necesito|pendiente(?:s)?(?: de)?|recordar|revisar|enviar|preparar|llamar|terminar|completar|entregar|agendar|programar|coordinar|responder|actualizar|investigar|to ?do|todo:|need to|must|have to|remember to|follow up)"
TASK_LINE_RE = re.compile(r"^\s*[-*+]\s*\[( |x|X)\]\s*(.+)$", re.MULTILINE)
TASK_SENTENCE_RE = re.compile(r"(?i)(?:^|[.\n!?;]\s*)((?:[^.\n!?;]{0,60}?)\b" + TASK_VERBS + r"\b[^.\n!?]{3,200})")
PRIORITY_RE = re.compile(r"(?i)\b(urgente|urgent|alta prioridad|high priority|prioridad alta|asap|importante|important|!{2,})\b")
DUE_RE = re.compile(r"(?i)\b(?:para|antes del?|hasta|due|by|deadline|vence)\s+(?:el\s+)?([^\n,.;]{3,40})")
DUE_EMOJI_RE = re.compile(r"[📅⏳🗓]\s*(\d{4}-\d{2}-\d{2})")


@dataclass
class ExtractedItem:
    kind: str                     # TASK | DECISION | LEARNING | EVENT
    text: str
    confidence: str = "AI_INFERENCE"
    metadata: dict[str, Any] = field(default_factory=dict)
    offset: int = 0


def extract_tasks(body: str, default_year: int | None = None) -> list[ExtractedItem]:
    items: list[ExtractedItem] = []
    body_nc = CODE_BLOCK_RE.sub(lambda m: " " * len(m.group(0)), body)
    seen: set[str] = set()
    for m in TASK_LINE_RE.finditer(body_nc):
        done = m.group(1).lower() == "x"
        text = m.group(2).strip()
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        md: dict[str, Any] = {"status": "done" if done else "open", "explicit": True}
        due = DUE_EMOJI_RE.search(text)
        dates = find_dates(text, default_year)
        if due:
            md["due"] = due.group(1)
        elif dates:
            md["due"] = dates[0]
        if PRIORITY_RE.search(text):
            md["priority"] = "high"
        items.append(ExtractedItem("TASK", text, "USER_ASSERTION", md, m.start()))
    for m in TASK_SENTENCE_RE.finditer(body_nc):
        text = m.group(1).strip(" -*\t")
        if len(text) < 8 or text.lstrip().startswith("#") or "?" in text[:3]:
            continue
        line_start = body_nc.rfind("\n", 0, m.start(1)) + 1
        if body_nc[line_start:m.start(1) + 1].lstrip().startswith("#"):
            continue
        key = re.sub(r"\W+", " ", text.lower()).strip()
        if key in seen or any(key in s or s in key for s in seen):
            continue
        seen.add(key)
        md = {"status": "open", "explicit": False}
        dm = DUE_RE.search(text)
        dates = find_dates(text, default_year)
        if dates:
            md["due"] = dates[0]
        elif dm:
            md["due_text"] = dm.group(1).strip()
        if PRIORITY_RE.search(text):
            md["priority"] = "high"
        items.append(ExtractedItem("TASK", text, "AI_INFERENCE", md, m.start()))
    return items


# ---------------------------------------------------------------- decisions
DECISION_RE = re.compile(
    r"(?i)(?:^|[.\n!?]\s*)((?:[^.\n!?]{0,80}?)\b(?:decid[íi](?:mos)?|se decidi[óo]|hemos decidido|he decidido|decisi[óo]n:|acordamos|se acord[óo]|quedamos en|optamos por|opt[ée] por|vamos a usar|elegimos|we decided|decided to|decision:|agreed to)\b[^.\n!?]{3,250})")
DECISION_REASON_RE = re.compile(r"(?i)\b(?:porque|ya que|debido a|dado que|because|since|para)\s+([^.\n]{3,200})")
DECISION_ALT_RE = re.compile(r"(?i)\b(?:en lugar de|en vez de|instead of|frente a|vs\.?|versus)\s+((?:(?!\b(?:porque|ya que|debido a|dado que|because|since|para)\b)[^.\n,;]){2,80}?)\s*(?=$|[.,;\n]|\b(?:porque|ya que|debido a|dado que|because|since|para)\b)")


def extract_decisions(body: str, default_year: int | None = None) -> list[ExtractedItem]:
    items: list[ExtractedItem] = []
    body_nc = CODE_BLOCK_RE.sub(lambda m: " " * len(m.group(0)), body)
    seen: set[str] = set()
    for m in DECISION_RE.finditer(body_nc):
        text = m.group(1).strip(" -*\t")
        key = re.sub(r"\W+", " ", text.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        # the following sentence often carries the reason
        tail = body_nc[m.end():m.end() + 300]
        md: dict[str, Any] = {}
        rm = DECISION_REASON_RE.search(text) or DECISION_REASON_RE.search(tail)
        if rm:
            md["reason"] = rm.group(1).strip()
        am = DECISION_ALT_RE.search(text)
        if am:
            md["alternatives"] = [am.group(1).strip()]
        dates = find_dates(text, default_year)
        if dates:
            md["date"] = dates[0]
        conf = "USER_ASSERTION" if re.search(r"(?i)\b(decid|decisi|acord)", text) else "AI_INFERENCE"
        items.append(ExtractedItem("DECISION", text, conf, md, m.start()))
    return items


# ---------------------------------------------------------------- learnings
LEARNING_RE = re.compile(
    r"(?i)(?:^|[.\n!?]\s*)((?:[^.\n!?]{0,40}?)\b(?:aprend[íi]|hoy aprend[íi]|aprendizaje:|me di cuenta|descubr[íi]|entend[íi] que|ahora s[ée] que|lecci[óo]n:|TIL:?|I learned|learned that|lesson:|key takeaway)\b[^.\n!?]{3,300})")


def extract_learnings(body: str) -> list[ExtractedItem]:
    items: list[ExtractedItem] = []
    body_nc = CODE_BLOCK_RE.sub(lambda m: " " * len(m.group(0)), body)
    seen: set[str] = set()
    for m in LEARNING_RE.finditer(body_nc):
        text = m.group(1).strip(" -*\t")
        key = re.sub(r"\W+", " ", text.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        items.append(ExtractedItem("LEARNING", text, "USER_ASSERTION", {}, m.start()))
    return items


# ---------------------------------------------------------------- entities
TECHNOLOGIES = {
    "python": "TECHNOLOGY", "sql": "TECHNOLOGY", "power bi": "TECHNOLOGY", "powerbi": "TECHNOLOGY", "power query": "TECHNOLOGY",
    "dax": "TECHNOLOGY", "excel": "TECHNOLOGY", "vba": "TECHNOLOGY", "typescript": "TECHNOLOGY", "javascript": "TECHNOLOGY",
    "react": "TECHNOLOGY", "node": "TECHNOLOGY", "nodejs": "TECHNOLOGY", "postgres": "TECHNOLOGY", "postgresql": "TECHNOLOGY",
    "sqlite": "TECHNOLOGY", "obsidian": "TECHNOLOGY", "pandas": "TECHNOLOGY", "numpy": "TECHNOLOGY", "fastapi": "TECHNOLOGY",
    "docker": "TECHNOLOGY", "git": "TECHNOLOGY", "github": "TECHNOLOGY", "azure": "TECHNOLOGY", "aws": "TECHNOLOGY",
    "bpm": "CONCEPT", "bpmn": "CONCEPT", "lean": "CONCEPT", "six sigma": "CONCEPT", "erlang c": "CONCEPT",
    "kanban": "CONCEPT", "scrum": "CONCEPT", "rag": "CONCEPT", "llm": "CONCEPT", "machine learning": "CONCEPT",
    "automatizacion": "CONCEPT", "automatización": "CONCEPT", "automation": "CONCEPT", "workflow": "CONCEPT",
    "power automate": "TECHNOLOGY", "sharepoint": "TECHNOLOGY", "teams": "TECHNOLOGY", "outlook": "TECHNOLOGY",
    "tableau": "TECHNOLOGY", "bizagi": "TECHNOLOGY", "camunda": "TECHNOLOGY", "uipath": "TECHNOLOGY", "n8n": "TECHNOLOGY",
    "claude": "TECHNOLOGY", "openai": "ORGANIZATION", "anthropic": "ORGANIZATION", "microsoft": "ORGANIZATION", "google": "ORGANIZATION",
}
PERSON_HINT_RE = re.compile(r"(?:@|\bcon\b\s+|\breuni[óo]n con\b\s+|\bllamar a\b\s+|\bhablar con\b\s+|\bmeeting with\b\s+)([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,2})")
PROPER_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñA-Z0-9]+(?:[ \t]+(?:de[ \t]+|del[ \t]+|la[ \t]+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñA-Z0-9]+){1,3})\b")
PROJECT_HINT_RE = re.compile(r"\b[Pp]royecto[ \t]+([A-ZÁÉÍÓÚÑ][\w\-]+(?:[ \t]+[A-ZÁÉÍÓÚÑ][\w\-]+){0,3})")
SENTENCE_START_WORDS = {"El", "La", "Los", "Las", "Un", "Una", "Hoy", "Ayer", "Mañana", "Este", "Esta", "Esto", "En", "Por", "Para",
                        "Con", "Sin", "The", "This", "That", "When", "Cuando", "Si", "If", "No", "Yes", "Sí", "Nota", "Note"}


def normalize_entity(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def extract_entities(body: str, links: list[str], tags: list[str], frontmatter: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Return (name, type, count). Deterministic, conservative."""
    counts: dict[tuple[str, str], int] = {}
    names: dict[tuple[str, str], str] = {}

    def add(name: str, etype: str, n: int = 1) -> None:
        name = name.strip().strip("[]#")
        if len(name) < 2:
            return
        norm = normalize_entity(name)
        # the same name never lives under two types: the first (more specific) wins
        for (other_norm, other_type) in counts:
            if other_norm == norm and other_type != etype:
                if etype == "CONCEPT" or other_type in ("PROJECT", "PERSON", "NOTE", "TECHNOLOGY"):
                    counts[(other_norm, other_type)] += n
                    return
        key = (norm, etype)
        counts[key] = counts.get(key, 0) + n
        names.setdefault(key, name)

    text = CODE_BLOCK_RE.sub(" ", body)
    for link in links:
        add(link, "NOTE")
    for tag in tags:
        if tag.startswith(("proyecto/", "project/")):
            add(tag.split("/", 1)[1].replace("-", " "), "PROJECT")
        elif tag.startswith(("persona/", "person/", "people/")):
            add(tag.split("/", 1)[1].replace("-", " "), "PERSON")
        elif tag.startswith(("curso/", "course/")):
            add(tag.split("/", 1)[1].replace("-", " "), "COURSE")
        else:
            add(tag.replace("-", " "), "TOPIC")
    for key in ("project", "proyecto", "projects"):
        v = frontmatter.get(key)
        if isinstance(v, str):
            add(v, "PROJECT", 3)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    add(x, "PROJECT", 3)
    for key in ("people", "personas", "person", "attendees", "asistentes"):
        v = frontmatter.get(key)
        if isinstance(v, str):
            add(v, "PERSON", 2)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    add(x, "PERSON", 2)
    lower = text.lower()
    for tech, etype in TECHNOLOGIES.items():
        n = len(re.findall(r"(?<![\w])" + re.escape(tech) + r"(?![\w])", lower))
        if n:
            add(tech.title() if etype != "TECHNOLOGY" else tech.upper() if len(tech) <= 3 else tech.title(), etype, n)
    for m in PERSON_HINT_RE.finditer(text):
        add(m.group(1), "PERSON")
    for m in PROJECT_HINT_RE.finditer(text):
        add(m.group(1), "PROJECT", 2)
    for m in PROPER_RE.finditer(text):
        cand = m.group(1)
        first = cand.split()[0]
        if first in SENTENCE_START_WORDS:
            continue
        if m.start() > 0 and text[m.start() - 1] in "[#":
            continue
        # skip if it is a sentence start (preceded by newline or period)
        prev = text[max(0, m.start() - 2):m.start()]
        if prev.strip() in ("", ".", "!", "?") and len(cand.split()) < 2:
            continue
        add(cand, "CONCEPT")
    out = [(names[k], k[1], c) for k, c in counts.items()]
    out.sort(key=lambda x: -x[2])
    return out[:80]


# ---------------------------------------------------------------- context
CONTEXT_HINTS = {
    "WORK": ["trabajo", "reunión", "reunion", "cliente", "jefe", "oficina", "proceso", "kpi", "informe", "gerencia", "área", "sprint", "meeting", "work"],
    "STUDY": ["universidad", "maestría", "maestria", "curso", "clase", "examen", "tarea", "profesor", "semestre", "tesis", "materia", "study", "lecture"],
    "PERSONAL": ["casa", "familia", "salud", "viaje", "compra", "cumpleaños", "amigo", "personal", "hogar"],
    "FINANCE": ["finanzas", "dinero", "ahorro", "inversión", "inversion", "banco", "préstamo", "prestamo", "presupuesto", "gasto", "sueldo", "budget"],
    "LEARNING": ["aprendí", "aprendi", "aprendizaje", "libro", "lectura", "tutorial", "til", "learned"],
    "PROJECT": ["proyecto", "project", "milestone", "entregable", "roadmap"],
}


def detect_context(text: str, tags: list[str], frontmatter: dict[str, Any], path: str) -> str:
    explicit = frontmatter.get("context") or frontmatter.get("contexto")
    if isinstance(explicit, str) and explicit.upper() in CONTEXT_HINTS:
        return explicit.upper()
    scores = {k: 0 for k in CONTEXT_HINTS}
    lower = (text[:4000] + " " + " ".join(tags) + " " + path).lower()
    for ctx, words in CONTEXT_HINTS.items():
        for w in words:
            scores[ctx] += lower.count(w)
    for ctx in CONTEXT_HINTS:
        if any(t == ctx.lower() or t.startswith(ctx.lower() + "/") for t in tags):
            scores[ctx] += 5
        if ctx.lower() in path.lower():
            scores[ctx] += 3
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else "PERSONAL"


def detect_project(text: str, tags: list[str], frontmatter: dict[str, Any], path: str) -> str | None:
    for key in ("project", "proyecto"):
        v = frontmatter.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().strip("[]")
        if isinstance(v, list) and v and isinstance(v[0], str):
            return v[0].strip().strip("[]")
    for t in tags:
        if t.startswith(("proyecto/", "project/")):
            return t.split("/", 1)[1].replace("-", " ").title()
    parts = path.split("/")
    for i, p in enumerate(parts[:-1]):
        if p.lower() in ("proyectos", "projects", "proyecto", "project") and i + 1 < len(parts) - 1:
            return parts[i + 1]
    m = PROJECT_HINT_RE.search(text[:3000])
    return m.group(1) if m else None


def keywords(text: str, n: int = 12) -> list[str]:
    freq: dict[str, int] = {}
    for w in content_words(text):
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:n]]
