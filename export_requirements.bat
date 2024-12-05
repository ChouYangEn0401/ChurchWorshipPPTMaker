@echo off
set VENV_DIR=venv

if not exist %VENV_DIR% (
    echo [Environment not found. Please set up the environment first.]
    exit /b 1
)

call %VENV_DIR%\Scripts\activate.bat
python project-installer\export_requirements.py
call %VENV_DIR%\Scripts\deactivate.bat

echo [Requirements exported successfully!]
pause
