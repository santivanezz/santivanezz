# ROADMAP

## v0.1 (MVP, este repositorio) — hecho
Plugin, watcher, Inbox, SQLite, indexación incremental, embeddings, búsqueda híbrida, grafo básico, RAG con citas,
detección de tareas y decisiones, dashboard, backup, asistente. Además ya incluidos de fase 2: clipboard, extensión de
navegador, conexiones sugeridas, contradicciones, inteligencia temporal, active recall, brain health, weekly review, briefing.

## Fase 2 — mejoras sobre lo existente
- Extracción con LLM (opcional) para tareas/decisiones/entidades con más recall, siempre marcadas `AI_INFERENCE`.
- Reranker cross-encoder local opcional.
- Consolidación asistida: propuesta de nota consolidada en `Inbox` (nunca merge automático).
- Serendipia con explicación en lenguaje natural vía LLM.
- Panel gráfico del grafo dentro de Obsidian (hoy: `/graph` JSON).
- Hotkey global nativa en Windows (hoy: AutoHotkey/plugin).

## Fase 3
- Calendario (ICS/Outlook) y correo como fuentes de eventos.
- Meeting intelligence: transcripciones → resumen, decisiones, tareas, personas, riesgos, compromisos (la nota `meeting` ya se procesa).
- Feedback learning más profundo (re-pesos de ranking por feedback).
- Integraciones externas por la API local; posible índice vectorial dedicado si el volumen lo exige.
