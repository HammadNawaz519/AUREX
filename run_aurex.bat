@echo off
title AUREX - MARK LIV
cd /d "%~dp0"
echo ========================================================
echo Starting AUREX (Mark-LIV with Gemini Live)...
echo ========================================================
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] AUREX exited with an error.
    pause
)
