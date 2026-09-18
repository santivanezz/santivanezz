# Copia el plugin compilado a la bóveda. Uso: scripts\install-plugin.ps1 -Vault "C:\ruta\Boveda Sergio"
param([string]$Vault = "D:\Organización y Metodos - Sergio Santivañez\Sergio\Boveda Sergio\Boveda Sergio")
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dest = Join-Path $Vault ".obsidian\plugins\sergio-brain"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
foreach ($f in @("main.js", "manifest.json", "styles.css")) { Copy-Item (Join-Path $root "plugin\$f") $dest -Force }
Write-Host "Plugin copiado a $dest. En Obsidian: Ajustes > Plugins de la comunidad > activar 'Sergio Brain'."
