"""`sergio-brain doctor`: inspect the real machine BEFORE building anything.

Locates "Boveda Sergio", detects Python/Node/npm/Git/Obsidian, checks optional
packages, identifies risks and limitations. Read-only.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

VAULT_NAME = "Boveda Sergio"


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return None


def obsidian_vaults() -> list[dict[str, Any]]:
    """Read Obsidian's own vault registry (obsidian.json)."""
    candidates = []
    if sys.platform.startswith("win"):
        candidates.append(Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json")
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json")
    else:
        candidates.append(Path.home() / ".config" / "obsidian" / "obsidian.json")
        candidates.append(Path.home() / "snap" / "obsidian" / "current" / ".config" / "obsidian" / "obsidian.json")
        candidates.append(Path.home() / ".var" / "app" / "md.obsidian.Obsidian" / "config" / "obsidian" / "obsidian.json")
    out = []
    for c in candidates:
        if c.exists():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                for vid, v in data.get("vaults", {}).items():
                    out.append({"id": vid, "path": v.get("path"), "open": v.get("open", False), "registry": str(c)})
            except (OSError, json.JSONDecodeError):
                continue
    return out


def find_vault(name: str = VAULT_NAME, extra_roots: list[Path] | None = None, max_depth: int = 5) -> list[Path]:
    hits: list[Path] = []
    for v in obsidian_vaults():
        p = v.get("path")
        if p and Path(p).name.lower() == name.lower() and Path(p).exists():
            hits.append(Path(p))
    roots = list(extra_roots or [])
    home = Path.home()
    roots += [home, home / "Documents", home / "Documentos", home / "OneDrive", home / "OneDrive - Personal", home / "Desktop", home / "Escritorio",
              home / "Dropbox", home / "Google Drive", home / "iCloudDrive"]
    if sys.platform.startswith("win"):
        for drive in "CDEFG":
            roots.append(Path(f"{drive}:/"))
        for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]))
    seen = {h.resolve() for h in hits}
    for root in roots:
        if not root.exists():
            continue
        try:
            for dirpath, dirnames, _ in os.walk(root):
                depth = len(Path(dirpath).relative_to(root).parts)
                dirnames[:] = [d for d in dirnames if not d.startswith((".", "$", "node_modules", "AppData", "Windows", "Program Files"))]
                if depth >= max_depth:
                    dirnames[:] = []
                for d in dirnames:
                    if d.lower() == name.lower():
                        p = Path(dirpath) / d
                        if p.resolve() not in seen:
                            hits.append(p)
                            seen.add(p.resolve())
        except (OSError, PermissionError):
            continue
    # prefer real vaults (with .obsidian folder)
    hits.sort(key=lambda p: (not (p / ".obsidian").exists(), len(str(p))))
    return hits


def obsidian_version() -> str | None:
    if sys.platform.startswith("win"):
        for base in (Path(os.environ.get("LOCALAPPDATA", "")) / "Obsidian", Path(os.environ.get("PROGRAMFILES", "")) / "Obsidian"):
            exe = base / "Obsidian.exe"
            if exe.exists():
                ver = _run(["powershell", "-NoProfile", "-Command", f"(Get-Item '{exe}').VersionInfo.ProductVersion"])
                return ver or "installed"
        return None
    if shutil.which("obsidian"):
        return "installed"
    if sys.platform == "darwin" and Path("/Applications/Obsidian.app").exists():
        return "installed"
    return None


def optional_packages() -> dict[str, bool]:
    out = {}
    for mod in ("numpy", "sentence_transformers", "anthropic", "pypdf", "docx", "openpyxl", "pptx", "watchdog", "pyperclip", "pytest"):
        try:
            __import__(mod)
            out[mod] = True
        except Exception:  # noqa: BLE001
            out[mod] = False
    return out


