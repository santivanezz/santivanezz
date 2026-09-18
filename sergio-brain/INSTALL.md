# INSTALL

## Requisitos

- Windows 10/11 (también Linux/macOS).
- Python **3.10+** (recomendado el instalador de python.org; incluye SQLite con FTS5).
- Obsidian 1.4+ con la bóveda **"Boveda Sergio"** ya creada.
- Opcional: Node 18+ solo si quieres modificar el plugin (viene compilado en `plugin/main.js`).
- Opcional: [Ollama](https://ollama.com) para LLM local, o `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` para nube.

## 1. Motor Python

```powershell
cd sergio-brain
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Vault "C:\Users\<tu usuario>\...\Boveda Sergio" -Local -Docs
```

Opciones: `-Local` (embeddings locales con sentence-transformers, ~500 MB la primera vez),
`-Docs` (PDF/DOCX/XLSX/PPTX), `-Claude` (SDK de Anthropic). Sin opciones el sistema funciona igual
con embeddings *hashed* offline.

Manual (cualquier SO):

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e "engine[local,docs,dev]"
sergio-brain doctor                                  # inspecciona tu PC y localiza la bóveda
sergio-brain init --vault "/ruta/Boveda Sergio"      # escribe config.toml; no toca la bóveda
```

`doctor` busca la bóveda en el registro de Obsidian (`%APPDATA%\obsidian\obsidian.json`), en
Documentos, OneDrive, Escritorio, etc. Si hay varias carpetas con ese nombre, elige con `--vault`.

## 2. Orden seguro de arranque

```powershell
sergio-brain audit                 # informe de solo lectura (tamaño, tags, enlaces, huérfanas, secretos)
sergio-brain backup                # snapshot zip de la bóveda + DB en %APPDATA%\SergioBrain\data\backups
sergio-brain index                 # crea también un snapshot automático la primera vez
sergio-brain search "Power Query"
sergio-brain ask "¿Qué tengo pendiente?"
sergio-brain serve                 # API en http://127.0.0.1:8765 + watcher + scheduler
```

Para que el motor arranque con Windows: `scripts\register-startup-task.ps1`.

## 3. Plugin de Obsidian

```powershell
scripts\install-plugin.ps1 -Vault "C:\ruta\Boveda Sergio"
```

(o copia `plugin/main.js`, `manifest.json`, `styles.css` a `<bóveda>\.obsidian\plugins\sergio-brain\`).
En Obsidian: *Ajustes → Plugins de la comunidad → desactivar modo restringido → activar "Sergio Brain"*.
Comprueba en la barra de estado: `🧠 N notas · 0 jobs · none`.

Atajos por defecto: `Ctrl+Shift+B` Omnibar (Ask/Search/Why/Changed), `Ctrl+Alt+S` Capture.

## 4. Extensión de navegador (opcional)

Chrome/Edge → `chrome://extensions` → *Modo desarrollador* → *Cargar descomprimida* → carpeta `browser-extension/`.
Botones: Save selection / URL / article / page. Solo captura cuando pulsas.

## 5. Hotkey global de portapapeles (opcional)

Instala AutoHotkey v2 y ejecuta `scripts\clipboard-hotkey.ahk` (Ctrl+Alt+S fuera de Obsidian).
Alternativa sin AHK: `sergio-brain capture --clipboard`.

## 6. Obsidian Sync (bóveda sincronizada con el celular)

Tu bóveda vive en `D:\Organización y Metodos - Sergio Santivañez\Sergio\Boveda Sergio\Boveda Sergio` y se sincroniza con Obsidian Sync.
Esto encaja bien con el diseño:

- **Lo que escribes en el celular** llega a esa carpeta por Sync; el watcher del motor (en el PC) lo indexa en segundos cuando el PC está encendido. Nada se pierde si el PC estaba apagado: la siguiente vez, `sergio-brain index` (o el arranque de `serve`) recoge todo lo pendiente por hash.
- **Lo que genera SERGIO BRAIN** (`SERGIO BRAIN/…`: briefing, reviews, Inbox, Brain Health) también se sincroniza, así que lo lees desde el celular.
- **El índice, los logs y los backups zip** están en `%APPDATA%\SergioBrain\data`, fuera de la bóveda: no consumen cuota de Sync ni generan conflictos.
- En *Ajustes → Sync → Excluded folders* añade `SERGIO BRAIN/Backups` (copias previas de bloques editados; no hacen falta en el móvil).
- El plugin es solo de escritorio (`isDesktopOnly`). En el celular usas Obsidian normal; en el PC, todo lo demás.
- Si Sync produce un conflicto, Obsidian crea `Nombre (conflicted copy).md`; Brain Health lo listará como duplicado.

## 7. Verificación

```bash
cd engine && pytest -q        # 31 tests, incluye los 15 acceptance tests del spec
```
