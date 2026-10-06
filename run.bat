@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The local environment is missing. Run setup.bat first.
    pause
    exit /b 1
)

echo Starting the Licensure Exam application...
echo Open http://127.0.0.1:8000 in your browser.
echo Press Ctrl+C in this window to stop the server.
echo.

.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload

endlocal
