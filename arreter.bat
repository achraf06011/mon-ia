@echo off
rem Arrete le serveur de l'agent (celui qui ecoute sur le port 8002)
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"
echo Agent arrete.
timeout /t 2 >nul
