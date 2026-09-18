@echo off
REM SERGIO BRAIN - instalacion en Windows SIN administrador, solo CMD.
REM Uso:  scripts\install.cmd            (busca "Boveda Sergio" automaticamente)
REM       scripts\install.cmd "D:\ruta\Boveda Sergio"
setlocal
cd /d "%~dp0.."
set ROOT=%CD%
echo == SERGIO BRAIN install (usuario, sin admin) ==

set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if "%PY%"=="" ( python --version >nul 2>&1 && set PY=python )
if "%PY%"=="" goto nopython
for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version.split()[0])"') do echo Python %%v

if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo Creando entorno virtual en %ROOT%\.venv ...
  %PY% -m venv "%ROOT%\.venv" || exit /b 1

:pipfail
echo.
echo pip fallo. Si estas detras del proxy corporativo prueba:
echo   "%VPY%" -m pip install --proxy http://usuario:clave@proxy:puerto -e "%ROOT%\engine[dev]"
echo o con certificados corporativos:
echo   "%VPY%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e "%ROOT%\engine[dev]"
exit /b 1
)
set VPY=%ROOT%\.venv\Scripts\python.exe
"%VPY%" -m pip install --upgrade pip --quiet
echo Instalando el motor (esto necesita Internet; si el proxy del banco lo bloquea, ver TROUBLESHOOTING.md) ...
"%VPY%" -m pip install -e "%ROOT%\engine[dev]" || goto pipfail
set SB=%ROOT%\.venv\Scripts\sergio-brain.exe
echo.
echo == Doctor ==
if "%~1"=="" ( "%SB%" doctor ) else ( "%SB%" doctor --vault "%~1" )
echo.
if "%~1"=="" ( "%SB%" init ) else ( "%SB%" init --vault "%~1" )
if errorlevel 1 (
  echo No se pudo localizar la boveda. Ejecuta:  scripts\install.cmd "D:\ruta\completa\Boveda Sergio"
  exit /b 1
)
echo.
echo Listo. Siguientes pasos (en este orden):
echo   "%SB%" audit
echo   "%SB%" backup
echo   "%SB%" index
echo   "%SB%" plugin-install
echo   scripts\serve.cmd
endlocal
exit /b 0

:nopython
echo.
echo No hay Python. Instalalo SIN admin:
echo   1. Abre https://www.python.org/downloads/windows/ y baja "Windows installer 64-bit" de Python 3.12
echo   2. Ejecuta el instalador: marca "Add python.exe to PATH" y pulsa "Install Now"
echo      Si aparece "Use admin privileges when installing py.exe", desmarcalo.
echo   3. Cierra y vuelve a abrir el CMD y ejecuta de nuevo scripts\install.cmd
exit /b 1
