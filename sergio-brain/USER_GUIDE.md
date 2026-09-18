# USER GUIDE

## Rutina

**Mañana** — `Ctrl+P → Morning briefing` (o automático al abrir Obsidian): AYER / HOY / ATENCIÓN / MEMORY / CONNECTIONS.
Se guarda en `SERGIO BRAIN/Reviews/Morning Briefing <fecha>.md`. El comando *Remember* muestra recordatorios activos.

**Durante el día** — escribe como siempre. Cada guardado se indexa. Usa:
- `Ctrl+Shift+B` **Omnibar**: Ask / Search / Why do I know this? / What changed?
- `Ctrl+Alt+S` **Capture**: selección o portapapeles → `SERGIO BRAIN/Inbox/` clasificado (TRIVIAL/TEMPORARY/USEFUL/KNOWLEDGE/TASK/REFERENCE) con provenance y aviso de "quizá ya existe".
- Panel lateral **Sergio Brain**: notas relacionadas (con razón), memorias de la nota y feedback ★/✕/!.
- Extensión del navegador: Save selection / URL / article / page.

**Noche** (automático a las 22:00 con `serve`) — consolidación: eventos → Daily Memory → memorias importantes → LONG_TERM; backup incremental.
**Domingo** — Weekly Brain Review. **Día 1** — Monthly Brain Review. Manual: `sergio-brain review weekly|monthly`.

## Preguntas que sabe responder

`¿Qué tengo pendiente?` (lista de tareas con antigüedad y vencimiento) · `¿Qué hice ayer / esta semana?` (timeline) ·
`¿Qué estaba haciendo con X?` · `¿Qué sé sobre X?` · `¿Qué decidí sobre X?` · `¿Por qué sé esto?` (cadena de provenance) ·
`¿Qué cambió en X?` (diff entre versiones + supersesiones) · `¿Qué proyectos/personas están relacionados con X?` ·
`¿Qué está aislado / desactualizado?` (Brain Health / `stale`).

Cada respuesta indica `I KNOW / I FOUND / I INFER / I DON'T KNOW` y cita `[[notas]]`. Sin evidencia: *Not enough evidence in Boveda Sergio.*

## Cómo escribir para que te entienda mejor

- Tareas: `- [ ] …` o frases con *tengo que / debo / revisar / enviar / preparar …*; fecha con `📅 2026-09-25` o "antes del 25/09/2026".
- Decisiones: *decidí / acordamos / optamos por X en lugar de Y porque …* → captura razón y alternativas.
- Aprendizajes: *hoy aprendí que …*, *me di cuenta …*, `TIL:`.
- Proyectos: frontmatter `project: Nombre` o tag `#proyecto/nombre` o carpeta `Proyectos/Nombre/`.
- Personas: `people: [Ana, Carlos]` o "reunión con Carlos".
- Sensible: `privacy: SENSITIVE` o `#sensitive` (nunca va a la nube); `do_not_index: true` (ni se lee).

## Command center

`SERGIO BRAIN/SERGIO BRAIN.md` (comando *Open SERGIO BRAIN command center*): TODAY, ACTIVE PROJECTS, RECENT MEMORY,
IMPORTANT MEMORY, SUGGESTED CONNECTIONS, CONTRADICTIONS, STALE KNOWLEDGE, BRAIN HEALTH, ASK.
`SERGIO BRAIN/Brain Health.md`: score y listas de huérfanas, duplicados, conceptos sin nota, metadatos ausentes,
información obsoleta, contradicciones, conocimiento fragmentado, proyectos incompletos, tareas vencidas.

## Sugerencias y contradicciones

Nunca se aplican solas. Acepta/rechaza con feedback (`sergio-brain feedback suggestion <id> USEFUL|IGNORE`, o botones en el plugin).
Las contradicciones muestran ambas afirmaciones, fechas y fuentes; tú decides. Al enlazar dos notas sugeridas, la sugerencia se cierra sola.

## CLI completa

`doctor init audit index search ask serve capture import backup review health tasks timeline why changed recall project suggestions contradictions feedback costs` — `sergio-brain <cmd> -h`. Añade `--json` para salida estructurada.
