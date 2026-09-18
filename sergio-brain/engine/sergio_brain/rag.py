"""RAG assistant: retrieve -> build dynamic context -> LLM (optional) -> answer with sources.

Truth rule: the answer separates I KNOW / I FOUND / I INFER / I DON'T KNOW.
Without enough evidence it says: "Not enough evidence in Boveda Sergio."
Without an LLM it returns an extractive answer built only from retrieved text.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

NOT_ENOUGH = "Not enough evidence in Boveda Sergio."

SYSTEM_PROMPT = """Eres SERGIO BRAIN ASSISTANT, la capa de razonamiento sobre la bóveda de Obsidian "Boveda Sergio" de Sergio.
Reglas absolutas:
1. Responde SOLO con la evidencia proporcionada en CONTEXT. No inventes recuerdos, fechas, personas ni fuentes.
2. Si la evidencia no basta, responde exactamente: "Not enough evidence in Boveda Sergio." y explica qué falta.
3. Diferencia claramente: I KNOW (afirmado en las notas), I FOUND (recuperado, relacionado), I INFER (deducción tuya, márcala como inferencia), I DON'T KNOW.
4. Cita las fuentes con el formato [[Título de la nota]] al final, bajo "Sources:". Solo notas que aparezcan en CONTEXT.
5. Responde en el idioma de la pregunta (normalmente español). Sé concreto y breve.
6. Si hay información contradictoria o con fechas distintas, muéstrala y no decidas cuál es correcta."""


class Assistant:
    def __init__(self, engine):
        self.e = engine
        self.db = engine.db

    # ------------------------------------------------------------ context
    def build_context(self, query: str, k: int = 8) -> dict[str, Any]:
        u = self.e.search.understand(query)
        results = self.e.search.search(query, k=k, since=u["since"])
        ctx: dict[str, Any] = {"understanding": u, "results": results, "memories": [], "timeline": [], "related": [], "entities": u["entities"], "projects": []}
        doc_ids = [r["document_id"] for r in results]
        if doc_ids:
            q = ",".join("?" * len(doc_ids))
            ctx["memories"] = [dict(m) for m in self.db.query(
                f"SELECT m.id, m.memory_type, m.content, m.status, m.event_date, m.due_date, m.confidence, d.title, d.path FROM memories m JOIN documents d ON d.id=m.document_id"
                f" WHERE m.document_id IN ({q}) AND m.status!='dismissed' ORDER BY m.importance DESC LIMIT 25", doc_ids)]
            ctx["projects"] = [dict(p) for p in self.db.query(
                f"SELECT DISTINCT p.name, p.status FROM relations r JOIN projects p ON p.id=r.target_id WHERE r.source_type='document' AND r.source_id IN ({q}) AND r.target_type='project'", doc_ids)]
            if results:
                ctx["related"] = self.e.graph.related_documents(results[0]["document_id"], k=5)
        if u["intent"] in ("tasks",):
            ctx["memories"] = self.e.memory.open_tasks(limit=40) + ctx["memories"]
        if u["intent"] in ("timeline",) or u["since"]:
            ctx["timeline"] = self.e.intel.timeline(since=u["since"] or (time.time() - 7 * 86400), limit=30)
        return ctx

    def _context_text(self, ctx: dict[str, Any]) -> tuple[str, list[str], list[str]]:
        limit = self.e.cfg.ai.max_context_chars
        parts: list[str] = []
        titles: list[str] = []
        privacy: list[str] = []
        used = 0
        for r in ctx["results"]:
            block = f"### [[{r['title']}]] ({r['path']})\n{r['content']}\n"
            if used + len(block) > limit:
                break
            parts.append(block)
            used += len(block)
            titles.append(r["title"])
            privacy.append(r.get("privacy", "PERSONAL"))
        if ctx["memories"]:
            mem_lines = [f"- ({m['memory_type']}, {m['confidence']}, {m.get('event_date') or ''}) {m['content'][:200]} — de [[{m['title']}]]" for m in ctx["memories"][:25]]
            block = "### Memorias extraídas\n" + "\n".join(mem_lines) + "\n"
            if used + len(block) <= limit:
                parts.append(block)
                used += len(block)
        if ctx["timeline"]:
            tl = [f"- {t['date']}: {t['kind']} — {t['title']}" for t in ctx["timeline"][:30]]
            block = "### Timeline\n" + "\n".join(tl) + "\n"
            if used + len(block) <= limit:
                parts.append(block)
        return "\n".join(parts), titles, privacy

    # ------------------------------------------------------------ ask
    def ask(self, question: str, k: int = 8, use_llm: bool = True) -> dict[str, Any]:
        t0 = time.time()
        ctx = self.build_context(question, k=k)
        context_text, titles, privacy = self._context_text(ctx)
        results = ctx["results"]
        strong = [r for r in results if r["score"] >= 0.35 and (r.get("rerank", 0) >= 0.2 or "entity" in r["sources"])]
        response: dict[str, Any] = {
            "question": question, "intent": ctx["understanding"]["intent"], "sources": [], "related": ctx["related"],
            "entities": ctx["entities"], "projects": ctx["projects"], "timeline": ctx["timeline"][:15],
            "memories": ctx["memories"][:15], "mode": "extractive", "evidence": "I DON'T KNOW",
        }
        for r in results:
            response["sources"].append({"title": r["title"], "path": r["path"], "score": r["score"], "snippet": r["snippet"][:240], "heading": r["heading"]})
            self.e.search.touch(r["document_id"])
        # Intent-specific structured answers that need no LLM
        intent = ctx["understanding"]["intent"]
        if intent == "tasks":
            tasks = self.e.memory.open_tasks(limit=40)
            if not tasks:
                response["answer"] = NOT_ENOUGH + " No hay tareas abiertas detectadas."
            else:
                lines = [f"- [ ] {t['content'][:140]} — [[{t['note_title']}]]" + (f" (vence {t['due_date']})" if t.get("due_date") else "") + (f" · {t['age_days']} días abierta" if t["age_days"] > 7 else "") for t in tasks[:25]]
                response["answer"] = "I KNOW (tareas detectadas en tus notas):\n" + "\n".join(lines)
                response["evidence"] = "I KNOW"
            response["duration_ms"] = int((time.time() - t0) * 1000)
            return response
        if intent == "why":
            response["why"] = self.e.intel.why_do_i_know(question)
        if intent == "changes" and results:
            response["changes"] = self.e.intel.what_changed(results[0]["document_id"])
        if not strong:
            response["answer"] = NOT_ENOUGH + (" Encontré notas vagamente relacionadas (ver Sources) pero ninguna responde con claridad." if results else "")
            response["duration_ms"] = int((time.time() - t0) * 1000)
            return response
        # LLM path
        llm = self.e.llm
        if use_llm and llm.available() and self.e.llm_allowed_for(privacy):
            user = f"PREGUNTA: {question}\n\nCONTEXT:\n{context_text}\n\nResponde siguiendo las reglas. Termina con 'Sources:' y la lista de [[notas]] usadas."
            t1 = time.time()
            res = llm.complete(SYSTEM_PROMPT, user, max_tokens=1500)
            self.e.costs.record(llm.name, llm.model, "llm", res, int((time.time() - t1) * 1000))
            if res.ok and res.text.strip():
                text = res.text.strip()
                # keep only sources that exist in context (never invent)
                cited = re.findall(r"\[\[([^\]]+)\]\]", text)
                bad = [c for c in cited if c not in titles]
                for c in bad:
                    text = text.replace(f"[[{c}]]", c)
                response["answer"] = text
                response["mode"] = f"llm:{llm.name}"
                response["evidence"] = "I FOUND" if NOT_ENOUGH not in text else "I DON'T KNOW"
                response["duration_ms"] = int((time.time() - t0) * 1000)
                return response
            response["llm_error"] = res.error
        elif use_llm and llm.cloud and not self.e.llm_allowed_for(privacy):
            response["llm_error"] = "context contains SENSITIVE notes; not sent to cloud provider"
        # Extractive fallback: quote the best passages
        lines = ["I FOUND (pasajes recuperados de Boveda Sergio, sin síntesis por LLM):", ""]
        for r in strong[:5]:
            snippet = " ".join(r["content"].split())[:400]
            lines.append(f"**[[{r['title']}]]**" + (f" › {r['heading']}" if r["heading"] else "") + f"\n> {snippet}\n")
        if ctx["memories"]:
            lines.append("Memorias relacionadas:")
            for m in ctx["memories"][:6]:
                lines.append(f"- ({m['memory_type']}) {m['content'][:160]} — [[{m['title']}]]")
        lines.append("")
        lines.append("Sources: " + ", ".join(f"[[{r['title']}]]" for r in strong[:5]))
        response["answer"] = "\n".join(lines)
        response["evidence"] = "I FOUND"
        response["duration_ms"] = int((time.time() - t0) * 1000)
        return response

    def summarize(self, text: str, purpose: str = "resumen", privacy: str = "PERSONAL", max_tokens: int = 600) -> str | None:
        """Optional LLM summary; returns None if no LLM available or content blocked from cloud."""
        llm = self.e.llm
        if not llm.available() or not self.e.llm_allowed_for([privacy]):
            return None
        t1 = time.time()
        res = llm.complete("Resume en español, fiel al texto, sin inventar. Devuelve solo el resumen.",
                           f"Propósito: {purpose}\n\nTEXTO:\n{text[: self.e.cfg.ai.max_context_chars]}", max_tokens=max_tokens)
        self.e.costs.record(llm.name, llm.model, "llm", res, int((time.time() - t1) * 1000))
        return res.text.strip() if res.ok else None
