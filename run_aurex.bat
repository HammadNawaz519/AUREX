@echo off
title AUREX Desktop Voice Widget
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
chcp 65001 >nul

echo ==========================================================
echo    AUREX - Desktop Voice Surface (Push-To-Talk)
echo ==========================================================

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

if "%1"=="browser" (
    echo Starting AUREX in Browser mode...
    python -m app.server
) else (
    echo Launching AUREX Frameless Desktop Widget...
    python -m app.desktop_widget
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo AUREX encountered an error or stopped. Exit code: %ERRORLEVEL%
    pause
)
