@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PyLearnSpark A3 Voice Server - No Venv

echo This is a backup launcher. It does not create .venv.
echo If it fails, use START_SERVER_WINDOWS.bat first.
echo.
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
start "" "http://127.0.0.1:8000"
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
pause
