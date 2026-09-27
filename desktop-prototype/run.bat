@echo off
setlocal
cd /d "%~dp0"

if exist ".setup-complete" if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe main.py
    goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
    py main.py
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python main.py
    goto :end
)

echo The app is not set up yet. Install Python 3.10 or newer, then run setup.bat.
pause

:end
endlocal
