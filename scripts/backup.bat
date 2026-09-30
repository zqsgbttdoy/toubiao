@echo off
chcp 65001 >nul
setlocal
title Bid Platform - Data Backup
pushd "%~dp0.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] Python venv not found: .venv\Scripts\python.exe
    echo         Please run this file inside the project folder where .venv exists.
    goto :end
)

echo Starting backup, please wait...
echo.
"%PY%" scripts\backup_data.py
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [ERROR] Backup failed, exit code = %RC%
)

:end
echo.
pause
popd
endlocal
