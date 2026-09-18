@echo off
REM Arranca el motor (API + watcher + scheduler). Dejar esta ventana abierta mientras usas Obsidian.
cd /d "%~dp0.."
".venv\Scripts\sergio-brain.exe" serve
