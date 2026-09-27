@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_COMMAND=py"
    goto :create_environment
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_COMMAND=python"
    goto :create_environment
)

echo Python was not found. Install Python 3.10 or newer, then run setup.bat again.
pause
exit /b 1

:create_environment
echo Creating the local Python environment...
%PYTHON_COMMAND% -m venv .venv
if errorlevel 1 goto :failed

echo Installing the required packages...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed

type nul > .setup-complete

echo.
echo Setup is complete. Double-click run.bat to start the app.
pause
exit /b 0

:failed
echo.
echo Setup did not complete. Review the error above and try again.
pause
exit /b 1
