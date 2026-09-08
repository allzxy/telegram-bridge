@echo off
title Hentikan Bridge-Telegram
echo ===================================================
echo   MENGHENTIKAN BRIDGE-TELEGRAM
echo ===================================================
echo.
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*bridge_telegram.py*' -or $_.CommandLine -like '*allzxy_bot.py*') -and $_.ProcessName -match 'python' }; if ($procs) { foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('[OK] Berhasil menghentikan proses ' + $p.ProcessName + ' (PID: ' + $p.ProcessId + ')') } } else { Write-Host '[INFO] Tidak ada proses bot yang sedang berjalan.' }"
echo.
pause
