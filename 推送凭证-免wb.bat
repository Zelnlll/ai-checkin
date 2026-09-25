@echo off
chcp 65001 >nul
cd /d "%~dp0"
python tools\push_panel.py --no-wb
echo.
pause
