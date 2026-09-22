@echo off
title Uninstall AUREX Windows Startup
cd /d "%~dp0"
python scripts\uninstall_startup.py
pause
