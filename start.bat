@echo off
title Hello World Website
cd /d "%~dp0"

echo ============================================
echo   Hello World Site Starting...
echo   Open in browser: http://127.0.0.1:5000
echo   Press Ctrl+C to stop.
echo ============================================
echo.

"C:\Users\Ê©¹§¹ú\.local\share\TeleAgent\runtimes\python\python.exe" app.py

echo.
echo Server stopped.
pause