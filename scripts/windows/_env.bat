@echo off
rem Shared setup for the other scripts (do not run directly).
chcp 65001 >nul
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PYTHONPATH=%ROOT%\src"
set "PYTHONUTF8=1"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
cd /d "%ROOT%"
