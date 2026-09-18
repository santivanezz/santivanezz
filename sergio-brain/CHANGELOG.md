# CHANGELOG

## 0.2.0 — 2026-09-18
- Conversaciones con IA en la bóveda: `import-chats` (ChatGPT, Claude, Gemini Takeout), `import-memory`, endpoint `POST /ai-chat`
  con upsert por conversación, extensión con "Save AI conversation" y auto-guardado opcional en chatgpt.com / claude.ai / gemini.google.com.
- Instaladores CMD sin administrador (`scripts\install.cmd`, `serve.cmd`, `register-startup-user.cmd`) y comando `plugin-install`.

## 0.1.0 — 2026-09-18
- Motor Python (`sergio_brain`): doctor, audit read-only, backup snapshot/incremental/restore, indexación incremental,
  redacción de secretos, chunks + FTS5 + embeddings (hashed/local/ollama/openai), extractores de tareas/decisiones/aprendizajes/
  entidades, grafo ligero con relaciones, búsqueda híbrida con RRF y rerank, asistente RAG con citas y regla de verdad,
  contradicciones/supersesión, timeline, why-do-I-know, what-changed, active recall con relevance engine, memory score explicable,
  decay y estados temporales, duplicados y consolidación, serendipia, Inbox de capturas clasificadas, importación de documentos,
  Daily Memory, Morning Briefing, Weekly/Monthly Review, Brain Health, Command Center, API local, scheduler, cola de jobs con retry,
  control de costes, proveedores intercambiables.
- Plugin de Obsidian: Omnibar (Ctrl+Shift+B), Capture (Ctrl+Alt+S), panel lateral de notas relacionadas/memorias/entidades,
  Remember, reviews, Brain Health, feedback, notificación de cambios, barra de estado.
- Extensión Chrome/Edge: Save selection / URL / article / page.
- Scripts Windows: instalación, plugin, tarea de inicio, hotkey AutoHotkey.
- 31 tests (15 acceptance tests del spec + unitarios).
