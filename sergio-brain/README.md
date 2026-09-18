# SERGIO BRAIN

**Personal Memory Operating System** para la bóveda de Obsidian **"Boveda Sergio"**.

No es un chatbot, ni un buscador, ni solo un RAG. Es la capa de inteligencia que
**captura, entiende, conecta, recuerda, consolida, recupera, avisa, explica y organiza**
tu conocimiento a lo largo del tiempo. Obsidian sigue siendo la interfaz; tus archivos
Markdown siguen siendo la fuente de verdad.

```
OBSIDIAN  +  PLUGIN (TypeScript)  +  MEMORY ENGINE (Python)  +  SQLITE (+FTS5)
          +  ÍNDICE VECTORIAL      +  GRAFO LIGERO            +  RAG  +  LLM opcional
```

## Qué hace hoy (MVP, v0.1.0)

| Capacidad | Cómo |
|---|---|
| Auditoría previa, sin tocar nada | `sergio-brain doctor`, `sergio-brain audit` |
| Backup antes de cualquier cambio | `sergio-brain backup` (snapshot + incremental + restore) |
| Indexación incremental (hash, solo lo que cambia) | `sergio-brain index`, watcher en `serve` |
| Búsqueda híbrida (FTS5 + vectores + entidades + título + recencia + rerank) | `sergio-brain search`, Omnibar |
| Memorias atómicas: TASK, DECISION, LEARNING, EPISODIC, RAW, LONG_TERM | extraídas automáticamente de cada nota |
| Grafo de entidades y relaciones, notas relacionadas con razón | panel lateral del plugin, `/related` |
| Asistente con citas y regla de verdad (`I KNOW / I FOUND / I INFER / I DON'T KNOW`) | `sergio-brain ask`, `Ctrl+Shift+B` |
| Contradicciones y supersesión (no decide, muestra ambas con fechas y fuentes) | `sergio-brain contradictions` |
| Serendipia, enlaces sugeridos, consolidación y duplicados (nunca aplicados solos) | `sergio-brain suggestions` |
| Memory score explicable, decay, estados temporales | `stale`, `Brain Health` |
| Why do I know this? / What changed? | `sergio-brain why`, `sergio-brain changed` |
| Inbox de capturas (clipboard, hotkey, extensión de navegador, manual) con clasificación | `sergio-brain capture`, `Ctrl+Alt+S` |
| Documentos (PDF, DOCX, XLSX, PPTX, TXT, CSV, MD) | `sergio-brain import` |
| Daily Memory, Morning Briefing, Weekly/Monthly Review, Brain Health, Command Center | `sergio-brain review …`, `health` |
| Active recall con relevance engine y feedback | `sergio-brain recall`, comando *Remember* |
| API local de memoria personal | `sergio-brain serve` → `http://127.0.0.1:8765` |
| Proveedores intercambiables (Claude, OpenAI, Ollama, ninguno) y control de costes | `config.toml`, `sergio-brain costs` |
| Seguridad: secretos redactados antes de indexar/loggear/enviar, niveles de privacidad | ver `SECURITY.md` |

Funciona **100 % offline** sin ningún modelo instalado (embeddings *hashed* + respuestas extractivas con citas).
Con `sentence-transformers` la búsqueda semántica mejora; con un LLM (Claude, OpenAI u Ollama) el asistente sintetiza.

## Estructura

```
sergio-brain/
  engine/              motor Python (paquete sergio_brain, CLI, API, tests)
  plugin/              plugin de Obsidian (TypeScript; main.js precompilado)
  browser-extension/   extensión Chrome/Edge (Save page / selection / URL / article)
  scripts/             instalación Windows, tarea de inicio, hotkey AutoHotkey
  docs/                ENVIRONMENT-REPORT.md (informe de la inspección real)
  INSTALL.md ARCHITECTURE.md CONFIGURATION.md SECURITY.md BACKUP.md
  USER_GUIDE.md TROUBLESHOOTING.md ROADMAP.md CHANGELOG.md DECISIONS.md
```

## Empezar (Windows)

```powershell
git clone https://github.com/santivanezz/santivanezz.git
cd santivanezz\sergio-brain
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Vault "C:\ruta\Boveda Sergio" -Local -Docs
.\.venv\Scripts\sergio-brain audit      # solo lectura
.\.venv\Scripts\sergio-brain backup     # snapshot completo
.\.venv\Scripts\sergio-brain index      # primera indexación
.\.venv\Scripts\sergio-brain serve      # API + watcher + scheduler
scripts\install-plugin.ps1 -Vault "C:\ruta\Boveda Sergio"
```

Detalles en [INSTALL.md](INSTALL.md) y uso diario en [USER_GUIDE.md](USER_GUIDE.md).

## Principios no negociables

1. **Markdown es la fuente de verdad.** SQLite es índice/memoria, los vectores son recuperación, el grafo es relación, el LLM es síntesis. Nunca al revés.
2. **Zero data loss.** Nunca se borra ni sobrescribe una nota tuya. Lo generado va a `SERGIO BRAIN/` con `sergio_brain: generated`; los bloques gestionados guardan copia previa.
3. **Nunca inventar.** Sin evidencia: `Not enough evidence in Boveda Sergio.`
4. **Sin vigilancia.** Nada de keylogging, grabación de pantalla ni credenciales. Solo capturas que tú disparas.
5. **Local-first.** Todo funciona sin Internet; la nube es opcional y bloqueable por nota.
