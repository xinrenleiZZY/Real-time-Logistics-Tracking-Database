@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\add_firewall_rule.ps1" -Port 7650
pause
endlocal
