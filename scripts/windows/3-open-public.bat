@echo off
rem Starts the web app AND a Cloudflare quick tunnel, so teammates can edit from their phones.
rem The public address changes every time; closing this window closes it.
call "%~dp0_env.bat"
if not exist "%VENV_PY%" (
  echo [X] 還沒安裝。請雙擊專案資料夾裡的 run_web.bat（會自動安裝）
  pause
  exit /b 1
)
title 敬拜 PPT 產生器 + 對外連結（關掉這個視窗，網址就失效）
"%VENV_PY%" -m worship_ppt web --public %*
if errorlevel 1 pause
