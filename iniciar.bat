@echo off
setlocal
chcp 65001 >nul
title Clips Kitty
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Rode o instalar.bat primeiro.
  pause
  exit /b 1
)

rem The app starts "python" from PATH: put the project's .venv first.
set "PATH=%~dp0.venv\Scripts;%ProgramFiles%\nodejs;%LOCALAPPDATA%\Programs\Ollama;%PATH%"

cd ui
call npm run dev