def run_doctor(vault_hint: str | None = None) -> dict[str, Any]:
    import sqlite3
    report: dict[str, Any] = {
        "os": {"platform": platform.platform(), "system": platform.system(), "release": platform.release(), "machine": platform.machine(), "user": os.environ.get("USERNAME") or os.environ.get("USER")},
        "tools": {
            "python": sys.version.split()[0], "python_exe": sys.executable,
            "pip": _run([sys.executable, "-m", "pip", "--version"]),
            "node": _run(["node", "--version"]), "npm": _run(["npm", "--version"]) or _run(["npm.cmd", "--version"]),
            "git": _run(["git", "--version"]), "obsidian": obsidian_version(),
            "ollama": _run(["ollama", "--version"]),
            "sqlite": sqlite3.sqlite_version,
        },
        "python_packages": optional_packages(),
        "obsidian_vaults": obsidian_vaults(),
        "env": {"ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")), "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY"))},
        "risks": [], "limitations": [], "recommendations": [],
    }
    fts_ok = True
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError:
        fts_ok = False
    report["tools"]["sqlite_fts5"] = fts_ok
    hits = find_vault(extra_roots=[Path(vault_hint).parent] if vault_hint else None)
    if vault_hint and Path(vault_hint).is_dir() and Path(vault_hint).resolve() not in {h.resolve() for h in hits}:
        hits.insert(0, Path(vault_hint))
    report["vault_candidates"] = [str(h) for h in hits]
    report["vault"] = str(hits[0]) if hits else None
    if hits:
        v = hits[0]
        md = sum(1 for _ in v.rglob("*.md"))
        report["vault_quick"] = {"markdown_files": md, "has_obsidian_folder": (v / ".obsidian").exists()}
        if any(part in ("OneDrive", "Dropbox", "Google Drive") for part in v.parts):
            report["risks"].append("La bóveda está en una carpeta sincronizada en la nube: conflictos de sincronización pueden crear duplicados 'Nombre (1).md'. El watcher los tratará como notas nuevas; revisa Brain Health > Duplicates.")
    else:
        report["risks"].append(f"No se encontró la bóveda '{VAULT_NAME}'. Indica la ruta: sergio-brain init --vault \"C:\\ruta\\Boveda Sergio\"")
    if not fts_ok:
        report["risks"].append("SQLite sin FTS5: la búsqueda full-text no funcionará. Instala Python oficial de python.org (incluye FTS5).")
    if sys.version_info < (3, 10):
        report["risks"].append("Python < 3.10 no está soportado.")
    if not report["tools"]["node"]:
        report["limitations"].append("Node no detectado: el plugin de Obsidian viene precompilado (main.js), Node solo hace falta para modificarlo.")
    if not report["python_packages"]["sentence_transformers"]:
        report["limitations"].append("sentence-transformers no instalado: se usará el embedding 'hashed' (offline, menor calidad). Instala con: pip install \"sergio-brain[local]\"")
    if not report["python_packages"]["pypdf"]:
        report["limitations"].append("pypdf no instalado: importación de PDF deshabilitada hasta: pip install \"sergio-brain[docs]\"")
    if not report["env"]["ANTHROPIC_API_KEY"] and not report["tools"]["ollama"]:
        report["limitations"].append("Sin LLM disponible (ni ANTHROPIC_API_KEY ni Ollama): el asistente responde en modo extractivo con citas. Todo lo demás funciona.")
    if len(hits) > 1:
        report["risks"].append(f"Se encontraron {len(hits)} carpetas llamadas '{VAULT_NAME}'. Se usará la primera; confirma con --vault.")
    report["recommendations"] = [
        "1. sergio-brain init --vault <ruta>      (crea config, NO toca la bóveda)",
        "2. sergio-brain audit                    (auditoría de solo lectura)",
        "3. sergio-brain backup                   (snapshot completo antes de indexar)",
        "4. sergio-brain index                    (indexación inicial, solo lectura de notas)",
        "5. sergio-brain serve                    (API + watcher para el plugin de Obsidian)",
    ]
    return report


def format_doctor(report: dict[str, Any]) -> str:
    L = ["SERGIO BRAIN — DOCTOR", "=" * 60, f"OS: {report['os']['platform']}  user: {report['os']['user']}", "", "Herramientas:"]
    for k, v in report["tools"].items():
        L.append(f"  {k:14s} {v if v else 'NO DETECTADO'}")
    L += ["", "Paquetes Python opcionales:"] + [f"  {k:22s} {'ok' if v else '-'}" for k, v in report["python_packages"].items()]
    L += ["", "Bóvedas registradas en Obsidian:"] + ([f"  {v['path']}  {'(abierta)' if v.get('open') else ''}" for v in report["obsidian_vaults"]] or ["  (registro de Obsidian no encontrado)"])
    L += ["", f"Boveda Sergio: {report['vault'] or 'NO ENCONTRADA'}"]
    if report.get("vault_quick"):
        L.append(f"  notas markdown: {report['vault_quick']['markdown_files']}  .obsidian: {report['vault_quick']['has_obsidian_folder']}")
    if len(report["vault_candidates"]) > 1:
        L += ["  otras candidatas:"] + [f"    {c}" for c in report["vault_candidates"][1:]]
    L += ["", "Riesgos:"] + ([f"  ! {r}" for r in report["risks"]] or ["  (ninguno)"])
    L += ["", "Limitaciones:"] + ([f"  - {r}" for r in report["limitations"]] or ["  (ninguna)"])
    L += ["", "Siguientes pasos:"] + [f"  {r}" for r in report["recommendations"]]
    return "\n".join(L)
