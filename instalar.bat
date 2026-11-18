@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Clips Kitty - Instalador
cd /d "%~dp0"

echo ============================================
echo   Clips Kitty - instalacao a partir do codigo
echo ============================================
echo.
echo Instala: Python 3.12, Node.js LTS, Ollama, FFmpeg,
echo as bibliotecas Python, a interface e o modelo de IA.
echo Pode levar de 10 a 30 minutos na primeira vez.
echo.
pause

where winget >nul 2>nul
if errorlevel 1 (
  echo [ERRO] winget nao encontrado. Instale o "App Installer" pela Microsoft Store e rode de novo.
  goto :fail
)

rem ---- 1. Python 3.12 -------------------------------------------------------
echo.
echo [1/6] Python 3.12
py -3.12 --version >nul 2>nul
if errorlevel 1 (
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
)
set "PYEXE="
py -3.12 --version >nul 2>nul && set "PYEXE=py -3.12"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE (
  echo [ERRO] Python 3.12 nao foi encontrado depois da instalacao. Feche esta janela e rode o instalar.bat de novo.
  goto :fail
)

rem ---- 2. Node.js -----------------------------------------------------------
echo.
echo [2/6] Node.js
where npm >nul 2>nul
if errorlevel 1 (
  winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
  set "PATH=%ProgramFiles%\nodejs;%PATH%"
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Node.js nao foi encontrado. Feche esta janela e rode o instalar.bat de novo.
  goto :fail
)

rem ---- 3. Ollama ------------------------------------------------------------
echo.
echo [3/6] Ollama
set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
where ollama >nul 2>nul
if errorlevel 1 (
  winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
)

rem ---- 4. Ambiente Python ---------------------------------------------------
echo.
echo [4/6] Bibliotecas Python (pasta .venv)
if not exist ".venv\Scripts\python.exe" (
  %PYEXE% -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail

rem ---- 5. FFmpeg e interface ------------------------------------------------
echo.
echo [5/6] FFmpeg e interface
".venv\Scripts\python.exe" scripts\fetch_ffmpeg.py || goto :fail
rem Modelos extras: TalkNet (acha a webcam), vozes da legenda, sons e o QuickJS do YouTube.
".venv\Scripts\python.exe" scripts\fetch_asd_model.py
".venv\Scripts\python.exe" scripts\fetch_voice_model.py
".venv\Scripts\python.exe" scripts\fetch_panns.py
".venv\Scripts\python.exe" scripts\fetch_quickjs.py
rem O download do Electron fica com o reparar_instalacao.py: o passo de
rem pos-instalacao do proprio Electron pode terminar calado com Node novo e
rem deixar o app sem abrir ("Electron uninstall").
set "ELECTRON_SKIP_BINARY_DOWNLOAD=1"
pushd ui
call npm install || (popd & goto :fail)
popd
set "ELECTRON_SKIP_BINARY_DOWNLOAD="
echo.
echo Conferindo a instalacao (Electron e bibliotecas Python)...
".venv\Scripts\python.exe" scripts\reparar_instalacao.py || goto :fail

rem ---- 6. Modelo de IA ------------------------------------------------------
echo.
echo [6/6] Modelo de IA (gemma3:4b, cerca de 3 GB)
where ollama >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Ollama ainda nao esta no PATH. Depois de reiniciar o PC rode:  ollama pull gemma3:4b
) else (
  ollama pull gemma3:4b
)

echo.
echo ============================================
echo   Pronto! Para abrir o app: iniciar.bat
echo ============================================
pause
exit /b 0

:fail
echo.
echo A instalacao parou por causa do erro acima.
pause
exit /b 1
