# CONFIGURATION

Archivo: `%APPDATA%\SergioBrain\config.toml` (Linux/macOS: `~/.config/sergio-brain/config.toml`).
Sobrescribir ruta: variable `SERGIO_BRAIN_CONFIG`; carpeta base: `SERGIO_BRAIN_HOME`; bóveda: `SERGIO_BRAIN_VAULT`.
Se genera con `sergio-brain init`. **Nunca contiene API keys**: usa `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.

```toml
vault_path = "C:\\Users\\sergio\\Documents\\Boveda Sergio"
data_dir = ""                 # vacío = %APPDATA%\SergioBrain\data (DB, logs, backups)
watch_poll_seconds = 2.0
debounce_seconds = 1.5
chunk_size = 900
chunk_overlap = 120
stale_days = 90               # STALE a partir de aquí
outdated_days = 180           # OUTDATED
language = "es"

[privacy]
do_not_index_tags = ["do_not_index", "private/no-index"]
do_not_send_to_cloud_tags = ["sensitive", "do_not_send_to_cloud"]
do_not_process_folders = [".obsidian", ".trash", ".git", "SERGIO BRAIN/Backups"]
default_level = "PERSONAL"    # PUBLIC | PERSONAL | WORK | SENSITIVE
cloud_blocked_levels = ["SENSITIVE"]
redact_secrets = true

[ai]
mode = "LOCAL_ONLY"           # LOCAL_ONLY | HYBRID | CLOUD
llm_provider = "none"         # none | claude | openai | ollama
llm_model = "claude-opus-5"
ollama_url = "http://localhost:11434"
ollama_model = "llama3.1"
openai_model = "gpt-4o-mini"
embedding_provider = "auto"   # auto (local si está instalado, si no hashed) | hashed | local | ollama | openai
embedding_model = "paraphrase-multilingual-MiniLM-L12-v2"
ollama_embedding_model = "nomic-embed-text"
openai_embedding_model = "text-embedding-3-small"
max_context_chars = 12000
cost_input_per_million = 5.0  # solo para la estimación de coste mostrada en `costs`
cost_output_per_million = 25.0

[server]
host = "127.0.0.1"
port = 8765
token = ""                    # si lo pones, el plugin y la extensión deben enviarlo (X-Brain-Token)

[layout]
brain_folder = "SERGIO BRAIN"
inbox_folder = "SERGIO BRAIN/Inbox"
daily_folder = "SERGIO BRAIN/Daily"
reviews_folder = "SERGIO BRAIN/Reviews"
imports_folder = "SERGIO BRAIN/Imports"
backups_folder = "SERGIO BRAIN/Backups"
daily_note_format = "%Y-%m-%d"
```

## Modos de IA

| Modo | Embeddings | LLM |
|---|---|---|
| `LOCAL_ONLY` | hashed / local / ollama | solo Ollama o ninguno; los proveedores cloud se ignoran |
| `HYBRID` | local | Claude/OpenAI si hay clave; notas `SENSITIVE` nunca salen |
| `CLOUD` | openai permitido | Claude/OpenAI |

## Frontmatter reconocido en tus notas

`project:` / `proyecto:` (nombre del proyecto), `people:` / `personas:`, `date:` / `fecha:`, `privacy: SENSITIVE`,
`context: WORK|STUDY|PERSONAL|FINANCE|PROJECT|LEARNING`, `do_not_index: true`, `source_url:` / `source:`.
Tags: `proyecto/<nombre>`, `persona/<nombre>`, `curso/<nombre>`, `meeting`, `sensitive`, `do_not_index`.
