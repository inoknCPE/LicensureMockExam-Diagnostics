@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo The local environment is missing. Run setup.bat first.
    pause
    exit /b 1
)

echo Starting the Licensure Exam application...
echo Open http://127.0.0.1:5000 in your browser.
echo Press Ctrl+C in this window to stop the server.
echo.

%PYTHON_EXE% -m uvicorn server:app --host 127.0.0.1 --port 5000 --reload

endlocal
