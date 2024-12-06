@echo off
set VENV_DIR=venv

:: 設定錯誤處理
setlocal enabledelayedexpansion
set ERROR_MSG=

if not exist %VENV_DIR% (
    echo [Setting Environment...]
    python project-installer\setup_env.py || set ERROR_MSG=Setup Failed
)

if "%ERROR_MSG%"=="" (
    echo [Activating Environment]
    call %VENV_DIR%\Scripts\activate.bat || set ERROR_MSG=Failed To Activate Environment
)

if "%ERROR_MSG%"=="" (
    echo [Update Check]
    python project-installer\update_check.py || set ERROR_MSG=Update Check Failed
)

if "%ERROR_MSG%"=="" (
    echo [Start Running]
    python tmp.py || set ERROR_MSG=Program Execution Failed
)

if "%ERROR_MSG%"=="" (
    echo [Deactivating Environment]
    call %VENV_DIR%\Scripts\deactivate.bat
)

if not "%ERROR_MSG%"=="" (
    echo.
    echo [ERROR]: %ERROR_MSG%
    pause
)

echo [Process Completed]
exit /b
