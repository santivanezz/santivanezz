# Conversaciones con IA (ChatGPT, Claude, Gemini) en Boveda Sergio

Ninguna de estas plataformas avisa a Obsidian por sí sola, así que SERGIO BRAIN las captura por dos vías.
Ambas escriben **una nota por conversación** en `SERGIO BRAIN/AI Chats/<Proveedor>/<fecha> <título>.md`, con
frontmatter (`provider`, `ai_chat_id`, `source_url`, `date`), secretos redactados, y se indexan como cualquier nota:
puedes preguntarle al asistente "¿qué le pregunté a ChatGPT sobre Erlang?" y te citará la conversación.
Si la misma conversación se guarda otra vez, la nota se actualiza (no se duplica).

## Vía 1 — Captura en vivo desde el navegador (día a día)

1. Instala la extensión (`browser-extension/`, ver INSTALL.md §4) y ten el motor corriendo (`scripts\serve.cmd`).
2. En ChatGPT, Claude o Gemini pulsa el icono de la extensión → **💬 Save AI conversation**.
3. Opcional: marca **Auto-guardar conversaciones**. La extensión guarda la conversación 20 s después de que deje de cambiar
   y al salir de la pestaña. Solo actúa en esos tres dominios; no lee ninguna otra web.

Aviso: los tres sitios cambian su HTML con frecuencia. Si un día detecta "0 mensajes", la extensión guarda el texto
principal de la página como respaldo, y basta con actualizar los selectores en `ai-chat.js`.

## Vía 2 — Importar el historial completo y la "memoria" (una vez, y cuando quieras)

| Proveedor | Cómo exportar | Archivo | Comando |
|---|---|---|---|
| ChatGPT | Ajustes → Controles de datos → Exportar datos → llega un correo con un zip | `conversations.json` | `sergio-brain import-chats conversations.json` |
| Claude | Ajustes → Privacidad → Exportar datos → correo con zip | `conversations.json` | `sergio-brain import-chats conversations.json --provider claude` |
| Gemini | takeout.google.com → solo "Mi actividad" → Gemini Apps → formato JSON | `MyActivity.json` | `sergio-brain import-chats MyActivity.json --provider gemini` |

El formato se detecta solo (`--provider auto`); el flag es por si falla. Gemini Takeout guarda tus preguntas y, a veces,
las respuestas; por eso ahí la vía 1 es más completa.

**Memoria del asistente sobre ti.** En cada asistente pregunta *"¿Qué recuerdas sobre mí? Lístalo todo en texto plano"*,
copia la respuesta a un `.txt` y:

```bat
.venv\Scripts\sergio-brain import-memory chatgpt memoria-chatgpt.txt
.venv\Scripts\sergio-brain import-memory claude memoria-claude.txt
.venv\Scripts\sergio-brain import-memory gemini memoria-gemini.txt
```

Crea `SERGIO BRAIN/AI Memory/<Proveedor> Memory.md` (se sobrescribe en cada importación) marcada como `EXTERNAL_SOURCE`.
ChatGPT también permite ver la memoria en Ajustes → Personalización → Memoria → Administrar; cópiala desde ahí.

## Privacidad

Las conversaciones se guardan con `privacy: PERSONAL`. Si alguna contiene datos del banco, añade `privacy: SENSITIVE` en el
frontmatter de esa nota y nunca se enviará a un LLM en la nube. Las contraseñas o tokens que hayas pegado en un chat se
redactan antes de escribir la nota.
