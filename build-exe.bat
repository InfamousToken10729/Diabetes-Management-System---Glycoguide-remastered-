@echo off
setlocal

title GlycoGuide Remastered - Executable Builder
echo ====================================================================
echo      GlycoGuide Remastered - Standalone Windows ^(.exe^) Builder
echo ====================================================================
echo.

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "PY_EXE="
set "PY_ARGS="
if not exist "%ROOT_DIR%.venv\Scripts\python.exe" goto :check_sys_py
"%ROOT_DIR%.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :check_sys_py
set "PY_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
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

echo [ERROR] Python 3 was not detected.
pause
exit /b 1

:found_py
echo [1/4] Verifying application dependencies...
"%PY_EXE%" %PY_ARGS% -m pip install -q -r "%ROOT_DIR%requirements.txt"

echo [2/4] Verifying PyInstaller...
"%PY_EXE%" %PY_ARGS% -m pip show pyinstaller >nul 2>&1
if not errorlevel 1 goto :build_exe
echo Installing PyInstaller...
"%PY_EXE%" %PY_ARGS% -m pip install pyinstaller
if errorlevel 1 goto :build_fail

:build_exe
echo [3/4] Building standalone GlycoGuide.exe...
"%PY_EXE%" %PY_ARGS% -m PyInstaller --noconfirm --clean --onefile ^
    --name "GlycoGuide" ^
    --add-data "static;static" ^
    --add-data "templates;templates" ^
    --icon "static/img/favicon.ico" ^
    app.py
if errorlevel 1 goto :build_fail

if exist "dist\GlycoGuide.exe" copy /y "dist\GlycoGuide.exe" "%ROOT_DIR%GlycoGuide.exe" >nul
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"
if exist "GlycoGuide.spec" del /f /q "GlycoGuide.spec"

echo.
echo ====================================================================
echo [4/4] Build Complete!
echo Standalone Executable: %ROOT_DIR%GlycoGuide.exe
echo ====================================================================
echo.
pause
exit /b 0

:build_fail
echo [ERROR] PyInstaller compilation failed.
pause
exit /b 1
