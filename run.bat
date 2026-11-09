@echo off
setlocal enabledelayedexpansion

title GlycoGuide Remastered — Local Test Server
echo ====================================================================
echo        GlycoGuide Remastered — Type 1 Diabetes Assistant
echo ====================================================================
echo.

set ROOT_DIR=%~dp0
cd /d "%ROOT_DIR%"

:: Check for Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python 3 was not detected in your PATH.
    echo Please install Python from https://www.python.org or run:
    echo   winget install Python.Python.3.13
    pause
    exit /b 1
)

echo [1/3] Verifying Python dependencies...
python -m pip install -q -r requirements.txt

echo [2/3] Starting GlycoGuide Remastered on http://localhost:8081...
echo.
echo ====================================================================
echo  Server is running at http://localhost:8081
echo  Press Ctrl+C to stop the server anytime.
echo ====================================================================
echo.

:: Launch browser after 1 second delay in background
start /min cmd /c "timeout /t 1 >nul && start http://localhost:8081"

:: Start Python Flask application
python app.py

pause
