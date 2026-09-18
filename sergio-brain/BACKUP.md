# BACKUP

| Operación | Comando | Qué hace |
|---|---|---|
| Snapshot | `sergio-brain backup [--label x]` | zip de toda la bóveda + copia consistente de la DB en `data/backups/` |
| Incremental | `sergio-brain backup --incremental` | zip solo con archivos cuyo hash cambió desde el último backup (manifest.json) |
| Listar | `sergio-brain backup --list` | historial |
| Restaurar a carpeta | `sergio-brain backup --restore <zip> --to <carpeta>` | recupera sin tocar la bóveda viva (recomendado) |
| Restaurar in-place | `sergio-brain backup --restore <zip> --in-place` | crea antes un snapshot `pre-restore`, luego sobrescribe |
| Rollback de edición | (API `rollback_last_edit`) | los bloques gestionados guardan copia previa en `SERGIO BRAIN/Backups/edits/` |

Automático: snapshot antes de la primera indexación; incremental cada noche desde el scheduler de `serve`;
snapshot `pre-restore` / `pre-rollback` antes de operaciones de riesgo.

Regla: **ninguna migración destructiva**. Las migraciones de esquema solo añaden tablas/columnas. Si un día hiciera
falta otra cosa, el comando pedirá confirmación y hará snapshot primero.

Recomendación: mantén además tu propio backup externo (OneDrive/Git) de la bóveda; este sistema no lo sustituye.
