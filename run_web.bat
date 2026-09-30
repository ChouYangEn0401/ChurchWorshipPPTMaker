@echo off
rem 敬拜 PPT 產生器（網頁版）：雙擊就會打開網頁。第一次會自動安裝（大約 1～2 分鐘）。
rem 要讓同工從外面一起編輯，改雙擊 run_web_public.bat。
if not exist "%~dp0.venv\Scripts\python.exe" (
  call "%~dp0scripts\windows\1-install.bat" --auto || exit /b 1
)
call "%~dp0scripts\windows\2-start.bat" %*
