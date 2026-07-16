@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 啟動教會敬拜 PPT 產生器（網頁版）...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run_web.py
) else (
    python run_web.py
)
pause
