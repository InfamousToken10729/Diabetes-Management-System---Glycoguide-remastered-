@echo off
setlocal

title GlycoGuide Remastered - Local Server
echo ====================================================================
echo        GlycoGuide Remastered - Type 1 Diabetes Assistant
echo ====================================================================
echo.

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "PY_EXE="
set "PY_ARGS="

:: 1. Prefer existing local virtual environment for instant boot
if not exist "%ROOT_DIR%.venv\Scripts\python.exe" goto :check_alt_venv
"%ROOT_DIR%.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :check_alt_venv
set "PY_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
goto :check_deps

:check_alt_venv
if not exist "%ROOT_DIR%venv\Scripts\python.exe" goto :detect_sys_py
"%ROOT_DIR%venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :detect_sys_py
set "PY_EXE=%ROOT_DIR%venv\Scripts\python.exe"
goto :check_deps

:detect_sys_py
set "SYS_EXE="
set "SYS_ARGS="
python -c "import sys; raise SystemExit(0 if sys.version_info[0]>=3 else 1)" >nul 2>&1
if not errorlevel 1 (
    set "SYS_EXE=python"
    goto :setup_venv
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "SYS_EXE=py"
    set "SYS_ARGS=-3"
    goto :setup_venv
)

echo [ERROR] Python 3 was not detected.
echo Please install Python 3 from https://www.python.org/downloads/
echo or run in PowerShell: winget install Python.Python.3.13
echo Note: Check "Add Python to PATH" during installation.
pause
exit /b 1

:setup_venv
echo [1/2] Creating isolated Python virtual environment ^(.venv^)...
"%SYS_EXE%" %SYS_ARGS% -m venv "%ROOT_DIR%.venv" >nul 2>&1
if not exist "%ROOT_DIR%.venv\Scripts\python.exe" goto :use_sys_py
set "PY_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
set "PY_ARGS="
goto :check_deps

:use_sys_py
echo [INFO] Virtual environment unavailable; using system Python directly...
set "PY_EXE=%SYS_EXE%"
set "PY_ARGS=%SYS_ARGS%"

:check_deps
"%PY_EXE%" %PY_ARGS% -c "import flask, requests" >nul 2>&1
if not errorlevel 1 goto :ready

echo [2/2] Installing required packages from requirements.txt...
"%PY_EXE%" %PY_ARGS% -m pip install -r "%ROOT_DIR%requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Please check your internet connection.
    pause
    exit /b 1
)

:ready
set "GLYCO_MANAGED_BY=run_bat"
set "GLYCO_RESTARTED=0"

:launch
echo.
echo Starting GlycoGuide Remastered on http://localhost:8081...
echo Press Ctrl+C anytime to stop the server.
echo.

"%PY_EXE%" %PY_ARGS% "%ROOT_DIR%app.py"
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="42" goto :do_restart
if not "%EXIT_CODE%"=="0" goto :error_pause
exit /b 0

:do_restart
echo.
echo [INFO] Applying update and restarting server...
set "GLYCO_NO_BROWSER=1"
set "GLYCO_RESTARTED=1"
timeout /t 1 /nobreak >nul
goto :launch

:error_pause
echo.
echo Server stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
