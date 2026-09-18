# Arranca el motor (API + watcher + scheduler). Ejecutar al iniciar sesión (ver INSTALL.md para la tarea programada).
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$exe = Join-Path $root ".venv\Scripts\sergio-brain.exe"
& $exe serve
