@echo off
rem 敬拜 PPT 產生器（網頁版）：雙擊就會打開網頁。第一次會自動安裝（大約 1～2 分鐘）。
rem 要讓同工從外面一起編輯，改雙擊 run_public.bat。
call "%~dp0scripts\windows\_env.bat"
if not exist "%VENV_PY%" (
  call "%~dp0scripts\windows\1-install.bat" --auto || exit /b 1
)
title 敬拜 PPT 產生器（關掉這個視窗就會停止）
"%VENV_PY%" "%ROOT%\main.py" web %*
if errorlevel 1 pause
