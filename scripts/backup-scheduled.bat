@echo off
REM Wrapper para correr scripts/backup.sh desde el Programador de tareas de
REM Windows (que no puede invocar un .sh directamente). Requiere Git Bash
REM instalado (ya lo usa este proyecto para el resto de los comandos).
REM
REM Configuracion de la tarea programada, ver README.md seccion "Backups".

cd /d "%~dp0.."
"C:\Program Files\Git\bin\bash.exe" scripts\backup.sh >> scripts\backup.log 2>&1
