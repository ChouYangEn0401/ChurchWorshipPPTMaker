@echo off
call "%~dp0_env.bat"
if not exist "%VENV_PY%" (
  echo [X] 還沒安裝。請雙擊專案資料夾裡的 run.bat（會自動安裝）
  pause
  exit /b 1
)
"%VENV_PY%" "%ROOT%\main.py" backup
pause
