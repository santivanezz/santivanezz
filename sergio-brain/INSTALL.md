# INSTALL

## Requisitos

- Windows 10/11 (también Linux/macOS).
- Python **3.10+** (recomendado el instalador de python.org; incluye SQLite con FTS5).
- Obsidian 1.4+ con la bóveda **"Boveda Sergio"** ya creada.
- Opcional: Node 18+ solo si quieres modificar el plugin (viene compilado en `plugin/main.js`).
- Opcional: [Ollama](https://ollama.com) para LLM local, o `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` para nube.

## 0. PC corporativo: solo CMD, sin administrador

Todo se instala **por usuario**, sin permisos de administrador y sin Git ni PowerShell:

1. **Python** (si `py -3 --version` y `python --version` fallan): descarga el *Windows installer (64-bit)* de Python 3.12 en
   python.org, ejecútalo, marca *Add python.exe to PATH* y pulsa *Install Now*. Se instala en `%LOCALAPPDATA%\Programs\Python`.
   Si pide administrador, desmarca *Use admin privileges when installing py.exe*. Alternativa: Python de la Microsoft Store (también sin admin).
2. **Código**: descarga el ZIP de la rama en
   `https://github.com/santivanezz/santivanezz/archive/refs/heads/claude/sergio-brain-memory-system-cvtbfh.zip`
   y descomprímelo, por ejemplo en `%USERPROFILE%\sergio-brain` (la carpeta `sergio-brain` de dentro del ZIP).
3. En CMD:
   ```bat
   cd %USERPROFILE%\sergio-brain
   scripts\install.cmd
   ```
   `install.cmd` crea `.venv`, instala el motor, ejecuta `doctor` y `init` (localiza "Boveda Sergio" en D:\ automáticamente;
   si hay dudas: `scripts\install.cmd "D:\ruta\Boveda Sergio"`).
4. Luego, en orden: `.venv\Scripts\sergio-brain audit` → `backup` → `index` → `plugin-install` → `scripts\serve.cmd`.
5. Arranque automático sin admin: `scripts\register-startup-user.cmd` (acceso directo en la carpeta Inicio del usuario).

Si el proxy del banco bloquea `pip`, `install.cmd` muestra las dos variantes (`--proxy` y `--trusted-host`).
Sin acceso a PyPI el sistema no puede instalarse; sin acceso a Hugging Face simplemente no instales `[local]` y usará embeddings offline.

## 1. Motor Python (con PowerShell)

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
