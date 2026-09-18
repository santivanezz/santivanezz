# ENVIRONMENT REPORT — sesión de construcción (2026-09-18)

Este informe documenta **lo que realmente se inspeccionó** al construir SERGIO BRAIN, y lo que no fue posible.

## Dónde se ejecutó esta sesión

La sesión corrió en un **contenedor Linux remoto** (Claude Code en la nube), no en tu PC Windows.
Hallazgos reales del entorno de construcción:

| Ítem | Resultado |
|---|---|
| Repositorio | `santivanezz/santivanezz` (README de perfil de GitHub; sin código previo) |
| Otros repos de la cuenta | 16 repos; **ninguno contiene "Boveda Sergio"** |
| Python | 3.11.15, SQLite 3.45.1 con FTS5 |
| Node / npm | 22.22.2 / 10.9.7 |
| Git | 2.43.0 |
| Obsidian | no instalado (contenedor) |
| Red | pip/npm disponibles vía proxy |

## Lo que NO se pudo hacer aquí (pasos 79.A–79.I del spec)

No existe acceso a tu máquina Windows ni a la bóveda desde este entorno, por lo que **no se ha auditado tu bóveda real
ni tu Windows**. En su lugar, el sistema incluye las herramientas que ejecutan exactamente esos pasos sobre tu entorno
real cuando lo instales:

- `sergio-brain doctor` → A–I: localiza "Boveda Sergio" (registro de Obsidian, Documentos, OneDrive, Escritorio, unidades),
  detecta versiones de Python/pip/Node/npm/Git/Obsidian/Ollama/SQLite-FTS5, paquetes opcionales, claves en entorno, riesgos y limitaciones.
- `sergio-brain audit` → sección 60 (1–14): tamaño, archivos, tipos, estructura, carpetas, tags, properties, enlaces/backlinks,
  duplicados, huérfanas, archivos problemáticos, posibles datos sensibles. **Solo lectura, verificado por test.**

## Cómo se validó el sistema

Con una bóveda sintética de prueba (proyecto, reunión, conceptos, nota con secretos, nota `do_not_index`) se ejecutó de punta a punta:
doctor → init → audit → backup → index → search → ask → tasks → decisions → contradictions → suggestions → why → changed →
briefing → weekly/monthly → health → command center → capture → import → API HTTP → restore. La suite `engine/tests` (31 tests,
incluidos los 15 acceptance tests del spec) pasa en 2 s.

## Riesgos y limitaciones conocidos antes de instalarlo en tu PC

1. Sin `sentence-transformers` la búsqueda semántica usa embeddings *hashed* (léxicos). Instala `[local]` para calidad real.
2. Los extractores son heurísticos (regex ES/EN): buen precision, recall limitado en redacciones inusuales. Todo queda etiquetado
   `AI_INFERENCE` o `USER_ASSERTION`, nunca `FACT`.
3. Si la bóveda vive en OneDrive, los conflictos de sincronización crean duplicados; Brain Health los lista.
4. Sin LLM configurado el asistente es extractivo (cita pasajes). Con Ollama es 100 % local; con Claude/OpenAI las notas
   `SENSITIVE` nunca salen.
5. `doctor` puede encontrar varias carpetas "Boveda Sergio" (copias); confirma con `--vault`.
