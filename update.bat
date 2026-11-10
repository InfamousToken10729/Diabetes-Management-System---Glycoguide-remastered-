@echo off
setlocal

title GlycoGuide Remastered - Updater
echo ====================================================================
echo         GlycoGuide Remastered - Safe Repository Updater
echo ====================================================================
echo.

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "PY_EXE="
set "PY_ARGS="

if not exist "%ROOT_DIR%.venv\Scripts\python.exe" goto :check_alt_venv
set "PY_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
goto :found_py

:check_alt_venv
if not exist "%ROOT_DIR%venv\Scripts\python.exe" goto :check_sys_py
set "PY_EXE=%ROOT_DIR%venv\Scripts\python.exe"
goto :found_py

:check_sys_py
python -c "import sys; raise SystemExit(0 if sys.version_info[0]>=3 else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=python"
    goto :found_py
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
    goto :found_py
)

:found_py
echo [1/3] Creating database safety backup...
if not defined PY_EXE goto :git_pull
"%PY_EXE%" %PY_ARGS% -c "import update_service; p = update_service.create_pre_update_backup(); print('Backup created:', p) if p else print('No database yet to back up.')" 2>nul

:git_pull
echo [2/3] Pulling latest version from GitHub...
git pull --ff-only
if errorlevel 1 goto :git_error

echo [3/3] Updating Python dependencies...
if not defined PY_EXE goto :done
"%PY_EXE%" %PY_ARGS% -m pip install -q -r "%ROOT_DIR%requirements.txt"

:done
echo.
echo ====================================================================
echo Update complete! Your local database was safely preserved.
echo ====================================================================
pause
exit /b 0

:git_error
echo [ERROR] Git pull failed. Make sure Git is installed and working tree is clean.
pause
exit /b 1
