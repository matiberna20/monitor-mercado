@echo off
REM Arranca el bot de Telegram y la revisión periódica de alertas.
REM Doble clic para iniciarlo, o programalo en el Programador de tareas de Windows.
cd /d "%~dp0"
".venv\Scripts\monitor.exe" bot
pause
