@echo off
title Pasang Auto Run Telegram Bridge
echo Memasang Auto Run ke folder Startup Windows...
set "CURRENT_DIR=%~dp0"
set "VBS_PATH=%CURRENT_DIR%start_bot_hidden.vbs"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo [1/2] Memasang Shortcut ke folder Startup...
(
    echo @echo off
    echo wscript.exe "%VBS_PATH%"
) > "%STARTUP_DIR%\TelegramBridge.cmd"

echo [2/2] Mendaftarkan ke Windows Task Scheduler (Anti-Sleep ^& Anti-Lock)...
schtasks /create /tn "TelegramBridgeDaemon" /tr "wscript.exe \"%VBS_PATH%\"" /sc onlogon /rl highest /f >nul 2>&1
schtasks /create /tn "TelegramBridgeKeepAlive" /tr "wscript.exe \"%VBS_PATH%\"" /sc minute /mo 5 /rl highest /f >nul 2>&1

echo.
echo =======================================================
echo [SUKSES] Auto Run ^& Keep-Alive Berhasil Dipasang!
echo - Startup Hook  : Aktif otomatis saat Windows login.
echo - Task Scheduler: Aktif saat lock screen ^& bangun sleep.
echo - Keep-Alive    : Menjaga bot tetap hidup tiap 5 menit.
echo =======================================================
echo.
pause
