@echo off
rem FreshCuff Fit - offline launcher for Windows.
rem Double-click this file. It starts a small web server on this computer only (127.0.0.1)
rem and opens the app in your browser. Your scan never leaves this computer.
rem Needs Python 3.8 or newer; nothing is downloaded or installed.
setlocal
title FreshCuff Fit (local)
set "HERE=%~dp0"
set "ONLINE=https://sensecraft3d-eng.github.io/freshcuff-fit/"
set "PY="

rem Prefer the Python launcher (py -3), then python. The Microsoft Store "python" alias fails this test on purpose.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto run
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto run

echo.
echo   Python 3.8 or newer was not found on this computer.
echo   You can install it from https://www.python.org/downloads/windows/
echo   (tick "Add python.exe to PATH" during installation),
echo   or simply use the online version, which is the same app and also keeps your scan on your computer:
echo     %ONLINE%
echo.
choice /c YN /m "  Open the online version now"
if errorlevel 2 goto end
start "" "%ONLINE%"
goto end

:run
%PY% "%HERE%start_local.py" %*
echo.
echo   FreshCuff Fit has stopped.
pause

:end
endlocal
