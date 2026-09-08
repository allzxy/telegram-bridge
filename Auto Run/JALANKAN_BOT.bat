@echo off
title Bridge-Telegram Launcher
echo ===================================================
echo   MEMULAI BRIDGE-TELEGRAM (BACKGROUND)
echo ===================================================
echo.
wscript.exe "%~dp0start_bot_hidden.vbs"
echo [OK] Bridge-Telegram berhasil dijalankan di background!
timeout /t 2 >nul
