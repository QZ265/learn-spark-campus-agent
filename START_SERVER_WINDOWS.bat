@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title PyLearnSpark A3 Voice Server

echo ============================================================
echo PyLearnSpark A3 Voice Final - Server Launcher
echo ============================================================
echo.
echo This window must stay open while using the website.
echo If anything fails, read server_start_log.txt in this folder.
echo.

set "LOG=%CD%\server_start_log.txt"
echo [START] %date% %time% > "%LOG%"
echo [DIR] %CD% >> "%LOG%"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo [ERROR] Python was not found. >> "%LOG%"
    echo.
    echo ERROR: Python was not found on this computer.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo During installation, tick: Add python.exe to PATH
    echo.
    pause
    exit /b 1
  )
)

echo [INFO] Python command: %PY% >> "%LOG%"
%PY% --version >> "%LOG%" 2>&1

echo.
echo Step 1/4: Checking virtual environment...
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  %PY% -m venv .venv >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo.
    echo ERROR: Failed to create virtual environment.
    echo Read server_start_log.txt, or run: python -m venv .venv
    echo.
    pause
    exit /b 1
  )
)

set "VPY=%CD%\.venv\Scripts\python.exe"

echo.
echo Step 2/4: Installing required packages...
"%VPY%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >> "%LOG%" 2>&1
"%VPY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn >> "%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo ERROR: Failed to install required packages.
  echo It may be caused by network or pip. Read server_start_log.txt.
  echo.
  pause
  exit /b 1
)

echo.
echo Step 3/4: Starting browser...
start "" "http://127.0.0.1:8000"

echo.
echo Step 4/4: Starting local server...
echo.
echo Website: http://127.0.0.1:8000
echo Chat page: http://127.0.0.1:8000/chat
echo Voice button works only after XF_ASR_APP_ID/API_KEY/API_SECRET are filled in config_keys.env.
echo.
echo DO NOT CLOSE THIS WINDOW.
echo Press Ctrl+C here only when you want to stop the server.
echo.
"%VPY%" -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload >> "%LOG%" 2>&1

echo.
echo Server stopped or failed. Please read server_start_log.txt.
echo.
pause
