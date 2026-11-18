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

if not exist "ui\node_modules" (
  echo A interface nao foi instalada. Rode o instalar.bat primeiro.
  pause
  exit /b 1
)

rem The app starts "python" from PATH: put the project's .venv first.
set "PATH=%~dp0.venv\Scripts;%ProgramFiles%\nodejs;%LOCALAPPDATA%\Programs\Ollama;%PATH%"

rem Confere (e conserta) o Electron e as bibliotecas Python antes de abrir.
".venv\Scripts\python.exe" scripts\reparar_instalacao.py
if errorlevel 1 (
  echo.
  echo Nao deu para consertar sozinho. Rode o instalar.bat de novo.
  pause
  exit /b 1
)

cd ui
call npm run dev
