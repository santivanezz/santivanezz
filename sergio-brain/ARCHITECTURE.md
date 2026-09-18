# ARCHITECTURE

## Capas (relación nunca invertida)

| Capa | Rol | Implementación |
|---|---|---|
| Obsidian Markdown | **SOURCE OF TRUTH** | tus archivos; solo lectura salvo `SERGIO BRAIN/` |
| SQLite | **INDEX / MEMORY ENGINE** | `engine/sergio_brain/db.py`, un archivo, WAL, FTS5 |
| Índice vectorial | **RETRIEVAL** | vectores float32 en SQLite + matriz numpy en memoria (`embeddings.py`) |
| Knowledge graph | **RELATIONSHIP LAYER** | tablas `entities`, `entity_mentions`, `relations` (`graph.py`) |
| LLM | **REASONING / SYNTHESIS** | `providers/` (Claude / OpenAI / Ollama / none), opcional |

## Flujo

```
nota guardada ──► plugin POST /notify ──┐
                  watcher (poll/watchdog)┴─► debounce ─► job queue (SQLite, retry) ─► Indexer
Indexer: hash → skip si igual → redact secrets → chunks → FTS5 → embeddings → entidades/relaciones
         → memorias (TASK/DECISION/LEARNING/EPISODIC/RAW) → versión (WHAT CHANGED) → eventos
post_analysis: link relations → memory scores → estados temporales → sugerencias/serendipia → contradicciones
```

Consulta:

```
QUERY → understand (intent, ventana temporal, entidades) → FTS5 ∥ vectores ∥ entidades ∥ título
      → RRF fusion → boosts (recencia, importancia, estado temporal) → rerank léxico
      → contexto dinámico (pasajes + memorias + timeline + relacionados) → LLM (si permitido) → respuesta con [[fuentes]]
      → sin evidencia fuerte: "Not enough evidence in Boveda Sergio."
```

## Módulos (`engine/sergio_brain/`)

| Módulo | Responsabilidad |
|---|---|
| `config.py` | TOML en `%APPDATA%\SergioBrain\config.toml`; secretos solo por variables de entorno |
| `doctor.py`, `audit.py` | inspección del PC / auditoría read-only de la bóveda |
| `vault.py`, `writer.py` | lectura de notas (frontmatter, tags, wikilinks) / escritura segura |
| `security.py` | detección y redacción de secretos, niveles de privacidad |
| `chunking.py`, `embeddings.py` | chunks por encabezado; proveedores hashed/local/ollama/openai; `VectorIndex` |
| `extractors.py` | tareas, decisiones (razón, alternativas), aprendizajes, entidades, contexto, proyecto, fechas |
| `indexer.py` | indexación incremental, versiones, memorias, relaciones |
| `memory.py` | memory score explicable, decay/estados temporales, duplicados, consolidación, feedback |
| `graph.py` | relacionados con razones, huérfanas, conceptos sin nota, sugerencias, serendipia |
| `search.py` | búsqueda híbrida + reranker |
| `rag.py` | asistente con citas y regla de verdad; resúmenes opcionales |
| `intelligence.py` | contradicciones/supersesión, timeline, why-do-I-know, what-changed, active recall, project memory |
| `reviews.py` | Daily Memory, briefing, weekly/monthly, Brain Health, Command Center, consolidación diaria |
| `inbox.py`, `documents.py` | capturas clasificadas con provenance; importación de documentos |
| `ai_chats.py` | conversaciones de ChatGPT/Claude/Gemini: parsers de exportación, captura en vivo, upsert por id, memoria del asistente |
| `backup.py` | snapshot, incremental por hash, restore, rollback de ediciones |
| `events.py`, `watcher.py` | bus de eventos, cola persistente con retry/backoff, debounce |
| `server.py` | API JSON local (stdlib), scheduler |
| `cli.py` | todos los comandos |

## Modelo de memoria

Una nota produce 0..n memorias (`memories`): `RAW` (capturas), `EPISODIC` (notas con fecha/reuniones: qué, cuándo, dónde),
`TASK`, `DECISION`, `LEARNING`, `LONG_TERM` (promovidas en consolidación), `SEMANTIC`/`PROJECT` (vía entidades y `projects`),
`ARCHIVED` (estado). Cada memoria lleva `confidence` (FACT / USER_ASSERTION / EXTERNAL_SOURCE / AI_INFERENCE / POSSIBLE / UNKNOWN),
`temporal_state`, `importance` + `importance_reason`, fingerprint estable para indexación incremental y `memory_versions`.

## Eventos

`NOTE_CREATED, NOTE_UPDATED, NOTE_DELETED, FILE_IMPORTED, CLIPBOARD_CAPTURED, WEB_CAPTURED, ENTITY_DISCOVERED, EMBEDDING_CREATED,
RELATION_DISCOVERED, MEMORY_CONSOLIDATED, TASK_DISCOVERED, DECISION_DISCOVERED, LEARNING_DISCOVERED, CONTRADICTION_DETECTED,
SUGGESTION_CREATED, BACKUP_CREATED` — persistidos en `events`; la cola `processing_jobs` reintenta con backoff exponencial.

## API local (`http://127.0.0.1:8765`)

`GET /health /search /related /memory/:id /memories /project/:name /projects /timeline /tasks /entities /graph /suggestions
/contradictions /stale /why /changed /recall /briefing /dashboard /brain-health /review /costs /inbox`
`POST /ask /memory /capture /feedback /notify /reindex /backup /consolidate /import /ai-chat /ai-memory`

## Rendimiento

Todo el trabajo pesado ocurre en el proceso Python, nunca en Obsidian. Indexación incremental por hash; embeddings por lote;
FTS5 para texto; matriz numpy para cosenos (miles de notas → milisegundos). El plugin solo hace peticiones HTTP cortas.

## Escala a 10 años

Sin vendor lock-in: proveedores intercambiables; el índice se regenera desde Markdown en cualquier momento (`index --force`);
migraciones de esquema solo aditivas; backups zip legibles sin el sistema. Si el volumen supera ~500k chunks,
`VectorIndex` es el único punto a sustituir (p. ej. por LanceDB) sin tocar el resto.
