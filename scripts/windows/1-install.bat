@echo off
call "%~dp0_env.bat"
echo === 敬拜 PPT 產生器（網頁版）：安裝 ===
set "PY="
py -3.11 -c "import sys" >nul 2>nul && set "PY=py -3.11"
if not defined PY ( py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3" )
if not defined PY ( python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [X] 找不到 Python 3.11 以上的版本。
  echo     請到 https://www.python.org/downloads/ 下載安裝。
  echo     安裝的第一個畫面記得勾選「Add python.exe to PATH」，裝好後再雙擊一次這個檔案。
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 1
)
for /f "delims=" %%V in ('%PY% --version') do echo [OK] 找到 %%V
if not exist "%VENV_PY%" (
  echo ... 建立獨立的 Python 環境 .venv
  %PY% -m venv "%ROOT%\.venv" || goto :fail
)
echo ... 安裝需要的套件（第一次大約 1～2 分鐘）
"%VENV_PY%" -m pip install --disable-pip-version-check -q --upgrade pip || goto :fail
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r "%ROOT%\requirements.txt" || goto :fail
"%VENV_PY%" "%ROOT%\main.py" init || goto :fail
echo.
set "CF="
for /f "delims=" %%P in ('where cloudflared 2^>nul') do if not defined CF set "CF=%%P"
if not defined CF if exist "%ProgramFiles(x86)%\cloudflared\cloudflared.exe" set "CF=%ProgramFiles(x86)%\cloudflared\cloudflared.exe"
if not defined CF if exist "%ProgramFiles%\cloudflared\cloudflared.exe" set "CF=%ProgramFiles%\cloudflared\cloudflared.exe"
if defined CF (
  echo [OK] 找到 cloudflared：可以開對外連結，讓同工從外面一起編輯。
) else (
  echo [提醒] 沒有找到 cloudflared。只在這台電腦用的話不需要；
  echo        要讓同工從外面一起編輯，請打開命令提示字元輸入：winget install --id Cloudflare.cloudflared
)
echo.
if /i "%~1"=="--auto" (
  echo 安裝完成！接著打開網頁…
  exit /b 0
)
echo 安裝完成！下一步：雙擊專案資料夾裡的 run.bat 打開網頁。
pause
exit /b 0
:fail
echo.
echo [X] 安裝失敗。請把上面的訊息截圖，傳給維護的人。
pause
exit /b 1
