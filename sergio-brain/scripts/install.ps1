# SERGIO BRAIN - instalación en Windows (PowerShell)
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-Vault "C:\ruta\Boveda Sergio"] [-Local] [-Docs]
param(
  [string]$Vault = "",
  [switch]$Local,   # instala sentence-transformers (embeddings locales de calidad; descarga ~500MB)
  [switch]$Docs,    # instala pypdf/python-docx/openpyxl/python-pptx
  [switch]$Claude   # instala el SDK de Anthropic (solo se usa si configuras ai.llm_provider = "claude")
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Write-Host "== SERGIO BRAIN install ==" -ForegroundColor Cyan
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python no encontrado. Instala Python 3.10+ desde https://www.python.org/downloads/windows/ (marca 'Add to PATH')." }
$ver = & $py.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Python $ver en $($py.Source)"
$venv = Join-Path $root ".venv"
if (-not (Test-Path $venv)) { & $py.Source -m venv $venv }
$pip = Join-Path $venv "Scripts\pip.exe"
$extras = @("dev")
if ($Local) { $extras += "local" }
if ($Docs) { $extras += "docs" }
if ($Claude) { $extras += "claude" }
& $pip install --upgrade pip | Out-Null
& $pip install -e ("$root\engine[" + ($extras -join ",") + "]")
$exe = Join-Path $venv "Scripts\sergio-brain.exe"
Write-Host "`n== Doctor ==" -ForegroundColor Cyan
if ($Vault) { & $exe doctor --vault $Vault } else { & $exe doctor }
if ($Vault) {
  & $exe init --vault $Vault
  Write-Host "`nSiguiente: `"$exe`" audit   (solo lectura)  ->  `"$exe`" backup  ->  `"$exe`" index  ->  `"$exe`" serve" -ForegroundColor Green
} else {
  Write-Host "`nEjecuta: `"$exe`" init --vault `"C:\ruta\Boveda Sergio`"" -ForegroundColor Yellow
}
Write-Host "Plugin de Obsidian: copia la carpeta 'plugin' a '<bóveda>\.obsidian\plugins\sergio-brain' (ver INSTALL.md)."
