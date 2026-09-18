@echo off
REM Arranque automatico SIN admin: crea un acceso directo en la carpeta Inicio del usuario.
cd /d "%~dp0.."
set TARGET=%CD%\scripts\serve.cmd
set LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SergioBrain.lnk
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%'); $s.TargetPath='%TARGET%'; $s.WindowStyle=7; $s.Save()" 2>nul || (
  echo PowerShell bloqueado: crea a mano un acceso directo a "%TARGET%" en:
  echo   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
  exit /b 1
)
echo Acceso directo creado en la carpeta Inicio: %LNK%
