# TROUBLESHOOTING

| Síntoma | Causa / solución |
|---|---|
| Barra de estado: `🧠 motor apagado` | Ejecuta `sergio-brain serve` (o registra la tarea de inicio). Comprueba `http://127.0.0.1:8765/health`. |
| `401 unauthorized` | `server.token` en config.toml no coincide con el del plugin/extensión. |
| `vault_path is not configured` | `sergio-brain init --vault "<ruta>"`. |
| `sqlite3.OperationalError: no such module: fts5` | Python sin FTS5 (algunas builds de tienda/conda). Instala Python de python.org. |
| Búsqueda semántica floja | Estás con embeddings `hashed`. `pip install "sergio-brain[local]"` y `sergio-brain index --force`. |
| Primera indexación lenta con `local` | Descarga del modelo (una vez) + cálculo de embeddings. Deja `serve` corriendo; los siguientes cambios son incrementales. |
| Respuestas solo extractivas | No hay LLM (`llm_provider = none`, sin clave, Ollama apagado, o `LOCAL_ONLY` con proveedor cloud). Ver `sergio-brain doctor`. |
| `context contains SENSITIVE notes; not sent to cloud provider` | Comportamiento esperado. Usa Ollama o quita `SENSITIVE` de la nota. |
| Nota no aparece | ¿tag `do_not_index`? ¿carpeta excluida? `sergio-brain index` fuerza el rescan; `--force` reindexa todo. |
| Duplicados `Nombre (1).md` | Conflictos de OneDrive/Dropbox. Brain Health > Duplicates los lista; consolida a mano. |
| Jobs `failed` | `SELECT * FROM processing_jobs WHERE status='failed'` en la DB; el log `data/logs/sergio_brain.log` tiene el error. Reencolar: reindexa la nota. |
| Quiero empezar de cero | Borra `data/sergio_brain.sqlite` (los backups y la bóveda no se tocan) y `sergio-brain index`. |
| Restaurar algo | Ver BACKUP.md. Empieza por `--restore <zip> --to <carpeta>` y compara. |

Logs: `%APPDATA%\SergioBrain\data\logs\sergio_brain.log` (rotativo, secretos redactados).
