@echo off
title Servidores Locales - Microservicios API
echo =======================================================
echo   Iniciando Microservicios en Local
echo   Auth Service (Dashboard): http://localhost:8000/
echo   Auth Service (Docs): http://localhost:8000/docs
echo   Log Service Dashboard: http://localhost:8010/
echo =======================================================
echo.

:: Verificar que el entorno virtual existe en la raíz
if not exist "%~dp0venv\Scripts\python.exe" (
    echo [ERROR] No se encontro el entorno virtual en %~dp0venv
    echo Por favor, asegurese de crearlo e instalar dependencias.
    pause
    exit /b
)

:: Levantar Auth Service en una ventana separada
echo Iniciando Auth Service en el puerto 8000...
start "Auth Service (Port 8000)" /D "%~dp0auth-service" ..\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload

:: Levantar Log Service en otra ventana separada
echo Iniciando Log Service en el puerto 8010...
start "Log Service (Port 8010)" /D "%~dp0log-service" ..\venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8010 --reload

echo.
echo [INFO] Ambos servicios se han lanzado en ventanas secundarias.
echo Presione cualquier tecla para salir de esta consola de control.
pause
