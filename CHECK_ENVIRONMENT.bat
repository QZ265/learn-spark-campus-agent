@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo Environment check
echo ============================================================
echo.
where py
where python
echo.
py -3 --version
python --version
echo.
echo If one of the above commands says not found, install Python 3.10+ and tick Add Python to PATH.
echo.
pause
