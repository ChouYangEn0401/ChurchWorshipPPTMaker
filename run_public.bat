@echo off
rem 敬拜 PPT 產生器（網頁版）＋ Cloudflare 對外連結：同工用手機就能一起編輯。
rem 關掉黑色視窗，網址就失效。第一次會自動安裝。
call "%~dp0scripts\windows\_env.bat"
if not exist "%VENV_PY%" (
  call "%~dp0scripts\windows\1-install.bat" --auto || exit /b 1
)
title 敬拜 PPT 產生器 + 對外連結（關掉這個視窗，網址就失效）
"%VENV_PY%" "%ROOT%\main.py" web --public %*
if errorlevel 1 pause
